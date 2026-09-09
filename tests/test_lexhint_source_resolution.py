from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
from lexhint.datasets import DatasetNotFound

from g2lex_data import sources
from g2lex_data.config import load_config
from g2lex_data.sources import resolve_source


@dataclass(frozen=True)
class FakeInstalled:
    language: str
    source_variant: str
    variant: str
    schema_version: str
    dataset_version: str
    path: Path
    release_tag: str = "data-fixture"
    release_published_at: str = "2026-09-10T00:00:00Z"
    asset: str = "fixture.sqlite3.gz"
    sha256: str = "release-sha256"
    wiktionary_edition: str = "enwiktionary"
    metadata_language: str = "en"


def _record(identifier: str = "en-us:lexhint") -> object:
    return load_config().asset(identifier)


def _install_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str = "2026.09.10") -> dict[str, object]:
    artifact = tmp_path / f"{version}.sqlite3"
    artifact.write_bytes(b"fixture")
    calls: dict[str, object] = {}
    installed = FakeInstalled(
        language="en",
        source_variant="native",
        variant="dictionary",
        schema_version="10",
        dataset_version=version,
        path=artifact,
    )

    def resolve(language: str, **kwargs: object) -> FakeInstalled:
        calls["language"] = language
        calls.update(kwargs)
        return installed

    class FakeLexicon:
        metadata: ClassVar[dict[str, str]] = {"schema_version": "10", "lexhint_version": "0.4.7"}

        @classmethod
        def from_path(cls, path: Path, **kwargs: object) -> FakeLexicon:
            calls["path"] = path
            calls["lexicon_kwargs"] = kwargs
            return cls()

    monkeypatch.setattr(sources, "resolve_installed_dataset", resolve)
    monkeypatch.setattr(sources, "Lexicon", FakeLexicon)
    return calls


def test_resolves_latest_compatible_installed_lexhint_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_fake(monkeypatch, tmp_path)
    resolved = resolve_source(_record())

    assert calls == {
        "language": "en",
        "variant": "dictionary",
        "source_variant": "native",
        "version": None,
        "path": tmp_path / "2026.09.10.sqlite3",
        "lexicon_kwargs": {"language": "en", "locale": "en_US"},
    }
    assert resolved.metadata["dataset_version"] == "2026.09.10"
    assert resolved.metadata["source_variant"] == "native"
    assert resolved.metadata["schema_version"] == "10"
    assert resolved.metadata["sqlite_size"] == 7
    assert resolved.metadata["sqlite_sha256"]


def test_explicit_source_variants_never_cross_select(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def resolve(language: str, **kwargs: object) -> FakeInstalled:
        source_variant = str(kwargs["source_variant"])
        calls.append(source_variant)
        artifact = tmp_path / f"{source_variant}.sqlite3"
        artifact.write_bytes(source_variant.encode())
        return FakeInstalled(
            language=language,
            source_variant=source_variant,
            variant="dictionary",
            schema_version="10",
            dataset_version="2026.09.10",
            path=artifact,
            wiktionary_edition="enwiktionary" if source_variant == "english" else "ptwiktionary",
            metadata_language="en" if source_variant == "english" else "pt",
        )

    class FakeLexicon:
        metadata: ClassVar[dict[str, str]] = {"schema_version": "10"}

        @classmethod
        def from_path(cls, path: Path, **kwargs: object) -> FakeLexicon:
            return cls()

    monkeypatch.setattr(sources, "resolve_installed_dataset", resolve)
    monkeypatch.setattr(sources, "Lexicon", FakeLexicon)
    english = resolve_source(_record("pt:lexhint"))
    native = resolve_source(_record("pt:lexhint-native"))

    assert calls == ["english", "native"]
    assert english.metadata["source_variant"] == "english"
    assert native.metadata["source_variant"] == "native"
    assert english.metadata["wiktionary_edition"] != native.metadata["wiktionary_edition"]


def test_schema_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _install_fake(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sources,
        "resolve_installed_dataset",
        lambda *args, **kwargs: FakeInstalled(
            language="en",
            source_variant="native",
            variant="dictionary",
            schema_version="9",
            dataset_version="2026.09.10",
            path=tmp_path / "2026.09.10.sqlite3",
        ),
    )
    with pytest.raises(ValueError, match="schema mismatch"):
        resolve_source(_record())
    assert "path" not in calls


def test_missing_artifact_message_is_versionless_and_source_qualified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sources,
        "resolve_installed_dataset",
        lambda *args, **kwargs: (_ for _ in ()).throw(DatasetNotFound("missing")),
    )
    with pytest.raises(FileNotFoundError) as error:
        resolve_source(_record())
    message = str(error.value)
    assert "lexhint dataset download en --variant dictionary --source-variant native" in message
    assert "--version" not in message


def test_lexhint_config_does_not_require_static_integrity_pins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake(monkeypatch, tmp_path)
    record = _record()
    assert record.source_sha256 is None
    assert record.source_size is None
    resolved = resolve_source(record)
    assert resolved.metadata["sqlite_size"] == 7
