from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cstr_de
from .crane import TRANSFORM_VERSION as CRANE_TRANSFORM_VERSION
from .crane import serialize_entries, transform_crane
from .lexhint_pronunciations import TRANSFORM_VERSION as LEXHINT_TRANSFORM_VERSION
from .lexhint_pronunciations import serialize_entries as serialize_lexhint_entries
from .lexhint_pronunciations import transform_lexhint
from .lexhint_pronunciations import write_report as write_lexhint_report

Transform = Callable[[Any, Path, Path], "TransformResult"]


@dataclass(frozen=True, slots=True)
class TransformResult:
    input_path: Path
    input_format: str
    metadata: dict[str, object]
    report_path: Path | None = None


from .kokoro_legacy import TRANSFORM_VERSION as KOKORO_LEGACY_TRANSFORM_VERSION
from .kokoro_legacy import transform_kokoro_legacy


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
        "transform": CRANE_TRANSFORM_VERSION,
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


def _lexhint(
    record: Any,
    source: Path,
    temp_dir: Path,
    *,
    source_metadata: Mapping[str, object] | None = None,
) -> TransformResult:
    from lexhint import Lexicon

    expected = record.transform_inputs or {}
    language = str(expected.get("lexhint_language", record.language.split("-", 1)[0]))
    locale = expected.get("lexhint_locale")
    include_neutral = bool(expected.get("include_neutral", True))
    lexicon = Lexicon.from_path(
        source,
        language=language,
        locale=locale if isinstance(locale, str) else None,
    )
    resolved = dict(source_metadata or {})
    transform_source_metadata = {
        "language": resolved.get("language", language),
        "source_variant": resolved.get(
            "source_variant", expected.get("lexhint_source_variant")
        ),
        "variant": resolved.get("variant", expected.get("lexhint_variant")),
        "dataset_version": resolved.get(
            "dataset_version", expected.get("lexhint_dataset_version")
        ),
        "schema_version": resolved.get(
            "schema_version", expected.get("lexhint_schema_version")
        ),
        "release_tag": resolved.get("release_tag"),
        "release_published_at": resolved.get("release_published_at"),
        "asset": resolved.get("asset"),
        "release_asset_sha256": resolved.get("release_asset_sha256"),
        "sqlite_sha256": resolved.get("sqlite_sha256", _sha256(source)),
        "sqlite_size": resolved.get("sqlite_size", source.stat().st_size),
        "wiktionary_edition": resolved.get("wiktionary_edition"),
        "metadata_language": resolved.get("metadata_language"),
        "locale": locale,
        "include_neutral": include_neutral,
        "lexhint_version": resolved.get("lexhint_version"),
    }
    result = transform_lexhint(
        lexicon.iter_pronunciations(include_neutral=include_neutral),
        source_metadata=transform_source_metadata,
    )
    temp_dir.mkdir(parents=True, exist_ok=True)
    intermediate = temp_dir / f"{record.slug}.json"
    intermediate.write_text(serialize_lexhint_entries(result.entries), encoding="utf-8")
    report_path = temp_dir / f"{record.slug}.transform-report.json"
    write_lexhint_report(result.report, report_path)
    metadata = {
        "transform": LEXHINT_TRANSFORM_VERSION,
        "transform_inputs": dict(expected),
        "source_metadata": transform_source_metadata,
        "transform_report_sha256": _sha256(report_path),
        "transform_report": result.report,
        "source_sha256": transform_source_metadata["sqlite_sha256"],
        "source_size": transform_source_metadata["sqlite_size"],
        "lexhint_language": transform_source_metadata["language"],
        "lexhint_source_variant": transform_source_metadata["source_variant"],
        "lexhint_variant": transform_source_metadata["variant"],
        "lexhint_dataset_version": transform_source_metadata["dataset_version"],
        "lexhint_schema_version": transform_source_metadata["schema_version"],
        "lexhint_locale": locale,
        "include_neutral": include_neutral,
    }
    return TransformResult(intermediate, "json-map", metadata, report_path)


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
    KOKORO_LEGACY_TRANSFORM_VERSION: transform_kokoro_legacy,
    CRANE_TRANSFORM_VERSION: _crane,
    LEXHINT_TRANSFORM_VERSION: _lexhint,
    cstr_de.TRANSFORM_ID: _cstr,
}


def apply(
    record: Any,
    source: Path,
    temp_dir: Path,
    *,
    source_metadata: Mapping[str, object] | None = None,
) -> TransformResult | None:
    if record.transform is None:
        return None
    try:
        transform = REGISTRY[record.transform]
    except KeyError as exc:
        raise ValueError(f"unknown transform ID: {record.transform}") from exc
    if record.transform == LEXHINT_TRANSFORM_VERSION:
        return _lexhint(record, source, temp_dir, source_metadata=source_metadata)
    return transform(record, source, temp_dir)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["REGISTRY", "TransformResult", "apply"]
