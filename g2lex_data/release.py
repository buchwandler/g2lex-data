from __future__ import annotations

import shutil
from pathlib import Path

from .build import build
from .catalog import build_catalog
from .common import ASSET_DIR, CATALOG_PATH, DIST_DIR, MANIFEST_DIR, sha256_file, write_json
from .config import load_config
from .validate import validate_all


def prepare_release(version: str) -> Path:
    config = load_config()
    tag = f"{config.release_tag_prefix}{version}"
    release_dir = DIST_DIR / tag
    shutil.rmtree(release_dir, ignore_errors=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    build()
    build_catalog(version)
    validate_all(catalog=True)

    files: list[dict[str, object]] = []
    for record in config.assets:
        for source in (ASSET_DIR / record.asset_name, MANIFEST_DIR / record.manifest_name):
            target = release_dir / source.name
            shutil.copy2(source, target)
            files.append({"name": target.name, "sha256": sha256_file(target), "size": target.stat().st_size})
    catalog_target = release_dir / "catalog.json"
    shutil.copy2(CATALOG_PATH, catalog_target)
    files.append({"name": catalog_target.name, "sha256": sha256_file(catalog_target), "size": catalog_target.stat().st_size})
    write_json(
        release_dir / "release.json",
        {"schema_version": 1, "version": version, "tag": tag, "asset_count": len(config.assets), "files": files},
    )
    return release_dir
