from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from g2lex_data import build
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

    manifest = build.build_one(record)
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
