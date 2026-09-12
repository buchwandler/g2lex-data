from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lexhint import Lexicon
from lexhint.datasets import DatasetNotFound, resolve_installed_dataset

from .common import ASSET_DIR
from .config import AssetConfig, load_config


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    path: Path
    metadata: Mapping[str, object]


def _lexhint_version() -> str:
    try:
        return version("lexhint")
    except PackageNotFoundError:
        return "0+unknown"


def _required_input(record: AssetConfig, key: str) -> str:
    value = (record.transform_inputs or {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{record.id} requires transform input {key}")
    return value.strip()


def _sha256_file(path: Path) -> str:
    from hashlib import sha256

    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lexhint_download_command(record: AssetConfig, *, version: str | None = None) -> str:
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    source_variant = _required_input(record, "lexhint_source_variant")
    command = (
        f"lexhint dataset download {language} --variant {variant} --source-variant {source_variant}"
    )
    if version is not None:
        command += f" --version {version}"
    return command


def _resolve_lexhint_dataset(
    *,
    record_id: str,
    language: str,
    variant: str,
    source_variant: str,
    schema_version: str,
    dataset_version: str | None,
    locale: str | None,
    include_neutral: bool,
    expected_package_version: str | None,
    expected_sqlite_sha256: str | None = None,
    install_command: str | None = None,
) -> ResolvedSource:
    if source_variant not in {"english", "native"}:
        raise ValueError(f"{record_id} has unsupported LexHint source variant: {source_variant}")
    try:
        installed = resolve_installed_dataset(
            language,
            variant=variant,
            source_variant=source_variant,
            version=dataset_version,
        )
    except DatasetNotFound as exc:
        command = install_command or (
            f"lexhint dataset download {language} --variant {variant} "
            f"--source-variant {source_variant}"
        )
        if dataset_version is not None:
            command += f" --version {dataset_version}"
            message = (
                f"Pinned LexHint transform dependency is not installed for {record_id}.\n"
                f"Install it with:\n{command}"
            )
        else:
            message = (
                "LexHint dictionary artifact is not installed:\n"
                f"language={language}\nsource_variant={source_variant}\nvariant={variant}\n\n"
                "Install the newest compatible source with:\n"
                f"{command}"
            )
        raise FileNotFoundError(message) from exc

    path = Path(installed.path)
    if not path.is_file():
        raise FileNotFoundError(f"LexHint dictionary artifact is not installed: {path}")
    normalized_language = language.strip().lower()
    if installed.language != normalized_language:
        raise ValueError(f"LexHint language mismatch for {record_id}")
    if installed.source_variant != source_variant or installed.variant != variant:
        raise ValueError(f"LexHint dataset identity mismatch for {record_id}")
    if str(installed.schema_version) != schema_version:
        raise ValueError(
            f"LexHint schema mismatch for {record_id}: "
            f"expected {schema_version}, got {installed.schema_version}"
        )
    if dataset_version is not None and str(installed.dataset_version) != dataset_version:
        raise ValueError(
            f"LexHint dataset version mismatch for {record_id}: "
            f"expected {dataset_version}, got {installed.dataset_version}"
        )
    if expected_package_version is not None and not isinstance(expected_package_version, str):
        raise ValueError(f"{record_id} transform input lexhint_version must be a string")
    actual_package_version = _lexhint_version()
    if expected_package_version is not None and expected_package_version != actual_package_version:
        raise ValueError(
            f"LexHint package version mismatch for {record_id}: "
            f"expected {expected_package_version}, got {actual_package_version}"
        )
    actual_hash = _sha256_file(path)
    actual_size = path.stat().st_size
    if expected_sqlite_sha256 is not None and expected_sqlite_sha256 != actual_hash:
        raise ValueError(
            f"LexHint artifact SHA-256 differs from pinned value for {record_id}: "
            f"expected {expected_sqlite_sha256}, got {actual_hash}"
        )

    lexicon = Lexicon.from_path(path, language=language, locale=locale)
    metadata = dict(lexicon.metadata)
    resolved_metadata: dict[str, object] = {
        "provider": "lexhint",
        "path": str(path),
        "language": installed.language,
        "source_variant": installed.source_variant,
        "variant": installed.variant,
        "dataset_version": installed.dataset_version,
        "schema_version": installed.schema_version,
        "release_tag": installed.release_tag,
        "release_published_at": installed.release_published_at,
        "asset": installed.asset,
        "release_asset_sha256": installed.sha256,
        "wiktionary_edition": installed.wiktionary_edition,
        "metadata_language": installed.metadata_language,
        "sqlite_sha256": actual_hash,
        "sqlite_size": actual_size,
        "sha256": actual_hash,
        "size": actual_size,
        "lexhint_version": actual_package_version,
        "artifact_builder_version": metadata.get("lexhint_version"),
        "locale": locale,
        "include_neutral": include_neutral,
    }
    return ResolvedSource(path, resolved_metadata)


def _resolve_lexhint(record: AssetConfig) -> ResolvedSource:
    inputs = record.transform_inputs or {}
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    source_variant = _required_input(record, "lexhint_source_variant")
    expected_schema = _required_input(record, "lexhint_schema_version")
    locale = inputs.get("lexhint_locale")
    if locale is not None and (not isinstance(locale, str) or not locale.strip()):
        raise ValueError(f"{record.id} transform input lexhint_locale must be a non-empty string")
    normalized_locale = locale.strip() if isinstance(locale, str) else None
    expected_package_version = inputs.get("lexhint_version")
    if expected_package_version is not None and not isinstance(expected_package_version, str):
        raise ValueError(f"{record.id} transform input lexhint_version must be a string")
    return _resolve_lexhint_dataset(
        record_id=record.id,
        language=language,
        variant=variant,
        source_variant=source_variant,
        schema_version=expected_schema,
        dataset_version=None,
        locale=normalized_locale,
        include_neutral=bool(inputs.get("include_neutral", False)),
        expected_package_version=expected_package_version,
        install_command=lexhint_download_command(record),
    )


def resolve_lexhint_transform_input(record: AssetConfig) -> ResolvedSource:
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    source_variant = _required_input(record, "lexhint_source_variant")
    schema_version = _required_input(record, "lexhint_schema_version")
    dataset_version = _required_input(record, "lexhint_dataset_version")
    expected_package_version = _required_input(record, "lexhint_version")
    expected_sqlite_sha256 = _required_input(record, "lexhint_artifact_sha256")
    return _resolve_lexhint_dataset(
        record_id=record.id,
        language=language,
        variant=variant,
        source_variant=source_variant,
        schema_version=schema_version,
        dataset_version=dataset_version,
        locale=None,
        include_neutral=False,
        expected_package_version=expected_package_version,
        expected_sqlite_sha256=expected_sqlite_sha256,
        install_command=lexhint_download_command(record, version=dataset_version),
    )


def _resolve_g2lex_assets(record: AssetConfig) -> ResolvedSource:
    if not record.source_ids:
        raise ValueError(f"{record.id} requires source_ids")
    config = load_config()
    source_paths: dict[str, Path] = {}
    for source_id in record.source_ids:
        parent = config.asset(source_id)
        if parent.source_provider not in {"file", "lexhint"}:
            raise ValueError(f"{record.id} has unsupported parent provider: {source_id}")
        path = ASSET_DIR / parent.asset_name
        if not path.is_file():
            raise FileNotFoundError(
                f"parent G2Lex asset is not built for {record.id}: {path}"
            )
        source_paths[source_id] = path
    first_path = source_paths[record.source_ids[0]]
    return ResolvedSource(
        first_path,
        {
            "provider": "g2lex-assets",
            "source_ids": list(record.source_ids),
            "source_paths": {source_id: str(path) for source_id, path in source_paths.items()},
        },
    )


def resolve_source(record: AssetConfig) -> ResolvedSource:
    if record.source_provider == "file":
        return ResolvedSource(
            record.source_path, {"provider": "file", "path": str(record.source_path)}
        )
    if record.source_provider == "lexhint":
        return _resolve_lexhint(record)
    if record.source_provider == "g2lex-assets":
        return _resolve_g2lex_assets(record)
    raise ValueError(f"unsupported source provider: {record.source_provider}")


__all__ = [
    "ResolvedSource",
    "lexhint_download_command",
    "resolve_lexhint_transform_input",
    "resolve_source",
]
