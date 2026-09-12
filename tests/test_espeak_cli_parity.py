from __future__ import annotations

import shutil
import subprocess

import pytest

from g2lex_data.espeak import EspeakBackend


@pytest.mark.parametrize("word", ["church", "judge", "batman", "-'"])
def test_backend_matches_espeak_cli(word: str) -> None:
    if shutil.which("espeak-ng") is None:
        pytest.skip("eSpeak-NG is unavailable")
    try:
        backend = EspeakBackend(expected_version="1.52.0.1")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    with backend:
        backend.set_voice("en-us")
        normal = (
            subprocess.check_output(["espeak-ng", "-v", "en-us", "--ipa", "-q", "--", word])
            .decode("utf-8")
            .removesuffix("\n")
        )
        piper = (
            subprocess.check_output(["espeak-ng", "-v", "en-us", "--ipa=3", "-q", "--", word])
            .decode("utf-8")
            .removesuffix("\n")
        )
        assert backend.phonemize_ipa(word) == normal
        assert backend.phonemize_ipa3(word) == piper
