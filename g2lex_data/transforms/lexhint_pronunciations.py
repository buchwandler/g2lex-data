from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import SELECTOR_ORDER, normalize_key, normalize_pos, ordered_selectors, plain_value
from .common import serialize_entries as _serialize_entries

TRANSFORM_VERSION = "lexhint-pronunciation-lowercase-v1"
_CANONICAL_SELECTORS = frozenset(SELECTOR_ORDER)


@dataclass(frozen=True, slots=True)
class LexHintTransformResult:
    entries: dict[str, object]
    report: dict[str, object]


def normalize_ipa(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    if len(value) >= 2 and (
        (value[0] == "[" and value[-1] == "]") or (value[0] == "/" and value[-1] == "/")
    ):
        value = value[1:-1]
    return value.strip()


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _collapse(
    item: Any,
) -> tuple[str | tuple[str, ...] | dict[str, object] | None, dict[str, object]]:
    key = normalize_key(item.key)
    by_pos: dict[str, list[str]] = {}
    global_values: list[str] = []
    exact_lower_values: list[str] = []
    empty_ipa_count = 0

    for group in item.groups:
        selector = normalize_pos(group.pos)
        values = by_pos.setdefault(selector, [])
        for pronunciation in group.pronunciations:
            ipa = normalize_ipa(pronunciation.ipa)
            if not ipa:
                empty_ipa_count += 1
                continue
            _append_unique(values, ipa)
            _append_unique(global_values, ipa)
            if group.word == key:
                _append_unique(exact_lower_values, ipa)

    unknown_pos_count = sum(
        1
        for group in item.groups
        if normalize_pos(group.pos) not in _CANONICAL_SELECTORS
        and unicodedata.normalize("NFC", group.pos).strip()
    )
    if not global_values:
        return None, {
            "key": key,
            "empty_ipa_count": empty_ipa_count,
            "case_collision": len({group.word for group in item.groups}) > 1,
            "unknown_pos_count": unknown_pos_count,
        }

    if len(global_values) == 1:
        value: object = global_values[0]
    else:
        nonempty_pos_values = [tuple(values) for values in by_pos.values() if values]
        if nonempty_pos_values and len(set(nonempty_pos_values)) == 1:
            value = plain_value(global_values)
        else:
            selectors: dict[str, object] = {
                "DEFAULT": exact_lower_values[0] if exact_lower_values else global_values[0]
            }
            for selector, values in by_pos.items():
                if values:
                    selectors[selector] = plain_value(values)
            value = ordered_selectors(selectors)

    unknown_pos_count = sum(
        1
        for group in item.groups
        if normalize_pos(group.pos) not in _CANONICAL_SELECTORS
        and unicodedata.normalize("NFC", group.pos).strip()
    )
    return value, {
        "key": key,
        "empty_ipa_count": empty_ipa_count,
        "case_collision": len({group.word for group in item.groups}) > 1,
        "unknown_pos_count": unknown_pos_count,
    }


def collapse_entry(item: Any) -> str | tuple[str, ...] | dict[str, object] | None:
    value, _ = _collapse(item)
    return value


def serialize_entries(entries: Mapping[str, object]) -> str:
    return _serialize_entries(entries)


def _audit_group(item: Any, value: object) -> dict[str, object]:
    groups: dict[str, list[str]] = {}
    for group in item.groups:
        selector = normalize_pos(group.pos)
        values = groups.setdefault(selector, [])
        for pronunciation in group.pronunciations:
            ipa = normalize_ipa(pronunciation.ipa)
            if ipa:
                _append_unique(values, ipa)
    default = value.get("DEFAULT") if isinstance(value, Mapping) else value
    return {
        "key": normalize_key(item.key),
        "groups": {
            key: plain_value(values) for key, values in ordered_selectors(groups).items() if values
        },
        "default": default,
    }


def transform_lexhint(
    entries: Iterable[Any], *, source_metadata: Mapping[str, object] | None = None
) -> LexHintTransformResult:
    output: dict[str, object] = {}
    reports: list[dict[str, object]] = []
    input_key_count = 0
    single_pronunciation_count = 0
    plain_multi_variant_count = 0
    pos_selector_count = 0
    case_collision_count = 0
    unknown_pos_count = 0
    empty_ipa_count = 0

    for item in entries:
        input_key_count += 1
        value, audit = _collapse(item)
        empty_ipa_count += int(audit["empty_ipa_count"])
        unknown_pos_count += int(audit["unknown_pos_count"])
        case_collision_count += int(audit["case_collision"])
        if value is None:
            continue
        key = str(audit["key"])
        output[key] = value
        if isinstance(value, Mapping):
            pos_selector_count += 1
            reports.append(_audit_group(item, value))
        elif isinstance(value, tuple):
            plain_multi_variant_count += 1
        else:
            single_pronunciation_count += 1

    report: dict[str, object] = {
        "transform": TRANSFORM_VERSION,
        "source": dict(source_metadata or {}),
        "input_key_count": input_key_count,
        "output_entry_count": len(output),
        "single_pronunciation_count": single_pronunciation_count,
        "plain_multi_variant_count": plain_multi_variant_count,
        "pos_selector_count": pos_selector_count,
        "case_collision_count": case_collision_count,
        "unknown_pos_count": unknown_pos_count,
        "empty_ipa_count": empty_ipa_count,
    }
    if reports:
        report["groups"] = reports
    return LexHintTransformResult(output, report)


def write_report(report: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


__all__ = [
    "TRANSFORM_VERSION",
    "LexHintTransformResult",
    "collapse_entry",
    "normalize_ipa",
    "serialize_entries",
    "transform_lexhint",
    "write_report",
]
