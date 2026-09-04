from __future__ import annotations

import json
from pathlib import Path

import g2lex

from g2lex_data.build import build_one
from g2lex_data.config import load_config


def test_swedish_nst_source_contract() -> None:
    record = load_config().asset("sv-se:nst")
    parsed = g2lex.read_typed_lexicon(
        record.source_path,
        format=record.source_format,
        source_id=record.source_id,
    )

    assert len(parsed) == 812343
    assert "hej" in parsed.entries


def test_swedish_nst_build_manifest_contract() -> None:
    record = load_config().asset("sv-se:nst")
    build_one(record)
    manifest = json.loads(
        (Path("build/manifests") / record.manifest_name).read_text(encoding="utf-8")
    )

    assert manifest["id"] == "sv-se:nst"
    assert manifest["source"]["sha256"] == record.source_sha256
    assert manifest["source"]["size"] == 38008908
    assert manifest["source"]["entry_count"] == 812343
    assert manifest["transform"] == {}
    assert manifest["verification"]["lossless"] is True
    assert manifest["asset"]["entry_count"] == 812343

    with g2lex.open(Path("build/assets") / record.asset_name) as asset:
        assert asset.metadata["logical_sha256"] == manifest["asset"]["logical_sha256"]
        assert asset.get("hej") is not None
