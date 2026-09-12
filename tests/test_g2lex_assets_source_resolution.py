from __future__ import annotations

from g2lex_data.config import load_config
from g2lex_data.sources import resolve_source


def test_derived_assets_have_plural_same_locale_sources() -> None:
    config = load_config()
    normal = config.asset("de-de:espeak")
    piper = config.asset("de-de:espeak-piper")
    assert normal.source_provider == "g2lex-assets"
    assert normal.source_ids == ("de-de:lexhint", "de-de:lexhint-native")
    assert piper.source_ids == normal.source_ids


def test_derived_source_resolution_returns_all_parent_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("g2lex_data.sources.ASSET_DIR", tmp_path)
    (tmp_path / "g2lex-en-us-lexhint.g2lex").touch()
    resolved = resolve_source(load_config().asset("en-us:espeak"))
    source_paths = resolved.metadata["source_paths"]
    assert set(source_paths) == {"en-us:lexhint"}
    assert resolved.metadata["provider"] == "g2lex-assets"
