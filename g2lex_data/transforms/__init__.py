from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capabilities import NO_RESOLVABLE_AMBIGUITIES, ResolutionCapability
from ..espeak import EspeakBackend
from ..inventory import build_word_inventory
from ..sources import resolve_lexhint_transform_input
from . import cstr_de
from .crane import TRANSFORM_VERSION as CRANE_TRANSFORM_VERSION
from .crane import serialize_entries, transform_crane
from .espeak import (
    NORMAL_TRANSFORM_ID,
    PIPER_TRANSFORM_ID,
    generate_espeak_pair,
)
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

    resolver_index_path: Path | None = None
    resolver_index_metadata: dict[str, object] | None = None
    resolution_capability: ResolutionCapability | None = None


from .kokoro_legacy import TRANSFORM_VERSION as KOKORO_LEGACY_TRANSFORM_VERSION
from .kokoro_legacy import transform_kokoro_legacy


def _espeak(
    record: Any,
    source: Path,
    temp_dir: Path,
    *,
    source_metadata: Mapping[str, object] | None = None,
) -> TransformResult:
    resolved = dict(source_metadata or {})
    raw_paths = resolved.get("source_paths")
    if isinstance(raw_paths, dict):
        source_paths = {source_id: Path(str(path)) for source_id, path in raw_paths.items()}
    else:
        source_paths = {record.source_ids[0]: source}
    inventory = build_word_inventory(source_paths, locale=record.id.split(":", 1)[0])
    inputs = record.transform_inputs or {}
    backend = EspeakBackend(
        git_revision=str(inputs.get("espeak_git_revision", record.revision)),
        expected_version=(
            str(inputs["expected_espeak_version"])
            if inputs.get("expected_espeak_version")
            else None
        ),
    )
    try:
        pair = generate_espeak_pair(
            inventory=inventory,
            voice=str(inputs["voice"]),
            backend=backend,
        )
    finally:
        backend.close()
    entries = pair.normal_entries if record.name == "espeak" else pair.piper_entries
    temp_dir.mkdir(parents=True, exist_ok=True)
    intermediate = temp_dir / f"{record.slug}.json"
    intermediate.write_text(
        __import__("json").dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    report = {
        **pair.shared_report,
        "variant": pair.normal_report if record.name == "espeak" else pair.piper_report,
    }
    report_path = temp_dir / f"{record.slug}.transform-report.json"
    report_path.write_text(
        __import__("json").dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return TransformResult(
        intermediate,
        "json-map",
        {
            "transform": record.transform,
            "transform_inputs": {**inputs, "generator": pair.shared_report["generator"]},
            "source_metadata": {"word_inventory": report["word_inventory"]},
            "transform_report_sha256": _sha256(report_path),
        },
        report_path,
    )


def _crane(record: Any, source: Path, temp_dir: Path) -> TransformResult:
    try:
        from lexhint import Lexicon
    except ModuleNotFoundError as exc:
        raise RuntimeError("the Crane transform requires the optional lexhint package") from exc

    expected = record.transform_inputs or {}
    resolved = resolve_lexhint_transform_input(record)
    language = str(expected["lexhint_language"])
    lexicon = Lexicon.from_path(resolved.path, language=language)
    resolved_metadata = dict(resolved.metadata)
    crane_sha256 = _sha256(source)
    lexhint_metadata = {
        "lexhint_language": resolved_metadata["language"],
        "lexhint_source_variant": resolved_metadata["source_variant"],
        "lexhint_variant": resolved_metadata["variant"],
        "lexhint_dataset_version": resolved_metadata["dataset_version"],
        "lexhint_schema_version": resolved_metadata["schema_version"],
        "lexhint_release_tag": resolved_metadata["release_tag"],
        "lexhint_release_asset": resolved_metadata["asset"],
        "lexhint_release_asset_sha256": resolved_metadata["release_asset_sha256"],
        "lexhint_artifact_sha256": resolved_metadata["sqlite_sha256"],
        "lexhint_artifact_size": resolved_metadata["sqlite_size"],
        "lexhint_wiktionary_edition": resolved_metadata["wiktionary_edition"],
        "lexhint_metadata_language": resolved_metadata["metadata_language"],
        "lexhint_version": resolved_metadata["lexhint_version"],
    }
    result = transform_crane(
        source,
        lexhint_lexicon=lexicon,
        source_metadata={"crane_source_sha256": crane_sha256, **lexhint_metadata},
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
    transform_inputs = dict(expected)
    transform_inputs.update(
        {
            "crane_sha256": crane_sha256,
            "lexhint_sha256": resolved_metadata["sqlite_sha256"],
            **lexhint_metadata,
        }
    )
    metadata = {
        "transform": CRANE_TRANSFORM_VERSION,
        "transform_inputs": transform_inputs,
        "source_metadata": lexhint_metadata,
        "transform_report_sha256": _sha256(report),
        **lexhint_metadata,
        "key_normalization": "NFC+lower",
        "transform_report": result.report,
    }
    return TransformResult(intermediate, "kokoro-json", metadata, report)




def _locale_filtered_discovery_entries(
    lexicon: Any, *, language: str, locale: str | None, include_neutral: bool
):
    """Filter entry-level pronunciations with LexHint's locale selection rules."""
    if not locale:
        return lexicon.iter_entries()

    from dataclasses import replace

    from lexhint.languages import source_tags_match_locale
    from pronresolve.normalization import normalize_pos, normalize_word

    def matches(pronunciation: Any) -> bool:
        return bool(pronunciation.tags) and source_tags_match_locale(
            pronunciation.tags, language, locale
        )

    locale_matched_keys: set[tuple[str, str]] = set()
    if not include_neutral:
        for entry in lexicon.iter_entries():
            if any(matches(pronunciation) for pronunciation in entry.pronunciations):
                locale_matched_keys.add((normalize_word(entry.word), normalize_pos(entry.pos)))

    def filtered_entries():
        for entry in lexicon.iter_entries():
            key = (normalize_word(entry.word), normalize_pos(entry.pos))
            if include_neutral:
                pronunciations = tuple(
                    pronunciation
                    for pronunciation in entry.pronunciations
                    if not pronunciation.tags or matches(pronunciation)
                )
            elif key in locale_matched_keys:
                pronunciations = tuple(
                    pronunciation
                    for pronunciation in entry.pronunciations
                    if matches(pronunciation)
                )
            else:
                pronunciations = tuple(
                    pronunciation
                    for pronunciation in entry.pronunciations
                    if not pronunciation.tags
                )
            yield replace(entry, pronunciations=pronunciations)

    return filtered_entries()


def _lexhint(
    record: Any,
    source: Path,
    temp_dir: Path,
    *,
    source_metadata: Mapping[str, object] | None = None,
) -> TransformResult:
    import pronresolve
    from lexhint import Lexicon
    from pronresolve import __version__ as pronresolve_version
    from pronresolve import discover_ambiguities, save_index
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
        "source_variant": resolved.get("source_variant", expected.get("lexhint_source_variant")),
        "variant": resolved.get("variant", expected.get("lexhint_variant")),
        "dataset_version": resolved.get("dataset_version", expected.get("lexhint_dataset_version")),
        "schema_version": resolved.get("schema_version", expected.get("lexhint_schema_version")),
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
    discovery = discover_ambiguities(
        _locale_filtered_discovery_entries(
            lexicon,
            language=language,
            locale=locale if isinstance(locale, str) else None,
            include_neutral=include_neutral,
        ),
        language=language,
        locale=locale if isinstance(locale, str) else None,
    )
    if discovery.index.schema_version != 2:
        raise ValueError(
            f"unsupported pronresolve schema version for g2lex-data: "
            f"{discovery.index.schema_version}"
        )
    profiles = discovery.index.profiles
    result = transform_lexhint(
        lexicon.iter_pronunciations(include_neutral=include_neutral),
        source_metadata=transform_source_metadata,
        reading_profiles=profiles,
    )
    result.report["ambiguity_discovery"] = discovery.report.as_dict()
    result.report["runtime_profile_count"] = len(profiles)
    result.report["runtime_cue_count"] = sum(len(profile.cues) for profile in profiles)
    result.report["resolver_index_schema_version"] = discovery.index.schema_version

    temp_dir.mkdir(parents=True, exist_ok=True)
    index_path = temp_dir / f"g2lex-{record.slug}.pronresolve.json"
    resolver_index_path: Path | None = None
    resolver_index_metadata: dict[str, object] | None = None
    if profiles:
        save_index(discovery.index, index_path)
        resolver_index_path = index_path
        resolver_index_metadata = {
            "name": index_path.name,
            "schema_version": discovery.index.schema_version,
            "language": discovery.index.language,
            "locale": discovery.index.locale,
            "dataset_version": transform_source_metadata["dataset_version"],
        }
        capability = ResolutionCapability("available", index=resolver_index_metadata)
        result.report["resolver_index_byte_size"] = index_path.stat().st_size
    else:
        index_path.unlink(missing_ok=True)
        capability = ResolutionCapability(
            "unnecessary", reason=NO_RESOLVABLE_AMBIGUITIES
        )
        result.report["resolver_index_byte_size"] = 0

    policy_id = getattr(pronresolve, "RUNTIME_POLICY_ID", None)
    if isinstance(policy_id, str) and policy_id:
        result.report["resolver_policy_id"] = policy_id

    intermediate = temp_dir / f"{record.slug}.json"
    intermediate.write_text(serialize_lexhint_entries(result.entries), encoding="utf-8")
    report_path = temp_dir / f"{record.slug}.transform-report.json"
    write_lexhint_report(result.report, report_path)
    transform_inputs = {
        **expected,
        "pronresolve_version": pronresolve_version,
        "pronresolve_index_schema_version": discovery.index.schema_version,
    }
    if isinstance(policy_id, str) and policy_id:
        transform_inputs["pronresolve_policy"] = policy_id
    metadata = {
        "transform": LEXHINT_TRANSFORM_VERSION,
        "transform_inputs": transform_inputs,
        **({"resolver_index": resolver_index_metadata} if resolver_index_metadata is not None else {}),
        "capabilities": {"pronunciation_resolution": capability.to_dict()},
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
    return TransformResult(
        intermediate,
        "json-map",
        metadata,
        report_path,
        resolver_index_path=resolver_index_path,
        resolution_capability=capability,
        resolver_index_metadata=resolver_index_metadata,
    )


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
    NORMAL_TRANSFORM_ID: _espeak,
    PIPER_TRANSFORM_ID: _espeak,
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
    if record.transform in {NORMAL_TRANSFORM_ID, PIPER_TRANSFORM_ID}:
        return _espeak(record, source, temp_dir, source_metadata=source_metadata)
    return transform(record, source, temp_dir)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["REGISTRY", "TransformResult", "apply"]
