from __future__ import annotations

import json

from substack_block_adapter.cli import main
from substack_block_adapter.models import MirrorConfig
from substack_block_adapter.mirror import mirror
from substack_block_adapter.substack import fetch_feed, normalize_publication, slugify


def test_normalize_publication():
    assert normalize_publication("example.substack.com/p/ignored") == "https://example.substack.com"
    assert normalize_publication("https://example.substack.com/") == "https://example.substack.com"


def test_slugify():
    assert slugify("Hello, Cruel World!") == "hello-cruel-world"


def test_mirror_builds_block_and_receipts(tmp_path, monkeypatch):
    pages = {
        0: [
            {
                "id": 2,
                "title": "Second Post",
                "subtitle": "B",
                "slug": "second-post",
                "canonical_url": "https://demo.substack.com/p/second-post",
                "post_date": "2026-02-01T00:00:00Z",
                "wordcount": 200,
            },
            {
                "id": 1,
                "title": "First Post",
                "subtitle": "A",
                "slug": "first-post",
                "canonical_url": "https://demo.substack.com/p/first-post",
                "post_date": "2026-01-01T00:00:00Z",
                "wordcount": 100,
            },
        ],
        20: [],
    }

    def fake_get_json(url: str):
        offset = int(url.split("offset=")[1])
        return pages[offset]

    sitemap = """<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://demo.substack.com/p/first-post</loc></url>
      <url><loc>https://demo.substack.com/p/second-post</loc></url>
    </urlset>
    """

    monkeypatch.setattr("substack_block_adapter.substack.get_json", fake_get_json)
    monkeypatch.setattr("substack_block_adapter.substack.get_text", lambda url: sitemap)

    out = tmp_path / "mirror"
    result = mirror(MirrorConfig(publication="demo.substack.com", out=str(out), block_id="demo"))
    assert result["post_count"] == 2
    assert result["completeness_gate_passed"] is True

    block = json.loads((out / "block.json").read_text())
    assert block["schema_version"] == "datamine.block.v1"
    assert [r["record_id"] for r in block["records"]] == ["s01-substack-r000001", "s01-substack-r000002"]
    assert block["records"][0]["title"] == "First Post"
    assert (out / "posts" / "2026-01-01-first-post.md").exists()

    report = json.loads((out / "receipts" / "scrape_completeness_report.json").read_text())
    assert report["total_api_posts"] == 2
    assert report["api_missing_from_sitemap_count"] == 0
    assert report["sitemap_missing_from_api_count"] == 0
    assert report["terminated_on_zero_new_batch"] is True


def test_cli_init_config_and_sources(tmp_path, capsys):
    cfg = tmp_path / "substack-block.toml"
    assert main(["init-config", "--publication", "demo.substack.com", "--config", str(cfg), "--block-id", "demo", "--source-mode", "rss_latest"]) == 0
    text = cfg.read_text()
    assert 'publication = "https://demo.substack.com"' in text
    assert 'source_mode = "rss_latest"' in text
    assert main(["sources"]) == 0
    assert "substack" in capsys.readouterr().out


def test_fetch_feed_parses_substack_rss(monkeypatch):
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
      <channel>
        <item>
          <title>Latest Post</title>
          <link>https://demo.substack.com/p/latest-post?utm_source=feed</link>
          <guid>https://demo.substack.com/p/latest-post</guid>
          <pubDate>Mon, 15 Jun 2026 12:32:55 GMT</pubDate>
          <description>A short summary</description>
          <content:encoded><![CDATA[<p>Hello</p>]]></content:encoded>
        </item>
      </channel>
    </rss>
    """
    monkeypatch.setattr("substack_block_adapter.substack.get_text", lambda url: rss)
    result = fetch_feed("demo.substack.com")
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post["title"] == "Latest Post"
    assert post["canonical_url"] == "https://demo.substack.com/p/latest-post"
    assert post["post_date"] == "2026-06-15T12:32:55Z"
    assert result.offset_probe == [{"offset": 0, "returned": 1, "new": 1}]


def test_rss_latest_preserves_existing_full_mirror_and_adds_new_post(tmp_path, monkeypatch):
    existing = {
        "id": 1,
        "title": "Old Post",
        "subtitle": "A",
        "slug": "old-post",
        "canonical_url": "https://demo.substack.com/p/old-post",
        "post_date": "2026-01-01T00:00:00Z",
    }
    out = tmp_path / "mirror"
    (out / "raw").mkdir(parents=True)
    (out / "raw" / "1.json").write_text(json.dumps(existing))

    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item><title>Old Post</title><link>https://demo.substack.com/p/old-post</link><guid>old</guid><pubDate>Thu, 01 Jan 2026 00:00:00 GMT</pubDate><description>A</description></item>
      <item><title>New Post</title><link>https://demo.substack.com/p/new-post</link><guid>new</guid><pubDate>Fri, 02 Jan 2026 00:00:00 GMT</pubDate><description>B</description></item>
    </channel></rss>"""
    sitemap = """<?xml version='1.0' encoding='UTF-8'?><urlset>
      <url><loc>https://demo.substack.com/p/old-post</loc></url>
      <url><loc>https://demo.substack.com/p/new-post</loc></url>
    </urlset>"""

    def fake_get_text(url: str):
        return rss if url.endswith("/feed") else sitemap

    monkeypatch.setattr("substack_block_adapter.substack.get_text", fake_get_text)
    result = mirror(MirrorConfig(publication="demo.substack.com", out=str(out), block_id="demo", source_mode="rss_latest"))
    assert result["post_count"] == 2
    report = json.loads((out / "receipts" / "scrape_completeness_report.json").read_text())
    assert report["source_mode"] == "rss_latest"
    assert report["latest_feed_posts"] == 2
    assert report["rss_latest_gate_passed"] is True
    assert (out / "posts" / "2026-01-02-new-post.md").exists()
