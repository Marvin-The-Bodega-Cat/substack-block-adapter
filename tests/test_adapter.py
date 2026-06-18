from __future__ import annotations

import json

from substack_block_adapter.cli import main
from substack_block_adapter.models import MirrorConfig
from substack_block_adapter.mirror import mirror
from substack_block_adapter.substack import normalize_publication, slugify


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
    assert main(["init-config", "--publication", "demo.substack.com", "--config", str(cfg), "--block-id", "demo"]) == 0
    assert 'publication = "https://demo.substack.com"' in cfg.read_text()
    assert main(["sources"]) == 0
    assert "substack" in capsys.readouterr().out
