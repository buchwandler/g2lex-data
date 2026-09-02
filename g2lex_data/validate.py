from __future__ import annotations

import g2lex

from .common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR, read_json, sha256_file
from .config import AssetConfig, load_config


def validate_one(record: AssetConfig) -> None:
    asset_path = ASSET_DIR / record.asset_name
    manifest_path = MANIFEST_DIR / record.manifest_name
    if not asset_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"missing build output for {record.id}")
    manifest = read_json(manifest_path)
    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise ValueError(f"invalid manifest asset object for {record.id}")
    if sha256_file(asset_path) != asset.get("sha256"):
        raise ValueError(f"asset SHA mismatch for {record.id}")
    verification = g2lex.verify_file(
        record.source_path,
        asset_path,
        input_format=record.source_format,
    )
    if not verification.get("lossless"):
        raise ValueError(f"asset no longer verifies losslessly for {record.id}")


def validate_catalog(path=CATALOG_PATH) -> None:
    catalog = read_json(path)
    if catalog.get("catalog_version") != 1:
        raise ValueError("unsupported catalog version")
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("catalog must contain artifacts")
    ids: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TypeError("catalog artifacts must be objects")
        identifier = artifact.get("id")
        if not isinstance(identifier, str) or identifier in ids:
            raise ValueError("catalog artifact ids must be unique strings")
        ids.add(identifier)
        asset = artifact.get("asset")
        if not isinstance(asset, dict) or len(str(asset.get("sha256", ""))) != 64:
            raise ValueError(f"invalid catalog asset for {identifier}")
        url = str(asset.get("url", ""))
        if not url.startswith(("https://", "file://")):
            raise ValueError(f"unsupported catalog asset URL for {identifier}: {url}")


def validate_all(*, catalog: bool = False) -> None:
    for record in load_config().assets:
        validate_one(record)
    if catalog:
        validate_catalog()
