from __future__ import annotations

import shutil

import pytest

from g2lex_data.espeak import EspeakBackend

pytestmark = pytest.mark.skipif(
    shutil.which("espeak-ng") is None, reason="eSpeak-NG is unavailable"
)


def test_backend_identity_voices_and_both_modes() -> None:
    try:
        backend = EspeakBackend(expected_version="1.52.0.1", git_revision="724808c")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    with backend:
        backend.set_voice("en-us")
        normal = backend.phonemize_ipa("church")
        piper = backend.phonemize_ipa3("church")
        assert normal
        assert piper
        assert "\u200d" in piper
        assert backend.identity.git_revision == "724808c"
        assert len(backend.identity.library_sha256) == 64
        assert len(backend.identity.data_sha256) == 64
        assert backend.voices()


def test_backend_requires_voice_and_rejects_empty_output() -> None:
    try:
        backend = EspeakBackend(expected_version="1.52.0.1")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    with backend:
        with pytest.raises(RuntimeError, match="set_voice"):
            backend.phonemize_ipa("word")
        backend.set_voice("en-us")
        with pytest.raises(ValueError, match="non-empty"):
            backend.phonemize_ipa("")
