from __future__ import annotations

import shutil
from pathlib import Path

from .build import build
from .catalog import _data_tag, build_catalog
from .common import (
    ASSET_DIR,
    CATALOG_PATH,
    DIST_DIR,
    MANIFEST_DIR,
    REPORT_DIR,
    read_json,
    sha256_file,
    write_json,
)
from .config import load_config
from .validate import validate_all, validate_espeak_generator_consistency, validate_prebuilt_set


def prepare_release(
    version: str,
    *,
    ids: list[str] | None = None,
    from_build: bool = False,
) -> Path:
    if not version or "/" in version or version.isspace():
        raise ValueError("version must be a non-empty release identifier")
    config = load_config()
    records = (
        config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    )
    tag = _data_tag(config, version)
    release_dir = DIST_DIR / tag
    if release_dir.exists():
        raise FileExistsError(f"immutable release already exists: {release_dir}")

    if from_build:
        validate_prebuilt_set(ids=ids, data_version=version)
        validate_espeak_generator_consistency(records)
    else:
        build(ids, data_version=version)

    build_catalog(version, ids=ids)
    validate_all(
        catalog=True,
        ids=ids,
        verify_transform=not from_build,
        verify_source=not from_build,
    )

    staging_dir = DIST_DIR / f".{tag}.staging"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, object]] = []
    staged_files: dict[str, dict[str, object]] = {}

    def add_file(source: Path) -> Path:
        target = staging_dir / source.name
        if not source.is_file():
            raise FileNotFoundError(f"release source is missing: {source}")
        item = {
            "name": target.name,
            "sha256": sha256_file(source),
            "size": source.stat().st_size,
        }
        previous = staged_files.get(target.name)
        if previous is not None:
            if previous != item:
                raise ValueError(f"conflicting release files named {target.name}")
            return target
        shutil.copy2(source, target)
        staged_files[target.name] = item
        files.append(item)
        return target

    pronunciation_resolution_counts = {
        "available": 0,
        "unnecessary": 0,
        "unavailable": 0,
    }
    pronunciation_binding_asset_counts = {
        "complete": 0,
        "partial": 0,
        "unbound": 0,
        "unavailable": 0,
    }
    binding_statuses = (
        "bound",
        "missing",
        "ambiguous",
        "unsupported_encoding",
        "unsafe_equivalence",
    )
    binding_reading_counts = {status: 0 for status in binding_statuses}
    shared_rules_by_id: dict[str, dict[str, object]] = {}
    expected_resolver_files: set[str] = set()
    expected_binding_report_files: set[str] = set()

    for record in records:
        for source in (ASSET_DIR / record.asset_name, MANIFEST_DIR / record.manifest_name):
            add_file(source)
        manifest = read_json(MANIFEST_DIR / record.manifest_name)
        resolver = manifest.get("shared_rules", manifest.get("resolver_index"))
        if manifest.get("shared_rules") is not None and manifest.get("resolver_index") != resolver:
            raise ValueError(f"legacy resolver alias differs from shared rules for {record.id}")
        capabilities = manifest.get("capabilities")
        if record.kind == "pronunciation":
            if not isinstance(capabilities, dict):
                raise ValueError(f"pronunciation capability is missing for {record.id}")
            capability = capabilities.get("pronunciation_resolution")
            if not isinstance(capability, dict):
                raise ValueError(f"pronunciation-resolution capability is missing for {record.id}")
            status = capability.get("status")
            if status not in pronunciation_resolution_counts:
                raise ValueError(f"invalid pronunciation capability for {record.id}")
            pronunciation_resolution_counts[status] += 1
            if status == "available" and resolver is None:
                raise ValueError(f"available pronunciation capability lacks shared rules for {record.id}")
            if status != "available" and resolver is not None:
                raise ValueError(f"non-available pronunciation capability has shared rules for {record.id}")

            binding = capabilities.get("pronunciation_binding")
            if binding is not None:
                if not isinstance(binding, dict):
                    raise TypeError(f"invalid pronunciation-binding capability for {record.id}")
                binding_status = binding.get("status")
                if binding_status not in pronunciation_binding_asset_counts:
                    raise ValueError(f"invalid pronunciation-binding status for {record.id}")
                pronunciation_binding_asset_counts[binding_status] += 1
                if binding_status == "unavailable":
                    if not isinstance(binding.get("reason"), str) or "report" in binding:
                        raise ValueError(f"invalid unavailable binding capability for {record.id}")
                else:
                    if (
                        not isinstance(resolver, dict)
                        or binding.get("rules_id") != resolver.get("rules_id")
                    ):
                        raise ValueError(f"binding rules_id mismatch for {record.id}")
                    counts = binding.get("status_counts")
                    reading_count = binding.get("reading_count")
                    report = binding.get("report")
                    if (
                        not isinstance(counts, dict)
                        or set(counts) != set(binding_statuses)
                        or not all(isinstance(value, int) and value >= 0 for value in counts.values())
                        or not isinstance(reading_count, int)
                        or sum(counts.values()) != reading_count
                        or not isinstance(report, dict)
                    ):
                        raise ValueError(f"invalid binding summary for {record.id}")
                    report_name = report.get("path", report.get("name"))
                    if not isinstance(report_name, str) or Path(report_name).name != report_name:
                        raise ValueError(f"invalid binding-report path for {record.id}")
                    report_path = REPORT_DIR / report_name
                    if not report_path.is_file():
                        raise FileNotFoundError(f"binding report is missing for {record.id}: {report_path}")
                    if sha256_file(report_path) != report.get("sha256"):
                        raise ValueError(f"binding report SHA mismatch for {record.id}")
                    if report_path.stat().st_size != report.get("size"):
                        raise ValueError(f"binding report size mismatch for {record.id}")
                    report_data = read_json(report_path)
                    if (
                        not isinstance(report_data, dict)
                        or report_data.get("rules_id") != binding.get("rules_id")
                        or report_data.get("phoneme_encoding") != binding.get("phoneme_encoding")
                        or report_data.get("reading_count") != reading_count
                        or report_data.get("status_counts") != counts
                    ):
                        raise ValueError(f"binding report summary mismatch for {record.id}")
                    report_bindings = report_data.get("bindings")
                    if not isinstance(report_bindings, list):
                        raise ValueError(f"binding report entries are missing for {record.id}")
                    actual_counts = {key: 0 for key in binding_statuses}
                    for item in report_bindings:
                        if not isinstance(item, dict) or item.get("status") not in actual_counts:
                            raise ValueError(f"invalid binding report entry for {record.id}")
                        actual_counts[item["status"]] += 1
                    if actual_counts != counts:
                        raise ValueError(f"binding report totals mismatch for {record.id}")
                    expected_binding_status = (
                        "complete"
                        if counts["bound"] == reading_count
                        else "partial"
                        if counts["bound"]
                        else "unbound"
                    )
                    if binding_status != expected_binding_status:
                        raise ValueError(f"binding status mismatch for {record.id}")
                    for key, value in counts.items():
                        binding_reading_counts[key] += value
                    add_file(report_path)
                    expected_binding_report_files.add(report_name)
        elif resolver is not None or capabilities is not None:
            raise ValueError(f"non-pronunciation asset has shared-rule metadata for {record.id}")

        if resolver is not None:
            if not isinstance(resolver, dict):
                raise TypeError(f"invalid shared-rules metadata for {record.id}")
            index_name = resolver.get("path", resolver.get("name"))
            rules_id = resolver.get("rules_id")
            if (
                not isinstance(index_name, str)
                or not index_name
                or Path(index_name).name != index_name
                or not isinstance(rules_id, str)
            ):
                raise ValueError(f"invalid shared-rules reference for {record.id}")
            source = ASSET_DIR / index_name
            add_file(source)
            from pronresolve import load_index

            index = load_index(source)
            if not index.profiles or index.schema_version != 3:
                raise ValueError(f"release shared rules must be non-empty schema v3 for {record.id}")
            if index.rules_id != rules_id:
                raise ValueError(f"release shared-rules ID mismatch for {record.id}")
            if (
                resolver.get("schema_version") != index.schema_version
                or resolver.get("language") != index.language
                or resolver.get("locale") != index.locale
                or resolver.get("dataset_version") != version
            ):
                raise ValueError(f"release shared-rules identity mismatch for {record.id}")
            prior = shared_rules_by_id.get(rules_id)
            if prior is not None and prior != resolver:
                raise ValueError(f"conflicting shared rules for rules_id {rules_id}")
            shared_rules_by_id[rules_id] = dict(resolver)
            expected_resolver_files.add(index_name)

    staged_resolver_files = {path.name for path in staging_dir.glob("*.pronresolve.json")}
    if staged_resolver_files != expected_resolver_files:
        raise ValueError("release shared-rules inventory does not match pronunciation capabilities")
    staged_binding_reports = {path.name for path in staging_dir.glob("*.binding-report.json")}
    if staged_binding_reports != expected_binding_report_files:
        raise ValueError("release binding-report inventory does not match pronunciation capabilities")
    resolver_index_count = len(shared_rules_by_id)
    resolver_index_total_size = sum(int(item["size"]) for item in shared_rules_by_id.values())
    resolver_index_total_profiles = 0
    resolver_index_total_cues = 0
    from pronresolve import load_index

    for item in shared_rules_by_id.values():
        index_path = ASSET_DIR / str(item["path"])
        index = load_index(index_path)
        resolver_index_total_profiles += len(index.profiles)
        resolver_index_total_cues += sum(len(profile.cues) for profile in index.profiles)
    catalog_target = staging_dir / "catalog.json"
    shutil.copy2(CATALOG_PATH, catalog_target)
    files.append(
        {
            "name": catalog_target.name,
            "sha256": sha256_file(catalog_target),
            "size": catalog_target.stat().st_size,
        }
    )
    write_json(
        staging_dir / "release.json",
        {
            "schema_version": 1,
            "data_version": version,
            "version": version,
            "tag": tag,
            "asset_count": len(records),
            "resolver_index_count": resolver_index_count,
            "shared_rules_count": resolver_index_count,
            "shared_rules_total_size": resolver_index_total_size,
            "shared_rules_total_profiles": resolver_index_total_profiles,
            "shared_rules_total_cues": resolver_index_total_cues,
            "pronunciation_binding_complete_assets": pronunciation_binding_asset_counts["complete"],
            "pronunciation_binding_partial_assets": pronunciation_binding_asset_counts["partial"],
            "pronunciation_binding_unbound_assets": pronunciation_binding_asset_counts["unbound"],
            "pronunciation_binding_unavailable_assets": pronunciation_binding_asset_counts["unavailable"],
            "pronunciation_binding_reading_count": sum(binding_reading_counts.values()),
            "pronunciation_binding_status_counts": binding_reading_counts,
            "pronunciation_resolution_available_assets": pronunciation_resolution_counts["available"],
            "pronunciation_resolution_unnecessary_assets": pronunciation_resolution_counts["unnecessary"],
            "pronunciation_resolution_unavailable_assets": pronunciation_resolution_counts["unavailable"],
            "resolver_index_total_size": resolver_index_total_size,
            "resolver_index_total_profiles": resolver_index_total_profiles,
            "resolver_index_total_cues": resolver_index_total_cues,
            "immutable": True,
            "files": files,
        },
    )
    staging_dir.replace(release_dir)
    return release_dir
