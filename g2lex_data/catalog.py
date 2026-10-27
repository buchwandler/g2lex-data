from __future__ import annotations

from pathlib import Path

from .capabilities import NO_RESOLVABLE_AMBIGUITIES, NO_SENSE_LINKED_MAPPING
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
        capabilities = manifest.get("capabilities")
        resolution_capability = None
        if record.kind == "pronunciation":
            if not isinstance(capabilities, dict):
                raise ValueError(f"pronunciation capability is missing for {record.id}")
            resolution_capability = capabilities.get("pronunciation_resolution")
            if not isinstance(resolution_capability, dict):
                raise ValueError(f"pronunciation-resolution capability is missing for {record.id}")
            status = resolution_capability.get("status")
            if status not in {"available", "unnecessary", "unavailable"}:
                raise ValueError(f"invalid pronunciation-resolution status for {record.id}")
            if status == "available":
                if (
                    not isinstance(resolution_capability.get("index"), dict)
                    or "reason" in resolution_capability
                ):
                    raise ValueError(f"available capability lacks index metadata for {record.id}")
            elif (
                not isinstance(resolution_capability.get("reason"), str)
                or not resolution_capability["reason"].strip()
                or "index" in resolution_capability
            ):
                raise ValueError(f"invalid {status} capability metadata for {record.id}")
            if status != "available":
                expected_reason = (
                    NO_RESOLVABLE_AMBIGUITIES
                    if status == "unnecessary"
                    else NO_SENSE_LINKED_MAPPING
                )
                if resolution_capability["reason"] != expected_reason:
                    raise ValueError(f"unexpected {status} capability reason for {record.id}")
            if status != "available":
                stale_index = ASSET_DIR / f"g2lex-{record.slug}.pronresolve.json"
                if stale_index.exists():
                    raise ValueError(f"non-available capability has a stale resolver file for {record.id}")
        elif capabilities is not None:
            raise ValueError(f"non-pronunciation asset has capability metadata for {record.id}")
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
        if resolution_capability is not None:
            artifact_entry["capabilities"] = {"pronunciation_resolution": resolution_capability}
        resolver = manifest.get("resolver_index")
        if record.kind == "pronunciation":
            assert isinstance(resolution_capability, dict)
            status = resolution_capability["status"]
            if status == "available" and resolver is None:
                raise ValueError(f"available capability lacks resolver index for {record.id}")
            if status != "available" and resolver is not None:
                raise ValueError(f"non-available capability has resolver index for {record.id}")
        elif resolver is not None:
            raise ValueError(f"non-pronunciation asset has a resolver index for {record.id}")
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
            if not index.profiles or index.schema_version != 2:
                raise ValueError(f"resolver index must be non-empty schema v2 for {record.id}")
            if (
                resolver.get("schema_version") != index.schema_version
                or resolver.get("language") != index.language
                or resolver.get("locale") != index.locale
            ):
                raise ValueError(f"resolver index identity mismatch for {record.id}")
            capability_index = resolution_capability["index"]
            expected_capability_index = {
                key: resolver.get(key)
                for key in (
                    "name",
                    "schema_version",
                    "language",
                    "locale",
                    "dataset_version",
                    "sha256",
                    "size",
                )
            }
            if capability_index != expected_capability_index:
                raise ValueError(f"catalog capability descriptor mismatch for {record.id}")
            assert isinstance(asset, dict)
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
