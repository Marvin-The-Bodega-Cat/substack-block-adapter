from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

from .models import MirrorConfig
from .mirror import mirror
from .substack import normalize_publication


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: Path) -> MirrorConfig:
    if tomllib is None:
        raise RuntimeError("tomllib is required; use Python 3.11+")
    data = tomllib.loads(path.read_text())
    if "publication" not in data:
        raise ValueError(f"{path} must contain publication = \"https://...\"")
    return MirrorConfig(
        publication=str(data["publication"]),
        out=str(data.get("out", "mirror")),
        block_id=data.get("block_id"),
        fetch_bodies=parse_bool(data.get("fetch_bodies", False)),
        source_id_prefix=str(data.get("source_id_prefix", "s01-substack")),
        source_mode=str(data.get("source_mode", "archive")),
    )


def write_config(path: Path, config: MirrorConfig) -> None:
    block_id = config.block_id or "substack-mirror"
    body = (
        f'publication = "{normalize_publication(config.publication)}"\n'
        f'out = "{config.out}"\n'
        f'block_id = "{block_id}"\n'
        f'fetch_bodies = {str(config.fetch_bodies).lower()}\n'
        f'source_id_prefix = "{config.source_id_prefix}"\n'
        f'source_mode = "{config.source_mode}"\n'
    )
    path.write_text(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="substack-block", description="Mirror a Substack into a Data Mine block.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-config", help="Write substack-block.toml")
    init.add_argument("--publication", required=True)
    init.add_argument("--out", default="mirror")
    init.add_argument("--block-id", default="substack-mirror")
    init.add_argument("--fetch-bodies", action="store_true")
    init.add_argument("--source-mode", choices=["archive", "rss_latest"], default="archive")
    init.add_argument("--config", default="substack-block.toml")

    m = sub.add_parser("mirror", help="Mirror a publication now")
    m.add_argument("--publication", required=True)
    m.add_argument("--out", default="mirror")
    m.add_argument("--block-id")
    m.add_argument("--fetch-bodies", action="store_true")
    m.add_argument("--source-id-prefix", default="s01-substack")
    m.add_argument("--source-mode", choices=["archive", "rss_latest"], default="archive")
    m.add_argument("--json", action="store_true")

    w = sub.add_parser("watch", help="Run mirror from TOML config")
    w.add_argument("--config", default="substack-block.toml")
    w.add_argument("--json", action="store_true")

    sub.add_parser("sources", help="List available source adapters")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "sources":
            print("substack")
            return 0
        if args.command == "init-config":
            config = MirrorConfig(
                publication=args.publication,
                out=args.out,
                block_id=args.block_id,
                fetch_bodies=args.fetch_bodies,
                source_mode=args.source_mode,
            )
            write_config(Path(args.config), config)
            print(f"wrote {args.config}")
            return 0
        if args.command == "mirror":
            config = MirrorConfig(
                publication=args.publication,
                out=args.out,
                block_id=args.block_id,
                fetch_bodies=args.fetch_bodies,
                source_id_prefix=args.source_id_prefix,
                source_mode=args.source_mode,
            )
            result = mirror(config)
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"mirrored {result['post_count']} posts to {result['out']}; completeness_gate_passed={result['completeness_gate_passed']}")
            return 0
        if args.command == "watch":
            config = load_config(Path(args.config))
            result = mirror(config)
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"mirrored {result['post_count']} posts to {result['out']}; completeness_gate_passed={result['completeness_gate_passed']}")
            return 0
    except Exception as exc:
        print(f"substack-block: error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
