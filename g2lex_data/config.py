from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "datasets.toml"
SUPPORTED_KINDS = {"pronunciation", "membership"}
SUPPORTED_ENCODINGS = {"ipa", "arpabet", "none", "kokoro-v1"}
SUPPORTED_FORMATS = {
    "kokoro-json",
    "json-map",
    "tsv",
    "ipa-tsv",
    "lxc-tsv",
    "jsonl",
    "words",
    "cmudict",
    "mfa",
    "pls",
    "gruut-sqlite",
    "lexhint-dictionary",
}
SUPPORTED_SOURCE_PROVIDERS = {"file", "lexhint"}


@dataclass(frozen=True, slots=True)
class AssetConfig:
    id: str
    language: str
    name: str
    display_name: str
    kind: str
    source: str
    source_format: str
    source_id: str
    source_sha256: str
    source_size: int
    phoneme_encoding: str
    provider: str
    revision: str
    license_expression: str
    license_url: str
    attribution: str
    source_url: str | None = None
    transform: str | None = None
    transform_inputs: dict[str, object] | None = None
    source_provider: str = "file"

    @property
    def source_path(self) -> Path:
        return ROOT / self.source

    @property
    def slug(self) -> str:
        return self.id.replace(":", "-").replace("/", "-")

    @property
    def asset_name(self) -> str:
        return f"g2lex-{self.slug}.g2lex"

    @property
    def manifest_name(self) -> str:
        return f"g2lex-{self.slug}.manifest.json"


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    schema_version: int
    contract_version: int
    repository: str
    catalog_version: int
    runtime_contract: str
    release_tag_prefix: str
    assets: tuple[AssetConfig, ...]

    def asset(self, identifier: str) -> AssetConfig:
        for record in self.assets:
            if record.id == identifier:
                return record
        raise KeyError(identifier)


def _text(values: dict[str, Any], key: str, label: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _integer(values: dict[str, Any], key: str, label: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}.{key} must be a non-negative integer")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _transform_inputs(value: object, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{label}.transform_inputs must be a TOML table")
    return dict(value)


def load_config(path: Path = CONFIG_PATH) -> RepositoryConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("datasets.toml schema_version must be 1")
    contract_version = raw.get("contract_version", 1)
    if contract_version != 1:
        raise ValueError("datasets.toml contract_version must be 1")
    items = raw.get("asset")
    if not isinstance(items, list) or not items:
        raise ValueError("datasets.toml requires at least one [[asset]] record")

    assets: list[AssetConfig] = []
    seen: set[str] = set()
    for index, values in enumerate(items):
        if not isinstance(values, dict):
            raise TypeError("asset records must be TOML tables")
        label = f"asset[{index}]"
        source_provider = values.get("source_provider", "file")
        if source_provider not in SUPPORTED_SOURCE_PROVIDERS:
            raise ValueError(f"unsupported {label}.source_provider: {source_provider}")
        identifier = _text(values, "id", label)
        if identifier in seen:
            raise ValueError(f"duplicate asset id: {identifier}")
        seen.add(identifier)
        kind = _text(values, "kind", label)
        source_format = _text(values, "source_format", label)
        encoding = _text(values, "phoneme_encoding", label)
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"unsupported {label}.kind: {kind}")
        if source_format not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported {label}.source_format: {source_format}")
        if encoding not in SUPPORTED_ENCODINGS:
            raise ValueError(f"unsupported {label}.phoneme_encoding: {encoding}")
        if kind == "pronunciation" and encoding == "none":
            raise ValueError(f"pronunciation asset {identifier} cannot use none encoding")
        if kind == "membership" and encoding != "none":
            raise ValueError(f"membership asset {identifier} must use none encoding")
        transform = values.get("transform")
        if transform is not None and (not isinstance(transform, str) or not transform.strip()):
            raise ValueError(f"{label}.transform must be a non-empty string or null")
        source_url = values.get("source_url")
        if source_url is not None and not isinstance(source_url, str):
            raise TypeError(f"{label}.source_url must be a string")
        assets.append(
            AssetConfig(
                id=identifier,
                language=_text(values, "language", label),
                name=_text(values, "name", label),
                display_name=_text(values, "display_name", label),
                kind=kind,
                source=_text(values, "source", label),
                source_format=source_format,
                source_id=_text(values, "source_id", label),
                source_sha256=_sha256(values.get("source_sha256"), f"{label}.source_sha256"),
                source_size=_integer(values, "source_size", label),
                phoneme_encoding=encoding,
                provider=_text(values, "provider", label),
                revision=_text(values, "revision", label),
                license_expression=_text(values, "license_expression", label),
                license_url=_text(values, "license_url", label),
                attribution=_text(values, "attribution", label),
                source_url=source_url,
                transform=transform.strip() if isinstance(transform, str) else None,
                transform_inputs=_transform_inputs(values.get("transform_inputs"), label),
                source_provider=source_provider,
            )
        )

    return RepositoryConfig(
        schema_version=1,
        contract_version=contract_version,
        repository=_text(raw, "repository", "root"),
        catalog_version=_integer(raw, "catalog_version", "root"),
        runtime_contract=_text(raw, "runtime_contract", "root"),
        release_tag_prefix=_text(raw, "release_tag_prefix", "root"),
        assets=tuple(assets),
    )
