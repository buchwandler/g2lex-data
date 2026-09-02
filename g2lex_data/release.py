from __future__ import annotations

import shutil
from pathlib import Path

from .build import build
from .catalog import _data_tag, build_catalog
from .common import ASSET_DIR, CATALOG_PATH, DIST_DIR, MANIFEST_DIR, sha256_file, write_json
from .config import load_config
from .validate import validate_all


def prepare_release(version: str, *, ids: list[str] | None = None) -> Path:
    if not version or "/" in version or version.isspace():
        raise ValueError("version must be a non-empty release identifier")
    config = load_config()
    records = config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    tag = _data_tag(config, version)
    release_dir = DIST_DIR / tag
    if release_dir.exists():
        raise FileExistsError(f"immutable release already exists: {release_dir}")
    staging_dir = DIST_DIR / f".{tag}.staging"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=False)

    build(ids, data_version=version)
    build_catalog(version, ids=ids)
    validate_all(catalog=True, ids=ids, verify_transform=False, verify_source=False)

    files: list[dict[str, object]] = []
    for record in records:
        for source in (ASSET_DIR / record.asset_name, MANIFEST_DIR / record.manifest_name):
            target = staging_dir / source.name
            shutil.copy2(source, target)
            files.append(
                {"name": target.name, "sha256": sha256_file(target), "size": target.stat().st_size}
            )
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
            "immutable": True,
            "files": files,
        },
    )
    staging_dir.replace(release_dir)
    return release_dir
