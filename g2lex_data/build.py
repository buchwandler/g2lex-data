from __future__ import annotations

import json
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import g2lex

from . import __version__
from .common import ASSET_DIR, MANIFEST_DIR, sha256_file, write_json
from .config import AssetConfig, load_config
from .espeak import EspeakBackend
from .inventory import build_word_inventory
from .sources import ResolvedSource, resolve_source
from .transforms import TransformResult, apply
from .transforms.espeak import generate_espeak_pair

MANIFEST_SCHEMA_VERSION = 1
GENERATOR_CONTRACT = 2


def _g2lex_version() -> str:
    try:
        return version("g2lex")
    except PackageNotFoundError:
        return getattr(g2lex, "__version__", "0+unknown")


def validate_source(
    record: AssetConfig, *, parse: bool = True, resolved_source: ResolvedSource | None = None
) -> dict[str, object]:
    resolved = resolved_source or resolve_source(record)
    path = resolved.path
    if not path.is_file():
        raise FileNotFoundError(f"missing source for {record.id}: {path}")
    if record.source_provider == "file":
        if path.stat().st_size != record.source_size:
            raise ValueError(f"source size mismatch for {record.id}")
        if sha256_file(path) != record.source_sha256:
            raise ValueError(f"source SHA-256 mismatch for {record.id}")
    if record.source_provider == "g2lex-assets":
        resolved_paths = resolved.metadata.get("source_paths")
        if not isinstance(resolved_paths, dict):
            raise ValueError(f"missing parent paths for {record.id}")
        source_paths = {source_id: Path(str(path)) for source_id, path in resolved_paths.items()}
        inventory = build_word_inventory(source_paths, locale=record.id.split(":", 1)[0])
        return {
            "entry_count": len(inventory.keys),
            "logical_sha256": inventory.logical_sha256,
            "format": record.source_format,
            "provider": record.source_provider,
            "resolved": dict(resolved.metadata),
            "word_inventory": {
                "source_ids": list(inventory.source_ids),
                "source_entry_counts": inventory.source_entry_counts,
                "union_entry_count": len(inventory.keys),
                "duplicate_key_count": inventory.duplicate_key_count,
                "logical_sha256": inventory.logical_sha256,
            },
        }
    if record.source_provider == "lexhint":
        return {
            "entry_count": None,
            "logical_sha256": None,
            "format": record.source_format,
            "provider": record.source_provider,
            "resolved": dict(resolved.metadata),
        }
    if not parse:
        return {}
    parsed = g2lex.read_typed_lexicon(path, format=record.source_format, source_id=record.source_id)
    values = tuple(parsed.entries.values())
    if record.kind == "membership":
        if not values or any(value is not g2lex.WORD_ONLY for value in values):
            raise ValueError(f"membership source is not WORD_ONLY: {path}")
    elif any(value is g2lex.WORD_ONLY for value in values):
        raise ValueError(f"pronunciation source contains WORD_ONLY: {path}")
    return {
        "entry_count": len(parsed),
        "logical_sha256": parsed.logical_sha256,
        "format": record.source_format,
        "provider": record.source_provider,
        "resolved": dict(resolved.metadata),
    }


def _transform_metadata(result: TransformResult | None) -> dict[str, object]:
    if result is None:
        return {}
    return {
        "id": result.metadata.get("transform"),
        "inputs": result.metadata.get("transform_inputs", {}),
        "report_sha256": result.metadata.get("transform_report_sha256"),
    }


def _build_derived(record: AssetConfig, *, data_version: str) -> dict[str, object]:
    config = load_config()
    source_paths: dict[str, Path] = {}
    for source_id in record.source_ids:
        parent = config.asset(source_id)
        build_one(parent, data_version=data_version)
        source_paths[source_id] = ASSET_DIR / parent.asset_name
    locale = record.id.split(":", 1)[0]
    inventory = build_word_inventory(source_paths, locale=locale)
    inputs = record.transform_inputs or {}
    backend = EspeakBackend(
        git_revision=str(inputs.get("espeak_git_revision", record.revision)),
        expected_version=(
            str(inputs["expected_espeak_version"])
            if inputs.get("expected_espeak_version")
            else None
        ),
    )
    try:
        pair = generate_espeak_pair(
            inventory=inventory,
            voice=str(inputs["voice"]),
            backend=backend,
        )
    finally:
        backend.close()
    entries = pair.normal_entries if record.name == "espeak" else pair.piper_entries
    report = {
        **pair.shared_report,
        "variant": pair.normal_report if record.name == "espeak" else pair.piper_report,
    }
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name
    with tempfile.TemporaryDirectory(prefix=f".{record.slug}.transform.") as temp_name:
        temp_dir = Path(temp_name)
        input_path = temp_dir / f"{record.slug}.json"
        input_path.write_text(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        report_path = temp_dir / f"{record.slug}.transform-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        transform_inputs = {**inputs, "generator": pair.shared_report["generator"]}
        transform_result = TransformResult(
            input_path,
            "json-map",
            {
                "transform": record.transform,
                "transform_inputs": transform_inputs,
                "source_metadata": {"word_inventory": report["word_inventory"]},
                "transform_report_sha256": sha256_file(report_path),
            },
            report_path,
        )
        g2lex.read_typed_lexicon(input_path, format="json-map", source_id=record.source_id)
        g2lex.pack_file(
            input_path,
            asset_path,
            input_format="json-map",
            source_id=record.source_id,
            metadata={
                "schema_version": 1,
                "contract_version": 1,
                "catalog_id": record.id,
                "language": record.language,
                "name": record.name,
                "display_name": record.display_name,
                "kind": record.kind,
                "phoneme_encoding": record.phoneme_encoding,
                "source_id": record.source_id,
                "source_format": record.source_format,
                "provider": record.provider,
                "revision": record.revision,
                "source_url": record.source_url,
                "license_expression": record.license_expression,
                "license_url": record.license_url,
                "attribution": record.attribution,
                "data_version": data_version,
                "producer": "g2lex-data",
                "producer_version": __version__,
                "g2lex_version": _g2lex_version(),
                "source_ids": list(record.source_ids),
                "word_inventory": report["word_inventory"],
                "transform": _transform_metadata(transform_result),
            },
        )
        verification = g2lex.verify_file(input_path, asset_path, input_format="json-map")
        if not verification.get("lossless"):
            raise ValueError(f"lossless verification failed for {record.id}: {verification}")
        inspected = g2lex.inspect_file(asset_path)
    source_payload = {
        "id": list(record.source_ids),
        "provider_type": record.source_provider,
        "path": None,
        "format": record.source_format,
        "url": record.source_url,
        "revision": record.revision,
        "sha256": None,
        "size": None,
        "entry_count": inventory.source_entry_counts,
        "logical_sha256": inventory.logical_sha256,
        "provider": record.provider,
        "license_expression": record.license_expression,
        "license_url": record.license_url,
        "attribution": record.attribution,
        "resolved": {
            "source_ids": list(record.source_ids),
            "source_paths": {key: str(value) for key, value in source_paths.items()},
        },
    }
    manifest = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "contract_version": 1,
        "id": record.id,
        "language": record.language,
        "name": record.name,
        "display_name": record.display_name,
        "kind": record.kind,
        "phoneme_encoding": record.phoneme_encoding,
        "data_version": data_version,
        "producer": {"name": "g2lex-data", "version": __version__},
        "g2lex": {"version": _g2lex_version(), "generator_contract": GENERATOR_CONTRACT},
        "source": source_payload,
        "word_inventory": report["word_inventory"],
        "transform": _transform_metadata(transform_result),
        "asset": {
            "name": record.asset_name,
            "filename": record.asset_name,
            "sha256": sha256_file(asset_path),
            "size": asset_path.stat().st_size,
            "format": inspected["format"],
            "schema": inspected["schema"],
            "entry_count": inspected["entry_count"],
            "logical_sha256": inspected["logical_sha256"],
        },
        "verification": {
            "source_integrity": True,
            "transform_deterministic": True,
            "lossless": True,
            "typed_values_preserved": True,
            "variant_order_preserved": True,
            "generated_from_validated_output": True,
            "pair_key_parity": True,
        },
    }
    write_json(MANIFEST_DIR / record.manifest_name, manifest)
    return manifest


def build_one(record: AssetConfig, *, data_version: str = "unreleased") -> dict[str, object]:
    if record.source_provider == "g2lex-assets":
        return _build_derived(record, data_version=data_version)
    resolved_source = resolve_source(record)
    source_info = validate_source(record, resolved_source=resolved_source)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name

    with tempfile.TemporaryDirectory(prefix=f".{record.slug}.transform.") as temp_name:
        transform_result = apply(
            record, resolved_source.path, Path(temp_name), source_metadata=resolved_source.metadata
        )
        input_path = transform_result.input_path if transform_result else resolved_source.path
        input_format = transform_result.input_format if transform_result else record.source_format
        g2lex.read_typed_lexicon(input_path, format=input_format, source_id=record.source_id)
        g2lex.pack_file(
            input_path,
            asset_path,
            input_format=input_format,
            source_id=record.source_id,
            metadata={
                "schema_version": 1,
                "contract_version": 1,
                "catalog_id": record.id,
                "language": record.language,
                "name": record.name,
                "display_name": record.display_name,
                "kind": record.kind,
                "phoneme_encoding": record.phoneme_encoding,
                "source_id": record.source_id,
                "source_format": record.source_format,
                "provider": record.provider,
                "revision": record.revision,
                "source_url": record.source_url,
                "license_expression": record.license_expression,
                "license_url": record.license_url,
                "attribution": record.attribution,
                "data_version": data_version,
                "producer": "g2lex-data",
                "producer_version": __version__,
                "g2lex_version": _g2lex_version(),
                "transform": _transform_metadata(transform_result),
            },
        )
        verification = g2lex.verify_file(input_path, asset_path, input_format=input_format)
        if not verification.get("lossless"):
            raise ValueError(f"lossless verification failed for {record.id}: {verification}")
        inspected = g2lex.inspect_file(asset_path)

    source_metadata = dict(resolved_source.metadata)
    source_payload: dict[str, object] = {
        "id": record.source_id,
        "provider_type": record.source_provider,
        "path": record.source,
        "format": record.source_format,
        "url": record.source_url,
        "revision": record.revision,
        "sha256": record.source_sha256,
        "size": record.source_size,
        "entry_count": source_info["entry_count"],
        "logical_sha256": source_info["logical_sha256"],
        "provider": record.provider,
        "license_expression": record.license_expression,
        "license_url": record.license_url,
        "attribution": record.attribution,
        "resolved": source_metadata,
    }
    if record.source_provider == "lexhint":
        source_payload.update(
            {
                "revision": source_metadata["release_tag"],
                "sha256": source_metadata["sqlite_sha256"],
                "size": source_metadata["sqlite_size"],
                "selector": {
                    "language": source_metadata["language"],
                    "source_variant": source_metadata["source_variant"],
                    "variant": source_metadata["variant"],
                    "schema_version": source_metadata["schema_version"],
                    "version_policy": "latest-compatible",
                },
            }
        )
    manifest: dict[str, object] = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "contract_version": 1,
        "id": record.id,
        "language": record.language,
        "name": record.name,
        "display_name": record.display_name,
        "kind": record.kind,
        "phoneme_encoding": record.phoneme_encoding,
        "data_version": data_version,
        "producer": {"name": "g2lex-data", "version": __version__},
        "g2lex": {"version": _g2lex_version(), "generator_contract": GENERATOR_CONTRACT},
        "source": source_payload,
        "transform": _transform_metadata(transform_result),
        "asset": {
            "name": record.asset_name,
            "filename": record.asset_name,
            "sha256": sha256_file(asset_path),
            "size": asset_path.stat().st_size,
            "format": inspected["format"],
            "schema": inspected["schema"],
            "entry_count": inspected["entry_count"],
            "logical_sha256": inspected["logical_sha256"],
        },
        "verification": {
            "source_integrity": True,
            "transform_deterministic": True,
            "lossless": True,
            "typed_values_preserved": True,
            "variant_order_preserved": True,
            "generated_from_validated_output": True,
        },
    }
    write_json(MANIFEST_DIR / record.manifest_name, manifest)
    return manifest


def build(
    ids: list[str] | None = None, *, data_version: str = "unreleased"
) -> tuple[dict[str, object], ...]:
    config = load_config()
    records = config.assets if not ids else tuple(config.asset(identifier) for identifier in ids)
    return tuple(build_one(record, data_version=data_version) for record in records)
