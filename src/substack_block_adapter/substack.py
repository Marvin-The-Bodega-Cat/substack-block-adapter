from __future__ import annotations

import email.utils
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timezone
from html.parser import HTMLParser
from typing import Any


USER_AGENT = "Mozilla/5.0 (compatible; substack-block-adapter/0.2.1; +https://github.com/Marvin-The-Bodega-Cat/substack-block-adapter)"


class FetchError(RuntimeError):
    pass


@dataclass
class ArchiveResult:
    posts: list[dict[str, Any]]
    offset_probe: list[dict[str, int]]


def normalize_publication(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("publication is required")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if not parsed.netloc:
        raise ValueError(f"invalid publication URL: {value}")
    scheme = "https"
    return urllib.parse.urlunparse((scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def slugify(value: str, fallback: str = "post") -> str:
    value = (value or fallback).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or fallback


def get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except Exception as exc:  # pragma: no cover - exact urllib subclasses vary
        raise FetchError(f"failed to fetch JSON {url}: {exc}") from exc


def get_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        raise FetchError(f"failed to fetch text {url}: {exc}") from exc


def archive_api_url(publication: str, offset: int) -> str:
    return f"{publication}/api/v1/archive?sort=new&search=&offset={offset}"


def fetch_archive(publication: str, *, step: int = 20, max_pages: int = 1000) -> ArchiveResult:
    publication = normalize_publication(publication)
    seen: set[str] = set()
    posts: list[dict[str, Any]] = []
    probe: list[dict[str, int]] = []
    for page in range(max_pages):
        offset = page * step
        data = get_json(archive_api_url(publication, offset))
        if not isinstance(data, list):
            raise FetchError(f"archive API returned {type(data).__name__}, expected list")
        new_count = 0
        for post in data:
            if not isinstance(post, dict):
                continue
            pid = str(post.get("id") or post.get("slug") or post.get("canonical_url") or len(posts))
            if pid in seen:
                continue
            seen.add(pid)
            posts.append(post)
            new_count += 1
        probe.append({"offset": offset, "returned": len(data), "new": new_count})
        if new_count == 0:
            break
    return ArchiveResult(posts=posts, offset_probe=probe)


def fetch_sitemap_post_urls(publication: str) -> list[str]:
    publication = normalize_publication(publication)
    xml_text = get_text(f"{publication}/sitemap.xml")
    root = ET.fromstring(xml_text)
    urls: list[str] = []
    for loc in root.iter():
        if loc.tag.endswith("loc") and loc.text:
            u = loc.text.strip()
            if "/p/" in urllib.parse.urlparse(u).path:
                urls.append(canonicalize_post_url(u))
    return sorted(set(urls))


def first_text(element: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in element.iter():
        local = child.tag.rsplit("}", 1)[-1]
        if local in names and child.text:
            return child.text.strip()
    return None


def rss_date_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return value


def fetch_feed(publication: str) -> ArchiveResult:
    """Fetch Substack's built-in RSS feed as a latest-post source.

    RSS is intentionally not comprehensive; Substack commonly exposes only the
    latest items. Use it for watchers, not for the initial full archive cut.
    """
    publication = normalize_publication(publication)
    feed_url = f"{publication}/feed"
    try:
        xml_text = get_text(feed_url)
        return parse_feed_xml(xml_text)
    except Exception as direct_exc:
        # GitHub-hosted runners can receive 403s from Substack even for /feed.
        # Jina Reader can still fetch the public feed and returns stable markdown
        # containing post URLs plus pubDate lines. Use it only as a fallback.
        try:
            return parse_jina_feed_markdown(get_text(jina_reader_url(feed_url)))
        except Exception as fallback_exc:
            raise FetchError(f"failed to fetch RSS feed {feed_url}: direct={direct_exc}; jina_fallback={fallback_exc}") from fallback_exc


def parse_feed_xml(xml_text: str) -> ArchiveResult:
    root = ET.fromstring(xml_text)
    posts: list[dict[str, Any]] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        link = first_text(item, ("link",))
        title = first_text(item, ("title",)) or "Untitled"
        description = first_text(item, ("description",)) or ""
        pub_date = rss_date_to_iso(first_text(item, ("pubDate",)))
        guid = first_text(item, ("guid",)) or link or title
        content = first_text(item, ("encoded",))
        if not link:
            continue
        canonical = canonicalize_post_url(link)
        slug = canonical.rstrip("/").split("/")[-1]
        posts.append({
            "id": guid,
            "title": title,
            "subtitle": description,
            "description": description,
            "slug": slug,
            "canonical_url": canonical,
            "post_date": pub_date,
            "body_html": content,
            "source_mode": "rss_latest",
        })
    return ArchiveResult(posts=posts, offset_probe=[{"offset": 0, "returned": len(posts), "new": len(posts)}])


def jina_reader_url(url: str) -> str:
    return "https://r.jina.ai/http://" + url


def title_from_slug(url: str) -> str:
    slug = canonicalize_post_url(url).rstrip("/").split("/")[-1]
    return " ".join(part.capitalize() for part in slug.split("-") if part) or "Untitled"


def parse_jina_feed_markdown(text: str) -> ArchiveResult:
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        match = re.search(r"https?://[^\s)\]]+/p/[^\s)\]]+", line)
        if not match:
            continue
        canonical = canonicalize_post_url(match.group(0))
        if canonical in seen:
            continue
        seen.add(canonical)
        pub_date = None
        for candidate in lines[i + 1 : i + 6]:
            if re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),", candidate):
                pub_date = rss_date_to_iso(candidate)
                break
        slug = canonical.rstrip("/").split("/")[-1]
        posts.append({
            "id": canonical,
            "title": title_from_slug(canonical),
            "subtitle": "",
            "description": "",
            "slug": slug,
            "canonical_url": canonical,
            "post_date": pub_date,
            "source_mode": "rss_latest_jina_fallback",
        })
    return ArchiveResult(posts=posts, offset_probe=[{"offset": 0, "returned": len(posts), "new": len(posts)}])


def canonicalize_post_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def post_url(publication: str, post: dict[str, Any]) -> str:
    raw = post.get("canonical_url") or post.get("url")
    if raw:
        return canonicalize_post_url(str(raw))
    slug = post.get("slug") or slugify(str(post.get("title") or post.get("id") or "post"))
    return f"{normalize_publication(publication)}/p/{slug}"


class BodyTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture = False
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        attrs_dict = {k: v or "" for k, v in attrs}
        cls = attrs_dict.get("class", "")
        if tag in {"article", "main"} or "body" in cls or "post" in cls:
            self.capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if text and (self.capture or len(text) > 80):
            self.parts.append(text)

    def text(self) -> str:
        return "\n\n".join(self.parts)


def fetch_body_text(url: str) -> str:
    parser = BodyTextParser()
    parser.feed(get_text(url))
    return parser.text()
