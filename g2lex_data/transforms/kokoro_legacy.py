from __future__ import annotations

from pathlib import Path
from typing import Any

import g2lex

from ..common import ROOT, sha256_file
from ..config import AssetConfig
from . import TransformResult
from .common import serialize_entries

TRANSFORM_VERSION = "kokoro-legacy-collapse-v1"


def _required_text(inputs: dict[str, object], key: str, record_id: str) -> str:
    value = inputs.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{TRANSFORM_VERSION} requires {key} for {record_id}")
    return value


def _required_int(inputs: dict[str, object], key: str, record_id: str) -> int:
    value = inputs.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{TRANSFORM_VERSION} requires non-negative {key} for {record_id}")
    return value


def _validate_source(path: Path, *, expected_size: int, expected_hash: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing {label} source: {path}")
    if path.stat().st_size != expected_size:
        raise ValueError(f"{label} source size mismatch: {path}")
    if sha256_file(path) != expected_hash:
        raise ValueError(f"{label} source SHA-256 mismatch: {path}")


def _load(path: Path, *, source_id: str) -> Any:
    return g2lex.read_typed_lexicon(
        path,
        format="kokoro-json",
        source_id=source_id,
        allow_tagged=True,
        allow_lists=True,
    )


def _report(
    record: AssetConfig,
    source: Path,
    gold: Any,
    silver: Any | None,
    layered: Any,
    *,
    secondary_path: Path | None,
    secondary_hash: str | None,
    secondary_size: int | None,
) -> dict[str, object]:
    gold_aliases = g2lex.CaseAliasMapping(gold.entries)
    silver_aliases = g2lex.CaseAliasMapping(silver.entries) if silver is not None else None
    gold_keys = set(gold.entries)
    silver_keys = set(silver.entries) if silver is not None else set()
    overlap = gold_keys & silver_keys
    gold_effective_keys = set(gold_aliases)
    shadowed_exact = silver_keys & gold_keys
    shadowed_alias = (silver_keys - gold_keys) & (gold_effective_keys - gold_keys)
    conflicting = sum(gold.entries[key] != silver.entries[key] for key in overlap) if silver else 0
    return {
        "asset_id": record.id,
        "primary_source_path": record.source,
        "primary_source_sha256": sha256_file(source),
        "primary_source_size": source.stat().st_size,
        "secondary_source_path": str(secondary_path.relative_to(ROOT)) if secondary_path else None,
        "secondary_source_sha256": secondary_hash,
        "secondary_source_size": secondary_size,
        "raw_gold_entry_count": len(gold),
        "raw_silver_entry_count": len(silver) if silver is not None else 0,
        "effective_gold_alias_count": len(gold_aliases) - len(gold),
        "effective_silver_alias_count": len(silver_aliases) - len(silver) if silver_aliases else 0,
        "raw_overlapping_key_count": len(overlap),
        "conflicting_overlapping_value_count": conflicting,
        "keys_shadowed_by_higher_priority_gold_exact_matches": len(shadowed_exact),
        "keys_shadowed_by_higher_priority_gold_aliases": len(shadowed_alias),
        "final_effective_entry_count": len(layered),
    }


def transform_kokoro_legacy(record: AssetConfig, source: Path, temp_dir: Path) -> TransformResult:
    inputs = dict(record.transform_inputs or {})
    if inputs.get("source_format") != record.source_format or record.source_format != "kokoro-json":
        raise ValueError(f"{TRANSFORM_VERSION} requires kokoro-json for {record.id}")
    if inputs.get("case_aliases") is not True:
        raise ValueError(f"{TRANSFORM_VERSION} requires case_aliases=true for {record.id}")

    gold = _load(source, source_id=record.source_id)
    silver: Any | None = None
    secondary_path: Path | None = None
    secondary_hash: str | None = None
    secondary_size: int | None = None
    precedence = inputs.get("precedence")
    secondary_source = inputs.get("secondary_source")
    if secondary_source is None:
        if precedence != ["gold"]:
            raise ValueError(f"invalid single-source precedence for {record.id}")
    else:
        if not isinstance(secondary_source, str) or not secondary_source:
            raise ValueError(f"invalid secondary_source for {record.id}")
        if precedence != ["gold", "silver"]:
            raise ValueError(f"invalid layered precedence for {record.id}")
        secondary_path = ROOT / secondary_source
        secondary_hash = _required_text(inputs, "secondary_sha256", record.id)
        secondary_size = _required_int(inputs, "secondary_size", record.id)
        secondary_id = _required_text(inputs, "secondary_source_id", record.id)
        secondary_format = inputs.get("source_format")
        if secondary_format != "kokoro-json":
            raise ValueError(f"invalid secondary source format for {record.id}")
        _validate_source(
            secondary_path,
            expected_size=secondary_size,
            expected_hash=secondary_hash,
            label="secondary",
        )
        silver = _load(secondary_path, source_id=secondary_id)

    gold_effective = g2lex.CaseAliasMapping(gold.entries)
    layers = [g2lex.LexiconLayer("gold", gold_effective, {"precedence": 0})]
    if silver is not None:
        silver_effective = g2lex.CaseAliasMapping(silver.entries)
        layers.append(g2lex.LexiconLayer("silver", silver_effective, {"precedence": 1}))
    layered = g2lex.LayeredLexicon(layers)
    entries = {key: layered[key] for key in layered}

    temp_dir.mkdir(parents=True, exist_ok=True)
    intermediate = temp_dir / f"{record.slug}.json"
    intermediate.write_text(serialize_entries(entries), encoding="utf-8")
    transformed = g2lex.read_typed_lexicon(
        intermediate,
        format="json-map",
        source_id=record.source_id,
        allow_tagged=True,
        allow_lists=True,
    )
    report = _report(
        record,
        source,
        gold,
        silver,
        layered,
        secondary_path=secondary_path,
        secondary_hash=secondary_hash,
        secondary_size=secondary_size,
    )
    report["logical_transformed_mapping_sha256"] = transformed.logical_sha256
    report["serialized_transformed_source_sha256"] = sha256_file(intermediate)
    report_path = temp_dir / f"{record.slug}.transform-report.json"
    import json

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "transform": TRANSFORM_VERSION,
        "transform_inputs": inputs,
        "transform_report_sha256": sha256_file(report_path),
        "transform_report": report,
    }
    return TransformResult(intermediate, "json-map", metadata, report_path)
