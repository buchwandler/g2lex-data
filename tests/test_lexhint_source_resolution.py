from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest
from lexhint import LexiconNotInstalled

from g2lex_data.config import load_config
from g2lex_data.sources import resolve_source


def _record() -> object:
    return load_config().asset("en-us:lexhint")


def test_resolves_pinned_installed_lexhint_artifact() -> None:
    resolved = resolve_source(_record())
    assert resolved.metadata["provider"] == "lexhint"
    assert resolved.metadata["language"] == "en"
    assert resolved.metadata["dataset_version"] == "2026.08.28"
    assert resolved.metadata["schema_version"] == "10"
    assert resolved.metadata["size"] == 859484160


@pytest.mark.parametrize("language", ("ja", "ko", "pt", "ru", "th", "vi", "zh"))
def test_resolves_multilingual_base_language_artifacts(language: str) -> None:
    record = load_config().asset(f"{language}:lexhint")
    resolved = resolve_source(record)
    assert resolved.metadata["provider"] == "lexhint"
    assert resolved.metadata["language"] == language
    assert resolved.metadata["variant"] == "dictionary"
    assert resolved.metadata["dataset_version"] == "2026.09.03"
    assert resolved.metadata["schema_version"] == "10"
    assert resolved.metadata["lexhint_version"] == "0.4.4"
    assert resolved.metadata["locale"] is None


def test_source_hash_mismatch_fails_closed() -> None:
    record = replace(_record(), source_sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        resolve_source(record)


def test_schema_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    artifact = tmp_path / "lexhint.sqlite3"
    artifact.write_bytes(b"fixture")

    class FakeLexicon:
        path = artifact
        variant = "dictionary"
        dataset_version = "2026.08.28"
        schema_version = "9"
        metadata: ClassVar[dict[str, str]] = {
            "schema_version": "9",
            "language": "en",
            "lexhint_version": "0.4.4",
        }

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    monkeypatch.setattr("g2lex_data.sources.Lexicon", FakeLexicon)
    record = replace(_record(), source_sha256=hashlib.sha256(b"fixture").hexdigest(), source_size=7)
    with pytest.raises(ValueError, match="schema mismatch"):
        resolve_source(record)


def test_resolver_does_not_download(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access")

    monkeypatch.setattr("lexhint.download.request", fail)
    assert resolve_source(_record()).metadata["provider"] == "lexhint"


def test_missing_artifact_message_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise LexiconNotInstalled("not installed")

    monkeypatch.setattr("g2lex_data.sources.Lexicon", missing)
    with pytest.raises(
        FileNotFoundError,
        match="lexhint dataset download en --variant dictionary --version 2026.08.28",
    ):
        resolve_source(_record())
