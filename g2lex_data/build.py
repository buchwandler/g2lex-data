from __future__ import annotations

import json
import os
import shutil
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Self

import g2lex

from . import __version__
from .capabilities import (
    NO_RESOLVABLE_AMBIGUITIES,
    NO_SENSE_LINKED_MAPPING,
    ResolutionCapability,
)
from .common import ASSET_DIR, MANIFEST_DIR, REPORT_DIR, sha256_file, write_json
from .config import AssetConfig, load_config
from .espeak import EspeakBackend
from .inventory import WordInventory, build_word_inventory
from .pronresolve_binding import bind_shared_rules
from .sources import ResolvedSource, resolve_source
from .transforms import TransformResult, apply
from .transforms.common import serialize_entries
from .transforms.espeak import EspeakPairResult, generate_espeak_pair
from .transforms.lexhint_pronunciations import TRANSFORM_VERSION as LEXHINT_TRANSFORM_VERSION

MANIFEST_SCHEMA_VERSION = 1
GENERATOR_CONTRACT = 2


def _g2lex_version() -> str:
    try:
        return version("g2lex")
    except PackageNotFoundError:
        return getattr(g2lex, "__version__", "0+unknown")


def validate_source(
    record: AssetConfig, *, parse: bool = True, resolved_source: ResolvedSource | None = None
) -> dict[str, object]:
    resolved = resolved_source or resolve_source(record)
    path = resolved.path
    if not path.is_file():
        raise FileNotFoundError(f"missing source for {record.id}: {path}")
    if record.source_provider == "file":
        if path.stat().st_size != record.source_size:
            raise ValueError(f"source size mismatch for {record.id}")
        if sha256_file(path) != record.source_sha256:
            raise ValueError(f"source SHA-256 mismatch for {record.id}")
    if record.source_provider == "g2lex-assets":
        resolved_paths = resolved.metadata.get("source_paths")
        if not isinstance(resolved_paths, dict):
            raise ValueError(f"missing parent paths for {record.id}")
        source_paths = {source_id: Path(str(path)) for source_id, path in resolved_paths.items()}
        inventory = build_word_inventory(source_paths, locale=record.id.split(":", 1)[0])
        return {
            "entry_count": len(inventory.keys),
            "logical_sha256": inventory.logical_sha256,
            "format": record.source_format,
            "provider": record.source_provider,
            "resolved": dict(resolved.metadata),
            "word_inventory": {
                "source_ids": list(inventory.source_ids),
                "source_entry_counts": inventory.source_entry_counts,
                "union_entry_count": len(inventory.keys),
                "duplicate_key_count": inventory.duplicate_key_count,
                "logical_sha256": inventory.logical_sha256,
            },
        }
    if record.source_provider == "lexhint":
        return {
            "entry_count": None,
            "logical_sha256": None,
            "format": record.source_format,
            "provider": record.source_provider,
            "resolved": dict(resolved.metadata),
        }
    if not parse:
        return {}
    parsed = g2lex.read_typed_lexicon(path, format=record.source_format, source_id=record.source_id)
    values = tuple(parsed.entries.values())
    if record.kind == "membership":
        if not values or any(value is not g2lex.WORD_ONLY for value in values):
            raise ValueError(f"membership source is not WORD_ONLY: {path}")
    elif any(value is g2lex.WORD_ONLY for value in values):
        raise ValueError(f"pronunciation source contains WORD_ONLY: {path}")
    return {
        "entry_count": len(parsed),
        "logical_sha256": parsed.logical_sha256,
        "format": record.source_format,
        "provider": record.source_provider,
        "resolved": dict(resolved.metadata),
    }


def _transform_metadata(result: TransformResult | None) -> dict[str, object]:
    if result is None:
        return {}
    metadata: dict[str, object] = {
        "id": result.metadata.get("transform"),
        "inputs": result.metadata.get("transform_inputs", {}),
        "report_sha256": result.metadata.get("transform_report_sha256"),
        "report_name": result.report_path.name if result.report_path is not None else None,
    }
    report = result.metadata.get("transform_report")
    if isinstance(report, dict):
        summary: dict[str, object] = {
            key: report[key]
            for key in (
                "runtime_profile_count",
                "runtime_cue_count",
                "resolver_index_schema_version",
                "resolver_index_byte_size",
                "resolver_policy_id",
            )
            if key in report
        }
        discovery = report.get("ambiguity_discovery")
        if isinstance(discovery, dict):
            summary["ambiguity_discovery"] = {
                key: discovery[key]
                for key in (
                    "entries_scanned",
                    "ambiguous_keys",
                    "resolvable_keys",
                    "unlinked_ambiguity_keys",
                    "non_ambiguous_keys",
                    "entries_without_pronunciation",
                    "entries_without_pos",
                )
                if key in discovery
            }
        if summary:
            metadata["report_summary"] = summary
    return metadata



def _pronunciation_resolution_capability(
    record: AssetConfig, result: TransformResult | None
) -> ResolutionCapability | None:
    if record.kind != "pronunciation":
        return None
    if result is not None and result.resolution_capability is not None:
        return result.resolution_capability
    if record.resolution_capability is not None:
        return record.resolution_capability
    return ResolutionCapability("unavailable", reason=NO_SENSE_LINKED_MAPPING)


def _capability_metadata(
    capability: ResolutionCapability | None, resolver: dict[str, object] | None
) -> dict[str, object] | None:
    if capability is None:
        return None
    if capability.status != "available":
        if resolver is not None:
            raise ValueError("non-available pronunciation capability cannot include a resolver index")
        return capability.to_dict()
    if resolver is None:
        raise ValueError("available pronunciation capability requires a resolver index")
    index = {
        key: resolver[key]
        for key in ("name", "schema_version", "language", "locale", "dataset_version", "sha256", "size")
    }
    return ResolutionCapability("available", index=index).to_dict()



def _verify_shared_rules_binding(
    packed_asset: Path,
    asset_id: str,
    binding_report: dict[str, object] | None,
) -> None:
    if binding_report is None:
        return
    records = binding_report.get("bindings")
    if not isinstance(records, list):
        raise TypeError(f"shared rules binding records are invalid for {asset_id}")
    with g2lex.open(packed_asset) as packed:
        for binding in records:
            if not isinstance(binding, dict) or binding.get("status") != "bound":
                continue
            reading_id = binding.get("reading_id")
            word = binding.get("word")
            if not isinstance(reading_id, str) or not isinstance(word, str):
                raise TypeError(f"shared rules binding identity is invalid for {asset_id}")
            selector = f"READING:{reading_id}"
            selected = packed.lookup(word, tag=selector)
            expected = binding.get("native_value")
            if isinstance(expected, list):
                matches = isinstance(selected, (tuple, list)) and list(selected) == expected
            else:
                matches = selected == expected
            if not matches:
                raise ValueError(f"shared rules selector mismatch for {word}/{selector} in {asset_id}")
def _binding_capability(
    report: dict[str, object] | None,
    report_reference: dict[str, object] | None,
) -> dict[str, object]:
    if report is None or report_reference is None:
        return {"status": "unavailable", "reason": "no_shared_rules_binding"}
    counts = report.get("status_counts")
    reading_count = report.get("reading_count")
    rules_id = report.get("rules_id")
    encoding = report.get("phoneme_encoding")
    if (
        not isinstance(counts, dict)
        or not isinstance(reading_count, int)
        or not isinstance(rules_id, str)
        or not isinstance(encoding, str)
    ):
        raise TypeError("shared-rules binding report has invalid summary fields")
    bound_count = counts.get("bound")
    if not isinstance(bound_count, int) or sum(counts.values()) != reading_count:
        raise ValueError("shared-rules binding counts do not match reading_count")
    status = "complete" if bound_count == reading_count else "partial" if bound_count else "unbound"
    return {
        "status": status,
        "rules_id": rules_id,
        "phoneme_encoding": encoding,
        "reading_count": reading_count,
        "status_counts": dict(counts),
        "report": dict(report_reference),
    }
def _shared_rules_reference(index, path: Path, dataset_version: str) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"shared rules artifact is missing: {path}")
    name = path.name
    if Path(name).name != name or not index.rules_id:
        raise ValueError("invalid shared rules artifact identity")
    return {
        "rules_id": index.rules_id,
        "name": name,
        "path": name,
        "schema_version": index.schema_version,
        "language": index.language,
        "locale": index.locale,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "dataset_version": dataset_version,
    }





def _publish_resolver_pair(
    staged_asset: Path, asset: Path, staged_index: Path, index: Path
) -> None:
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for destination in (asset, index):
            if destination.exists():
                backup = staged_asset.parent / f"{destination.name}.previous"
                os.replace(destination, backup)
                backups.append((destination, backup))
        os.replace(staged_asset, asset)
        published.append(asset)
        os.replace(staged_index, index)
        published.append(index)
    except BaseException:
        for destination in published:
            destination.unlink(missing_ok=True)
        for destination, backup in reversed(backups):
            os.replace(backup, destination)
        raise



def _publish_asset_without_resolver(staged_asset: Path, asset: Path, stale_index: Path) -> None:
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for destination in (asset, stale_index):
            if destination.exists():
                backup = staged_asset.parent / f"{destination.name}.previous"
                os.replace(destination, backup)
                backups.append((destination, backup))
        os.replace(staged_asset, asset)
        published.append(asset)
    except BaseException:
        for destination in published:
            destination.unlink(missing_ok=True)
        for destination, backup in reversed(backups):
            os.replace(backup, destination)
        raise

def _validate_espeak_pair_config(normal: AssetConfig, piper: AssetConfig) -> None:
    if normal.name != "espeak" or piper.name != "espeak-piper":
        raise ValueError("eSpeak pair must contain espeak and espeak-piper records")
    if normal.source_provider != "g2lex-assets" or piper.source_provider != "g2lex-assets":
        raise ValueError("eSpeak pair must use g2lex-assets providers")
    if normal.source_ids != piper.source_ids:
        raise ValueError("eSpeak pair source IDs differ")
    normal_inputs = normal.transform_inputs or {}
    piper_inputs = piper.transform_inputs or {}
    locale_fields = ("language",)
    for field in locale_fields:
        if getattr(normal, field) != getattr(piper, field):
            raise ValueError(f"eSpeak pair {field} differs")
    for field in ("voice", "espeak_git_revision", "expected_espeak_version", "piper_version"):
        if normal_inputs.get(field) != piper_inputs.get(field):
            raise ValueError(f"eSpeak pair transform input {field} differs")
    expected = (
        (normal_inputs.get("output_mode"), "ipa"),
        (piper_inputs.get("output_mode"), "ipa3"),
        (normal.phoneme_encoding, "ipa"),
        (piper.phoneme_encoding, "espeak-ipa3"),
        (normal.transform, "g2lex-espeak-ipa-v1"),
        (piper.transform, "g2lex-espeak-piper-ipa3-v1"),
    )
    if any(actual != expected_value for actual, expected_value in expected):
        raise ValueError("eSpeak pair output configuration is invalid")


def _build_source_record(
    record: AssetConfig,
    *,
    data_version: str,
    shared_rules: object | None = None,
    shared_equivalence_policy: object | None = None,
) -> dict[str, object]:
    resolved_source = resolve_source(record)
    source_info = validate_source(record, resolved_source=resolved_source)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name

    resolver_index_payload: dict[str, object] | None = None
    resolver_index_path: Path | None = None
    binding_report_data: dict[str, object] | None = None
    binding_report_path: Path | None = None
    binding_report_reference: dict[str, object] | None = None
    shared_rules_payload: dict[str, object] | None = None
    binding_capability_data: dict[str, object] | None = None
    with tempfile.TemporaryDirectory(
        prefix=f".{record.slug}.transform.", dir=ASSET_DIR
    ) as temp_name:
        transform_result = apply(
            record,
            resolved_source.path,
            Path(temp_name),
            source_metadata=resolved_source.metadata,
            shared_rules=shared_rules,
        )
        resolution_capability = _pronunciation_resolution_capability(record, transform_result)
        if resolution_capability is not None:
            has_resolver_path = (
                transform_result is not None and transform_result.resolver_index_path is not None
            )
            if resolution_capability.status == "available" and not has_resolver_path:
                raise ValueError(f"available pronunciation capability has no resolver index for {record.id}")
            if resolution_capability.status != "available" and has_resolver_path:
                raise ValueError(f"non-available pronunciation capability has a resolver index for {record.id}")
        staged_asset_path = Path(temp_name) / record.asset_name
        staged_index_path: Path | None = None
        if transform_result is not None and transform_result.resolver_index_path is not None:
            from pronresolve import load_index

            descriptor = transform_result.resolver_index_metadata
            if descriptor is None:
                raise ValueError(f"resolver index metadata is missing for {record.id}")
            index_name = str(descriptor.get("name", ""))
            if not index_name or Path(index_name).name != index_name:
                raise ValueError(f"invalid resolver index name for {record.id}")
            staged_index_path = transform_result.resolver_index_path
            if not staged_index_path.is_file():
                raise FileNotFoundError(
                    f"resolver index is missing for {record.id}: {staged_index_path}"
                )
            index = load_index(staged_index_path)
            if not index.profiles:
                raise ValueError(f"available resolver index is empty for {record.id}")
            for field, actual in (
                ("schema_version", index.schema_version),
                ("language", index.language),
                ("locale", index.locale),
            ):
                if descriptor.get(field) != actual:
                    raise ValueError(f"resolver index {field} mismatch for {record.id}")
            resolver_index_path = ASSET_DIR / index_name
            resolver_index_payload = {
                **descriptor,
                "path": index_name,
                "sha256": sha256_file(staged_index_path),
                "size": staged_index_path.stat().st_size,
                "dataset_version": data_version,
            }
        input_path = transform_result.input_path if transform_result else resolved_source.path
        input_format = transform_result.input_format if transform_result else record.source_format
        binding_index = shared_rules
        if (
            binding_index is None
            and transform_result is not None
            and transform_result.resolver_index_path is not None
        ):
            from pronresolve import load_index

            binding_index = load_index(transform_result.resolver_index_path)
        if (
            record.kind == "pronunciation"
            and binding_index is not None
            and binding_index is not False
        ):
            rules_id = binding_index.rules_id
            index_name = f"g2lex-{rules_id}.pronresolve.json"
            if staged_index_path is not None:
                rules_path = staged_index_path
            else:
                rules_path = ASSET_DIR / index_name
            from pronresolve import load_index

            disk_index = load_index(rules_path)
            if disk_index.to_dict() != binding_index.to_dict():
                raise ValueError(f"shared rules artifact does not match rules_id {rules_id}")
            shared_rules_payload = _shared_rules_reference(
                disk_index,
                rules_path,
                data_version,
            )
            resolver_index_payload = shared_rules_payload
            resolution_capability = ResolutionCapability(
                "available", index=shared_rules_payload
            )
        elif record.kind == "pronunciation" and shared_rules is False:
            resolution_capability = ResolutionCapability(
                "unnecessary", reason=NO_RESOLVABLE_AMBIGUITIES
            )
        capability_document = _capability_metadata(
            resolution_capability, resolver_index_payload
        )
        if (
            record.kind == "pronunciation"
            and binding_index is not None
            and binding_index is not False
        ):
            parsed_target = g2lex.read_typed_lexicon(
                input_path,
                format=input_format,
                source_id=record.source_id,
            )
            binding_result = bind_shared_rules(
                parsed_target.entries,
                binding_index,
                phoneme_encoding=record.phoneme_encoding,
                equivalence_policy=shared_equivalence_policy,
            )
            binding_report_data = binding_result.report.as_dict()
            binding_report_path = Path(temp_name) / f"{record.slug}.binding-report.json"
            write_json(binding_report_path, binding_report_data)
            binding_report_reference = {
                "name": binding_report_path.name,
                "path": binding_report_path.name,
                "sha256": sha256_file(binding_report_path),
                "size": binding_report_path.stat().st_size,
            }
            input_path = Path(temp_name) / f"{record.slug}.bound.json"
            input_path.write_text(
                serialize_entries(binding_result.entries),
                encoding="utf-8",
            )
            input_format = "json-map"
        if record.kind == "pronunciation":
            binding_capability_data = _binding_capability(
                binding_report_data,
                binding_report_reference,
            )
        g2lex.read_typed_lexicon(input_path, format=input_format, source_id=record.source_id)
        g2lex.pack_file(
            input_path,
            staged_asset_path,
            input_format=input_format,
            source_id=record.source_id,
            metadata={
                "schema_version": 1,
                "contract_version": 1,
                "catalog_id": record.id,
                "id": record.id,
                "language": record.language,
                "name": record.name,
                "display_name": record.display_name,
                "kind": record.kind,
                "phoneme_encoding": record.phoneme_encoding,
                "source_id": record.source_id,
                "source_format": record.source_format,
                "provider": record.provider,
                "revision": record.revision,
                "source_url": record.source_url,
                "license_expression": record.license_expression,
                "license_url": record.license_url,
                "attribution": record.attribution,
                "data_version": data_version,
                "producer": "g2lex-data",
                "producer_version": __version__,
                "g2lex_version": _g2lex_version(),
                "transform": _transform_metadata(transform_result),
                **(
                    {"resolver_index": resolver_index_payload}
                    if resolver_index_payload is not None
                    else {}
                ),
                **(
                    {"shared_rules": shared_rules_payload}
                    if shared_rules_payload is not None
                    else {}
                ),
                **(
                    {
                        "capabilities": {
                            **(
                                {"pronunciation_resolution": capability_document}
                                if capability_document is not None
                                else {}
                            ),
                            **(
                                {"pronunciation_binding": binding_capability_data}
                                if binding_capability_data is not None
                                else {}
                            ),
                        }
                    }
                    if capability_document is not None or binding_capability_data is not None
                    else {}
                ),
            },
        )
        verification = g2lex.verify_file(input_path, staged_asset_path, input_format=input_format)
        if not verification.get("lossless"):
            raise ValueError(f"lossless verification failed for {record.id}: {verification}")
        inspected = g2lex.inspect_file(staged_asset_path)
        _verify_shared_rules_binding(staged_asset_path, record.id, binding_report_data)

        if staged_index_path is not None:
            assert staged_index_path is not None and resolver_index_path is not None
            _publish_resolver_pair(
                staged_asset_path, asset_path, staged_index_path, resolver_index_path
            )
        else:
            stale_index = ASSET_DIR / f"g2lex-{record.slug}.pronresolve.json"
            _publish_asset_without_resolver(staged_asset_path, asset_path, stale_index)
        if transform_result is not None and transform_result.report_path is not None:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                transform_result.report_path,
                REPORT_DIR / f"{record.slug}.transform-report.json",
            )
        if binding_report_path is not None:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                binding_report_path,
                REPORT_DIR / f"{record.slug}.binding-report.json",
            )
    source_metadata = dict(resolved_source.metadata)
    source_payload: dict[str, object] = {
        "id": record.source_id,
        "provider_type": record.source_provider,
        "path": record.source,
        "format": record.source_format,
        "url": record.source_url,
        "revision": record.revision,
        "sha256": record.source_sha256,
        "size": record.source_size,
        "entry_count": source_info["entry_count"],
        "logical_sha256": source_info["logical_sha256"],
        "provider": record.provider,
        "license_expression": record.license_expression,
        "license_url": record.license_url,
        "attribution": record.attribution,
        "resolved": source_metadata,
    }
    if record.source_provider == "lexhint":
        source_payload.update(
            {
                "revision": source_metadata["release_tag"],
                "sha256": source_metadata["sqlite_sha256"],
                "size": source_metadata["sqlite_size"],
                "selector": {
                    "language": source_metadata["language"],
                    "source_variant": source_metadata["source_variant"],
                    "variant": source_metadata["variant"],
                    "schema_version": source_metadata["schema_version"],
                    "version_policy": "latest-compatible",
                },
            }
        )
    manifest: dict[str, object] = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "contract_version": 1,
        "id": record.id,
        "language": record.language,
        "name": record.name,
        "display_name": record.display_name,
        "kind": record.kind,
        "phoneme_encoding": record.phoneme_encoding,
        "data_version": data_version,
        "producer": {"name": "g2lex-data", "version": __version__},
        "g2lex": {"version": _g2lex_version(), "generator_contract": GENERATOR_CONTRACT},
        "source": source_payload,
        "transform": _transform_metadata(transform_result),
        **(
            {"resolver_index": resolver_index_payload}
            if resolver_index_payload is not None
            else {}
        ),
        **(
            {"shared_rules": shared_rules_payload}
            if shared_rules_payload is not None
            else {}
        ),
        **(
            {
                "capabilities": {
                    **(
                        {"pronunciation_resolution": capability_document}
                        if capability_document is not None
                        else {}
                    ),
                    **(
                        {"pronunciation_binding": binding_capability_data}
                        if binding_capability_data is not None
                        else {}
                    ),
                }
            }
            if capability_document is not None or binding_capability_data is not None
            else {}
        ),
        "asset": {
            "name": record.asset_name,
            "filename": record.asset_name,
            "sha256": sha256_file(asset_path),
            "size": asset_path.stat().st_size,
            "format": inspected["format"],
            "schema": inspected["schema"],
            "entry_count": inspected["entry_count"],
            "logical_sha256": inspected["logical_sha256"],
        },
        "verification": {
            "source_integrity": True,
            "transform_deterministic": True,
            "lossless": True,
            "typed_values_preserved": True,
            "variant_order_preserved": True,
            "resolver_index_pair": resolver_index_payload is not None,
            "generated_from_validated_output": True,
        },
    }
    write_json(MANIFEST_DIR / record.manifest_name, manifest)
    return manifest


def _write_espeak_variant(
    record: AssetConfig,
    *,
    entries: dict[str, object],
    binding_report: dict[str, object] | None = None,
    shared_rules: object | None = None,

    pair: EspeakPairResult,
    inventory: WordInventory,
    source_paths: dict[str, Path],
    data_version: str,
) -> dict[str, object]:
    report = {
        **pair.shared_report,
        "variant": pair.normal_report if record.name == "espeak" else pair.piper_report,
    }
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSET_DIR / record.asset_name
    inputs = record.transform_inputs or {}
    shared_rules_payload: dict[str, object] | None = None
    resolution_capability = _pronunciation_resolution_capability(record, None)
    if shared_rules is not None and shared_rules is not False:
        rules_path = ASSET_DIR / f"g2lex-{shared_rules.rules_id}.pronresolve.json"
        from pronresolve import load_index

        disk_index = load_index(rules_path)
        if disk_index.to_dict() != shared_rules.to_dict():
            raise ValueError(f"shared rules artifact does not match rules_id {shared_rules.rules_id}")
        shared_rules_payload = _shared_rules_reference(disk_index, rules_path, data_version)
        resolution_capability = ResolutionCapability("available", index=shared_rules_payload)
    elif shared_rules is False:
        resolution_capability = ResolutionCapability(
            "unnecessary", reason=NO_RESOLVABLE_AMBIGUITIES
        )
    capability_document = _capability_metadata(resolution_capability, shared_rules_payload)
    with tempfile.TemporaryDirectory(prefix=f".{record.slug}.transform.", dir=ASSET_DIR) as temp_name:
        temp_dir = Path(temp_name)
        staged_asset_path = temp_dir / record.asset_name
        input_path = temp_dir / f"{record.slug}.json"
        input_path.write_text(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        binding_report_path: Path | None = None
        binding_report_reference: dict[str, object] | None = None
        if binding_report is not None:
            binding_report_path = temp_dir / f"{record.slug}.binding-report.json"
            write_json(binding_report_path, binding_report)
            binding_report_reference = {
                "name": binding_report_path.name,
                "path": binding_report_path.name,
                "sha256": sha256_file(binding_report_path),
                "size": binding_report_path.stat().st_size,
            }
        binding_capability_data = _binding_capability(
            binding_report,
            binding_report_reference,
        )
        report["pronunciation_binding"] = binding_capability_data
        report_path = temp_dir / f"{record.slug}.transform-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        transform_inputs = {**inputs, "generator": pair.shared_report["generator"]}
        transform_result = TransformResult(
            input_path,
            "json-map",
            {
                "transform": record.transform,
                "transform_inputs": transform_inputs,
                "source_metadata": {"word_inventory": report["word_inventory"]},
                **(
                    {"pronunciation_binding": binding_capability_data}
                    if binding_report is not None
                    else {}
                ),
                "transform_report_sha256": sha256_file(report_path),
            },
            report_path,
        )
        g2lex.read_typed_lexicon(input_path, format="json-map", source_id=record.source_id)
        g2lex.pack_file(
            input_path,
            staged_asset_path,
            input_format="json-map",
            source_id=record.source_id,
            metadata={
                "schema_version": 1,
                "contract_version": 1,
                "catalog_id": record.id,
                "id": record.id,
                "language": record.language,
                "name": record.name,
                "display_name": record.display_name,
                "kind": record.kind,
                "phoneme_encoding": record.phoneme_encoding,
                "source_id": record.source_id,
                "source_format": record.source_format,
                "provider": record.provider,
                "revision": record.revision,
                "source_url": record.source_url,
                "license_expression": record.license_expression,
                "license_url": record.license_url,
                "attribution": record.attribution,
                "data_version": data_version,
                "producer": "g2lex-data",
                "producer_version": __version__,
                "g2lex_version": _g2lex_version(),
                "source_ids": list(record.source_ids),
                "word_inventory": report["word_inventory"],
                "transform": _transform_metadata(transform_result),
                **(
                    {"resolver_index": shared_rules_payload}
                    if shared_rules_payload is not None
                    else {}
                ),
                **(
                    {"shared_rules": shared_rules_payload}
                    if shared_rules_payload is not None
                    else {}
                ),
                **(
                    {
                        "capabilities": {
                            **(
                                {"pronunciation_resolution": capability_document}
                                if capability_document is not None
                                else {}
                            ),
                            "pronunciation_binding": binding_capability_data,
                        }
                    }
                    if capability_document is not None or binding_capability_data is not None
                    else {}
                ),
            },
        )
        verification = g2lex.verify_file(input_path, staged_asset_path, input_format="json-map")
        if not verification.get("lossless"):
            raise ValueError(f"lossless verification failed for {record.id}: {verification}")
        inspected = g2lex.inspect_file(staged_asset_path)
        _publish_asset_without_resolver(
            staged_asset_path, asset_path, ASSET_DIR / f"g2lex-{record.slug}.pronresolve.json"
        )
        _verify_shared_rules_binding(staged_asset_path, record.id, binding_report)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, REPORT_DIR / f"{record.slug}.transform-report.json")
        if binding_report_path is not None:
            shutil.copy2(
                binding_report_path,
                REPORT_DIR / f"{record.slug}.binding-report.json",
            )
    source_payload = {
        "id": list(record.source_ids),
        "provider_type": record.source_provider,
        "path": None,
        "format": record.source_format,
        "url": record.source_url,
        "revision": record.revision,
        "sha256": None,
        "size": None,
        "entry_count": inventory.source_entry_counts,
        "logical_sha256": inventory.logical_sha256,
        "provider": record.provider,
        "license_expression": record.license_expression,
        "license_url": record.license_url,
        "attribution": record.attribution,
        "resolved": {
            "source_ids": list(record.source_ids),
            "source_paths": {key: str(value) for key, value in source_paths.items()},
        },
    }
    manifest = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "contract_version": 1,
        "id": record.id,
        "language": record.language,
        "name": record.name,
        "display_name": record.display_name,
        "kind": record.kind,
        "phoneme_encoding": record.phoneme_encoding,
        "data_version": data_version,
        "producer": {"name": "g2lex-data", "version": __version__},
        "g2lex": {"version": _g2lex_version(), "generator_contract": GENERATOR_CONTRACT},
        "source": source_payload,
        "word_inventory": report["word_inventory"],
        "transform": _transform_metadata(transform_result),
        **(
            {"resolver_index": shared_rules_payload}
            if shared_rules_payload is not None
            else {}
        ),
        **(
            {"shared_rules": shared_rules_payload}
            if shared_rules_payload is not None
            else {}
        ),
        **(
            {
                "capabilities": {
                    **(
                        {"pronunciation_resolution": capability_document}
                        if capability_document is not None
                        else {}
                    ),
                    "pronunciation_binding": binding_capability_data,
                }
            }
            if capability_document is not None or binding_capability_data is not None
            else {}
        ),
        "asset": {
            "name": record.asset_name,
            "filename": record.asset_name,
            "sha256": sha256_file(asset_path),
            "size": asset_path.stat().st_size,
            "format": inspected["format"],
            "schema": inspected["schema"],
            "entry_count": inspected["entry_count"],
            "logical_sha256": inspected["logical_sha256"],
        },
        "verification": {
            "source_integrity": True,
            "transform_deterministic": True,
            "lossless": True,
            "typed_values_preserved": True,
            "variant_order_preserved": True,
            "generated_from_validated_output": True,
            "pair_key_parity": True,
        },
    }
    write_json(MANIFEST_DIR / record.manifest_name, manifest)
    return manifest


class BuildSession:
    def __init__(self, *, data_version: str) -> None:
        self.config = load_config()
        self.data_version = data_version
        self.manifests: dict[str, dict[str, object]] = {}
        self._espeak_backend: EspeakBackend | None = None
        self._closed = False
        self._shared_rules_by_locale: dict[str, object | None] = {}
        self._shared_equivalence_by_locale: dict[str, object | None] = {}

    def _uses_shared_rules(self, record: AssetConfig) -> bool:
        if record.kind != "pronunciation":
            return False
        if record.transform == LEXHINT_TRANSFORM_VERSION:
            return True
        if record.name == "gold" and record.phoneme_encoding == "ipa":
            return True
        if record.name == "espeak" and record.phoneme_encoding == "ipa":
            return True
        return (record.transform_inputs or {}).get("pronresolve_shared_rules") is True


    def _canonical_rules_record(self, locale: str) -> AssetConfig | None:
        candidates = [
            candidate
            for candidate in self.config.assets
            if candidate.id.split(":", 1)[0] == locale
            and candidate.kind == "pronunciation"
            and candidate.source_provider == "lexhint"
            and candidate.transform == LEXHINT_TRANSFORM_VERSION
        ]
        return next(
            (candidate for candidate in candidates if candidate.name == "lexhint-native"),
            None,
        ) or next((candidate for candidate in candidates if candidate.name == "lexhint"), None)

    def _shared_equivalence_policy_for(self, record: AssetConfig) -> object | None:
        if not self._uses_shared_rules(record):
            return None
        locale = record.id.split(":", 1)[0]
        if locale in self._shared_equivalence_by_locale:
            return self._shared_equivalence_by_locale[locale]
        canonical = self._canonical_rules_record(locale)
        if canonical is None:
            return None
        inputs = canonical.transform_inputs or {}
        equivalence_name = inputs.get("pronunciation_equivalence", "exact")
        if equivalence_name == "exact":
            policy = None
        elif equivalence_name == "phonodist":
            stress_policy = inputs.get("stress_policy", "all")
            if stress_policy not in ("all", "primary"):
                raise ValueError("stress_policy must be 'all' or 'primary'")
            from pronresolve import PhonodistEquivalence

            language = str(inputs.get("lexhint_language", canonical.language.split("-", 1)[0]))
            policy = PhonodistEquivalence(language=language, stress_policy=stress_policy)
        else:
            raise ValueError("pronunciation_equivalence must be 'exact' or 'phonodist'")
        self._shared_equivalence_by_locale[locale] = policy
        return policy
    def _shared_rules_for(self, record: AssetConfig) -> object | None:
        if not self._uses_shared_rules(record):
            return None
        locale = record.id.split(":", 1)[0]
        if locale in self._shared_rules_by_locale:
            return self._shared_rules_by_locale[locale]
        canonical = self._canonical_rules_record(locale)
        if canonical is None:
            if (
                record.transform == LEXHINT_TRANSFORM_VERSION
                or (record.transform_inputs or {}).get("pronresolve_shared_rules") is True
            ):
                raise ValueError(f"no canonical LexHint rules source is configured for locale {locale!r}")
            return None
        if record.id == canonical.id:
            return None

        manifest = self.build_record(canonical)
        descriptor = manifest.get("shared_rules", manifest.get("resolver_index"))
        if not isinstance(descriptor, dict):
            self._shared_rules_by_locale[locale] = False
            return False
        name = descriptor.get("path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"canonical rules index path is invalid for {canonical.id}")
        from pronresolve import load_index

        index = load_index(ASSET_DIR / name)
        if descriptor.get("rules_id") != index.rules_id:
            raise ValueError(f"canonical rules_id mismatch for {canonical.id}")
        self._shared_rules_by_locale[locale] = index
        return index

    def build_record(self, record: AssetConfig) -> dict[str, object]:
        cached = self.manifests.get(record.id)
        if cached is not None:
            return cached
        if record.source_provider == "g2lex-assets":
            normal, piper = self.build_espeak_pair(record.id.split(":", 1)[0])
            return normal if record.name == "espeak" else piper
        shared_rules = self._shared_rules_for(record)
        equivalence_policy = self._shared_equivalence_policy_for(record)
        if shared_rules is None and equivalence_policy is None:
            manifest = _build_source_record(record, data_version=self.data_version)
        else:
            manifest = _build_source_record(
                record,
                data_version=self.data_version,
                shared_rules=shared_rules,
                shared_equivalence_policy=equivalence_policy,
            )
        self.manifests[record.id] = manifest
        return manifest

    def build_id(self, identifier: str) -> dict[str, object]:
        return self.build_record(self.config.asset(identifier))

    def _get_espeak_backend(self, record: AssetConfig) -> EspeakBackend:
        if self._espeak_backend is None:
            inputs = record.transform_inputs or {}
            self._espeak_backend = EspeakBackend(
                git_revision=str(inputs.get("espeak_git_revision", record.revision)),
                expected_version=(
                    str(inputs["expected_espeak_version"])
                    if inputs.get("expected_espeak_version")
                    else None
                ),
            )
        return self._espeak_backend

    def espeak_backend(self, record: AssetConfig) -> EspeakBackend:
        return self._get_espeak_backend(record)

    def build_espeak_pair(self, locale: str) -> tuple[dict[str, object], dict[str, object]]:
        normal_id = f"{locale}:espeak"
        piper_id = f"{locale}:espeak-piper"
        normal_record = self.config.asset(normal_id)
        piper_record = self.config.asset(piper_id)
        normal_manifest = self.manifests.get(normal_id)
        piper_manifest = self.manifests.get(piper_id)
        if normal_manifest is not None and piper_manifest is not None:
            return normal_manifest, piper_manifest
        if normal_manifest is not None or piper_manifest is not None:
            raise RuntimeError(f"incomplete eSpeak pair cache for {locale}")
        _validate_espeak_pair_config(normal_record, piper_record)
        source_paths: dict[str, Path] = {}
        for source_id in normal_record.source_ids:
            parent = self.config.asset(source_id)
            self.build_record(parent)
            source_paths[source_id] = ASSET_DIR / parent.asset_name
        inventory = build_word_inventory(source_paths, locale=locale)
        inputs = normal_record.transform_inputs or {}
        pair = generate_espeak_pair(
            inventory=inventory,
            voice=str(inputs["voice"]),
            backend=self._get_espeak_backend(normal_record),
        )
        shared_rules = self._shared_rules_for(normal_record)
        shared_equivalence_policy = self._shared_equivalence_policy_for(normal_record)
        normal_entries: dict[str, object] = dict(pair.normal_entries)
        piper_entries: dict[str, object] = dict(pair.piper_entries)
        normal_binding_report: dict[str, object] | None = None
        piper_binding_report: dict[str, object] | None = None
        if shared_rules is not None and shared_rules is not False:
            normal_binding = bind_shared_rules(
                normal_entries,
                shared_rules,
                phoneme_encoding=normal_record.phoneme_encoding,
                equivalence_policy=shared_equivalence_policy,
            )
            piper_binding = bind_shared_rules(
                piper_entries,
                shared_rules,
                phoneme_encoding=piper_record.phoneme_encoding,
                equivalence_policy=shared_equivalence_policy,
            )
            normal_entries = normal_binding.entries
            piper_entries = piper_binding.entries
            normal_binding_report = normal_binding.report.as_dict()
            piper_binding_report = piper_binding.report.as_dict()
        normal_manifest = _write_espeak_variant(
            normal_record,
            entries=normal_entries,
            pair=pair,
            inventory=inventory,
            source_paths=source_paths,
            data_version=self.data_version,
            binding_report=normal_binding_report,
            shared_rules=shared_rules,

        )
        piper_manifest = _write_espeak_variant(
            piper_record,
            entries=piper_entries,
            pair=pair,
            inventory=inventory,
            source_paths=source_paths,
            binding_report=piper_binding_report,
            shared_rules=shared_rules,

            data_version=self.data_version,
        )
        self.manifests[normal_id] = normal_manifest
        self.manifests[piper_id] = piper_manifest
        return normal_manifest, piper_manifest

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._espeak_backend is not None:
            self._espeak_backend.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def build_one(record: AssetConfig, *, data_version: str = "unreleased") -> dict[str, object]:
    with BuildSession(data_version=data_version) as session:
        return session.build_record(record)


def build(
    ids: list[str] | None = None, *, data_version: str = "unreleased"
) -> tuple[dict[str, object], ...]:
    config = load_config()
    records = (
        config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)
    )
    with BuildSession(data_version=data_version) as session:
        return tuple(session.build_record(record) for record in records)


def build_static(*, data_version: str = "unreleased") -> tuple[dict[str, object], ...]:
    from .build_plan import static_asset_ids

    config = load_config()
    return build(list(static_asset_ids(config)), data_version=data_version)


def build_espeak_pairs(
    locales: list[str], *, data_version: str = "unreleased"
) -> tuple[dict[str, object], ...]:
    with BuildSession(data_version=data_version) as session:
        manifests: list[dict[str, object]] = []
        seen: set[str] = set()
        for locale in locales:
            if locale in seen:
                continue
            seen.add(locale)
            normal, piper = session.build_espeak_pair(locale)
            manifests.extend((normal, piper))
        return tuple(manifests)


__all__ = [
    "BuildSession",
    "build",
    "build_espeak_pairs",
    "build_one",
    "validate_source",
]
