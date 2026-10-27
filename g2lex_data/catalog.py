from __future__ import annotations

from pathlib import Path

from .common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR, sha256_file, write_json
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
        artifact_entry: dict[str, object] = {
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
        resolver = manifest.get("resolver_index")
        transform = manifest.get("transform")
        transform_inputs = transform.get("inputs", {}) if isinstance(transform, dict) else {}
        if not isinstance(transform_inputs, dict):
            transform_inputs = {}
        if resolver is None and transform_inputs.get("pronresolve_version") is not None:
            raise ValueError(f"resolver index missing from manifest for {record.id}")
        if resolver is not None:
            if not isinstance(resolver, dict):
                raise TypeError(f"invalid resolver index metadata for {record.id}")
            index_name = resolver.get("path", resolver.get("name"))
            if (
                not isinstance(index_name, str)
                or not index_name
                or Path(index_name).name != index_name
            ):
                raise ValueError(f"invalid resolver index path for {record.id}")
            index_path = ASSET_DIR / index_name
            if not index_path.is_file():
                raise FileNotFoundError(f"resolver index missing for {record.id}: {index_path}")
            if sha256_file(index_path) != resolver.get("sha256"):
                raise ValueError(f"resolver index SHA mismatch for {record.id}")
            if index_path.stat().st_size != resolver.get("size"):
                raise ValueError(f"resolver index size mismatch for {record.id}")
            if resolver.get("dataset_version") != version:
                raise ValueError(f"resolver index data version mismatch for {record.id}")
            from pronresolve import load_index

            index = load_index(index_path)
            if (
                resolver.get("schema_version") != index.schema_version
                or resolver.get("language") != index.language
                or resolver.get("locale") != index.locale
            ):
                raise ValueError(f"resolver index identity mismatch for {record.id}")
            artifact_entry["resolver_index"] = {
                "name": index_name,
                "url": _join_url(root, index_name),
                "sha256": resolver["sha256"],
                "size": resolver["size"],
                "schema_version": index.schema_version,
                "language": index.language,
                "locale": index.locale,
                "dataset_version": version,
            }
        artifacts.append(artifact_entry)
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
