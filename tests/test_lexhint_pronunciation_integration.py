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
from g2lex_data.transforms.lexhint_pronunciations import normalize_key


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
            "lexhint_dataset_version": "fixture",
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
        ("ja", "家", "kaː"),
        ("ko", "집", "tɕipː"),
        ("pt", "AÇÃO", "aˈsɐ̃w"),
        ("ru", "ДОМ", "ˈdom"),
        ("th", "บ้าน", "baːn˥"),
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
            "lexhint_dataset_version": "fixture",
            "lexhint_schema_version": "10",
            "include_neutral": True,
            "key_normalization": "nfc-lower",
            "lexhint_version": "0.4.4",
        },
    )
    result = apply(record, artifact, tmp_path / f"{language}-output")
    asset = tmp_path / f"{language}.g2lex"
    g2lex.pack_file(result.input_path, asset, input_format=result.input_format, source_id="fixture")

    with g2lex.open(asset) as lexicon:
        assert lexicon.lookup(word.lower()) == ipa


@pytest.mark.parametrize(
    ("language", "word"),
    (
        ("ja", "こんにちは"),
        ("ko", "집"),
        ("pt", "casa"),
        ("ru", "дом"),
        ("th", "การบ้าน"),
        ("vi", "nhà"),
        ("zh", "家"),
    ),
)
def test_installed_multilingual_pronunciation_smoke(language: str, word: str) -> None:
    source = Lexicon(language, variant="dictionary", dataset_version="2026.09.03")
    groups = source.pronunciations(word, include_neutral=True)
    assert groups
    assert any(
        pronunciation.ipa.strip("[]/") for group in groups for pronunciation in group.pronunciations
    )

    with g2lex.open(Path("build/assets") / f"g2lex-{language}-lexhint.g2lex") as output:
        assert output.lookup(normalize_key(word)) is not None
