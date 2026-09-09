from __future__ import annotations

import json
from pathlib import Path

from g2lex_data.config import load_config

CATALOG = Path(__file__).parents[2] / "lexhint-datasets/catalog/datasets-v2.json"
ENGLISH_SOURCE_LANGUAGES = {
    "ar", "az", "bg", "ca", "ceb", "cs", "de", "el", "es", "fr", "ga", "he",
    "hi", "hu", "hy", "it", "ja", "ko", "la", "lt", "lv", "mr", "nl", "pl", "pt",
    "ro", "ru", "sv", "ta", "te", "tl", "tr", "uk", "ur", "vi", "zh",
}
NATIVE_SOURCE_LANGUAGES = {
    "cs", "de", "el", "en", "es", "fr", "id", "it", "ja", "ko", "ku", "ms", "pl",
    "pt", "ru", "th", "tr", "vi", "zh",
}


def _dictionary_pairs() -> dict[str, set[str]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["catalog_version"] == 2
    assert catalog["runtime_contract"] == 2
    artifacts = catalog["artifacts"]
    return {
        variant: {
            item["language"]
            for item in artifacts
            if item["source_variant"] == variant and item["variant"] == "dictionary"
        }
        for variant in ("english", "native")
    }


def test_catalog_has_expected_source_qualified_dictionary_pairs() -> None:
    pairs = _dictionary_pairs()
    assert pairs["english"] == ENGLISH_SOURCE_LANGUAGES
    assert pairs["native"] == NATIVE_SOURCE_LANGUAGES


def test_catalog_source_qualified_artifacts_are_unique_and_version_agnostic() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    artifacts = catalog["artifacts"]
    assert len({item["id"] for item in artifacts}) == len(artifacts)
    assert len({
        (item["language"], item["source_variant"], item["variant"], item["schema_version"])
        for item in artifacts
        if item["variant"] == "dictionary"
    }) == 55
    assert all("source_variant" in item for item in artifacts)


def test_g2lex_asset_names_follow_source_matrix() -> None:
    config = load_config()
    records = {record.id: record for record in config.assets if record.source_provider == "lexhint"}
    assert len(records) == 56
    for language in ENGLISH_SOURCE_LANGUAGES:
        identifier = "de-de:lexhint" if language == "de" else f"{language}:lexhint"
        record = records[identifier]
        assert record.name == "lexhint"
        assert record.transform_inputs["lexhint_source_variant"] == "english"
    for language in NATIVE_SOURCE_LANGUAGES - {"en"}:
        identifier = "de-de:lexhint-native" if language == "de" else f"{language}:lexhint-native"
        record = records[identifier]
        assert record.name == "lexhint-native"
        assert record.transform_inputs["lexhint_source_variant"] == "native"
    assert records["en-us:lexhint"].transform_inputs["lexhint_source_variant"] == "native"
    assert records["en-gb:lexhint"].transform_inputs["lexhint_source_variant"] == "native"
    for language in ("id", "ku", "ms", "th"):
        assert f"{language}:lexhint" not in records
        assert f"{language}:lexhint-native" in records
    assert all("lexhint_dataset_version" not in (record.transform_inputs or {}) for record in records.values())
