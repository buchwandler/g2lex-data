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
SUPPORTED_ENCODINGS = {"ipa", "arpabet", "none", "kokoro-v1", "espeak-ipa3"}
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
    "g2lex",
}
SUPPORTED_SOURCE_PROVIDERS = {"file", "lexhint", "g2lex-assets"}


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
    source_sha256: str | None
    source_size: int | None
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
    source_ids: tuple[str, ...] = ()

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

    espeak_generation: dict[str, object] | None = None

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


def _optional_integer(values: dict[str, Any], key: str, label: str) -> int | None:
    return None if values.get(key) is None else _integer(values, key, label)


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _optional_sha256(value: object, label: str) -> str | None:
    return None if value is None else _sha256(value, label)


def _transform_inputs(value: object, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{label}.transform_inputs must be a TOML table")
    return dict(value)


_DEFAULT_ESPEAK_VOICES = {
    "ar": "ar",
    "az": "az",
    "bg": "bg",
    "ca": "ca",
    "cs": "cs",
    "de-de": "de",
    "el": "el",
    "en-gb": "en",
    "en-us": "en-us",
    "es": "es",
    "fr": "fr",
    "ga": "ga",
    "he": "he",
    "hi": "hi",
    "hu": "hu",
    "hy": "hy",
    "id": "id",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "ku": "ku",
    "la": "la",
    "lt": "lt",
    "lv": "lv",
    "mr": "mr",
    "ms": "ms",
    "nl": "nl",
    "pl": "pl",
    "pt": "pt",
    "pt-br": "pt-br",
    "pt-pt": "pt",
    "ro": "ro",
    "ru": "ru",
    "sv": "sv",
    "ta": "ta",
    "te": "te",
    "th": "th",
    "tr": "tr",
    "uk": "uk",
    "ur": "ur",
    "vi": "vi",
    "zh": "cmn",
}


def _source_ids(value: object, label: str, provider: str) -> tuple[str, ...]:
    if value is None:
        if provider == "g2lex-assets":
            raise ValueError(f"{label}.source_ids is required for g2lex-assets")
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise TypeError(f"{label}.source_ids must be a non-empty array of strings")
    result = tuple(item.strip() for item in value)
    if not result:
        raise ValueError(f"{label}.source_ids must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{label}.source_ids must not contain duplicates")
    if provider != "g2lex-assets":
        raise ValueError(f"{label}.source_ids is only supported for g2lex-assets")
    return result


def _generation_config(raw: dict[str, Any]) -> dict[str, object] | None:
    value = raw.get("espeak_generation")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("espeak_generation must be a TOML table")
    config = dict(value)
    if not isinstance(config.get("enabled", False), bool):
        raise TypeError("espeak_generation.enabled must be a boolean")
    for key in ("voice_overrides", "unsupported"):
        entries = config.get(key, {})
        if not isinstance(entries, dict) or not all(
            isinstance(name, str) and isinstance(reason, str) for name, reason in entries.items()
        ):
            raise TypeError(f"espeak_generation.{key} must be a string table")
        config[key] = {name.lower(): reason for name, reason in entries.items()}
    return config


def _derived_espeak_assets(
    assets: list[AssetConfig],
    generation: dict[str, object] | None,
) -> list[AssetConfig]:
    if not generation or not generation.get("enabled", False):
        return assets
    groups: dict[str, list[AssetConfig]] = {}
    for record in assets:
        if record.name in {"lexhint", "lexhint-native"}:
            locale = record.id.split(":", 1)[0]
            groups.setdefault(locale, []).append(record)
    overrides = generation.get("voice_overrides", {})
    unsupported = generation.get("unsupported", {})
    assert isinstance(overrides, dict) and isinstance(unsupported, dict)
    result = list(assets)
    for locale, parents in sorted(groups.items()):
        if locale in unsupported:
            continue
        source_ids = tuple(sorted(parent.id for parent in parents))
        voice = overrides.get(locale, _DEFAULT_ESPEAK_VOICES.get(locale))
        if not isinstance(voice, str) or not voice.strip():
            continue
        language = parents[0].language
        common_inputs: dict[str, object] = {
            "source_ids": list(source_ids),
            "voice": voice.strip(),
            "piper_version": generation.get("piper_version"),
            "espeak_git_revision": generation.get("espeak_git_revision"),
            "expected_espeak_version": generation.get("expected_espeak_version"),
        }
        for name, mode, encoding, transform in (
            ("espeak", "ipa", "ipa", "g2lex-espeak-ipa-v1"),
            ("espeak-piper", "ipa3", "espeak-ipa3", "g2lex-espeak-piper-ipa3-v1"),
        ):
            identifier = f"{locale}:{name}"
            inputs = {**common_inputs, "output_mode": mode}
            result.append(
                AssetConfig(
                    id=identifier,
                    language=language,
                    name=name,
                    display_name=(
                        f"{language} eSpeak IPA"
                        if name == "espeak"
                        else f"{language} eSpeak IPA for Piper raw phonemes"
                    ),
                    kind="pronunciation",
                    source="",
                    source_format="g2lex",
                    source_id=identifier,
                    source_sha256=None,
                    source_size=None,
                    phoneme_encoding=encoding,
                    provider="eSpeak-NG",
                    revision=str(generation.get("espeak_git_revision", "unknown")),
                    license_expression="CC-BY-SA-4.0",
                    license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                    attribution="LexHint word inventory; pronunciation generated with eSpeak-NG",
                    transform=transform,
                    transform_inputs=inputs,
                    source_provider="g2lex-assets",
                    source_ids=source_ids,
                )
            )
    return result


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
    generation = _generation_config(raw)
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
        source = (
            values.get("source", "")
            if source_provider == "g2lex-assets"
            else _text(values, "source", label)
        )
        assets.append(
            AssetConfig(
                id=identifier,
                language=_text(values, "language", label),
                name=_text(values, "name", label),
                display_name=_text(values, "display_name", label),
                kind=kind,
                source=source,
                source_format=source_format,
                source_id=_text(values, "source_id", label),
                source_sha256=(
                    _sha256(values.get("source_sha256"), f"{label}.source_sha256")
                    if source_provider == "file"
                    else _optional_sha256(values.get("source_sha256"), f"{label}.source_sha256")
                ),
                source_size=(
                    _integer(values, "source_size", label)
                    if source_provider == "file"
                    else _optional_integer(values, "source_size", label)
                ),
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
                source_ids=_source_ids(values.get("source_ids"), label, source_provider),
            )
        )
    assets = _derived_espeak_assets(assets, generation)
    records = {record.id: record for record in assets}
    for record in assets:
        if record.source_provider != "g2lex-assets":
            continue
        if not record.source_ids:
            raise ValueError(f"{record.id} requires source_ids")
        locale = record.id.split(":", 1)[0]
        for source_id in record.source_ids:
            if source_id == record.id:
                raise ValueError(f"{record.id} cannot reference itself")
            source = records.get(source_id)
            if source is None:
                raise ValueError(f"{record.id} references unknown source {source_id}")
            if source.name not in {"lexhint", "lexhint-native"}:
                raise ValueError(f"{record.id} source {source_id} is not a LexHint asset")
            if source.id.split(":", 1)[0] != locale:
                raise ValueError(f"{record.id} sources must share locale prefix")
    return RepositoryConfig(
        schema_version=1,
        contract_version=contract_version,
        repository=_text(raw, "repository", "root"),
        catalog_version=_integer(raw, "catalog_version", "root"),
        runtime_contract=_text(raw, "runtime_contract", "root"),
        release_tag_prefix=_text(raw, "release_tag_prefix", "root"),
        assets=tuple(assets),
        espeak_generation=generation,
    )
