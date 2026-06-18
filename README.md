# Substack Block Adapter

A standalone Data Mine source adapter that turns a Substack publication into a GitHub-backed mirror and a frozen block.

The useful boundary:

- Substack is the live source.
- The mirror repository is the receipt trail.
- `block.json` is the frozen cut that downstream Data Mine pipelines consume.

Sources are not blocks. Sources are where reality keeps changing its story.

## What it does

`substack-block`:

1. supports two source modes:
   - `archive`: paginates the Substack archive API for a full initial cut;
   - `rss_latest`: reads Substack's built-in `/feed` RSS for ongoing latest-post watchers;
2. cross-checks discovered post URLs against `sitemap.xml` when available;
3. writes one markdown file per post;
4. writes raw source JSON per post;
5. writes a Data Mine compatible `block.json` with ordered `SourceRecord` rows;
6. writes scrape/update receipts;
7. supports a weekly GitHub Actions watcher that commits newly discovered posts.

## Install

```bash
python3 -m pip install -e .
```

## Quick start

```bash
substack-block init-config --publication https://example.substack.com --out mirror --source-mode rss_latest
substack-block watch --config substack-block.toml
```

Or run directly:

```bash
substack-block mirror \
  --publication https://example.substack.com \
  --out mirror \
  --block-id example-substack-weekly \
  --source-mode archive
```

## Repository mirror shape

```text
mirror/
  README.md
  block.json
  index.json
  posts/
    2026-06-18-post-slug.md
  raw/
    <post-id>.json
  receipts/
    scrape_completeness_report.json
    update_receipt.json
```

## Weekly watcher

This repository includes `.github/workflows/weekly-substack-mirror.yml`.

To use it in a mirror repo:

1. commit `substack-block.toml` with your publication URL;
2. enable GitHub Actions;
3. the workflow runs weekly and can also be dispatched manually;
4. if `mirror/` changes, the workflow commits the update.

Example config:

```toml
publication = "https://example.substack.com"
out = "mirror"
block_id = "example-substack"
fetch_bodies = false
source_mode = "rss_latest"
```

`fetch_bodies = false` is the safe default. It mirrors archive metadata and stable URLs. Set it true only if you accept extra HTML fetching and parsing variance.

Use `source_mode = "archive"` for a full initial mirror. Use `source_mode = "rss_latest"` for scheduled GitHub Actions watchers: it reads the built-in RSS feed, avoids the archive API path that can 403 from GitHub-hosted runners, and preserves existing mirrored raw posts while appending feed-discovered posts. RSS is intentionally a latest-post source, not a comprehensive historical source.

## Completeness gate

The adapter records:

- total unique API posts;
- offset probe history;
- sitemap `/p/` URL count;
- API URLs missing from sitemap;
- sitemap URLs missing from API.

A mirror is only called comprehensive when both diff counts are zero and archive pagination terminates on a zero-new batch.

## Data Mine contract

`block.json` records use stable ordered IDs:

```json
{
  "record_id": "s01-substack-r000001",
  "source_type": "substack",
  "source_id": "123456",
  "title": "Post title",
  "text": "Title and subtitle or fetched body text",
  "timestamp": "2026-06-18T00:00:00Z",
  "uri": "https://example.substack.com/p/post-slug",
  "metadata": {}
}
```

The block includes a deterministic `source_config_fingerprint` so future cuts can be compared without vibes. Vibes remain regrettably popular.

## Public-safety note

This adapter is for public Substack posts. Private archives, paid content, leaked exports, or credentialed scraping do not belong in public mirror repos unless the rights and privacy boundary are explicit.
