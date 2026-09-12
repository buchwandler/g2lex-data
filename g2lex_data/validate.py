from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

import g2lex

from .build import validate_source
from .common import ASSET_DIR, CATALOG_PATH, MANIFEST_DIR, read_json, sha256_file
from .config import AssetConfig, load_config
from .inventory import build_word_inventory, logical_sha256_for_keys
from .sources import resolve_source
from .transforms import apply


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
    if not isinstance(skipped_value, list) or not all(isinstance(key, str) for key in skipped_value):
        raise ValueError(f"invalid skipped keys for {record.id}")
    skipped_keys = tuple(skipped_value)
    if skipped_keys != tuple(sorted(skipped_keys)) or len(set(skipped_keys)) != len(skipped_keys):
        raise ValueError(f"skipped keys are not deterministic for {record.id}")
    if (
        provenance.get("union_entry_count") != len(inventory.keys)
        or provenance.get("union_logical_sha256") != inventory.logical_sha256
    ):
        raise ValueError(f"derived source union provenance mismatch for {record.id}")
    if (
        provenance.get("generated_entry_count") != len(keys)
        or provenance.get("logical_sha256") != provenance.get("generated_logical_sha256")
    ):
        raise ValueError(f"derived generated inventory count mismatch for {record.id}")
    generated_sha256 = logical_sha256_for_keys(keys)
    if provenance.get("generated_logical_sha256") != generated_sha256:
        raise ValueError(f"derived generated inventory hash mismatch for {record.id}")
    if set(keys).intersection(skipped_keys) or tuple(sorted(set(keys) | set(skipped_keys))) != inventory.keys:
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
    if record.source_provider == "g2lex-assets":
        _validate_derived_pair(record, asset_path, manifest)
    elif verify_transform:
        with tempfile.TemporaryDirectory(prefix=f".{record.slug}.validate.") as temp_name:
            result = apply(record, resolved_source.path, Path(temp_name))
            input_path = result.input_path if result else resolved_source.path
            input_format = result.input_format if result else record.source_format
            verification = g2lex.verify_file(input_path, asset_path, input_format=input_format)
            if not verification.get("lossless"):
                raise ValueError(f"asset no longer verifies losslessly for {record.id}")
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
        if source.get("sha256") != expected_source_sha256 or source.get("size") != expected_source_size:
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
    if actual_ids != expected_ids:
        raise ValueError("catalog IDs do not match configured assets")


def validate_prebuilt_set(*, ids: list[str] | None = None, data_version: str) -> None:
    records = _records(ids)
    expected_assets = {record.asset_name for record in records}
    expected_manifests = {record.manifest_name for record in records}
    for record in records:
        asset_path = ASSET_DIR / record.asset_name
        manifest_path = MANIFEST_DIR / record.manifest_name
        if not asset_path.is_file():
            raise FileNotFoundError(f"prebuilt release is incomplete: missing asset: {record.asset_name}")
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
    if ids is None:
        actual_assets = {path.name for path in ASSET_DIR.glob("*.g2lex")}
        actual_manifests = {path.name for path in MANIFEST_DIR.glob("*.manifest.json")}
        unexpected_assets = sorted(actual_assets - expected_assets)
        unexpected_manifests = sorted(actual_manifests - expected_manifests)
        if unexpected_assets or unexpected_manifests:
            unexpected = unexpected_assets + unexpected_manifests
            raise ValueError(f"prebuilt release contains unexpected outputs: {', '.join(unexpected)}")


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
