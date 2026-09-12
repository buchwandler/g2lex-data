from __future__ import annotations

from .config import AssetConfig, RepositoryConfig


def _locale(record: AssetConfig) -> str:
    return record.id.split(":", 1)[0]


def supported_espeak_locales(config: RepositoryConfig) -> tuple[str, ...]:
    normal_locales = {_locale(record) for record in config.assets if record.name == "espeak"}
    piper_locales = {_locale(record) for record in config.assets if record.name == "espeak-piper"}
    if normal_locales != piper_locales:
        raise ValueError("configured eSpeak locales do not have complete pairs")
    locales: list[str] = []
    for locale in sorted(normal_locales):
        normal = config.asset(f"{locale}:espeak")
        piper = config.asset(f"{locale}:espeak-piper")
        if normal.source_provider != "g2lex-assets" or piper.source_provider != "g2lex-assets":
            raise ValueError(f"eSpeak locale {locale} is not source-backed by g2lex-assets")
        locales.append(locale)
    return tuple(locales)


def espeak_bundle_ids(config: RepositoryConfig, locale: str) -> tuple[str, ...]:
    normal = config.asset(f"{locale}:espeak")
    piper = config.asset(f"{locale}:espeak-piper")
    if normal.source_ids != piper.source_ids:
        raise ValueError(f"eSpeak pair source IDs differ for {locale}")
    return tuple(dict.fromkeys((*normal.source_ids, normal.id, piper.id)))


def static_asset_ids(config: RepositoryConfig) -> tuple[str, ...]:
    bundled = {
        identifier
        for locale in supported_espeak_locales(config)
        for identifier in espeak_bundle_ids(config, locale)
    }
    return tuple(record.id for record in config.assets if record.id not in bundled)


__all__ = ["espeak_bundle_ids", "static_asset_ids", "supported_espeak_locales"]
