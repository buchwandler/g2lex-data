from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import g2lex
import pytest

from g2lex_data.config import load_config
from g2lex_data.transforms import apply, kokoro_legacy


def _effective(*paths: Path) -> dict[str, object]:
    layers = []
    for index, path in enumerate(paths):
        parsed = g2lex.read_typed_lexicon(path, format="kokoro-json", source_id=path.stem)
        mapping = g2lex.CaseAliasMapping(parsed.entries)
        layers.append(g2lex.LexiconLayer(str(index), mapping, {}))
    layered = g2lex.LayeredLexicon(layers)
    return {key: layered[key] for key in layered}


def _normalized(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _normalized(value[key]) for key in value}
    if isinstance(value, tuple):
        return tuple(_normalized(item) for item in value)
    return value


def _build_asset(record_id: str, tmp_path: Path) -> tuple[dict[str, object], Path]:
    record = load_config().asset(record_id)
    result = apply(record, record.source_path, tmp_path / "transform")
    assert result is not None
    asset = tmp_path / f"{record.slug}.g2lex"
    g2lex.pack_file(
        result.input_path, asset, input_format=result.input_format, source_id=record.source_id
    )
    return result.metadata["transform_report"], asset


@pytest.mark.parametrize(
    ("record_id", "source_paths"),
    [
        (
            "en-us:gold",
            (
                Path("sources/kokorog2p/en/us_gold.json"),
                Path("sources/kokorog2p/en/us_silver.json"),
            ),
        ),
        (
            "en-gb:gold",
            (
                Path("sources/kokorog2p/en/gb_gold.json"),
                Path("sources/kokorog2p/en/gb_silver.json"),
            ),
        ),
        ("fr-fr:gold", (Path("sources/kokorog2p/fr/fr_gold.json"),)),
    ],
)
def test_migrated_asset_matches_every_effective_legacy_entry(
    record_id: str, source_paths: tuple[Path, ...], tmp_path: Path
) -> None:
    expected = _effective(*source_paths)
    report, asset = _build_asset(record_id, tmp_path)
    with g2lex.open(asset) as actual_lexicon:
        actual = {key: actual_lexicon[key] for key in actual_lexicon}

    assert set(actual) == set(expected)
    assert _normalized(actual) == _normalized(expected)
    assert report["final_effective_entry_count"] == len(expected)
    assert report["logical_transformed_mapping_sha256"]
    assert report["serialized_transformed_source_sha256"]


def _synthetic_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gold_path = tmp_path / "gold.json"
    silver_path = tmp_path / "silver.json"
    gold_path.write_text(
        json.dumps(
            {
                "cat": "gold-cat",
                "Dog": "gold-dog",
                "Tuple": ["first", "second"],
                "Tagged": {"DEFAULT": "default", "NOUN": "noun"},
            }
        ),
        encoding="utf-8",
    )
    silver_path.write_text(
        json.dumps(
            {
                "cat": "silver-cat",
                "Cat": "silver-explicit-alias",
                "dog": "silver-dog",
                "other": "silver-other",
            }
        ),
        encoding="utf-8",
    )
    record = load_config().asset("en-us:gold")
    inputs = dict(record.transform_inputs or {})
    inputs.update(
        {
            "secondary_source": "silver.json",
            "secondary_source_id": "synthetic-silver",
            "secondary_sha256": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
            "secondary_size": silver_path.stat().st_size,
        }
    )
    monkeypatch.setattr(kokoro_legacy, "ROOT", tmp_path)
    return replace(record, transform_inputs=inputs), gold_path, silver_path


def test_collision_precedence_and_typed_values_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, gold_path, _ = _synthetic_record(tmp_path, monkeypatch)
    result = apply(record, gold_path, tmp_path / "output")
    assert result is not None
    parsed = g2lex.read_typed_lexicon(result.input_path, format=result.input_format)

    assert parsed.entries["cat"] == "gold-cat"
    assert parsed.entries["Cat"] == "gold-cat"
    assert parsed.entries["Dog"] == "gold-dog"
    assert parsed.entries["dog"] == "gold-dog"
    assert parsed.entries["other"] == "silver-other"
    assert parsed.entries["Other"] == "silver-other"
    assert parsed.entries["Tuple"] == ("first", "second")
    assert parsed.entries["Tagged"] == {"DEFAULT": "default", "NOUN": "noun"}

    report = result.metadata["transform_report"]
    assert report["raw_overlapping_key_count"] == 1
    assert report["conflicting_overlapping_value_count"] == 1
    assert report["keys_shadowed_by_higher_priority_gold_aliases"] == 2


def test_secondary_hash_and_size_are_required_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, gold_path, silver_path = _synthetic_record(tmp_path, monkeypatch)
    inputs = dict(record.transform_inputs or {})

    bad_hash = replace(record, transform_inputs={**inputs, "secondary_sha256": "0" * 64})
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        apply(bad_hash, gold_path, tmp_path / "bad-hash")

    bad_size = replace(
        record, transform_inputs={**inputs, "secondary_size": silver_path.stat().st_size + 1}
    )
    with pytest.raises(ValueError, match="size mismatch"):
        apply(bad_size, gold_path, tmp_path / "bad-size")

    missing_hash = replace(
        record,
        transform_inputs={key: value for key, value in inputs.items() if key != "secondary_sha256"},
    )
    with pytest.raises(ValueError, match="secondary_sha256"):
        apply(missing_hash, gold_path, tmp_path / "missing-hash")


def test_transform_output_and_report_are_deterministic(tmp_path: Path) -> None:
    record = load_config().asset("fr-fr:gold")
    first = apply(record, record.source_path, tmp_path / "first")
    second = apply(record, record.source_path, tmp_path / "second")
    assert first is not None and second is not None
    assert first.input_path.read_bytes() == second.input_path.read_bytes()
    assert first.report_path is not None and second.report_path is not None
    assert first.report_path.read_bytes() == second.report_path.read_bytes()
