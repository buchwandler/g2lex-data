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
    resolver_index_count = 0
    resolver_index_total_size = 0
    resolver_index_total_profiles = 0
    resolver_index_total_cues = 0
    pronunciation_resolution_counts = {
        "available": 0,
        "unnecessary": 0,
        "unavailable": 0,
    }
    expected_resolver_files: set[str] = set()
    for record in records:
        for source in (ASSET_DIR / record.asset_name, MANIFEST_DIR / record.manifest_name):
            target = staging_dir / source.name
            shutil.copy2(source, target)
            files.append(
                {"name": target.name, "sha256": sha256_file(target), "size": target.stat().st_size}
            )
        manifest = read_json(MANIFEST_DIR / record.manifest_name)
        resolver = manifest.get("resolver_index")
        if record.kind == "pronunciation":
            capabilities = manifest.get("capabilities")
            capability = (
                capabilities.get("pronunciation_resolution")
                if isinstance(capabilities, dict)
                else None
            )
            if not isinstance(capability, dict):
                raise ValueError(f"pronunciation capability is missing for {record.id}")
            status = capability.get("status")
            if status not in pronunciation_resolution_counts:
                raise ValueError(f"invalid pronunciation capability for {record.id}")
            pronunciation_resolution_counts[status] += 1
            if status == "available" and resolver is None:
                raise ValueError(f"available pronunciation capability lacks a resolver for {record.id}")
            if status != "available" and resolver is not None:
                raise ValueError(f"non-available pronunciation capability has a resolver for {record.id}")
        elif resolver is not None:
            raise ValueError(f"non-pronunciation asset has a resolver index for {record.id}")
        if resolver is not None:
            if not isinstance(resolver, dict):
                raise TypeError(f"invalid resolver index metadata for {record.id}")
            index_name = resolver.get("path", resolver.get("name"))
            if not isinstance(index_name, str) or not index_name or Path(index_name).name != index_name:
                raise ValueError(f"invalid resolver index path for {record.id}")
            source = ASSET_DIR / index_name
            target = staging_dir / index_name
            shutil.copy2(source, target)
            files.append(
                {"name": target.name, "sha256": sha256_file(target), "size": target.stat().st_size}
            )
            from pronresolve import load_index

            index = load_index(source)
            if not index.profiles or index.schema_version != 2:
                raise ValueError(f"release resolver must be non-empty schema v2 for {record.id}")
            resolver_index_count += 1
            resolver_index_total_size += target.stat().st_size
            resolver_index_total_profiles += len(index.profiles)
            resolver_index_total_cues += sum(len(profile.cues) for profile in index.profiles)
            expected_resolver_files.add(index_name)
    staged_resolver_files = {path.name for path in staging_dir.glob("*.pronresolve.json")}
    if staged_resolver_files != expected_resolver_files:
        raise ValueError("release resolver inventory does not match available pronunciation capabilities")
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
