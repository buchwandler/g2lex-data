from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lexhint import Lexicon
from lexhint.datasets import DatasetNotFound, resolve_installed_dataset

from .config import AssetConfig


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


def lexhint_download_command(record: AssetConfig) -> str:
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    source_variant = _required_input(record, "lexhint_source_variant")
    return (
        f"lexhint dataset download {language} --variant {variant} --source-variant {source_variant}"
    )


def _resolve_lexhint(record: AssetConfig) -> ResolvedSource:
    inputs = record.transform_inputs or {}
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    source_variant = _required_input(record, "lexhint_source_variant")
    if source_variant not in {"english", "native"}:
        raise ValueError(f"{record.id} has unsupported LexHint source variant: {source_variant}")
    expected_schema = _required_input(record, "lexhint_schema_version")
    locale = inputs.get("lexhint_locale")
    if locale is not None and (not isinstance(locale, str) or not locale.strip()):
        raise ValueError(f"{record.id} transform input lexhint_locale must be a non-empty string")
    normalized_locale = locale.strip() if isinstance(locale, str) else None

    try:
        installed = resolve_installed_dataset(
            language, variant=variant, source_variant=source_variant, version=None
        )
    except DatasetNotFound as exc:
        raise FileNotFoundError(
            "LexHint dictionary artifact is not installed:\n"
            f"language={language}\nsource_variant={source_variant}\nvariant={variant}\n\n"
            "Install the newest compatible source with:\n"
            f"{lexhint_download_command(record)}"
        ) from exc

    path = Path(installed.path)
    if not path.is_file():
        raise FileNotFoundError(f"LexHint dictionary artifact is not installed: {path}")
    actual_hash = _sha256_file(path)
    actual_size = path.stat().st_size
    if installed.language != language.strip().lower():
        raise ValueError(f"LexHint language mismatch for {record.id}")
    if installed.source_variant != source_variant or installed.variant != variant:
        raise ValueError(f"LexHint dataset identity mismatch for {record.id}")
    if str(installed.schema_version) != expected_schema:
        raise ValueError(
            f"LexHint schema mismatch for {record.id}: "
            f"expected {expected_schema}, got {installed.schema_version}"
        )

    lexicon = Lexicon.from_path(path, language=language, locale=normalized_locale)
    metadata = dict(lexicon.metadata)
    expected_package_version = inputs.get("lexhint_version")
    actual_package_version = _lexhint_version()
    if expected_package_version is not None and expected_package_version != actual_package_version:
        raise ValueError(
            f"LexHint package version mismatch for {record.id}: "
            f"expected {expected_package_version}, got {actual_package_version}"
        )

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
        "locale": normalized_locale,
        "include_neutral": inputs.get("include_neutral", False),
    }
    return ResolvedSource(path, resolved_metadata)


def resolve_source(record: AssetConfig) -> ResolvedSource:
    if record.source_provider == "file":
        return ResolvedSource(
            record.source_path, {"provider": "file", "path": str(record.source_path)}
        )
    if record.source_provider == "lexhint":
        return _resolve_lexhint(record)
    raise ValueError(f"unsupported source provider: {record.source_provider}")


__all__ = ["ResolvedSource", "lexhint_download_command", "resolve_source"]
