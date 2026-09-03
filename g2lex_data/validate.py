from __future__ import annotations

import tempfile
from pathlib import Path

import g2lex

from .build import validate_source
from .common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR, read_json, sha256_file
from .config import AssetConfig, load_config
from .sources import resolve_source
from .transforms import apply


def validate_one(
    record: AssetConfig,
    *,
    verify_transform: bool = True,
    verify_source: bool = True,
) -> None:
    resolved_source = resolve_source(record)
    source_info = validate_source(record, parse=verify_source, resolved_source=resolved_source)
    asset_path = ASSET_DIR / record.asset_name
    manifest_path = MANIFEST_DIR / record.manifest_name
    if not asset_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"missing build output for {record.id}")
    manifest = read_json(manifest_path)
    if manifest.get("id") != record.id:
        raise ValueError(f"manifest id mismatch for {record.id}")
    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise TypeError(f"invalid manifest asset object for {record.id}")
    if sha256_file(asset_path) != asset.get("sha256"):
        raise ValueError(f"asset SHA mismatch for {record.id}")
    if asset_path.stat().st_size != asset.get("size"):
        raise ValueError(f"asset size mismatch for {record.id}")
    if asset.get("entry_count") != g2lex.inspect_file(asset_path).get("entry_count"):
        raise ValueError(f"asset entry count mismatch for {record.id}")
    if verify_transform:
        with tempfile.TemporaryDirectory(prefix=f".{record.slug}.validate.") as temp_name:
            result = apply(record, resolved_source.path, Path(temp_name))
            input_path = result.input_path if result else resolved_source.path
            input_format = result.input_format if result else record.source_format
            verification = g2lex.verify_file(input_path, asset_path, input_format=input_format)
            if not verification.get("lossless"):
                raise ValueError(f"asset no longer verifies losslessly for {record.id}")

    source = manifest.get("source")
    if not isinstance(source, dict):
        raise TypeError(f"invalid manifest source object for {record.id}")
    if source.get("sha256") != record.source_sha256 or source.get("size") != record.source_size:
        raise ValueError(f"manifest source pin mismatch for {record.id}")
    if verify_source and source.get("entry_count") != source_info["entry_count"]:
        raise ValueError(f"manifest source entry count mismatch for {record.id}")


def validate_catalog(path: Path = CATALOG_PATH, *, ids: list[str] | None = None) -> None:
    catalog = read_json(path)
    if (
        catalog.get("catalog_version") != 1
        or catalog.get("runtime_contract") != "g2lex-data.catalog.v1"
    ):
        raise ValueError("unsupported catalog contract")
    artifacts = catalog.get("artifacts")
    config = load_config()
    records = (
        config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    )
    if not isinstance(artifacts, list) or len(artifacts) != len(records):
        raise ValueError("catalog must contain exactly one artifact per configured asset")
    expected_ids = {record.id for record in records}
    actual_ids: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TypeError("catalog artifacts must be objects")
        identifier = artifact.get("id")
        if not isinstance(identifier, str) or identifier in actual_ids:
            raise ValueError("catalog artifact ids must be unique strings")
        actual_ids.add(identifier)
        if identifier not in expected_ids:
            raise ValueError(f"unknown catalog artifact {identifier}")
        asset = artifact.get("asset")
        manifest = artifact.get("manifest")
        if not isinstance(asset, dict) or not isinstance(manifest, dict):
            raise TypeError(f"invalid catalog artifact references for {identifier}")
        if not isinstance(asset.get("sha256"), str) or len(asset["sha256"]) != 64:
            raise ValueError(f"invalid catalog asset hash for {identifier}")
        if not isinstance(manifest.get("sha256"), str) or len(manifest["sha256"]) != 64:
            raise ValueError(f"invalid catalog manifest hash for {identifier}")
        for key in ("url",):
            if not str(asset.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog asset URL for {identifier}")
            if not str(manifest.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog manifest URL for {identifier}")
    if actual_ids != expected_ids:
        raise ValueError("catalog IDs do not match configured assets")


def validate_all(
    *,
    catalog: bool = False,
    ids: list[str] | None = None,
    verify_transform: bool = True,
    verify_source: bool = True,
) -> None:
    config = load_config()
    records = (
        config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    )
    for record in records:
        validate_one(record, verify_transform=verify_transform, verify_source=verify_source)
    if catalog:
        validate_catalog(ids=ids)
