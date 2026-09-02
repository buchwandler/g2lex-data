from __future__ import annotations

from pathlib import Path

from .common import CATALOG_PATH, MANIFEST_DIR, read_json, sha256_file, write_json
from .config import load_config


def _release_root(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}"


def _join_url(root: str, filename: str) -> str:
    return root.rstrip("/") + "/" + filename


def build_catalog(version: str, *, base_url: str | None = None, output: Path = CATALOG_PATH) -> dict[str, object]:
    if not version or "/" in version or version.isspace():
        raise ValueError("version must be a non-empty release identifier")
    config = load_config()
    tag = f"{config.release_tag_prefix}{version}"
    root = base_url or _release_root(config.repository, tag)
    artifacts: list[dict[str, object]] = []
    for record in config.assets:
        manifest_path = MANIFEST_DIR / record.manifest_name
        if not manifest_path.is_file():
            raise FileNotFoundError(f"manifest missing for {record.id}; build assets first")
        manifest = read_json(manifest_path)
        asset = manifest["asset"]
        source = manifest["source"]
        assert isinstance(asset, dict) and isinstance(source, dict)
        artifacts.append(
            {
                "id": record.id,
                "language": record.language,
                "name": record.name,
                "display_name": record.display_name,
                "kind": record.kind,
                "phoneme_encoding": record.phoneme_encoding,
                "data_version": version,
                "release_tag": tag,
                "source": {
                    "provider": source["provider"],
                    "revision": source["revision"],
                    "license_expression": source["license_expression"],
                },
                "manifest": {
                    "name": record.manifest_name,
                    "url": _join_url(root, record.manifest_name),
                    "sha256": sha256_file(manifest_path),
                },
                "asset": {
                    "name": record.asset_name,
                    "url": _join_url(root, record.asset_name),
                    "sha256": asset["sha256"],
                    "size": asset["size"],
                    "format": asset["format"],
                    "schema": asset["schema"],
                    "entry_count": asset["entry_count"],
                    "logical_sha256": asset["logical_sha256"],
                },
            }
        )
    catalog: dict[str, object] = {
        "catalog_version": config.catalog_version,
        "runtime_contract": config.runtime_contract,
        "repository": config.repository,
        "data_version": version,
        "release_tag": tag,
        "artifacts": artifacts,
    }
    write_json(output, catalog)
    return catalog
