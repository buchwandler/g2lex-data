from __future__ import annotations

from pathlib import Path

from .capabilities import NO_RESOLVABLE_AMBIGUITIES, NO_SENSE_LINKED_MAPPING
from .common import (
    ASSET_DIR,
    CATALOG_PATH,
    MANIFEST_DIR,
    REPORT_DIR,
    read_json,
    sha256_file,
    write_json,
)
from .config import load_config


def _release_root(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}"


def _data_tag(config, version: str) -> str:
    prefix = config.release_tag_prefix
    return version if version.startswith(prefix) else f"{prefix}{version}"


def _join_url(root: str, filename: str) -> str:
    return root.rstrip("/") + "/" + filename


def _binding_catalog_reference(
    record_id: str,
    capability: object,
    root: str,
) -> dict[str, object]:
    if not isinstance(capability, dict):
        raise TypeError(f"pronunciation-binding capability is missing for {record_id}")
    status = capability.get("status")
    if status == "unavailable":
        reason = capability.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"invalid unavailable binding capability for {record_id}")
        return {"status": status, "reason": reason}
    if status not in {"complete", "partial", "unbound"}:
        raise ValueError(f"invalid pronunciation-binding status for {record_id}")
    rules_id = capability.get("rules_id")
    encoding = capability.get("phoneme_encoding")
    reading_count = capability.get("reading_count")
    counts = capability.get("status_counts")
    report = capability.get("report")
    if (
        not isinstance(rules_id, str)
        or not isinstance(encoding, str)
        or not isinstance(reading_count, int)
        or not isinstance(counts, dict)
        or not all(isinstance(value, int) and value >= 0 for value in counts.values())
        or sum(counts.values()) != reading_count
        or not isinstance(report, dict)
    ):
        raise ValueError(f"invalid pronunciation-binding summary for {record_id}")
    name = report.get("path", report.get("name"))
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError(f"invalid binding-report path for {record_id}")
    report_path = REPORT_DIR / name
    if not report_path.is_file():
        raise FileNotFoundError(f"binding report missing for {record_id}: {report_path}")
    if sha256_file(report_path) != report.get("sha256"):
        raise ValueError(f"binding report SHA mismatch for {record_id}")
    if report_path.stat().st_size != report.get("size"):
        raise ValueError(f"binding report size mismatch for {record_id}")
    report_data = read_json(report_path)
    if (
        not isinstance(report_data, dict)
        or report_data.get("rules_id") != rules_id
        or report_data.get("phoneme_encoding") != encoding
        or report_data.get("reading_count") != reading_count
        or report_data.get("status_counts") != counts
    ):
        raise ValueError(f"binding report summary mismatch for {record_id}")
    return {
        "status": status,
        "rules_id": rules_id,
        "phoneme_encoding": encoding,
        "reading_count": reading_count,
        "status_counts": dict(counts),
        "report": {
            "name": name,
            "url": _join_url(root, name),
            "sha256": report["sha256"],
            "size": report["size"],
        },
    }


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
    shared_rules_by_id: dict[str, dict[str, object]] = {}
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
        binding_catalog_reference = None
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
            binding_capability = capabilities.get("pronunciation_binding")
            if binding_capability is not None:
                binding_catalog_reference = _binding_catalog_reference(
                    record.id,
                    binding_capability,
                    root,
                )
            else:
                binding_catalog_reference = None
            if binding_capability is not None:
                binding_status = binding_capability.get("status")
                if (status == "available") == (binding_status == "unavailable"):
                    raise ValueError(f"resolution/binding capability mismatch for {record.id}")
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
        artifact_capabilities: dict[str, object] = {}
        if resolution_capability is not None:
            artifact_capabilities["pronunciation_resolution"] = resolution_capability
        if binding_catalog_reference is not None:
            artifact_capabilities["pronunciation_binding"] = binding_catalog_reference
        if artifact_capabilities:
            artifact_entry["capabilities"] = artifact_capabilities
        resolver = manifest.get("shared_rules", manifest.get("resolver_index"))
        if manifest.get("shared_rules") is not None and manifest.get("resolver_index") != resolver:
            raise ValueError(f"legacy resolver alias differs from shared rules for {record.id}")
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
            if not index.profiles or index.schema_version != 3:
                raise ValueError(f"shared rules must be non-empty schema v3 for {record.id}")
            if resolver.get("rules_id") != index.rules_id:
                raise ValueError(f"shared-rules identity mismatch for {record.id}")
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
            rules_reference = {
                "rules_id": index.rules_id,
                "name": index_name,
                "url": _join_url(root, index_name),
                "sha256": resolver["sha256"],
                "size": resolver["size"],
                "schema_version": index.schema_version,
                "language": index.language,
                "locale": index.locale,
                "dataset_version": version,
            }
            existing_reference = shared_rules_by_id.get(index.rules_id)
            if existing_reference is not None and existing_reference != rules_reference:
                raise ValueError(f"conflicting shared rules references for {index.rules_id}")
            shared_rules_by_id[index.rules_id] = rules_reference
            artifact_entry["shared_rules"] = rules_reference
            artifact_entry["resolver_index"] = rules_reference
        artifacts.append(artifact_entry)
    catalog: dict[str, object] = {
        "catalog_version": config.catalog_version,
        "runtime_contract": config.runtime_contract,
        "repository": config.repository,
        "data_version": version,
        "release_tag": tag,
        "shared_rules": sorted(
            shared_rules_by_id.values(),
            key=lambda item: str(item["rules_id"]),
        ),
        "artifacts": artifacts,
    }
    write_json(output, catalog)
    return catalog
