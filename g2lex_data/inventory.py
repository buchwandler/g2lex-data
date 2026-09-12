from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import g2lex


@dataclass(frozen=True, slots=True)
class WordInventory:
    locale: str
    source_ids: tuple[str, ...]
    source_entry_counts: dict[str, int]
    keys: tuple[str, ...]
    duplicate_key_count: int
    logical_sha256: str


def logical_sha256_for_keys(keys: tuple[str, ...]) -> str:
    digest = sha256()
    for key in keys:
        encoded = key.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

def build_word_inventory(
    source_paths: Mapping[str, Path],
    *,
    locale: str,
) -> WordInventory:
    if not locale or not locale.strip():
        raise ValueError("locale must be non-empty")
    source_ids = tuple(sorted(source_paths))
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source IDs must be unique")
    for source_id in source_ids:
        if source_id.split(":", 1)[0] != locale:
            raise ValueError(f"source {source_id} does not belong to locale {locale}")

    all_keys: set[str] = set()
    source_entry_counts: dict[str, int] = {}
    for source_id in source_ids:
        path = Path(source_paths[source_id])
        with g2lex.open(path) as lexicon:
            keys = tuple(lexicon.keys())
        source_entry_counts[source_id] = len(keys)
        all_keys.update(keys)

    ordered_keys = tuple(sorted(all_keys))
    duplicate_key_count = sum(source_entry_counts.values()) - len(ordered_keys)
    return WordInventory(
        locale=locale,
        source_ids=source_ids,
        source_entry_counts=source_entry_counts,
        keys=ordered_keys,
        duplicate_key_count=duplicate_key_count,
        logical_sha256=logical_sha256_for_keys(ordered_keys),
    )


__all__ = ["WordInventory", "build_word_inventory", "logical_sha256_for_keys"]
