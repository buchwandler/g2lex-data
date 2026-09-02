from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import g2lex

from g2lex_data import __version__
from g2lex_data.build import build_one
from g2lex_data.catalog import build_catalog
from g2lex_data.common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR
from g2lex_data.config import ROOT, load_config
from g2lex_data.release import prepare_release
from g2lex_data.validate import validate_all, validate_one


def setup_function() -> None:
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    CATALOG_PATH.unlink(missing_ok=True)


def test_dynamic_version_is_exposed() -> None:
    assert isinstance(__version__, str) and __version__


def test_typed_asset_is_lossless_and_deterministic() -> None:
    record = load_config().asset("de-de:demo")
    build_one(record)
    first = (ASSET_DIR / record.asset_name).read_bytes()
    validate_one(record)
    build_one(record)
    second = (ASSET_DIR / record.asset_name).read_bytes()
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
    with g2lex.open(ASSET_DIR / record.asset_name) as lexicon:
        assert lexicon["Haus"] == "haʊ̯s"
        assert lexicon.lookup("die", tag="DET") == "diː"
        assert lexicon.lookup_all("führen") == ("ˈfyːʁən", "ˈfyːɐ̯n")


def test_arpabet_variants_are_preserved() -> None:
    record = load_config().asset("en-us:demo-cmu")
    build_one(record)
    with g2lex.open(ASSET_DIR / record.asset_name) as lexicon:
        assert lexicon.lookup_all("read") == ("R IY1 D", "R EH1 D")


def test_membership_asset_round_trips() -> None:
    record = load_config().asset("ja-jp:demo-words")
    build_one(record)
    with g2lex.open(ASSET_DIR / record.asset_name) as lexicon:
        assert "東京" in lexicon
        assert lexicon["東京"] is g2lex.WORD_ONLY


def test_catalog_supports_production_and_local_release_roots(tmp_path: Path) -> None:
    for record in load_config().assets:
        build_one(record)
    catalog = build_catalog("0.1.0")
    assert catalog["release_tag"] == "data-0.1.0"
    for artifact in catalog["artifacts"]:
        assert "/releases/download/data-0.1.0/" in artifact["asset"]["url"]

    local = build_catalog("0.1.0", base_url=tmp_path.as_uri(), output=tmp_path / "catalog.json")
    assert all(item["asset"]["url"].startswith("file://") for item in local["artifacts"])


def test_release_is_self_contained() -> None:
    release_dir = prepare_release("0.1.0")
    release = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    assert release["asset_count"] == 3
    assert (release_dir / "catalog.json").is_file()
    validate_all(catalog=True)
    for record in load_config().assets:
        assert (release_dir / record.asset_name).is_file()
        assert (release_dir / record.manifest_name).is_file()
