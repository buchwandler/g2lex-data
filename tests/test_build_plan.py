from __future__ import annotations

from g2lex_data.build_plan import espeak_bundle_ids, static_asset_ids, supported_espeak_locales
from g2lex_data.config import load_config


def test_configured_assets_are_partitioned_without_overlap() -> None:
    config = load_config()
    locales = supported_espeak_locales(config)
    bundles = [set(espeak_bundle_ids(config, locale)) for locale in locales]
    static_ids = set(static_asset_ids(config))
    all_ids = {record.id for record in config.assets}

    assert len(locales) == 42
    assert set.intersection(*bundles) == set()
    assert all(not static_ids.intersection(bundle) for bundle in bundles)
    assert static_ids.union(*bundles) == all_ids
    assert config.asset("ceb:lexhint").id in static_ids
    assert config.asset("tl:lexhint").id in static_ids


def test_locale_bundles_include_parents_before_pair_members() -> None:
    config = load_config()

    assert espeak_bundle_ids(config, "de-de") == (
        "de-de:lexhint",
        "de-de:lexhint-native",
        "de-de:espeak",
        "de-de:espeak-piper",
    )
