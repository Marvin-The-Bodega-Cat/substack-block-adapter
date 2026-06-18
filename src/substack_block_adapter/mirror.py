from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MirrorConfig, SourceRecord
from .substack import (
    FetchError,
    canonicalize_post_url,
    fetch_archive,
    fetch_body_text,
    fetch_feed,
    fetch_sitemap_post_urls,
    normalize_publication,
    post_url,
    slugify,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def config_fingerprint(config: MirrorConfig) -> str:
    payload = json.dumps(config.normalized_for_hash(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def post_timestamp(post: dict[str, Any]) -> str | None:
    for key in ("post_date", "published_at", "updated_at", "created_at"):
        if post.get(key):
            return str(post[key])
    return None


def post_slug(post: dict[str, Any], url: str) -> str:
    if post.get("slug"):
        return slugify(str(post["slug"]))
    path = url.rstrip("/").split("/")[-1]
    return slugify(path or str(post.get("id") or "post"))


def post_date_prefix(timestamp: str | None) -> str:
    if timestamp and len(timestamp) >= 10 and timestamp[4:5] == "-":
        return timestamp[:10]
    return "undated"


def markdown_for_post(post: dict[str, Any], url: str, body_text: str | None) -> str:
    title = str(post.get("title") or "Untitled")
    subtitle = str(post.get("subtitle") or post.get("description") or "")
    frontmatter = {
        "id": str(post.get("id") or ""),
        "title": title,
        "subtitle": subtitle,
        "canonical_url": url,
        "post_date": post_timestamp(post),
        "slug": post.get("slug"),
        "wordcount": post.get("wordcount"),
        "reaction_count": post.get("reaction_count"),
        "comment_count": post.get("comment_count"),
    }
    lines = ["---"]
    for k, v in frontmatter.items():
        if v is not None:
            safe = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{safe}"')
    lines.extend(["---", "", f"# {title}", ""])
    if subtitle:
        lines.extend([subtitle, ""])
    lines.extend([f"Source: {url}", ""])
    if body_text:
        lines.extend([body_text, ""])
    else:
        lines.append("Body text was not fetched for this mirror cut. The canonical URL is the source pointer.")
    return "\n".join(lines).rstrip() + "\n"


def source_text(post: dict[str, Any], body_text: str | None) -> str:
    if body_text:
        return body_text
    parts = [str(post.get("title") or "")]
    subtitle = post.get("subtitle") or post.get("description")
    if subtitle:
        parts.append(str(subtitle))
    return "\n\n".join(p for p in parts if p)


def load_existing_raw_posts(out: Path, publication: str) -> list[dict[str, Any]]:
    raw_dir = out / "raw"
    if not raw_dir.exists():
        return []
    posts: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            post = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(post, dict):
            try:
                # Only keep objects that can be resolved to a post URL.
                post_url(publication, post)
            except Exception:
                continue
            posts.append(post)
    return posts


def merge_posts_by_url(publication: str, base: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for post in base:
        by_url[canonicalize_post_url(post_url(publication, post))] = post
    for post in updates:
        url = canonicalize_post_url(post_url(publication, post))
        if url not in by_url:
            by_url[url] = post
    return list(by_url.values())


def fetch_posts_for_config(config: MirrorConfig, publication: str, out: Path) -> tuple[list[dict[str, Any]], list[dict[str, int]], str, bool]:
    mode = (config.source_mode or "archive").strip().lower().replace("-", "_")
    if mode == "archive":
        archive = fetch_archive(publication)
        return archive.posts, archive.offset_probe, "archive", bool(archive.offset_probe and archive.offset_probe[-1]["new"] == 0)
    if mode in {"rss", "rss_latest", "feed"}:
        feed = fetch_feed(publication)
        existing = load_existing_raw_posts(out, publication)
        merged = merge_posts_by_url(publication, existing, feed.posts)
        return merged, feed.offset_probe, "rss_latest", True
    raise ValueError(f"unknown source_mode {config.source_mode!r}; expected 'archive' or 'rss_latest'")


def mirror(config: MirrorConfig) -> dict[str, Any]:
    publication = normalize_publication(config.publication)
    out = Path(config.out)
    out.mkdir(parents=True, exist_ok=True)
    generated_at = now_iso()
    posts, source_probe, source_mode, source_terminated = fetch_posts_for_config(config, publication, out)

    sitemap_urls: list[str] = []
    sitemap_error: str | None = None
    try:
        sitemap_urls = fetch_sitemap_post_urls(publication)
    except Exception as exc:
        sitemap_error = str(exc)

    records: list[SourceRecord] = []
    post_index: list[dict[str, Any]] = []
    fetched_bodies = 0
    body_errors: list[dict[str, str]] = []

    sorted_posts = sorted(
        posts,
        key=lambda p: (post_timestamp(p) or "", str(p.get("id") or "")),
        reverse=False,
    )
    for i, post in enumerate(sorted_posts, start=1):
        url = post_url(publication, post)
        pid = str(post.get("id") or post.get("slug") or url)
        timestamp = post_timestamp(post)
        slug = post_slug(post, url)
        md_name = f"{post_date_prefix(timestamp)}-{slug}.md"
        body_text = None
        if config.fetch_bodies:
            try:
                body_text = fetch_body_text(url)
                fetched_bodies += 1
            except Exception as exc:
                body_errors.append({"url": url, "error": str(exc)})
        (out / "posts" / md_name).parent.mkdir(parents=True, exist_ok=True)
        (out / "posts" / md_name).write_text(markdown_for_post(post, url, body_text))
        dump_json(out / "raw" / f"{slugify(pid)}.json", post)
        record = SourceRecord(
            record_id=f"{config.source_id_prefix}-r{i:06d}",
            source_type="substack",
            source_id=pid,
            title=str(post.get("title") or "Untitled"),
            text=source_text(post, body_text),
            timestamp=timestamp,
            uri=url,
            metadata={
                "slug": post.get("slug"),
                "subtitle": post.get("subtitle"),
                "wordcount": post.get("wordcount"),
                "reaction_count": post.get("reaction_count"),
                "comment_count": post.get("comment_count"),
                "markdown_path": f"posts/{md_name}",
                "raw_path": f"raw/{slugify(pid)}.json",
            },
        )
        records.append(record)
        post_index.append({
            "record_id": record.record_id,
            "source_id": pid,
            "title": record.title,
            "timestamp": timestamp,
            "uri": url,
            "markdown_path": f"posts/{md_name}",
        })

    api_urls = sorted({canonicalize_post_url(post_url(publication, p)) for p in posts})
    api_set = set(api_urls)
    sitemap_set = set(sitemap_urls)
    block_id = config.block_id or slugify(publication.replace("https://", "").replace(".", "-"))
    fingerprint = config_fingerprint(config)
    block = {
        "schema_version": "datamine.block.v1",
        "block_id": block_id,
        "title": f"Substack mirror: {publication}",
        "created_at": generated_at,
        "source_adapter": "substack-block-adapter@0.2.0",
        "source_config_fingerprint": fingerprint,
        "source_config": config.normalized_for_hash(),
        "records": [r.to_dict() for r in records],
    }
    report = {
        "schema_version": "substack.scrape_completeness.v1",
        "publication": publication,
        "generated_at": generated_at,
        "source_mode": source_mode,
        "total_api_posts": len(posts) if source_mode == "archive" else None,
        "total_source_posts": len(posts),
        "latest_feed_posts": source_probe[0]["returned"] if source_mode == "rss_latest" and source_probe else None,
        "date_range": {
            "min": min([r.timestamp for r in records if r.timestamp], default=None),
            "max": max([r.timestamp for r in records if r.timestamp], default=None),
        },
        "sitemap_post_url_count": len(sitemap_urls),
        "sitemap_error": sitemap_error,
        "api_missing_from_sitemap_count": len(api_set - sitemap_set) if sitemap_urls else None,
        "sitemap_missing_from_api_count": len(sitemap_set - api_set) if sitemap_urls else None,
        "api_missing_from_sitemap_sample": sorted(api_set - sitemap_set)[:10] if sitemap_urls else [],
        "sitemap_missing_from_api_sample": sorted(sitemap_set - api_set)[:10] if sitemap_urls else [],
        "source_probe": source_probe,
        "offset_probe": source_probe if source_mode == "archive" else [],
        "terminated_on_zero_new_batch": source_terminated if source_mode == "archive" else None,
        "rss_latest_gate_passed": source_mode == "rss_latest" and bool(source_probe),
        "fetch_bodies": config.fetch_bodies,
        "fetched_bodies": fetched_bodies,
        "body_errors": body_errors[:20],
        "block_path": "block.json",
        "index_path": "index.json",
    }
    if source_mode == "archive":
        complete = (
            report["terminated_on_zero_new_batch"]
            and sitemap_urls
            and report["api_missing_from_sitemap_count"] == 0
            and report["sitemap_missing_from_api_count"] == 0
        )
    else:
        # RSS is a latest-post watcher source, not a comprehensive source.
        complete = bool(report["rss_latest_gate_passed"])
    report["completeness_gate_passed"] = bool(complete)

    index = {
        "publication": publication,
        "generated_at": generated_at,
        "block_id": block_id,
        "source_config_fingerprint": fingerprint,
        "post_count": len(records),
        "posts": post_index,
    }
    readme = f"# Substack mirror: {publication}\n\nGenerated at: {generated_at}\n\nPosts mirrored: {len(records)}\n\nBlock: `block.json`\n\nCompleteness gate passed: `{bool(complete)}`\n"

    dump_json(out / "block.json", block)
    dump_json(out / "index.json", index)
    dump_json(out / "receipts" / "scrape_completeness_report.json", report)
    dump_json(out / "receipts" / "update_receipt.json", {
        "promise": "Mirror Substack archive into markdown/raw files and produce a Data Mine block.",
        "result": f"Mirrored {len(records)} posts from {publication}; completeness_gate_passed={bool(complete)}.",
        "created_at": generated_at,
        "evidence": ["block.json", "index.json", "receipts/scrape_completeness_report.json"],
    })
    (out / "README.md").write_text(readme)
    write_csv(out / "posts.csv", post_index)
    return {"out": str(out), "post_count": len(records), "completeness_gate_passed": bool(complete), "report": report}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["record_id", "source_id", "timestamp", "title", "uri", "markdown_path"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})
