from __future__ import annotations

from g2lex_data.config import load_config


def test_each_supported_locale_has_paired_derived_assets() -> None:
    config = load_config()
    source_locales = {
        record.id.split(":", 1)[0]
        for record in config.assets
        if record.name in {"lexhint", "lexhint-native"}
    }
    unsupported = set((config.espeak_generation or {}).get("unsupported", {}))
    generated = [record for record in config.assets if record.source_provider == "g2lex-assets"]
    assert len(generated) == 2 * len(source_locales - unsupported)
    for locale in sorted(source_locales - unsupported):
        normal = config.asset(f"{locale}:espeak")
        piper = config.asset(f"{locale}:espeak-piper")
        assert normal.source_ids == piper.source_ids
        assert normal.transform_inputs["voice"] == piper.transform_inputs["voice"]
        assert normal.phoneme_encoding == "ipa"
        assert piper.phoneme_encoding == "espeak-ipa3"
        assert normal.transform == "g2lex-espeak-ipa-v1"
        assert piper.transform == "g2lex-espeak-piper-ipa3-v1"
        assert normal.asset_name == f"g2lex-{locale}-espeak.g2lex"
        assert piper.asset_name == f"g2lex-{locale}-espeak-piper.g2lex"


def test_german_cstr_migration_is_source_accurate() -> None:
    config = load_config()
    assert config.asset("de-de:cstr").transform == "cstr-de-ipa-v1"
    assert config.asset("de-de:espeak").source_provider == "g2lex-assets"
    assert config.asset("de-de:espeak-piper").source_provider == "g2lex-assets"
