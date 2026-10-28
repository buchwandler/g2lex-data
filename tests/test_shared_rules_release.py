from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pronresolve import AmbiguityIndex, ReadingProfile, SemanticAnchor, reading_id_v2, save_index

from g2lex_data import release
from g2lex_data.config import load_config


@dataclass(frozen=True)
class _FixtureConfig:
    assets: tuple[object, ...]
    release_tag_prefix: str = "data-"

    def asset(self, identifier: str):
        return next(record for record in self.assets if record.id == identifier)


def test_release_deduplicates_shared_rules_and_aggregates_binding_totals(
    monkeypatch, tmp_path: Path
) -> None:
    records = (
        load_config().asset("en-us:lexhint"),
        load_config().asset("en-us:gold"),
    )
    config = _FixtureConfig(records)
    assets = tmp_path / "assets"
    manifests = tmp_path / "manifests"
    reports = tmp_path / "reports"
    dist = tmp_path / "dist"
    catalog_path = tmp_path / "catalog.json"
    assets.mkdir()
    manifests.mkdir()
    reports.mkdir()

    profiles = tuple(
        ReadingProfile(
            word="read",
            pos="NOUN",
            reading_id=reading_id_v2("en", "read", "NOUN", SemanticAnchor("fixture:en", (ipa,))),
            anchor_ipa=ipa,
        )
        for ipa in ("ɹiːd", "ɹɛd")
    )
    index = AmbiguityIndex(
        language="en",
        locale="en-US",
        rules_id="en-us-r2-fixture",
        profiles=profiles,
    )
    index_name = f"g2lex-{index.rules_id}.pronresolve.json"
    index_path = assets / index_name
    save_index(index, index_path)
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    resolver = {
        "rules_id": index.rules_id,
        "name": index_name,
        "path": index_name,
        "schema_version": index.schema_version,
        "language": index.language,
        "locale": index.locale,
        "dataset_version": "2026.12.01",
        "sha256": index_hash,
        "size": index_path.stat().st_size,
    }
    capability_index = {
        key: resolver[key]
        for key in ("name", "schema_version", "language", "locale", "dataset_version", "sha256", "size")
    }

    for record in records:
        asset_path = assets / record.asset_name
        asset_path.write_bytes(f"asset:{record.id}".encode())
        bindings = [
            {
                "reading_id": profile.reading_id,
                "word": profile.word,
                "pos": profile.pos,
                "status": "bound",
                "native_value": profile.anchor_ipa,
            }
            for profile in profiles
        ]
        binding_report = {
            "rules_id": index.rules_id,
            "phoneme_encoding": record.phoneme_encoding,
            "reading_count": len(bindings),
            "status_counts": {
                "bound": len(bindings),
                "missing": 0,
                "ambiguous": 0,
                "unsupported_encoding": 0,
                "unsafe_equivalence": 0,
            },
            "bindings": bindings,
        }
        report_name = f"{record.slug}.binding-report.json"
        report_path = reports / report_name
        report_path.write_text(json.dumps(binding_report, sort_keys=True), encoding="utf-8")
        binding_capability = {
            "status": "complete",
            "rules_id": index.rules_id,
            "phoneme_encoding": record.phoneme_encoding,
            "reading_count": len(bindings),
            "status_counts": binding_report["status_counts"],
            "report": {
                "name": report_name,
                "path": report_name,
                "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "size": report_path.stat().st_size,
            },
        }
        manifest = {
            "id": record.id,
            "data_version": "2026.12.01",
            "shared_rules": resolver,
            "resolver_index": resolver,
            "capabilities": {
                "pronunciation_resolution": {"status": "available", "index": capability_index},
                "pronunciation_binding": binding_capability,
            },
        }
        (manifests / record.manifest_name).write_text(json.dumps(manifest), encoding="utf-8")

    catalog_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(release, "load_config", lambda: config)
    monkeypatch.setattr(release, "ASSET_DIR", assets)
    monkeypatch.setattr(release, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(release, "REPORT_DIR", reports)
    monkeypatch.setattr(release, "DIST_DIR", dist)
    monkeypatch.setattr(release, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(release, "validate_prebuilt_set", lambda **_kwargs: None)
    monkeypatch.setattr(release, "validate_espeak_generator_consistency", lambda _records: None)
    monkeypatch.setattr(release, "build_catalog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(release, "validate_all", lambda **_kwargs: None)

    release_dir = release.prepare_release("2026.12.01", ids=[record.id for record in records], from_build=True)
    summary = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))

    assert summary["shared_rules_count"] == 1
    assert summary["resolver_index_count"] == 1
    assert summary["shared_rules_total_profiles"] == len(profiles)
    assert summary["pronunciation_binding_complete_assets"] == len(records)
    assert summary["pronunciation_binding_reading_count"] == len(records) * len(profiles)
    assert summary["pronunciation_binding_status_counts"]["bound"] == len(records) * len(profiles)
    assert (release_dir / index_name).is_file()
    assert len(tuple(release_dir.glob("*.pronresolve.json"))) == 1
    assert len(tuple(release_dir.glob("*.binding-report.json"))) == len(records)
