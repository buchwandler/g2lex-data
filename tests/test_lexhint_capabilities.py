from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lexhint.builder import build_dictionary

from g2lex_data import build, catalog, release, validate
from g2lex_data.config import load_config
from g2lex_data.sources import ResolvedSource


def test_zero_profile_build_removes_stale_sidecar_and_releases_capability(
    tmp_path: Path, monkeypatch
) -> None:
    record = load_config().asset("en-us:lexhint")
    source_jsonl = tmp_path / "dictionary.jsonl"
    source_jsonl.write_text(
        json.dumps(
            {
                "word": "house",
                "lang_code": "en",
                "pos": "noun",
                "sounds": [{"ipa": "[haʊs]"}],
                "senses": [{"glosses": ["a dwelling"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    artifact, _ = build_dictionary(
        "en", source_jsonl, output=tmp_path / "lexhint.sqlite3", no_frequency=True
    )
    source_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = {
        "provider": "lexhint",
        "path": str(artifact),
        "language": "en",
        "source_variant": "native",
        "variant": "dictionary",
        "dataset_version": "2026.11.01",
        "schema_version": "10",
        "release_tag": "fixture-release",
        "release_published_at": "",
        "asset": "fixture.sqlite3",
        "release_asset_sha256": source_hash,
        "wiktionary_edition": "enwiktionary",
        "metadata_language": "en",
        "sqlite_sha256": source_hash,
        "sqlite_size": artifact.stat().st_size,
        "lexhint_version": "0.4.8",
        "locale": "en_US",
    }
    resolved = ResolvedSource(artifact, metadata)
    assets = tmp_path / "assets"
    manifests = tmp_path / "manifests"
    reports = tmp_path / "reports"
    catalog_path = tmp_path / "catalog.json"
    dist = tmp_path / "dist"
    stale_sidecar = assets / f"g2lex-{record.slug}.pronresolve.json"
    assets.mkdir()
    stale_sidecar.write_bytes(b"old-empty-index")

    monkeypatch.setattr(build, "resolve_source", lambda _: resolved)
    monkeypatch.setattr(
        build,
        "validate_source",
        lambda *args, **kwargs: {"entry_count": None, "logical_sha256": None, "resolved": metadata},
    )
    monkeypatch.setattr(build, "ASSET_DIR", assets)
    monkeypatch.setattr(build, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(build, "REPORT_DIR", reports)
    monkeypatch.setattr(validate, "ASSET_DIR", assets)
    monkeypatch.setattr(validate, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(validate, "resolve_source", lambda _: resolved)
    monkeypatch.setattr(catalog, "ASSET_DIR", assets)
    monkeypatch.setattr(catalog, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(release, "ASSET_DIR", assets)
    monkeypatch.setattr(release, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(release, "DIST_DIR", dist)
    monkeypatch.setattr(release, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(
        release,
        "build_catalog",
        lambda version, ids=None: catalog.build_catalog(version, ids=ids, output=catalog_path),
    )
    original_validate_catalog = validate.validate_catalog
    monkeypatch.setattr(
        validate,
        "validate_catalog",
        lambda path=None, ids=None: original_validate_catalog(path or catalog_path, ids=ids),
    )

    manifest = build.build_one(record, data_version="2026.11.01")
    expected_capability = {
        "status": "unnecessary",
        "reason": "no_resolvable_same_pos_ambiguities",
    }
    assert manifest["capabilities"]["pronunciation_resolution"] == expected_capability
    assert manifest.get("resolver_index") is None
    assert not stale_sidecar.exists()
    report_path = reports / f"{record.slug}.transform-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runtime_profile_count"] == 0
    assert report["ambiguity_discovery"]["entries_scanned"] > 0
    validate.validate_one(record, verify_source=False)

    built_catalog = catalog.build_catalog("2026.11.01", ids=[record.id], output=catalog_path)
    catalog_entry = built_catalog["artifacts"][0]
    assert catalog_entry["capabilities"]["pronunciation_resolution"] == expected_capability
    assert "resolver_index" not in catalog_entry
    validate.validate_catalog(path=catalog_path, ids=[record.id])

    release_dir = release.prepare_release("2026.11.01", ids=[record.id])
    release_summary = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    assert not tuple(release_dir.glob("*.pronresolve.json"))
    assert release_summary["pronunciation_resolution_available_assets"] == 0
    assert release_summary["pronunciation_resolution_unnecessary_assets"] == 1
    assert release_summary["pronunciation_resolution_unavailable_assets"] == 0
    assert release_summary["resolver_index_count"] == 0
    assert release_summary["resolver_index_total_size"] == 0
