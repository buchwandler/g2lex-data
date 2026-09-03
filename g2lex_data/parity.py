from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import g2lex

from .common import ASSET_DIR, sha256_file
from .config import load_config

BASELINE_PATH = Path(__file__).resolve().parents[1] / "baseline" / "kokoro-german.json"

def benchmark_asset(actual_path: Path, oracle_path: Path, target_path: Path) -> dict[str, object]:
    import time

    with g2lex.open(target_path) as target, g2lex.open(oracle_path) as oracle:
        target_keys = tuple(target)
        started = time.perf_counter()
        with g2lex.open(actual_path) as actual:
            open_time = time.perf_counter() - started
            selected_values = [actual.lookup(key) for key in target_keys]
            selected_exact = sum(
                value is not None and value == oracle.lookup(key)
                for key, value in zip(target_keys, selected_values, strict=True)
            )
            oracle_variant_exact = sum(
                value is not None and value in oracle.lookup_all(key)
                for key, value in zip(target_keys, selected_values, strict=True)
            )
            started = time.perf_counter()
            for key in target_keys:
                actual.get(key)
            lookup_seconds = time.perf_counter() - started
        actual_values = selected_values

    usable = sum(isinstance(value, str) and bool(value) for value in actual_values)
    coverage = sum(value is not None for value in actual_values)
    return {
        "coverage": coverage / len(target_keys) if target_keys else 0.0,
        "usable_first_pronunciation": usable / len(target_keys) if target_keys else 0.0,
        "invalid_first_pronunciation": 1.0 - usable / len(target_keys) if target_keys else 0.0,
        "target_vocabulary_validity": coverage / len(target_keys) if target_keys else 0.0,
        "lookup_throughput": len(target_keys) / lookup_seconds if lookup_seconds else 0.0,
        "selected_exact": selected_exact / len(target_keys) if target_keys else 0.0,
        "oracle_variant_exact": oracle_variant_exact / len(target_keys) if target_keys else 0.0,
        "cold_open_seconds": open_time,
        "asset_bytes": actual_path.stat().st_size,
    }


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("producer") != "KokoroG2P":
        raise ValueError("unsupported Kokoro baseline format")
    if not isinstance(data.get("assets"), dict):
        raise TypeError("baseline assets must be an object")
    return data


def _baseline_asset_path(root: Path, name: str) -> Path:
    candidates = (root / name, root / "kokorog2p" / "lexicons" / "data" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"baseline asset not found: {name}")


def _value_difference(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return False
    if hasattr(actual, "items") and hasattr(expected, "items"):
        return dict(actual.items) != dict(expected.items)
    return True


def compare_asset(
    actual_path: Path, baseline_path: Path, expected: dict[str, Any]
) -> dict[str, object]:
    actual_hash = sha256_file(actual_path)
    with g2lex.open(actual_path) as actual, g2lex.open(baseline_path) as baseline:
        result: dict[str, object] = {
            "entry_count": len(actual),
            "expected_entry_count": expected["entry_count"],
            "logical_sha256": actual.metadata.get("logical_sha256"),
            "expected_logical_sha256": expected["logical_sha256"],
            "asset_sha256": actual_hash,
            "expected_asset_sha256": expected["asset_sha256"],
        }
        if (
            result["logical_sha256"] == expected["logical_sha256"]
            and len(actual) == expected["entry_count"]
        ):
            result["ok"] = True
            result["comparison"] = "logical-hash"
            return result
        actual_keys = set(actual)
        baseline_keys = set(baseline)
        missing = sorted(baseline_keys - actual_keys)
        extra = sorted(actual_keys - baseline_keys)
        mismatch = None
        for key in sorted(actual_keys & baseline_keys):
            if _value_difference(actual.get(key), baseline.get(key)):
                mismatch = key
                break
        result.update(
            {
                "missing_keys": missing[:20],
                "extra_keys": extra[:20],
                "value_mismatch": mismatch,
                "ok": not missing and not extra and mismatch is None,
                "comparison": "logical-content",
            }
        )
        return result


def compare_german(
    baseline_path: Path = BASELINE_PATH,
    *,
    baseline_dir: Path,
) -> dict[str, object]:
    baseline = load_baseline(baseline_path)
    results: dict[str, object] = {}
    for record in load_config().assets:
        if not record.id.startswith("de-de:"):
            continue
        expected = baseline["assets"].get(record.id)
        if expected is None:
            continue
        if not isinstance(expected, dict):
            raise TypeError(f"invalid baseline record for {record.id}")
        results[record.id] = compare_asset(
            ASSET_DIR / record.asset_name,
            _baseline_asset_path(baseline_dir, str(expected["asset_name"])),
            expected,
        )
    benchmarks: dict[str, object] = {}
    lexhint_record = next((record for record in load_config().assets if record.id == "de-de:lexhint"), None)
    crane_expected = baseline["assets"].get("de-de:crane")
    lexhint_path = (ASSET_DIR / lexhint_record.asset_name) if lexhint_record else None
    if lexhint_path and lexhint_path.is_file() and isinstance(crane_expected, dict):
        crane_path = _baseline_asset_path(baseline_dir, str(crane_expected["asset_name"]))
        benchmarks["de-de:lexhint"] = benchmark_asset(lexhint_path, crane_path, crane_path)
    failed = [identifier for identifier, result in results.items() if not result["ok"]]
    return {"baseline": str(baseline_path), "assets": results, "benchmarks": benchmarks, "ok": not failed}
