from __future__ import annotations

from pathlib import Path

from .common import CATALOG_PATH, MANIFEST_DIR, sha256_file, write_json
from .config import load_config


def _release_root(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}"


def _data_tag(config, version: str) -> str:
    prefix = config.release_tag_prefix
    return version if version.startswith(prefix) else f"{prefix}{version}"


def _join_url(root: str, filename: str) -> str:
    return root.rstrip("/") + "/" + filename


def build_catalog(
    version: str,
    *,
    base_url: str | None = None,
    output: Path = CATALOG_PATH,
    ids: list[str] | None = None,
) -> dict[str, object]:
    if not version or "/" in version or version.isspace():
        raise ValueError("version must be a non-empty release identifier")
    config = load_config()
    records = (
        config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    )
    tag = _data_tag(config, version)
    root = base_url or _release_root(config.repository, tag)
    artifacts: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in records:
        manifest_path = MANIFEST_DIR / record.manifest_name
        if not manifest_path.is_file():
            raise FileNotFoundError(f"manifest missing for {record.id}; build assets first")
        manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("id") != record.id:
            raise ValueError(f"manifest id mismatch for {record.id}")
        if manifest.get("data_version") != version:
            raise ValueError(
                f"manifest data version mismatch for {record.id}: "
                f"expected {version}, got {manifest.get('data_version')}"
            )
        if record.id in seen:
            raise ValueError(f"duplicate catalog id: {record.id}")
        seen.add(record.id)
        asset = manifest.get("asset")
        source = manifest.get("source")
        if not isinstance(asset, dict) or not isinstance(source, dict):
            raise TypeError(f"invalid manifest for {record.id}")
        artifacts.append(
            {
                "id": record.id,
                "language": manifest["language"],
                "name": manifest["name"],
                "display_name": manifest["display_name"],
                "kind": manifest["kind"],
                "phoneme_encoding": manifest["phoneme_encoding"],
                "data_version": version,
                "release_tag": tag,
                "provider": source["provider"],
                "license": {
                    "expression": source["license_expression"],
                    "url": source["license_url"],
                    "attribution": source["attribution"],
                },
                "source": {
                    "provider": source["provider"],
                    "revision": source["revision"],
                    "license_expression": source["license_expression"],
                },
                "manifest": {
                    "name": record.manifest_name,
                    "url": _join_url(root, record.manifest_name),
                    "sha256": sha256_file(manifest_path),
                    "size": manifest_path.stat().st_size,
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
                "word_inventory_sources": source.get("id"),
                "generator": (manifest.get("transform") or {}).get("inputs", {}).get("generator"),
                "variant": (
                    {
                        "family": "espeak",
                        "mode": "piper-ipa3" if record.name == "espeak-piper" else "ipa",
                    }
                    if record.source_provider == "g2lex-assets"
                    else None
                ),
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
