from __future__ import annotations

import json
from pathlib import Path

import g2lex

from g2lex_data.parity import benchmark_asset


def _pack(path: Path, values: dict[str, object]) -> None:
    source = path.with_suffix(".json")
    source.write_text(json.dumps(values), encoding="utf-8")
    g2lex.pack_file(source, path, input_format="json-map", source_id="fixture")


def test_benchmark_asset_reports_migration_metrics(tmp_path: Path) -> None:
    oracle = tmp_path / "oracle.g2lex"
    actual = tmp_path / "actual.g2lex"
    _pack(oracle, {"one": "a", "two": ["b", "c"]})
    _pack(actual, {"one": "a"})

    metrics = benchmark_asset(actual, oracle, oracle)
    assert metrics["coverage"] == 0.5
    assert metrics["usable_first_pronunciation"] == 0.5
    assert metrics["invalid_first_pronunciation"] == 0.5
    assert metrics["target_vocabulary_validity"] == 0.5
    assert metrics["selected_exact"] == 0.5
    assert metrics["oracle_variant_exact"] == 0.5
    assert metrics["lookup_throughput"] > 0
    assert metrics["cold_open_seconds"] >= 0
    assert metrics["asset_bytes"] == actual.stat().st_size
