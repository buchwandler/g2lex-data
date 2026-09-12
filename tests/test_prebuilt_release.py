from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from g2lex_data.build import build_one
from g2lex_data.catalog import build_catalog
from g2lex_data.common import ASSET_DIR, CATALOG_PATH
from g2lex_data.config import ROOT, load_config
from g2lex_data.release import prepare_release
from g2lex_data.validate import validate_one


@pytest.fixture(autouse=True)
def clean_outputs() -> None:
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    CATALOG_PATH.unlink(missing_ok=True)


def _demo_records():
    return [load_config().asset(identifier) for identifier in ("de-de:demo", "en-us:demo-cmu")]


def test_prebuilt_release_does_not_call_build(monkeypatch) -> None:
    records = _demo_records()
    for record in records:
        build_one(record, data_version="2026.09.test")

    def fail_build(*args, **kwargs):
        raise AssertionError("prebuilt release called build")

    monkeypatch.setattr("g2lex_data.release.build", fail_build)
    release_dir = prepare_release(
        "2026.09.test", ids=[record.id for record in records], from_build=True
    )

    assert release_dir.is_dir()
    assert (release_dir / "catalog.json").is_file()


def test_prebuilt_release_rejects_missing_asset() -> None:
    record = _demo_records()[0]
    build_one(record, data_version="2026.09.test")
    (ASSET_DIR / record.asset_name).unlink()

    with pytest.raises(FileNotFoundError, match="missing asset"):
        prepare_release("2026.09.test", ids=[record.id], from_build=True)


def test_prebuilt_release_rejects_mixed_versions() -> None:
    records = _demo_records()
    build_one(records[0], data_version="2026.09.12")
    build_one(records[1], data_version="2026.09.13")

    with pytest.raises(ValueError, match="manifest data version mismatch"):
        prepare_release("2026.09.12", ids=[record.id for record in records], from_build=True)


def test_offline_validation_does_not_resolve_external_source(monkeypatch) -> None:
    record = _demo_records()[0]
    build_one(record, data_version="test")
    monkeypatch.setattr(
        "g2lex_data.validate.resolve_source",
        lambda record: (_ for _ in ()).throw(AssertionError("source was resolved")),
    )

    validate_one(record, verify_source=False, verify_transform=False)


def test_catalog_rejects_manifest_version_mismatch() -> None:
    record = _demo_records()[0]
    build_one(record, data_version="2026.09.12")

    with pytest.raises(ValueError, match="manifest data version mismatch"):
        build_catalog("2026.09.13", ids=[record.id])


@pytest.mark.parametrize("field", ["library_sha256", "data_sha256", "version"])
def test_generator_identity_rejects_mixed_shards(monkeypatch, field: str) -> None:
    from g2lex_data import validate as validate_module

    records = [
        SimpleNamespace(id="aa:espeak", source_provider="g2lex-assets", manifest_name="aa.manifest.json"),
        SimpleNamespace(id="bb:espeak", source_provider="g2lex-assets", manifest_name="bb.manifest.json"),
    ]
    generator = {"version": "1", "git_revision": "r", "library_sha256": "l", "data_sha256": "d"}
    manifests = {
        "aa.manifest.json": {"transform": {"inputs": {"generator": generator}}},
        "bb.manifest.json": {"transform": {"inputs": {"generator": {**generator, field: "other"}}}},
    }
    monkeypatch.setattr(validate_module, "read_json", lambda path: manifests[path.name])

    with pytest.raises(ValueError, match="generator identity differs"):
        validate_module.validate_espeak_generator_consistency(records)
