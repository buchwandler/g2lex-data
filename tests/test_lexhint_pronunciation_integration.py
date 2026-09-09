from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import g2lex
import pytest
from lexhint import Lexicon
from lexhint.builder import build_dictionary

from g2lex_data.config import load_config
from g2lex_data.transforms import apply


def _build_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "dictionary.jsonl"
    records = [
        {
            "word": "live",
            "lang_code": "en",
            "pos": "verb",
            "sounds": [{"ipa": "[ˈlɪv]"}],
            "senses": [{"glosses": ["to live"]}],
        },
        {
            "word": "live",
            "lang_code": "en",
            "pos": "adjective",
            "sounds": [
                {"ipa": "[ˈlaɪv]", "tags": ["US"]},
                {"ipa": "[ˈlɪv]", "tags": ["GB"]},
            ],
            "senses": [{"glosses": ["alive"]}],
        },
        {
            "word": "neutral",
            "lang_code": "en",
            "pos": "noun",
            "sounds": [{"ipa": "[ˈnjuːtrəl]"}],
            "senses": [{"glosses": ["not regional"]}],
        },
    ]
    source.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    artifact, _ = build_dictionary(
        "en", source, output=tmp_path / "lexhint.sqlite3", no_frequency=True
    )
    return artifact


def _build_portuguese_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "pt-dictionary.jsonl"
    record = {
        "word": "leite",
        "lang_code": "pt",
        "pos": "noun",
        "sounds": [
            {"ipa": "[ˈlej.t͡ʃi]", "tags": ["Brazil"]},
            {"ipa": "[ˈleɪ̯.t͡ʃi]", "tags": ["Brazil"]},
            {"ipa": "[ˈlej.ti]", "tags": ["Northeast-Brazil"]},
            {"ipa": "[ˈlɐj.tɨ]", "tags": ["Portugal"]},
            {"ipa": "[ˈlej.tɨ]", "tags": ["Northern", "Portugal"]},
            {"ipa": "[ˈle.tɨ]", "tags": ["Portugal", "Southern"]},
        ],
        "senses": [{"glosses": ["milk"]}],
    }
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    artifact, _ = build_dictionary("pt", source, output=tmp_path / "pt.sqlite3", no_frequency=True)
    return artifact


def _pt_record(locale: str | None) -> object:
    base = load_config().asset("pt:lexhint")
    inputs = dict(base.transform_inputs or {})
    if locale is None:
        inputs.pop("lexhint_locale", None)
    else:
        inputs["lexhint_locale"] = locale
    return replace(
        base,
        id=f"pt:{locale or 'neutral'}",
        transform_inputs=inputs,
    )


def _record(locale: str | None) -> object:
    base = load_config().asset("de-de:crane")
    return replace(
        base,
        id=f"en:{locale or 'neutral'}",
        language="en-US",
        source_format="lexhint-dictionary",
        source_provider="lexhint",
        transform="lexhint-pronunciation-lowercase-v1",
        transform_inputs={
            "lexhint_language": "en",
            "lexhint_variant": "dictionary",
            "lexhint_source_variant": "native",
            "lexhint_schema_version": "10",
            "lexhint_locale": locale,
            "include_neutral": True,
        },
    )


def test_one_artifact_can_derive_locale_outputs(tmp_path: Path) -> None:
    artifact = _build_fixture(tmp_path)
    us = apply(_record("en_US"), artifact, tmp_path / "us")
    gb = apply(_record("en_GB"), artifact, tmp_path / "gb")
    assert us.input_path.read_bytes() != gb.input_path.read_bytes()
    assert json.loads(us.input_path.read_text(encoding="utf-8"))["live"] == {
        "DEFAULT": "ˈlɪv",
        "VERB": "ˈlɪv",
        "ADJ": "ˈlaɪv",
    }
    assert json.loads(gb.input_path.read_text(encoding="utf-8"))["live"] == "ˈlɪv"
    assert us.metadata["transform_inputs"] != gb.metadata["transform_inputs"]
    assert (
        us.metadata["source_sha256"]
        == gb.metadata["source_sha256"]
        == hashlib.sha256(artifact.read_bytes()).hexdigest()
    )


def test_portuguese_locale_projections_share_one_artifact(tmp_path: Path) -> None:
    artifact = _build_portuguese_fixture(tmp_path)
    br = apply(_pt_record("pt_BR"), artifact, tmp_path / "br")
    pt = apply(_pt_record("pt_PT"), artifact, tmp_path / "pt")
    neutral = apply(_pt_record(None), artifact, tmp_path / "neutral")
    br_values = json.loads(br.input_path.read_text(encoding="utf-8"))
    pt_values = json.loads(pt.input_path.read_text(encoding="utf-8"))
    neutral_values = json.loads(neutral.input_path.read_text(encoding="utf-8"))

    assert br_values["leite"] == [
        "ˈlej.t͡ʃi",
        "ˈleɪ̯.t͡ʃi",
        "ˈlej.ti",
    ]
    assert pt_values["leite"] == ["ˈlɐj.tɨ", "ˈlej.tɨ", "ˈle.tɨ"]
    assert neutral_values["leite"] == [
        "ˈlej.t͡ʃi",
        "ˈleɪ̯.t͡ʃi",
        "ˈlej.ti",
        "ˈlɐj.tɨ",
        "ˈlej.tɨ",
        "ˈle.tɨ",
    ]
    assert br.input_path.read_bytes() != pt.input_path.read_bytes()
    assert br.metadata["source_sha256"] == pt.metadata["source_sha256"]
    assert br.metadata["source_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert br.metadata["transform_inputs"] != pt.metadata["transform_inputs"]
    assert br.metadata["transform_inputs"]["lexhint_locale"] == "pt_BR"
    assert pt.metadata["transform_inputs"]["lexhint_locale"] == "pt_PT"


def test_portuguese_regional_values_round_trip_through_g2lex(tmp_path: Path) -> None:
    artifact = _build_portuguese_fixture(tmp_path)
    br = apply(_pt_record("pt_BR"), artifact, tmp_path / "br")
    pt = apply(_pt_record("pt_PT"), artifact, tmp_path / "pt")
    br_asset = tmp_path / "pt-br.g2lex"
    pt_asset = tmp_path / "pt-pt.g2lex"
    g2lex.pack_file(br.input_path, br_asset, input_format=br.input_format, source_id="fixture")
    g2lex.pack_file(pt.input_path, pt_asset, input_format=pt.input_format, source_id="fixture")

    with g2lex.open(br_asset) as lexicon:
        assert lexicon.lookup("leite") == "ˈlej.t͡ʃi"
        assert lexicon.lookup_all("leite") == (
            "ˈlej.t͡ʃi",
            "ˈleɪ̯.t͡ʃi",
            "ˈlej.ti",
        )
    with g2lex.open(pt_asset) as lexicon:
        assert lexicon.lookup("leite") == "ˈlɐj.tɨ"
        assert lexicon.lookup_all("leite") == (
            "ˈlɐj.tɨ",
            "ˈlej.tɨ",
            "ˈle.tɨ",
        )


def test_neutral_pronunciation_survives_locale_filtering(tmp_path: Path) -> None:
    artifact = _build_fixture(tmp_path)
    result = apply(_record("en_US"), artifact, tmp_path / "us")
    values = json.loads(result.input_path.read_text(encoding="utf-8"))
    assert values["neutral"] == "ˈnjuːtrəl"


def test_transformed_values_round_trip_through_g2lex(tmp_path: Path) -> None:
    artifact = _build_fixture(tmp_path)
    result = apply(_record("en_US"), artifact, tmp_path / "us")
    asset = tmp_path / "asset.g2lex"
    g2lex.pack_file(result.input_path, asset, input_format=result.input_format, source_id="fixture")
    with g2lex.open(asset) as lexicon:
        assert lexicon.lookup("live", tag="ADJ") == "ˈlaɪv"
        assert lexicon.lookup_all("neutral") == ("ˈnjuːtrəl",)
    assert (
        Lexicon.from_path(artifact, language="en", locale="en_US").metadata["schema_version"]
        == "10"
    )


@pytest.mark.parametrize(
    ("language", "word", "ipa"),
    (
        ("cs", "DŮM", "duːm"),
        ("el", "ΣΠΊΤΙ", "ˈspiti"),
        ("es", "CASA", "ˈkasa"),
        ("fr", "MAISON", "mɛzɔ̃"),
        ("id", "RUMAH", "ˈrumah"),
        ("it", "CASA", "ˈkaza"),
        ("ja", "家", "kaː"),
        ("ko", "집", "tɕipː"),
        ("ku", "MAL", "mal"),
        ("ms", "RUMAH", "rumah"),
        ("pl", "DOM", "dɔm"),
        ("pt", "AÇÃO", "aˈsɐ̃w"),
        ("ru", "ДОМ", "ˈdom"),
        ("th", "บ้าน", "baːn˥"),
        ("tr", "EV", "ev"),
        ("vi", "NHÀ", "naː˧˩"),
        ("zh", "家", "tɕja˥"),
    ),
)
def test_multilingual_fixture_round_trip(
    tmp_path: Path, language: str, word: str, ipa: str
) -> None:
    source = tmp_path / f"{language}.jsonl"
    source.write_text(
        json.dumps(
            {
                "word": word,
                "lang_code": language,
                "pos": "noun",
                "sounds": [{"ipa": f"[{ipa}]"}],
                "senses": [{"glosses": ["fixture"]}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact, _ = build_dictionary(
        language, source, output=tmp_path / f"{language}.sqlite3", no_frequency=True
    )

    record = replace(
        load_config().asset("de-de:crane"),
        id=f"{language}:fixture",
        language=language,
        source_provider="lexhint",
        source_format="lexhint-dictionary",
        transform="lexhint-pronunciation-lowercase-v1",
        transform_inputs={
            "lexhint_language": language,
            "lexhint_variant": "dictionary",
            "lexhint_source_variant": "native",
            "lexhint_schema_version": "10",
            "include_neutral": True,
            "key_normalization": "nfc-lower",
            "lexhint_version": "0.4.7",
        },
    )
    result = apply(record, artifact, tmp_path / f"{language}-output")
    asset = tmp_path / f"{language}.g2lex"
    g2lex.pack_file(result.input_path, asset, input_format=result.input_format, source_id="fixture")

    with g2lex.open(asset) as lexicon:
        assert lexicon.lookup(word.lower()) == ipa
