from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import g2lex
from lexhint.builder import build_dictionary

from g2lex_data import build, validate
from g2lex_data.config import load_config
from g2lex_data.sources import ResolvedSource


def test_lexhint_manifest_records_exact_resolved_identity(tmp_path: Path, monkeypatch) -> None:
    base = load_config().asset("de-de:demo")
    record = replace(
        base,
        id="fixture:lexhint",
        source_provider="lexhint",
        source_format="jsonl",
        source_id="lexhint:fixture:english:dictionary",
        source_sha256=None,
        source_size=None,
        revision="latest-compatible",
        transform=None,
        transform_inputs={
            "lexhint_language": "en",
            "lexhint_source_variant": "english",
            "lexhint_variant": "dictionary",
            "lexhint_schema_version": "10",
        },
    )
    source = Path("sources/demo/de_demo.jsonl").resolve()
    metadata = {
        "provider": "lexhint",
        "path": str(source),
        "language": "en",
        "source_variant": "english",
        "variant": "dictionary",
        "dataset_version": "2026.09.10",
        "schema_version": "10",
        "release_tag": "data-en-english-2026.09.10",
        "release_published_at": "2026-09-10T00:00:00Z",
        "asset": "lexhint-en-english-dictionary-s10-2026.09.10.sqlite3.gz",
        "release_asset_sha256": "release-sha256",
        "wiktionary_edition": "enwiktionary",
        "metadata_language": "en",
        "sqlite_sha256": "sqlite-sha256",
        "sqlite_size": 123,
        "lexhint_version": "0.4.7",
        "locale": None,
    }
    monkeypatch.setattr(build, "resolve_source", lambda record: ResolvedSource(source, metadata))
    monkeypatch.setattr(
        build,
        "validate_source",
        lambda record, **kwargs: {
            "entry_count": 1,
            "logical_sha256": "logical-sha256",
            "resolved": metadata,
        },
    )
    monkeypatch.setattr(build, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(build, "MANIFEST_DIR", tmp_path / "manifests")
    monkeypatch.setattr(validate, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(validate, "MANIFEST_DIR", tmp_path / "manifests")
    monkeypatch.setattr(validate, "resolve_source", lambda record: ResolvedSource(source, metadata))
    monkeypatch.setattr(
        validate,
        "validate_source",
        lambda record, **kwargs: {
            "entry_count": 1,
            "logical_sha256": "logical-sha256",
            "resolved": metadata,
        },
    )

    manifest = build.build_one(record)
    asset_path = tmp_path / "assets" / record.asset_name
    asset_manifest = manifest["asset"]
    assert manifest["id"] == record.id
    assert manifest["language"] == record.language
    assert manifest["name"] == record.name
    assert manifest["phoneme_encoding"] == record.phoneme_encoding
    assert len(asset_manifest["sha256"]) == 64
    assert len(asset_manifest["logical_sha256"]) == 64
    with g2lex.open(asset_path) as lexicon:
        local_metadata = lexicon.metadata
    assert local_metadata["id"] == record.id
    assert local_metadata["language"] == record.language
    assert local_metadata["name"] == record.name
    assert local_metadata["phoneme_encoding"] == record.phoneme_encoding
    assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == asset_manifest["sha256"]
    assert local_metadata["logical_sha256"] == asset_manifest["logical_sha256"]
    source_manifest = manifest["source"]

    assert source_manifest["revision"] == "data-en-english-2026.09.10"
    assert source_manifest["selector"] == {
        "language": "en",
        "source_variant": "english",
        "variant": "dictionary",
        "schema_version": "10",
        "version_policy": "latest-compatible",
    }
    assert source_manifest["resolved"]["dataset_version"] == "2026.09.10"
    assert source_manifest["resolved"]["release_tag"] == "data-en-english-2026.09.10"
    assert source_manifest["resolved"]["release_asset_sha256"] == "release-sha256"
    assert source_manifest["resolved"]["sqlite_sha256"] == "sqlite-sha256"
    assert source_manifest["resolved"]["sqlite_size"] == 123
    assert "2026.09.10" in json.dumps(manifest)
    validate.validate_one(record, verify_transform=False, verify_source=False)


def test_portuguese_regional_manifests_record_projection_identity(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "pt.jsonl"
    source.write_text(
        json.dumps(
            {
                "word": "leite",
                "lang_code": "pt",
                "pos": "noun",
                "sounds": [
                    {"ipa": "[ˈlej.t͡ʃi]", "tags": ["Brazil"]},
                    {"ipa": "[ˈlɐj.tɨ]", "tags": ["Portugal"]},
                ],
                "senses": [{"glosses": ["milk"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    artifact, _ = build_dictionary("pt", source, output=tmp_path / "pt.sqlite3", no_frequency=True)
    source_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    common_metadata = {
        "provider": "lexhint",
        "path": str(artifact),
        "language": "pt",
        "source_variant": "english",
        "variant": "dictionary",
        "dataset_version": "2026.09.10",
        "schema_version": "10",
        "release_tag": "data-pt-english-2026.09.10",
        "release_published_at": "2026-09-10T00:00:00Z",
        "asset": "lexhint-pt-english-dictionary-s10-2026.09.10.sqlite3.gz",
        "release_asset_sha256": "release-sha256",
        "wiktionary_edition": "enwiktionary",
        "metadata_language": "pt",
        "sqlite_sha256": source_sha256,
        "sqlite_size": artifact.stat().st_size,
        "lexhint_version": "0.4.7",
        "include_neutral": True,
    }

    def resolve(record):
        metadata = {
            **common_metadata,
            "locale": record.transform_inputs.get("lexhint_locale"),
        }
        return ResolvedSource(artifact, metadata)

    monkeypatch.setattr(build, "resolve_source", resolve)
    monkeypatch.setattr(
        build,
        "validate_source",
        lambda record, **kwargs: {
            "entry_count": None,
            "logical_sha256": None,
            "resolved": kwargs["resolved_source"].metadata,
        },
    )
    monkeypatch.setattr(build, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(build, "MANIFEST_DIR", tmp_path / "manifests")

    br_manifest = build.build_one(load_config().asset("pt-br:lexhint"))
    pt_manifest = build.build_one(load_config().asset("pt-pt:lexhint"))

    assert br_manifest["id"] == "pt-br:lexhint"
    assert br_manifest["language"] == "pt-BR"
    assert pt_manifest["id"] == "pt-pt:lexhint"
    assert pt_manifest["language"] == "pt-PT"
    assert br_manifest["transform"]["inputs"]["lexhint_locale"] == "pt_BR"
    assert pt_manifest["transform"]["inputs"]["lexhint_locale"] == "pt_PT"
    assert br_manifest["source"]["resolved"]["locale"] == "pt_BR"
    assert pt_manifest["source"]["resolved"]["locale"] == "pt_PT"
    assert br_manifest["source"]["resolved"]["sqlite_sha256"] == source_sha256
    assert pt_manifest["source"]["resolved"]["sqlite_sha256"] == source_sha256
    assert (
        br_manifest["source"]["resolved"]["release_tag"]
        == pt_manifest["source"]["resolved"]["release_tag"]
    )
    assert br_manifest["transform"]["inputs"] != pt_manifest["transform"]["inputs"]
    assert br_manifest["asset"]["logical_sha256"] != pt_manifest["asset"]["logical_sha256"]
    assert br_manifest["asset"]["sha256"] != pt_manifest["asset"]["sha256"]


def test_lexhint_resolver_pair_manifest_catalog_and_release(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from g2lex_data import catalog, release

    record = load_config().asset("en-us:lexhint")
    rows = [
        {
            "word": "read",
            "lang_code": "en",
            "pos": "noun",
            "sounds": [{"ipa": "[riːd]"}],
            "senses": [{"glosses": ["a reading"]}],
        },
        {
            "word": "read",
            "lang_code": "en",
            "pos": "noun",
            "sounds": [{"ipa": "[rɛd]"}],
            "senses": [{"glosses": ["a past tense"]}],
        },
    ]
    source_jsonl = tmp_path / "dictionary.jsonl"
    source_jsonl.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
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
        "release_asset_sha256": "release-hash",
        "wiktionary_edition": "enwiktionary",
        "metadata_language": "en",
        "sqlite_sha256": source_hash,
        "sqlite_size": artifact.stat().st_size,
        "lexhint_version": "0.4.7",
        "locale": "en_US",
    }
    resolved = ResolvedSource(artifact, metadata)
    assets = tmp_path / "assets"
    manifests = tmp_path / "manifests"
    reports = tmp_path / "reports"
    catalog_path = tmp_path / "catalog.json"
    dist = tmp_path / "dist"

    monkeypatch.setattr(build, "resolve_source", lambda _: resolved)
    monkeypatch.setattr(
        build,
        "validate_source",
        lambda *args, **kwargs: {
            "entry_count": None,
            "logical_sha256": None,
            "resolved": metadata,
        },
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
    resolver_index = manifest["resolver_index"]
    assert resolver_index["dataset_version"] == "2026.11.01"
    assert len(resolver_index["sha256"]) == 64
    index_bytes = (assets / resolver_index["path"]).read_bytes()
    assert resolver_index["sha256"] == hashlib.sha256(index_bytes).hexdigest()
    assert resolver_index["size"] == len(index_bytes)
    assert (assets / resolver_index["path"]).is_file()
    assert (reports / f"{record.slug}.transform-report.json").is_file()
    validate.validate_one(record, verify_source=False)
    index_path = assets / resolver_index["path"]
    index_path.write_bytes(index_bytes + b"corrupt")
    with pytest.raises(ValueError, match="resolver index SHA mismatch"):
        validate.validate_one(record, verify_transform=False, verify_source=False)
    index_path.write_bytes(index_bytes)

    built_catalog = catalog.build_catalog("2026.11.01", ids=[record.id], output=catalog_path)
    catalog_reference = built_catalog["artifacts"][0]["resolver_index"]
    assert catalog_reference["sha256"] == resolver_index["sha256"]
    assert catalog_reference["dataset_version"] == "2026.11.01"
    validate.validate_catalog(path=catalog_path, ids=[record.id])

    release_dir = release.prepare_release("2026.11.01", ids=[record.id], from_build=True)
    assert (release_dir / resolver_index["path"]).is_file()
    release_manifest = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    assert release_manifest["resolver_index_count"] == 1
    assert any(
        item["name"] == resolver_index["path"] and item["sha256"] == resolver_index["sha256"]
        for item in release_manifest["files"]
    )
