from __future__ import annotations

import shutil

import pytest

from g2lex_data.espeak import EspeakBackend


def test_piper_raw_phoneme_block_preserves_tie_character() -> None:
    if shutil.which("espeak-ng") is None:
        pytest.skip("eSpeak-NG is unavailable")
    try:
        backend = EspeakBackend(expected_version="1.52.0.1")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    with backend:
        backend.set_voice("en-us")
        value = backend.phonemize_ipa3("church")
    raw_block = f"[[ {value} ]]"
    assert raw_block.startswith("[[ ")
    assert raw_block.endswith(" ]]")
    assert "\u200d" in raw_block
