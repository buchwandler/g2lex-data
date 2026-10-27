from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

import g2lex

from .build import validate_source
from .capabilities import NO_RESOLVABLE_AMBIGUITIES, NO_SENSE_LINKED_MAPPING
from .common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR, read_json, sha256_file
from .config import AssetConfig, load_config
from .inventory import build_word_inventory, logical_sha256_for_keys
from .sources import resolve_source
from .transforms import TransformResult, apply


def _validate_resolver_index(
    record: AssetConfig,
    asset_path: Path,
    manifest: dict[str, object],
    *,
    generated: TransformResult | None = None,
) -> None:
    transform = manifest.get("transform")
    inputs = transform.get("inputs", {}) if isinstance(transform, dict) else {}
    inputs = inputs if isinstance(inputs, dict) else {}
    descriptor = manifest.get("resolver_index")
    capabilities = manifest.get("capabilities")

    if record.kind != "pronunciation":
        if descriptor is not None or capabilities is not None:
            raise ValueError(f"non-pronunciation asset has pronunciation capability metadata: {record.id}")
        with g2lex.open(asset_path) as packed:
            if packed.metadata.get("resolver_index") is not None:
                raise ValueError(f"non-pronunciation asset has resolver metadata: {record.id}")
        return

    if not isinstance(capabilities, dict):
        raise TypeError(f"pronunciation capability is missing for {record.id}")
    capability = capabilities.get("pronunciation_resolution")
    if not isinstance(capability, dict):
        raise TypeError(f"pronunciation-resolution capability is missing for {record.id}")
    status = capability.get("status")
    if status not in {"available", "unnecessary", "unavailable"}:
        raise ValueError(f"invalid pronunciation-resolution status for {record.id}")

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
            raise ValueError(f"non-available capability has a resolver descriptor for {record.id}")
        stale_index = ASSET_DIR / f"g2lex-{record.slug}.pronresolve.json"
        if stale_index.exists():
            raise ValueError(f"non-available capability has a stale resolver file for {record.id}")
        with g2lex.open(asset_path) as packed:
            if packed.metadata.get("resolver_index") is not None:
                raise ValueError(f"non-available capability has embedded resolver metadata for {record.id}")
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
        raise TypeError(f"available pronunciation capability lacks resolver descriptor for {record.id}")
    name = descriptor.get("path", descriptor.get("name"))
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError(f"invalid resolver index path for {record.id}")
    index_path = ASSET_DIR / name
    if not index_path.is_file():
        raise FileNotFoundError(f"missing resolver index for {record.id}: {index_path}")
    if sha256_file(index_path) != descriptor.get("sha256"):
        raise ValueError(f"resolver index SHA mismatch for {record.id}")
    if index_path.stat().st_size != descriptor.get("size"):
        raise ValueError(f"resolver index size mismatch for {record.id}")

    from pronresolve import load_index

    index = load_index(index_path)
    if not index.profiles or index.schema_version != 2:
        raise ValueError(f"available resolver index must be non-empty schema v2 for {record.id}")
    if (
        descriptor.get("schema_version") != index.schema_version
        or descriptor.get("language") != index.language
        or descriptor.get("locale") != index.locale
        or descriptor.get("dataset_version") != manifest.get("data_version")
    ):
        raise ValueError(f"resolver index identity mismatch for {record.id}")
    expected_capability_index = {
        key: descriptor.get(key)
        for key in ("name", "schema_version", "language", "locale", "dataset_version", "sha256", "size")
    }
    if capability["index"] != expected_capability_index:
        raise ValueError(f"capability resolver descriptor mismatch for {record.id}")
    if inputs.get("pronresolve_index_schema_version") != index.schema_version:
        raise ValueError(f"resolver index schema input mismatch for {record.id}")
    expected_language = inputs.get("lexhint_language")
    if expected_language is not None and str(expected_language).casefold() != index.language:
        raise ValueError(f"resolver index language input mismatch for {record.id}")
    expected_locale = inputs.get("lexhint_locale")
    if expected_locale != index.locale:
        raise ValueError(f"resolver index locale input mismatch for {record.id}")

    with g2lex.open(asset_path) as packed:
        embedded = packed.metadata.get("resolver_index")
        if embedded != descriptor:
            raise ValueError(f"G2Lex resolver index metadata mismatch for {record.id}")
        if packed.metadata.get("capabilities") != capabilities:
            raise ValueError(f"G2Lex capability metadata mismatch for {record.id}")
        for profile in index.profiles:
            if not isinstance(profile.ipa, str) or not profile.ipa:
                raise ValueError(f"resolver profile must have scalar IPA for {record.id}")
            selector = f"READING:{profile.reading_id}"
            if packed.lookup(profile.word, tag=selector) != profile.ipa:
                raise ValueError(f"resolver selector mismatch for {record.id}: {selector}")

    if generated is not None:
        generated_capability = generated.resolution_capability
        if (
            generated.resolver_index_path is None
            or generated_capability is None
            or generated_capability.status != "available"
            or generated_capability.index is None
        ):
            raise ValueError(f"generated resolver index is missing for {record.id}")
        for field in ("name", "schema_version", "language", "locale"):
            if generated_capability.index.get(field) != capability["index"].get(field):
                raise ValueError(f"generated resolver capability mismatch for {record.id}")
        generated_index = load_index(generated.resolver_index_path)
        if generated_index.to_dict() != index.to_dict():
            raise ValueError(f"resolver index does not match current transform for {record.id}")

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
    if record.source_provider == "g2lex-assets":
        _validate_derived_pair(record, asset_path, manifest)
        _validate_resolver_index(record, asset_path, manifest)
    elif verify_transform:
        with tempfile.TemporaryDirectory(prefix=f".{record.slug}.validate.") as temp_name:
            generated_transform_result = apply(record, resolved_source.path, Path(temp_name))
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
            verification = g2lex.verify_file(input_path, asset_path, input_format=input_format)
            if not verification.get("lossless"):
                raise ValueError(f"asset no longer verifies losslessly for {record.id}")
            _validate_resolver_index(
                record, asset_path, manifest, generated=generated_transform_result
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
    expected_ids = {record.id for record in records}
    records_by_id = {record.id: record for record in records}
    actual_ids: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TypeError("catalog artifacts must be objects")
        identifier = artifact.get("id")
        if not isinstance(identifier, str) or identifier in actual_ids:
            raise ValueError("catalog artifact ids must be unique strings")
        actual_ids.add(identifier)
        if identifier not in expected_ids:
            raise ValueError(f"unknown catalog artifact {identifier}")
        asset = artifact.get("asset")
        manifest = artifact.get("manifest")
        if not isinstance(asset, dict) or not isinstance(manifest, dict):
            raise TypeError(f"invalid catalog artifact references for {identifier}")
        if not isinstance(asset.get("sha256"), str) or len(asset["sha256"]) != 64:
            raise ValueError(f"invalid catalog asset hash for {identifier}")
        if not isinstance(manifest.get("sha256"), str) or len(manifest["sha256"]) != 64:
            raise ValueError(f"invalid catalog manifest hash for {identifier}")
        for key in ("url",):
            if not str(asset.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog asset URL for {identifier}")
            if not str(manifest.get(key, "")).startswith(("https://", "file://")):
                raise ValueError(f"unsupported catalog manifest URL for {identifier}")
        record = records_by_id[identifier]
        manifest_document = read_json(MANIFEST_DIR / record.manifest_name)
        manifest_caps = manifest_document.get("capabilities")
        catalog_caps = artifact.get("capabilities")
        manifest_index = manifest_document.get("resolver_index")
        catalog_index = artifact.get("resolver_index")
        _validate_resolver_index(record, ASSET_DIR / record.asset_name, manifest_document)
        if record.kind == "pronunciation":
            if catalog_caps != manifest_caps or not isinstance(manifest_caps, dict):
                raise ValueError(f"catalog pronunciation capability mismatch for {identifier}")
            capability = manifest_caps.get("pronunciation_resolution")
            if not isinstance(capability, dict):
                raise ValueError(f"manifest pronunciation capability missing for {identifier}")
            if capability.get("status") == "available":
                if not isinstance(manifest_index, dict) or not isinstance(catalog_index, dict):
                    raise ValueError(f"catalog resolver index missing for {identifier}")
                index_name = manifest_index.get("path", manifest_index.get("name"))
                expected_index = {
                    "name": index_name,
                    "url": str(asset["url"]).rsplit("/", 1)[0] + "/" + str(index_name),
                    "sha256": manifest_index.get("sha256"),
                    "size": manifest_index.get("size"),
                    "schema_version": manifest_index.get("schema_version"),
                    "language": manifest_index.get("language"),
                    "locale": manifest_index.get("locale"),
                    "dataset_version": manifest_index.get("dataset_version"),
                }
                if catalog_index != expected_index:
                    raise ValueError(f"catalog resolver index mismatch for {identifier}")
            elif manifest_index is not None or catalog_index is not None:
                raise ValueError(f"non-available catalog capability has resolver index for {identifier}")
        elif catalog_caps is not None or manifest_caps is not None or catalog_index is not None:
            raise ValueError(f"non-pronunciation catalog artifact has capabilities for {identifier}")
    if actual_ids != expected_ids:
        raise ValueError("catalog IDs do not match configured assets")


def validate_prebuilt_set(*, ids: list[str] | None = None, data_version: str) -> None:
    records = _records(ids)
    expected_assets = {record.asset_name for record in records}
    expected_manifests = {record.manifest_name for record in records}
    expected_resolver_indexes: set[str] = set()
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
                descriptor = manifest["resolver_index"]
                expected_resolver_indexes.add(str(descriptor.get("path", descriptor.get("name"))))
    if ids is None:
        actual_resolver_indexes = {path.name for path in ASSET_DIR.glob("*.pronresolve.json")}
        if actual_resolver_indexes != expected_resolver_indexes:
            raise ValueError("resolver sidecar inventory does not match available pronunciation capabilities")
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
