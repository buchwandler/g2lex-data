from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

TRANSFORM_ID = "cstr-de-ipa-v1"


def _strip_one_outer_pair(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "/" and value[-1] == "/":
        return value[1:-1]
    return value


def normalize_cstr(source: Path, output: Path) -> dict[str, object]:
    """Normalize CSTR IPA rows while retaining row order for each spelling."""
    values: dict[str, list[str]] = defaultdict(list)
    physical_rows = 0
    skipped_header = False
    with source.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, 1):
            physical_rows += 1
            line = line.rstrip("\r\n")
            if not line:
                continue
            fields = line.split("\t")
            if line_number == 1 and len(fields) >= 2 and fields[:2] == ["word", "espeak_ipa"]:
                skipped_header = True
                continue
            if len(fields) not in (2, 3):
                raise ValueError(
                    f"{source}:{line_number}: expected two or three tab-separated fields"
                )
            word, pronunciation = fields[:2]
            if not word:
                raise ValueError(f"{source}:{line_number}: empty spelling")
            pronunciation = _strip_one_outer_pair(pronunciation)
            if not pronunciation:
                raise ValueError(f"{source}:{line_number}: empty pronunciation")
            values[word].append(pronunciation)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for word in sorted(values):
            for pronunciation in values[word]:
                stream.write(f"{word}\t{pronunciation}\n")
    return {
        "transform": TRANSFORM_ID,
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "source_rows": physical_rows,
        "source_unique_spellings": len(values),
        "transformed_rows": sum(len(items) for items in values.values()),
        "skipped_header": skipped_header,
        "strip_outer_delimiters": True,
        "preserve_internal_slashes": True,
        "retain_optional_annotations": True,
    }


def report_json(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
