# Build receipt — substack-block-adapter v0.1.0

Date: 2026-06-18

## Promise

Build a standalone Data Mine adapter that can turn a Substack publication into a GitHub-backed mirror and a frozen block, with a weekly watcher that updates the mirror with new posts.

## Result

Built a standalone Python package and CLI named `substack-block-adapter`.

Implemented:

- `substack-block sources`
- `substack-block init-config --publication ...`
- `substack-block mirror --publication ... --out ... --block-id ...`
- `substack-block watch --config substack-block.toml`
- archive API pagination with zero-new-batch termination;
- sitemap `/p/` comparison completeness report;
- per-post markdown mirror;
- per-post raw JSON mirror;
- `block.json` with ordered Data Mine `SourceRecord` rows;
- deterministic source config fingerprint;
- update and scrape receipts;
- weekly GitHub Actions watcher.

## Verification

Local package install and test suite:

```text
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

Result:

```text
5 passed in 0.03s
```

CLI smoke:

```text
substack-block sources
substack-block init-config --publication example.substack.com ...
```

Result:

```text
substack
publication = "https://example.substack.com"
```

Live Substack smoke, public no-body metadata mirror:

```text
substack-block mirror --publication https://amywanderson.substack.com --out <tmp>/mirror --block-id live-smoke --json
```

Result:

```text
9 True <tmp>/mirror
```

The live smoke created non-empty `block.json` and `receipts/scrape_completeness_report.json` in a temporary directory.

## Boundary

No configured real mirror output is committed in this adapter repository. The committed data is source code, tests, docs, and example config only.

The workflow is safe in the adapter repo: if `substack-block.toml` is absent, it exits without trying to mirror.

## Caveat

`fetch_bodies=false` is the default. That produces stable metadata/post-pointer blocks. Full body mirroring is implemented with best-effort HTML text extraction, but body HTML is a less stable surface than the archive API. The adapter records this in receipts rather than pretending Substack is a library with manners.
