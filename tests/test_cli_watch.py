from __future__ import annotations

import json

from substack_block_adapter.cli import main


def test_watch_uses_config(tmp_path, monkeypatch):
    cfg = tmp_path / "substack-block.toml"
    out = tmp_path / "mirror"
    cfg.write_text(
        f'publication = "https://demo.substack.com"\n'
        f'out = "{out}"\n'
        f'block_id = "demo"\n'
        f'fetch_bodies = false\n'
    )

    monkeypatch.setattr("substack_block_adapter.substack.get_json", lambda url: [])
    monkeypatch.setattr(
        "substack_block_adapter.substack.get_text",
        lambda url: "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'></urlset>",
    )

    assert main(["watch", "--config", str(cfg)]) == 0
    block = json.loads((out / "block.json").read_text())
    assert block["block_id"] == "demo"
