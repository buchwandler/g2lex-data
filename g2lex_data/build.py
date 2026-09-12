from __future__ import annotations

import json
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Self

import g2lex

from . import __version__
from .common import ASSET_DIR, MANIFEST_DIR, sha256_file, write_json
from .config import AssetConfig, load_config
from .espeak import EspeakBackend
from .inventory import WordInventory, build_word_inventory
from .sources import ResolvedSource, resolve_source
from .transforms import TransformResult, apply
from .transforms.espeak import EspeakPairResult, generate_espeak_pair

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


def _validate_espeak_pair_config(normal: AssetConfig, piper: AssetConfig) -> None:
    if normal.name != "espeak" or piper.name != "espeak-piper":
        raise ValueError("eSpeak pair must contain espeak and espeak-piper records")
    if normal.source_provider != "g2lex-assets" or piper.source_provider != "g2lex-assets":
        raise ValueError("eSpeak pair must use g2lex-assets providers")
    if normal.source_ids != piper.source_ids:
        raise ValueError("eSpeak pair source IDs differ")
    normal_inputs = normal.transform_inputs or {}
    piper_inputs = piper.transform_inputs or {}
    locale_fields = ("language",)
    for field in locale_fields:
        if getattr(normal, field) != getattr(piper, field):
            raise ValueError(f"eSpeak pair {field} differs")
    for field in ("voice", "espeak_git_revision", "expected_espeak_version", "piper_version"):
        if normal_inputs.get(field) != piper_inputs.get(field):
            raise ValueError(f"eSpeak pair transform input {field} differs")
    expected = (
        (normal_inputs.get("output_mode"), "ipa"),
        (piper_inputs.get("output_mode"), "ipa3"),
        (normal.phoneme_encoding, "ipa"),
        (piper.phoneme_encoding, "espeak-ipa3"),
        (normal.transform, "g2lex-espeak-ipa-v1"),
        (piper.transform, "g2lex-espeak-piper-ipa3-v1"),
    )
    if any(actual != expected_value for actual, expected_value in expected):
        raise ValueError("eSpeak pair output configuration is invalid")


def _build_source_record(record: AssetConfig, *, data_version: str) -> dict[str, object]:
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


def _write_espeak_variant(
    record: AssetConfig,
    *,
    entries: dict[str, str],
    pair: EspeakPairResult,
    inventory: WordInventory,
    source_paths: dict[str, Path],
    data_version: str,
) -> dict[str, object]:
    report = {
        **pair.shared_report,
        "variant": pair.normal_report if record.name == "espeak" else pair.piper_report,
    }
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name
    inputs = record.transform_inputs or {}
    with tempfile.TemporaryDirectory(prefix=f".{record.slug}.transform.") as temp_name:
        temp_dir = Path(temp_name)
        input_path = temp_dir / f"{record.slug}.json"
        input_path.write_text(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        report_path = temp_dir / f"{record.slug}.transform-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
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


class BuildSession:
    def __init__(self, *, data_version: str) -> None:
        self.config = load_config()
        self.data_version = data_version
        self.manifests: dict[str, dict[str, object]] = {}
        self._espeak_backend: EspeakBackend | None = None
        self._closed = False

    def build_record(self, record: AssetConfig) -> dict[str, object]:
        cached = self.manifests.get(record.id)
        if cached is not None:
            return cached
        if record.source_provider == "g2lex-assets":
            normal, piper = self.build_espeak_pair(record.id.split(":", 1)[0])
            return normal if record.name == "espeak" else piper
        manifest = _build_source_record(record, data_version=self.data_version)
        self.manifests[record.id] = manifest
        return manifest

    def build_id(self, identifier: str) -> dict[str, object]:
        return self.build_record(self.config.asset(identifier))

    def _get_espeak_backend(self, record: AssetConfig) -> EspeakBackend:
        if self._espeak_backend is None:
            inputs = record.transform_inputs or {}
            self._espeak_backend = EspeakBackend(
                git_revision=str(inputs.get("espeak_git_revision", record.revision)),
                expected_version=(
                    str(inputs["expected_espeak_version"])
                    if inputs.get("expected_espeak_version")
                    else None
                ),
            )
        return self._espeak_backend

    def espeak_backend(self, record: AssetConfig) -> EspeakBackend:
        return self._get_espeak_backend(record)

    def build_espeak_pair(self, locale: str) -> tuple[dict[str, object], dict[str, object]]:
        normal_id = f"{locale}:espeak"
        piper_id = f"{locale}:espeak-piper"
        normal_record = self.config.asset(normal_id)
        piper_record = self.config.asset(piper_id)
        normal_manifest = self.manifests.get(normal_id)
        piper_manifest = self.manifests.get(piper_id)
        if normal_manifest is not None and piper_manifest is not None:
            return normal_manifest, piper_manifest
        if normal_manifest is not None or piper_manifest is not None:
            raise RuntimeError(f"incomplete eSpeak pair cache for {locale}")
        _validate_espeak_pair_config(normal_record, piper_record)
        source_paths: dict[str, Path] = {}
        for source_id in normal_record.source_ids:
            parent = self.config.asset(source_id)
            self.build_record(parent)
            source_paths[source_id] = ASSET_DIR / parent.asset_name
        inventory = build_word_inventory(source_paths, locale=locale)
        inputs = normal_record.transform_inputs or {}
        pair = generate_espeak_pair(
            inventory=inventory,
            voice=str(inputs["voice"]),
            backend=self._get_espeak_backend(normal_record),
        )
        normal_manifest = _write_espeak_variant(
            normal_record,
            entries=pair.normal_entries,
            pair=pair,
            inventory=inventory,
            source_paths=source_paths,
            data_version=self.data_version,
        )
        piper_manifest = _write_espeak_variant(
            piper_record,
            entries=pair.piper_entries,
            pair=pair,
            inventory=inventory,
            source_paths=source_paths,
            data_version=self.data_version,
        )
        self.manifests[normal_id] = normal_manifest
        self.manifests[piper_id] = piper_manifest
        return normal_manifest, piper_manifest

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._espeak_backend is not None:
            self._espeak_backend.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def build_one(record: AssetConfig, *, data_version: str = "unreleased") -> dict[str, object]:
    with BuildSession(data_version=data_version) as session:
        return session.build_record(record)


def build(
    ids: list[str] | None = None, *, data_version: str = "unreleased"
) -> tuple[dict[str, object], ...]:
    config = load_config()
    records = config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    with BuildSession(data_version=data_version) as session:
        return tuple(session.build_record(record) for record in records)


def build_static(*, data_version: str = "unreleased") -> tuple[dict[str, object], ...]:
    from .build_plan import static_asset_ids

    config = load_config()
    return build(list(static_asset_ids(config)), data_version=data_version)

def build_espeak_pairs(
    locales: list[str], *, data_version: str = "unreleased"
) -> tuple[dict[str, object], ...]:
    with BuildSession(data_version=data_version) as session:
        manifests: list[dict[str, object]] = []
        seen: set[str] = set()
        for locale in locales:
            if locale in seen:
                continue
            seen.add(locale)
            normal, piper = session.build_espeak_pair(locale)
            manifests.extend((normal, piper))
        return tuple(manifests)


__all__ = [
    "BuildSession",
    "build",
    "build_espeak_pairs",
    "build_one",
    "validate_source",
]
