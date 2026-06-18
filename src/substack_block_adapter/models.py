from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    record_id: str
    source_type: str
    source_id: str
    title: str
    text: str
    timestamp: str | None
    uri: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MirrorConfig:
    publication: str
    out: str = "mirror"
    block_id: str | None = None
    fetch_bodies: bool = False
    source_id_prefix: str = "s01-substack"
    source_mode: str = "archive"

    def normalized_for_hash(self) -> dict[str, Any]:
        return {
            "publication": self.publication.rstrip("/"),
            "out": self.out,
            "block_id": self.block_id,
            "fetch_bodies": self.fetch_bodies,
            "source_id_prefix": self.source_id_prefix,
            "source_mode": self.source_mode,
        }
