from __future__ import annotations

from pathlib import Path

import pytest

from g2lex_data.config import SUPPORTED_ENCODINGS, load_config
from g2lex_data.parity import load_baseline
from g2lex_data.transforms import REGISTRY, apply
from g2lex_data.transforms.cstr_de import normalize_cstr

PRODUCTION_IDS = {
    "de-de:gold",
    "de-de:crane",
    "de-de:espeak",
    "de-de:olaph",
    "sv-se:nst",
    "en-us:cmudict",
    "en-us:gold",
    "en-gb:gold",
    "fr-fr:gold",
}


def test_production_configuration_contract() -> None:
    config = load_config()
    assert PRODUCTION_IDS <= {record.id for record in config.assets}
    assert SUPPORTED_ENCODINGS == {"ipa", "arpabet", "none", "kokoro-v1"}
    kokoro_ids = {record.id for record in config.assets if record.phoneme_encoding == "kokoro-v1"}
    assert kokoro_ids == {"en-us:gold", "en-gb:gold", "fr-fr:gold"}
    assert "en-us:silver" not in {record.id for record in config.assets}
    assert "en-gb:silver" not in {record.id for record in config.assets}
    assert config.asset("de-de:crane").transform == "de-crane-lowercase-lexhint-v1"
    assert config.asset("de-de:espeak").transform == "cstr-de-ipa-v1"
    for identifier in ("en-us:lexhint", "en-gb:lexhint", "de-de:lexhint"):
        record = config.asset(identifier)
        assert record.source_provider == "lexhint"
        assert record.phoneme_encoding == "ipa"
        assert record.transform == "lexhint-pronunciation-lowercase-v1"
        assert record.source_sha256 is None
        assert record.source_size is None
    assert config.asset("en-us:lexhint").transform_inputs["lexhint_source_variant"] == "native"
    assert config.asset("en-gb:lexhint").transform_inputs["lexhint_source_variant"] == "native"
    assert config.asset("de-de:lexhint").transform_inputs["lexhint_source_variant"] == "english"
    assert config.asset("en-us:lexhint").transform_inputs["lexhint_locale"] == "en_US"
    assert config.asset("en-gb:lexhint").transform_inputs["lexhint_locale"] == "en_GB"
    assert config.asset("en-us:lexhint").transform_inputs["include_neutral"] is True
    assert "lexhint_locale" not in (config.asset("de-de:lexhint").transform_inputs or {})


def test_swedish_nst_configuration_contract() -> None:
    record = load_config().asset("sv-se:nst")

    assert record.language == "sv-SE"
    assert record.name == "nst"
    assert record.kind == "pronunciation"
    assert record.source_provider == "file"
    assert record.source_format == "tsv"
    assert record.source_id == "sv-se:nst"
    assert record.phoneme_encoding == "ipa"
    assert record.transform is None
    assert record.source_size == 38008908
    assert record.source_sha256 == (
        "65eb3aae9c737f6d04c22a44b2ab836d1ec01f682b1cdee07bb2209852355296"
    )
    assert record.provider == "Joakim/kokoro-sv-g2p"
    assert record.revision == "d19dd10"


@pytest.mark.parametrize(
    ("identifier", "language", "name", "source_variant"),
    (
        ("cs:lexhint", "cs", "lexhint", "english"),
        ("de-de:lexhint", "de", "lexhint", "english"),
        ("pt:lexhint", "pt", "lexhint", "english"),
        ("pt:lexhint-native", "pt", "lexhint-native", "native"),
        ("id:lexhint-native", "id", "lexhint-native", "native"),
        ("en-us:lexhint", "en", "lexhint", "native"),
    ),
)
def test_lexhint_configuration_contract(
    identifier: str, language: str, name: str, source_variant: str
) -> None:
    record = load_config().asset(identifier)
    assert record.language.lower().split("-", 1)[0] == language
    assert record.name == name
    assert record.kind == "pronunciation"
    assert record.source_provider == "lexhint"
    assert record.source_format == "lexhint-dictionary"
    assert record.phoneme_encoding == "ipa"
    assert record.provider == "buchwandler/lexhint-datasets"
    assert record.transform == "lexhint-pronunciation-lowercase-v1"

    inputs = record.transform_inputs or {}
    assert inputs["lexhint_language"] == language
    assert inputs["lexhint_source_variant"] == source_variant
    assert inputs["lexhint_variant"] == "dictionary"
    assert inputs["lexhint_schema_version"] == "10"
    assert inputs["include_neutral"] is True
    assert inputs["key_normalization"] == "nfc-lower"
    assert inputs["lexhint_version"] == "0.4.7"
    assert "lexhint_dataset_version" not in inputs

def test_cstr_transform_skips_only_header_and_strips_outer_delimiters(tmp_path: Path) -> None:
    source = tmp_path / "source.tsv"
    output = tmp_path / "normalized.tsv"
    source.write_text(
        "word\tespeak_ipa\nword\t/a/b/\nword\t/c/\textra\nother\tplain/ipa\n",
        encoding="utf-8",
    )
    report = normalize_cstr(source, output)
    assert report["skipped_header"] is True
    assert output.read_text(encoding="utf-8") == "other\tplain/ipa\nword\ta/b\nword\tc\n"


def test_unknown_transform_id_fails(tmp_path: Path) -> None:
    record = load_config().asset("de-de:demo")
    bad = record.__class__(
        **{
            field: ("missing-transform-v1" if field == "transform" else getattr(record, field))
            for field in record.__dataclass_fields__
        }
    )
    with pytest.raises(ValueError, match="unknown transform ID"):
        apply(bad, record.source_path, tmp_path)


def test_baseline_is_compact_and_complete() -> None:
    baseline = load_baseline()
    assert set(baseline["assets"]) == {
        "de-de:gold",
        "de-de:crane",
        "de-de:espeak",
        "de-de:olaph",
    }
    assert all(len(item["logical_sha256"]) == 64 for item in baseline["assets"].values())


def test_transform_registry_has_stable_ids() -> None:
    assert set(REGISTRY) == {
        "de-crane-lowercase-lexhint-v1",
        "lexhint-pronunciation-lowercase-v1",
        "cstr-de-ipa-v1",
        "kokoro-legacy-collapse-v1",
    }
