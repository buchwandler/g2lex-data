from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from pathlib import Path

import g2lex

from .build import validate_source
from .capabilities import NO_RESOLVABLE_AMBIGUITIES, NO_SENSE_LINKED_MAPPING
from .common import (
    ASSET_DIR,
    CATALOG_PATH,
    MANIFEST_DIR,
    REPORT_DIR,
    read_json,
    sha256_file,
)
from .config import AssetConfig, load_config
from .inventory import build_word_inventory, logical_sha256_for_keys
from .pronresolve_binding import bind_shared_rules
from .sources import resolve_source
from .transforms import TransformResult, apply


def _validate_resolver_index(
    record: AssetConfig,
    asset_path: Path,
    manifest: dict[str, object],
    *,
    generated: TransformResult | None = None,
    generated_binding_report: dict[str, object] | None = None,
) -> None:
    transform = manifest.get("transform")
    inputs = transform.get("inputs", {}) if isinstance(transform, dict) else {}
    inputs = inputs if isinstance(inputs, dict) else {}
    descriptor = manifest.get("shared_rules", manifest.get("resolver_index"))
    if manifest.get("shared_rules") is not None and manifest.get("resolver_index") != descriptor:
        raise ValueError(f"legacy resolver alias differs from shared rules for {record.id}")
    capabilities = manifest.get("capabilities")

    if record.kind != "pronunciation":
        if descriptor is not None or capabilities is not None:
            raise ValueError(f"non-pronunciation asset has pronunciation capability metadata: {record.id}")
        with g2lex.open(asset_path) as packed:
            if (
                packed.metadata.get("resolver_index") is not None
                or packed.metadata.get("shared_rules") is not None
            ):
                raise ValueError(f"non-pronunciation asset has shared-rule metadata: {record.id}")
        return

    if not isinstance(capabilities, dict):
        raise TypeError(f"pronunciation capability is missing for {record.id}")
    capability = capabilities.get("pronunciation_resolution")
    if not isinstance(capability, dict):
        raise TypeError(f"pronunciation-resolution capability is missing for {record.id}")
    status = capability.get("status")
    if status not in {"available", "unnecessary", "unavailable"}:
        raise ValueError(f"invalid pronunciation-resolution status for {record.id}")
    binding_capability = capabilities.get("pronunciation_binding")
    binding_report_data: dict[str, object] | None = None

    if status != "available":
        reason = capability.get("reason")
        if not isinstance(reason, str) or not reason.strip() or "index" in capability:
            raise ValueError(f"invalid {status} pronunciation capability for {record.id}")
        expected_reason = (
            NO_RESOLVABLE_AMBIGUITIES if status == "unnecessary" else NO_SENSE_LINKED_MAPPING
        )
        if reason != expected_reason:
            raise ValueError(f"unexpected {status} pronunciation capability reason for {record.id}")
        if descriptor is not None:
            raise ValueError(f"non-available capability has shared rules for {record.id}")
        if binding_capability is not None and (
            not isinstance(binding_capability, dict)
            or binding_capability.get("status") != "unavailable"
            or not isinstance(binding_capability.get("reason"), str)
            or "report" in binding_capability
        ):
            raise ValueError(f"invalid unavailable binding capability for {record.id}")
        stale_index = ASSET_DIR / f"g2lex-{record.slug}.pronresolve.json"
        if stale_index.exists():
            raise ValueError(f"non-available capability has a stale shared-rules file for {record.id}")
        with g2lex.open(asset_path) as packed:
            if (
                packed.metadata.get("resolver_index") is not None
                or packed.metadata.get("shared_rules") is not None
            ):
                raise ValueError(f"non-available capability has embedded shared rules for {record.id}")
            if packed.metadata.get("capabilities") != capabilities:
                raise ValueError(f"G2Lex capability metadata mismatch for {record.id}")
        if record.resolution_capability is not None and capability != record.resolution_capability.to_dict():
            raise ValueError(f"configured pronunciation capability mismatch for {record.id}")
        if status == "unnecessary":
            transform_summary = transform.get("report_summary") if isinstance(transform, dict) else None
            discovery = (
                transform_summary.get("ambiguity_discovery")
                if isinstance(transform_summary, dict)
                else None
            )
            if (
                not isinstance(transform_summary, dict)
                or transform_summary.get("runtime_profile_count") != 0
                or not isinstance(discovery, dict)
                or discovery.get("entries_scanned") is None
                or discovery.get("resolvable_keys") != 0
            ):
                raise ValueError(f"zero-profile discovery evidence is missing for {record.id}")
            if generated is not None:
                generated_capability = generated.resolution_capability
                generated_report = generated.metadata.get("transform_report")
                if (
                    generated_capability is None
                    or generated_capability.status != "unnecessary"
                    or generated_capability.reason != reason
                    or not isinstance(generated_report, dict)
                    or generated_report.get("runtime_profile_count") != 0
                ):
                    raise ValueError(f"current zero-profile transform evidence mismatch for {record.id}")
        return

    if not isinstance(capability.get("index"), dict) or "reason" in capability:
        raise ValueError(f"available pronunciation capability lacks index metadata for {record.id}")
    if not isinstance(descriptor, dict):
        raise TypeError(f"available pronunciation capability lacks shared-rules descriptor for {record.id}")
    name = descriptor.get("path", descriptor.get("name"))
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError(f"invalid shared-rules path for {record.id}")
    index_path = ASSET_DIR / name
    if not index_path.is_file():
        raise FileNotFoundError(f"missing shared rules for {record.id}: {index_path}")
    if sha256_file(index_path) != descriptor.get("sha256"):
        raise ValueError(f"shared-rules SHA mismatch for {record.id}")
    if index_path.stat().st_size != descriptor.get("size"):
        raise ValueError(f"shared-rules size mismatch for {record.id}")

    from pronresolve import load_index

    index = load_index(index_path)
    if not index.profiles or index.schema_version not in {2, 3}:
        raise ValueError(f"available shared rules must be non-empty schema v2/v3 for {record.id}")
    if index.schema_version == 3 and descriptor.get("rules_id") != index.rules_id:
        raise ValueError(f"shared-rules rules_id mismatch for {record.id}")
    if (
        descriptor.get("schema_version") != index.schema_version
        or descriptor.get("language") != index.language
        or descriptor.get("locale") != index.locale
        or descriptor.get("dataset_version") != manifest.get("data_version")
    ):
        raise ValueError(f"shared-rules identity mismatch for {record.id}")
    expected_capability_index = {
        key: descriptor.get(key)
        for key in ("name", "schema_version", "language", "locale", "dataset_version", "sha256", "size")
    }
    if capability["index"] != expected_capability_index:
        raise ValueError(f"capability shared-rules descriptor mismatch for {record.id}")
    schema_input = inputs.get("pronresolve_index_schema_version")
    if schema_input is not None and schema_input != index.schema_version:
        raise ValueError(f"shared-rules schema input mismatch for {record.id}")
    expected_language = inputs.get("lexhint_language")
    if expected_language is not None and str(expected_language).casefold() != index.language:
        raise ValueError(f"shared-rules language input mismatch for {record.id}")
    expected_locale = inputs.get("lexhint_locale")
    if expected_locale is not None and expected_locale != index.locale:
        raise ValueError(f"shared-rules locale input mismatch for {record.id}")

    if binding_capability is not None:
        if not isinstance(binding_capability, dict):
            raise TypeError(f"invalid pronunciation-binding capability for {record.id}")
        binding_status = binding_capability.get("status")
        valid_binding_statuses = {"bound", "missing", "ambiguous", "unsupported_encoding", "unsafe_equivalence"}
        if binding_status not in {"complete", "partial", "unbound"}:
            raise ValueError(f"invalid shared-rules binding status for {record.id}")
        if binding_capability.get("rules_id") != index.rules_id:
            raise ValueError(f"binding rules_id mismatch for {record.id}")
        counts = binding_capability.get("status_counts")
        reading_count = binding_capability.get("reading_count")
        report = binding_capability.get("report")
        if (
            not isinstance(counts, dict)
            or set(counts) != valid_binding_statuses
            or not all(isinstance(value, int) and value >= 0 for value in counts.values())
            or not isinstance(reading_count, int)
            or sum(counts.values()) != reading_count
            or not isinstance(report, dict)
        ):
            raise ValueError(f"invalid pronunciation-binding summary for {record.id}")
        expected_binding_status = (
            "complete"
            if counts["bound"] == reading_count
            else "partial"
            if counts["bound"]
            else "unbound"
        )
        if binding_status != expected_binding_status:
            raise ValueError(f"pronunciation-binding status mismatch for {record.id}")
        report_name = report.get("path", report.get("name"))
        if not isinstance(report_name, str) or Path(report_name).name != report_name:
            raise ValueError(f"invalid binding-report path for {record.id}")
        report_path = REPORT_DIR / report_name
        if not report_path.is_file():
            raise FileNotFoundError(f"binding report missing for {record.id}: {report_path}")
        if sha256_file(report_path) != report.get("sha256"):
            raise ValueError(f"binding report SHA mismatch for {record.id}")
        if report_path.stat().st_size != report.get("size"):
            raise ValueError(f"binding report size mismatch for {record.id}")
        loaded_report = read_json(report_path)
        if (
            not isinstance(loaded_report, dict)
            or loaded_report.get("rules_id") != index.rules_id
            or loaded_report.get("phoneme_encoding") != binding_capability.get("phoneme_encoding")
            or loaded_report.get("reading_count") != reading_count
            or loaded_report.get("status_counts") != counts
        ):
            raise ValueError(f"binding report summary mismatch for {record.id}")
        report_bindings = loaded_report.get("bindings")
        profiles = {profile.reading_id: profile for profile in index.profiles}
        if not isinstance(report_bindings, list) or len(report_bindings) != len(profiles):
            raise ValueError(f"binding report coverage mismatch for {record.id}")
        bindings_by_id: dict[str, dict[str, object]] = {}
        actual_counts = {status_name: 0 for status_name in valid_binding_statuses}
        for item in report_bindings:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("reading_id"), str)
                or item["reading_id"] not in profiles
                or item["reading_id"] in bindings_by_id
                or item.get("status") not in actual_counts
            ):
                raise ValueError(f"invalid binding report entry for {record.id}")
            profile = profiles[item["reading_id"]]
            if item.get("word") != profile.word or item.get("pos") != profile.pos:
                raise ValueError(f"binding report profile mismatch for {record.id}")
            bindings_by_id[item["reading_id"]] = item
            actual_counts[item["status"]] += 1
        if set(bindings_by_id) != set(profiles) or actual_counts != counts:
            raise ValueError(f"binding report totals mismatch for {record.id}")
        binding_report_data = loaded_report
    elif index.schema_version == 3:
        raise ValueError(f"schema-v3 shared rules lack binding metadata for {record.id}")

    with g2lex.open(asset_path) as packed:
        if packed.metadata.get("resolver_index") != descriptor:
            raise ValueError(f"G2Lex resolver alias mismatch for {record.id}")
        if packed.metadata.get("shared_rules") != descriptor:
            raise ValueError(f"G2Lex shared-rules metadata mismatch for {record.id}")
        if packed.metadata.get("capabilities") != capabilities:
            raise ValueError(f"G2Lex capability metadata mismatch for {record.id}")
        if binding_report_data is not None:
            profiles = {profile.reading_id: profile for profile in index.profiles}
            for binding in binding_report_data["bindings"]:
                assert isinstance(binding, dict)
                if binding["status"] != "bound":
                    continue
                selector = f"READING:{binding['reading_id']}"
                if packed.lookup(str(binding["word"]), tag=selector) != binding.get("native_value"):
                    raise ValueError(f"bound shared-rules selector mismatch for {record.id}: {selector}")
        elif index.schema_version == 2:
            for profile in index.profiles:
                selector = f"READING:{profile.reading_id}"
                if packed.lookup(profile.word, tag=selector) != profile.ipa:
                    raise ValueError(f"legacy resolver selector mismatch for {record.id}: {selector}")

    if generated is not None and generated.resolver_index_path is not None:
        generated_capability = generated.resolution_capability
        if (
            generated_capability is None
            or generated_capability.status != "available"
            or generated_capability.index is None
        ):
            raise ValueError(f"generated shared rules are missing for {record.id}")
        generated_index = load_index(generated.resolver_index_path)
        if generated_index.to_dict() != index.to_dict():
            raise ValueError(f"shared rules do not match current transform for {record.id}")
    if generated_binding_report is not None and binding_report_data != generated_binding_report:
        raise ValueError(f"binding report does not match current transform for {record.id}")

def _records(ids: list[str] | None) -> tuple[AssetConfig, ...]:
    config = load_config()
    return config.assets if ids is None else tuple(config.asset(identifier) for identifier in ids)


def _validate_derived_pair(
    record: AssetConfig,
    asset_path: Path,
    manifest: dict[str, object],
) -> None:
    config = load_config()
    source_paths: dict[str, Path] = {}
    for source_id in record.source_ids:
        parent = config.asset(source_id)
        path = ASSET_DIR / parent.asset_name
        if not path.is_file():
            raise FileNotFoundError(f"parent G2Lex asset is missing for {record.id}: {path}")
        source_paths[source_id] = path
    inventory = build_word_inventory(source_paths, locale=record.id.split(":", 1)[0])
    with g2lex.open(asset_path) as lexicon:
        keys = tuple(lexicon.keys())
    provenance = manifest.get("word_inventory")
    if not isinstance(provenance, dict):
        raise TypeError(f"missing word inventory provenance for {record.id}")
    skipped_value = provenance.get("skipped_keys")
    if not isinstance(skipped_value, list) or not all(
        isinstance(key, str) for key in skipped_value
    ):
        raise ValueError(f"invalid skipped keys for {record.id}")
    skipped_keys = tuple(skipped_value)
    if skipped_keys != tuple(sorted(skipped_keys)) or len(set(skipped_keys)) != len(skipped_keys):
        raise ValueError(f"skipped keys are not deterministic for {record.id}")
    if (
        provenance.get("union_entry_count") != len(inventory.keys)
        or provenance.get("union_logical_sha256") != inventory.logical_sha256
    ):
        raise ValueError(f"derived source union provenance mismatch for {record.id}")
    if provenance.get("generated_entry_count") != len(keys) or provenance.get(
        "logical_sha256"
    ) != provenance.get("generated_logical_sha256"):
        raise ValueError(f"derived generated inventory count mismatch for {record.id}")
    generated_sha256 = logical_sha256_for_keys(keys)
    if provenance.get("generated_logical_sha256") != generated_sha256:
        raise ValueError(f"derived generated inventory hash mismatch for {record.id}")
    if (
        set(keys).intersection(skipped_keys)
        or tuple(sorted(set(keys) | set(skipped_keys))) != inventory.keys
    ):
        raise ValueError(f"derived asset key inventory mismatch for {record.id}")
    pair_name = "espeak-piper" if record.name == "espeak" else "espeak"
    pair_id = f"{record.id.split(':', 1)[0]}:{pair_name}"
    pair_record = config.asset(pair_id)
    pair_path = ASSET_DIR / pair_record.asset_name
    pair_manifest_path = MANIFEST_DIR / pair_record.manifest_name
    if not pair_path.is_file() or not pair_manifest_path.is_file():
        raise FileNotFoundError(f"paired asset is missing for {record.id}: {pair_id}")
    with g2lex.open(pair_path) as pair_lexicon:
        if tuple(pair_lexicon.keys()) != keys:
            raise ValueError(f"paired asset key mismatch for {record.id}")
    pair_manifest = read_json(pair_manifest_path)
    pair_provenance = pair_manifest.get("word_inventory")
    if not isinstance(pair_provenance, dict):
        raise TypeError(f"missing paired word inventory provenance for {record.id}")
    for field in (
        "union_logical_sha256",
        "generated_logical_sha256",
        "logical_sha256",
        "skipped_entry_count",
        "skipped_keys",
    ):
        if pair_provenance.get(field) != provenance.get(field):
            raise ValueError(f"paired inventory provenance mismatch for {record.id}")


def validate_one(
    record: AssetConfig,
    *,
    verify_transform: bool = True,
    verify_source: bool = True,
) -> None:
    resolved_source = None
    source_info = None
    if verify_source or verify_transform:
        resolved_source = resolve_source(record)
    if verify_source:
        source_info = validate_source(record, parse=True, resolved_source=resolved_source)
    asset_path = ASSET_DIR / record.asset_name
    manifest_path = MANIFEST_DIR / record.manifest_name
    if not asset_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"missing build output for {record.id}")
    manifest = read_json(manifest_path)
    if manifest.get("id") != record.id:
        raise ValueError(f"manifest id mismatch for {record.id}")
    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise TypeError(f"invalid manifest asset object for {record.id}")
    if sha256_file(asset_path) != asset.get("sha256"):
        raise ValueError(f"asset SHA mismatch for {record.id}")
    if asset_path.stat().st_size != asset.get("size"):
        raise ValueError(f"asset size mismatch for {record.id}")
    inspected = g2lex.inspect_file(asset_path)
    if asset.get("entry_count") != inspected.get("entry_count"):
        raise ValueError(f"asset entry count mismatch for {record.id}")
    if asset.get("logical_sha256") != inspected.get("logical_sha256"):
        raise ValueError(f"asset logical hash mismatch for {record.id}")
    generated_transform_result: TransformResult | None = None
    generated_binding_report: dict[str, object] | None = None
    if record.source_provider == "g2lex-assets":
        _validate_derived_pair(record, asset_path, manifest)
        _validate_resolver_index(record, asset_path, manifest)
    elif verify_transform:
        with tempfile.TemporaryDirectory(prefix=f".{record.slug}.validate.") as temp_name:
            shared_rules_descriptor = manifest.get("shared_rules", manifest.get("resolver_index"))
            shared_rules_index = None
            shared_equivalence_policy = None
            is_canonical_rules_record = False
            if isinstance(shared_rules_descriptor, dict):
                from pronresolve import load_index

                rules_name = shared_rules_descriptor.get("path", shared_rules_descriptor.get("name"))
                if not isinstance(rules_name, str) or Path(rules_name).name != rules_name:
                    raise ValueError(f"invalid shared-rules path for {record.id}")
                shared_rules_index = load_index(ASSET_DIR / rules_name)
                if shared_rules_index.schema_version == 3:
                    from .build import BuildSession

                    session = BuildSession(data_version=str(manifest.get("data_version", "unreleased")))
                    try:
                        canonical_record = session._canonical_rules_record(record.id.split(":", 1)[0])
                        is_canonical_rules_record = (
                            canonical_record is not None and canonical_record.id == record.id
                        )
                        shared_equivalence_policy = session._shared_equivalence_policy_for(record)
                    finally:
                        session.close()
            generated_transform_result = apply(
                record,
                resolved_source.path,
                Path(temp_name),
                shared_rules=(
                    shared_rules_index
                    if shared_rules_index is not None
                    and shared_rules_index.schema_version == 3
                    and not is_canonical_rules_record
                    else None
                ),

            )
            input_path = (
                generated_transform_result.input_path
                if generated_transform_result
                else resolved_source.path
            )
            input_format = (
                generated_transform_result.input_format
                if generated_transform_result
                else record.source_format
            )
            if shared_rules_index is not None and shared_rules_index.schema_version == 3:
                parsed_target = g2lex.read_typed_lexicon(
                    input_path,
                    format=input_format,
                    source_id=record.source_id,
                )
                binding_result = bind_shared_rules(
                    parsed_target.entries,
                    shared_rules_index,
                    phoneme_encoding=record.phoneme_encoding,
                    equivalence_policy=shared_equivalence_policy,
                )
                generated_binding_report = binding_result.report.as_dict()
                bound_input_path = Path(temp_name) / f"{record.slug}.bound.json"
                bound_input_path.write_text(
                    json.dumps(binding_result.entries, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                input_path = bound_input_path
                input_format = "json-map"
            verification = g2lex.verify_file(input_path, asset_path, input_format=input_format)
            if not verification.get("lossless"):
                raise ValueError(f"asset no longer verifies losslessly for {record.id}")
            _validate_resolver_index(
                record,
                asset_path,
                manifest,
                generated=generated_transform_result,
                generated_binding_report=generated_binding_report,
            )
    else:
        _validate_resolver_index(record, asset_path, manifest)
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise TypeError(f"invalid manifest source object for {record.id}")
    if verify_source:
        if record.source_provider == "lexhint":
            expected_source_sha256 = resolved_source.metadata["sqlite_sha256"]
            expected_source_size = resolved_source.metadata["sqlite_size"]
        else:
            expected_source_sha256 = record.source_sha256
            expected_source_size = record.source_size
        if (
            source.get("sha256") != expected_source_sha256
            or source.get("size") != expected_source_size
        ):
            raise ValueError(f"manifest source pin mismatch for {record.id}")
        if (
            record.source_provider != "g2lex-assets"
            and source.get("entry_count") != source_info["entry_count"]
        ):
            raise ValueError(f"manifest source entry count mismatch for {record.id}")


def validate_catalog(path: Path = CATALOG_PATH, *, ids: list[str] | None = None) -> None:
    catalog = read_json(path)
    if (
        catalog.get("catalog_version") != 1
        or catalog.get("runtime_contract") != "g2lex-data.catalog.v1"
    ):
        raise ValueError("unsupported catalog contract")
    artifacts = catalog.get("artifacts")
    records = _records(ids)
    if not isinstance(artifacts, list) or len(artifacts) != len(records):
        raise ValueError("catalog must contain exactly one artifact per configured asset")
    records_by_id = {record.id: record for record in records}
    expected_ids = set(records_by_id)
    actual_ids: set[str] = set()
    shared_rules_by_id: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TypeError("catalog artifact entries must be objects")
        identifier = artifact.get("id")
        if identifier not in records_by_id or identifier in actual_ids:
            raise ValueError(f"unexpected or duplicate catalog ID: {identifier}")
        actual_ids.add(identifier)
        asset = artifact.get("asset")
        manifest = artifact.get("manifest")
        if not isinstance(asset, dict) or not isinstance(manifest, dict):
            raise TypeError(f"catalog artifact {identifier} lacks asset metadata")
        for key in ("url",):
            if not str(asset.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog asset URL for {identifier}")
            if not str(manifest.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog manifest URL for {identifier}")
        record = records_by_id[identifier]
        manifest_document = read_json(MANIFEST_DIR / record.manifest_name)
        manifest_caps = manifest_document.get("capabilities")
        catalog_caps = artifact.get("capabilities")
        manifest_index = manifest_document.get("shared_rules", manifest_document.get("resolver_index"))
        catalog_index = artifact.get("shared_rules", artifact.get("resolver_index"))
        _validate_resolver_index(record, ASSET_DIR / record.asset_name, manifest_document)
        if record.kind == "pronunciation":
            if not isinstance(manifest_caps, dict) or not isinstance(catalog_caps, dict):
                raise ValueError(f"catalog pronunciation capability mismatch for {identifier}")
            manifest_resolution = manifest_caps.get("pronunciation_resolution")
            catalog_resolution = catalog_caps.get("pronunciation_resolution")
            if manifest_resolution != catalog_resolution:
                raise ValueError(f"catalog pronunciation-resolution mismatch for {identifier}")
            manifest_binding = manifest_caps.get("pronunciation_binding")
            catalog_binding = catalog_caps.get("pronunciation_binding")
            if manifest_binding is None and catalog_binding is None:
                pass
            elif not isinstance(manifest_binding, dict) or not isinstance(catalog_binding, dict):
                raise ValueError(f"catalog pronunciation-binding mismatch for {identifier}")
            elif manifest_binding.get("status") == "unavailable":
                if catalog_binding != {
                    "status": manifest_binding.get("status"),
                    "reason": manifest_binding.get("reason"),
                }:
                    raise ValueError(f"catalog unavailable binding mismatch for {identifier}")
            else:
                report = manifest_binding.get("report")
                catalog_report = catalog_binding.get("report")
                if not isinstance(report, dict) or not isinstance(catalog_report, dict):
                    raise ValueError(f"catalog binding report reference missing for {identifier}")
                report_name = report.get("path", report.get("name"))
                expected_report = {
                    "name": report_name,
                    "url": str(asset["url"]).rsplit("/", 1)[0] + "/" + str(report_name),
                    "sha256": report.get("sha256"),
                    "size": report.get("size"),
                }
                expected_binding = {
                    key: manifest_binding.get(key)
                    for key in (
                        "status",
                        "rules_id",
                        "phoneme_encoding",
                        "reading_count",
                        "status_counts",
                    )
                }
                expected_binding["report"] = expected_report
                if catalog_binding != expected_binding:
                    raise ValueError(f"catalog pronunciation-binding mismatch for {identifier}")
            if manifest_resolution.get("status") == "available":
                if not isinstance(manifest_index, dict) or not isinstance(catalog_index, dict):
                    raise ValueError(f"catalog shared rules missing for {identifier}")
                index_name = manifest_index.get("path", manifest_index.get("name"))
                expected_index = {
                    "rules_id": manifest_index.get("rules_id"),
                    "name": index_name,
                    "url": str(asset["url"]).rsplit("/", 1)[0] + "/" + str(index_name),
                    "sha256": manifest_index.get("sha256"),
                    "size": manifest_index.get("size"),
                    "schema_version": manifest_index.get("schema_version"),
                    "language": manifest_index.get("language"),
                    "locale": manifest_index.get("locale"),
                    "dataset_version": manifest_index.get("dataset_version"),
                }
                if catalog_index != expected_index or artifact.get("resolver_index") != expected_index:
                    raise ValueError(f"catalog shared-rules reference mismatch for {identifier}")
                rules_id = str(expected_index["rules_id"])
                previous = shared_rules_by_id.get(rules_id)
                if previous is not None and previous != expected_index:
                    raise ValueError(f"catalog has conflicting shared rules for {rules_id}")
                shared_rules_by_id[rules_id] = expected_index
            elif manifest_index is not None or catalog_index is not None:
                raise ValueError(f"non-available catalog capability has shared rules for {identifier}")
        elif catalog_caps is not None or manifest_caps is not None or catalog_index is not None:
            raise ValueError(f"non-pronunciation catalog artifact has capabilities for {identifier}")
    if actual_ids != expected_ids:
        raise ValueError("catalog IDs do not match configured assets")
    catalog_shared_rules = catalog.get("shared_rules", [])
    if not isinstance(catalog_shared_rules, list):
        raise TypeError("catalog shared_rules must be an array")
    expected_shared_rules = sorted(
        shared_rules_by_id.values(),
        key=lambda item: str(item["rules_id"]),
    )
    if catalog_shared_rules != expected_shared_rules:
        raise ValueError("catalog shared-rules inventory is inconsistent")
def validate_prebuilt_set(*, ids: list[str] | None = None, data_version: str) -> None:
    records = _records(ids)
    expected_assets = {record.asset_name for record in records}
    expected_manifests = {record.manifest_name for record in records}
    expected_resolver_indexes: set[str] = set()
    expected_binding_reports: set[str] = set()
    for record in records:
        asset_path = ASSET_DIR / record.asset_name
        manifest_path = MANIFEST_DIR / record.manifest_name
        if not asset_path.is_file():
            raise FileNotFoundError(
                f"prebuilt release is incomplete: missing asset: {record.asset_name}"
            )
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"prebuilt release is incomplete: missing manifest: {record.manifest_name}"
            )
        manifest = read_json(manifest_path)
        if manifest.get("id") != record.id:
            raise ValueError(f"manifest id mismatch for {record.id}")
        if manifest.get("data_version") != data_version:
            raise ValueError(
                f"manifest data version mismatch for {record.id}: "
                f"expected {data_version}, got {manifest.get('data_version')}"
            )
        asset = manifest.get("asset")
        if not isinstance(asset, dict):
            raise TypeError(f"invalid manifest asset object for {record.id}")
        inspected = g2lex.inspect_file(asset_path)
        checks = (
            (sha256_file(asset_path), asset.get("sha256"), "asset SHA"),
            (asset_path.stat().st_size, asset.get("size"), "asset size"),
            (inspected.get("entry_count"), asset.get("entry_count"), "asset entry count"),
            (inspected.get("logical_sha256"), asset.get("logical_sha256"), "asset logical hash"),
        )
        for actual, expected, label in checks:
            if actual != expected:
                raise ValueError(f"{label} mismatch for {record.id}")
        _validate_resolver_index(record, asset_path, manifest)
        if record.kind == "pronunciation":
            capability = manifest["capabilities"]["pronunciation_resolution"]
            if capability["status"] == "available":
                descriptor = manifest.get("shared_rules", manifest.get("resolver_index"))
                expected_resolver_indexes.add(str(descriptor.get("path", descriptor.get("name"))))
            binding = manifest["capabilities"].get("pronunciation_binding")
            if isinstance(binding, dict) and binding.get("status") != "unavailable":
                report = binding.get("report")
                if not isinstance(report, dict):
                    raise ValueError(f"binding report descriptor missing for {record.id}")
                expected_binding_reports.add(str(report.get("path", report.get("name"))))
    if ids is None:
        actual_resolver_indexes = {path.name for path in ASSET_DIR.glob("*.pronresolve.json")}
        if actual_resolver_indexes != expected_resolver_indexes:
            raise ValueError("resolver sidecar inventory does not match available pronunciation capabilities")
        actual_binding_reports = {path.name for path in REPORT_DIR.glob("*.binding-report.json")}
        if actual_binding_reports != expected_binding_reports:
            raise ValueError("binding-report inventory does not match pronunciation capabilities")
        actual_assets = {path.name for path in ASSET_DIR.glob("*.g2lex")}
        actual_manifests = {path.name for path in MANIFEST_DIR.glob("*.manifest.json")}
        unexpected_assets = sorted(actual_assets - expected_assets)
        unexpected_manifests = sorted(actual_manifests - expected_manifests)
        if unexpected_assets or unexpected_manifests:
            unexpected = unexpected_assets + unexpected_manifests
            raise ValueError(
                f"prebuilt release contains unexpected outputs: {', '.join(unexpected)}"
            )


def validate_espeak_generator_consistency(records: Iterable[AssetConfig]) -> None:
    identities: set[tuple[object, object, object, object]] = set()
    for record in records:
        if record.source_provider != "g2lex-assets":
            continue
        manifest = read_json(MANIFEST_DIR / record.manifest_name)
        generator = (manifest.get("transform") or {}).get("inputs", {}).get("generator")
        if not isinstance(generator, dict):
            raise TypeError(f"missing eSpeak generator identity for {record.id}")
        identities.add(
            (
                generator.get("version"),
                generator.get("git_revision"),
                generator.get("library_sha256"),
                generator.get("data_sha256"),
            )
        )
    if len(identities) > 1:
        raise ValueError("eSpeak generator identity differs across release shards")


def validate_all(
    *,
    catalog: bool = False,
    ids: list[str] | None = None,
    verify_transform: bool = True,
    verify_source: bool = True,
) -> None:
    records = _records(ids)
    for record in records:
        validate_one(record, verify_transform=verify_transform, verify_source=verify_source)
    if catalog:
        validate_catalog(ids=ids)
