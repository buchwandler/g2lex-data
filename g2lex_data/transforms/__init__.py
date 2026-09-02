from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cstr_de
from .crane import TRANSFORM_VERSION, serialize_entries, transform_crane

Transform = Callable[[Any, Path, Path], "TransformResult"]


@dataclass(frozen=True, slots=True)
class TransformResult:
    input_path: Path
    input_format: str
    metadata: dict[str, object]
    report_path: Path | None = None


def _crane(record: Any, source: Path, temp_dir: Path) -> TransformResult:
    try:
        from lexhint import Lexicon
    except ModuleNotFoundError as exc:
        raise RuntimeError("the Crane transform requires the optional lexhint package") from exc

    expected = record.transform_inputs or {}
    lexicon = Lexicon(str(expected.get("lexhint_language", record.language.split("-", 1)[0])))
    artifact = Path(lexicon.path)
    actual_hash = _sha256(artifact)
    if expected.get("lexhint_artifact_sha256") != actual_hash:
        raise ValueError(f"LexHint artifact SHA-256 differs from pinned value for {record.id}")
    result = transform_crane(
        source,
        lexhint_lexicon=lexicon,
        source_metadata={
            "crane_source_sha256": _sha256(source),
            "lexhint_language": expected.get("lexhint_language"),
            "lexhint_artifact": expected.get("lexhint_artifact"),
            "lexhint_artifact_sha256": actual_hash,
            "lexhint_version": expected.get("lexhint_version"),
        },
    )
    intermediate = temp_dir / f"{record.slug}.json"
    intermediate.write_text(serialize_entries(result.entries), encoding="utf-8")
    report = temp_dir / f"{record.slug}.transform-report.json"
    cstr_de.report_json(result.report)
    report.write_text(
        __import__("json").dumps(result.report, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    metadata = {
        "transform": TRANSFORM_VERSION,
        "transform_inputs": {
            "crane_sha256": _sha256(source),
            "lexhint_sha256": actual_hash,
            "lexhint_version": expected.get("lexhint_version"),
        },
        "transform_report_sha256": _sha256(report),
        "lexhint_language": expected.get("lexhint_language"),
        "lexhint_artifact": expected.get("lexhint_artifact"),
        "lexhint_artifact_sha256": actual_hash,
        "lexhint_version": expected.get("lexhint_version"),
        "key_normalization": "NFC+lower",
        "transform_report": result.report,
    }
    return TransformResult(intermediate, "kokoro-json", metadata, report)


def _cstr(record: Any, source: Path, temp_dir: Path) -> TransformResult:
    output = temp_dir / f"{record.slug}.tsv"
    report = cstr_de.normalize_cstr(source, output)
    report_path = temp_dir / f"{record.slug}.transform-report.json"
    report_path.write_text(cstr_de.report_json(report), encoding="utf-8")
    return TransformResult(
        output,
        "tsv",
        {
            "transform": cstr_de.TRANSFORM_ID,
            "transform_inputs": dict(record.transform_inputs or {}),
            "transform_report_sha256": _sha256(report_path),
            "transform_report": report,
        },
        report_path,
    )


REGISTRY: dict[str, Transform] = {
    TRANSFORM_VERSION: _crane,
    cstr_de.TRANSFORM_ID: _cstr,
}


def apply(record: Any, source: Path, temp_dir: Path) -> TransformResult | None:
    if record.transform is None:
        return None
    try:
        transform = REGISTRY[record.transform]
    except KeyError as exc:
        raise ValueError(f"unknown transform ID: {record.transform}") from exc
    return transform(record, source, temp_dir)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["REGISTRY", "TransformResult", "apply"]
