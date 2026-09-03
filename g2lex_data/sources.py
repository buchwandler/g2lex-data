from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lexhint import Lexicon, LexiconNotInstalled

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


def _resolve_lexhint(record: AssetConfig) -> ResolvedSource:
    inputs = record.transform_inputs or {}
    language = _required_input(record, "lexhint_language")
    variant = _required_input(record, "lexhint_variant")
    dataset_version = _required_input(record, "lexhint_dataset_version")
    locale = inputs.get("lexhint_locale")
    if locale is not None and (not isinstance(locale, str) or not locale.strip()):
        raise ValueError(f"{record.id} transform input lexhint_locale must be a non-empty string")

    try:
        lexicon = Lexicon(
            language,
            variant=variant,
            dataset_version=dataset_version,
            locale=locale.strip() if isinstance(locale, str) else None,
        )
    except LexiconNotInstalled as exc:
        raise FileNotFoundError(
            "LexHint dictionary artifact is not installed:\n"
            f"language={language}\nvariant={variant}\ndataset_version={dataset_version}\n\n"
            "Install it explicitly with:\n"
            f"lexhint dataset download {language} --variant {variant} --version {dataset_version}"
        ) from exc

    path = Path(lexicon.path)
    if not path.is_file():
        raise FileNotFoundError(f"LexHint dictionary artifact is not installed: {path}")
    actual_hash = _sha256_file(path)
    actual_size = path.stat().st_size
    if actual_size != record.source_size:
        raise ValueError(f"LexHint source size mismatch for {record.id}")
    if actual_hash != record.source_sha256:
        raise ValueError(f"LexHint source SHA-256 mismatch for {record.id}")

    metadata = dict(lexicon.metadata)
    expected_schema = _required_input(record, "lexhint_schema_version")
    actual_schema = str(metadata.get("schema_version", lexicon.schema_version))
    if actual_schema != expected_schema:
        raise ValueError(
            f"LexHint schema mismatch for {record.id}: expected {expected_schema}, got {actual_schema}"
        )
    if str(metadata.get("language")) != language.strip().lower():
        raise ValueError(f"LexHint language mismatch for {record.id}")
    if lexicon.variant != variant or lexicon.dataset_version != dataset_version:
        raise ValueError(f"LexHint dataset identity mismatch for {record.id}")

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
        "language": language,
        "variant": variant,
        "dataset_version": dataset_version,
        "schema_version": actual_schema,
        "sha256": actual_hash,
        "size": actual_size,
        "lexhint_version": actual_package_version,
        "artifact_builder_version": metadata.get("lexhint_version"),
        "locale": locale,
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


__all__ = ["ResolvedSource", "resolve_source"]
