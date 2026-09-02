from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import g2lex

from . import __version__
from .common import ASSET_DIR, MANIFEST_DIR, sha256_file, write_json
from .config import AssetConfig, load_config

GENERATOR_CONTRACT = 1


def _g2lex_version() -> str:
    try:
        return version("g2lex")
    except PackageNotFoundError:
        return getattr(g2lex, "__version__", "0+unknown")


def validate_source(record: AssetConfig) -> None:
    path = record.source_path
    if not path.is_file():
        raise FileNotFoundError(f"missing source for {record.id}: {path}")
    if path.stat().st_size != record.source_size:
        raise ValueError(f"source size mismatch for {record.id}")
    if sha256_file(path) != record.source_sha256:
        raise ValueError(f"source SHA-256 mismatch for {record.id}")


def build_one(record: AssetConfig) -> dict[str, object]:
    validate_source(record)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name
    metadata: dict[str, object] = {
        "catalog_id": record.id,
        "source_id": record.source_id,
        "display_name": record.display_name,
        "language": record.language,
        "locale": record.language,
        "provider": record.provider,
        "revision": record.revision,
        "pronunciation_alphabet": record.phoneme_encoding,
        "license_expression": record.license_expression,
        "license_url": record.license_url,
        "attribution": record.attribution,
        "data_kind": record.kind,
        "parser_id": record.source_format,
        "parser_version": "1",
        "producer": "g2lex-data",
        "producer_version": __version__,
    }
    if record.source_url:
        metadata["source_url"] = record.source_url

    packed = g2lex.pack_file(
        record.source_path,
        asset_path,
        input_format=record.source_format,
        source_id=record.source_id,
        metadata=metadata,
    )
    verified = g2lex.verify_file(
        record.source_path,
        asset_path,
        input_format=record.source_format,
    )
    if not verified.get("lossless"):
        raise ValueError(f"lossless verification failed for {record.id}: {verified}")
    inspected = g2lex.inspect_file(asset_path)
    manifest: dict[str, object] = {
        "manifest_version": 1,
        "id": record.id,
        "language": record.language,
        "name": record.name,
        "display_name": record.display_name,
        "kind": record.kind,
        "phoneme_encoding": record.phoneme_encoding,
        "source": {
            "path": record.source,
            "format": record.source_format,
            "source_id": record.source_id,
            "sha256": record.source_sha256,
            "size": record.source_size,
            "provider": record.provider,
            "revision": record.revision,
            "url": record.source_url,
            "license_expression": record.license_expression,
            "license_url": record.license_url,
            "attribution": record.attribution,
        },
        "asset": {
            "name": record.asset_name,
            "sha256": sha256_file(asset_path),
            "size": asset_path.stat().st_size,
            "format": inspected["format"],
            "schema": inspected["schema"],
            "entry_count": inspected["entry_count"],
            "logical_sha256": inspected["logical_sha256"],
        },
        "build": {
            "g2lex_version": _g2lex_version(),
            "producer_version": __version__,
            "generator_contract": GENERATOR_CONTRACT,
            "deterministic": True,
            "self_verified": bool(packed.get("self_verified")),
            "lossless": True,
        },
    }
    write_json(MANIFEST_DIR / record.manifest_name, manifest)
    return manifest


def build(ids: list[str] | None = None) -> tuple[dict[str, object], ...]:
    config = load_config()
    records = config.assets if not ids else tuple(config.asset(identifier) for identifier in ids)
    return tuple(build_one(record) for record in records)
