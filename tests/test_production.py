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
    "en-us:cmudict",
}


def test_production_configuration_contract() -> None:
    config = load_config()
    assert PRODUCTION_IDS <= {record.id for record in config.assets}
    assert SUPPORTED_ENCODINGS == {"ipa", "arpabet", "none"}
    assert all(record.phoneme_encoding != "kokoro-v1" for record in config.assets)
    assert config.asset("de-de:crane").transform == "de-crane-lowercase-lexhint-v1"
    assert config.asset("de-de:espeak").transform == "cstr-de-ipa-v1"


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
    assert set(REGISTRY) == {"de-crane-lowercase-lexhint-v1", "cstr-de-ipa-v1"}
