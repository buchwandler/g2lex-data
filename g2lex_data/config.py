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
}


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


def load_config(path: Path = CONFIG_PATH) -> RepositoryConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("datasets.toml schema_version must be 1")
    items = raw.get("asset")
    if not isinstance(items, list) or not items:
        raise ValueError("datasets.toml requires at least one [[asset]] record")

    assets: list[AssetConfig] = []
    seen: set[str] = set()
    for index, values in enumerate(items):
        if not isinstance(values, dict):
            raise TypeError("asset records must be TOML tables")
        label = f"asset[{index}]"
        identifier = _text(values, "id", label)
        if identifier in seen:
            raise ValueError(f"duplicate asset id: {identifier}")
        seen.add(identifier)
        kind = _text(values, "kind", label)
        source_format = _text(values, "source_format", label)
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"unsupported {label}.kind: {kind}")
        if source_format not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported {label}.source_format: {source_format}")
        sha = _text(values, "source_sha256", label)
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ValueError(f"{label}.source_sha256 must be lowercase SHA-256")
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
                source_sha256=sha,
                source_size=_integer(values, "source_size", label),
                phoneme_encoding=_text(values, "phoneme_encoding", label),
                provider=_text(values, "provider", label),
                revision=_text(values, "revision", label),
                license_expression=_text(values, "license_expression", label),
                license_url=_text(values, "license_url", label),
                attribution=_text(values, "attribution", label),
                source_url=source_url,
            )
        )

    return RepositoryConfig(
        schema_version=1,
        repository=_text(raw, "repository", "root"),
        catalog_version=_integer(raw, "catalog_version", "root"),
        runtime_contract=_text(raw, "runtime_contract", "root"),
        release_tag_prefix=_text(raw, "release_tag_prefix", "root"),
        assets=tuple(assets),
    )
