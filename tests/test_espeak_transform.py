from __future__ import annotations

from types import SimpleNamespace

import pytest

from g2lex_data.inventory import WordInventory, logical_sha256_for_keys
from g2lex_data.transforms.espeak import generate_espeak_pair


class FakeBackend:
    identity = SimpleNamespace(
        version="1.52.0.1",
        git_revision="test-revision",
        library_path="/test/libespeak-ng.so",
        library_sha256="a" * 64,
        data_path="/test/espeak-data",
        data_sha256="b" * 64,
    )

    def __init__(self, values: dict[str, tuple[str, str]]) -> None:
        self.values = values
        self.voice = None

    def set_voice(self, voice: str) -> None:
        self.voice = voice

    def phonemize_ipa(self, text: str) -> str:
        return self.values[text][0]

    def phonemize_ipa3(self, text: str) -> str:
        return self.values[text][1]


def _inventory() -> WordInventory:
    keys = ("-'", "church", "word")
    return WordInventory(
        locale="en-us",
        source_ids=("en-us:lexhint",),
        source_entry_counts={"en-us:lexhint": len(keys)},
        keys=keys,
        duplicate_key_count=0,
        logical_sha256=logical_sha256_for_keys(keys),
    )


def test_pair_skips_keys_without_pronunciation() -> None:
    result = generate_espeak_pair(
        inventory=_inventory(),
        voice="en-us",
        backend=FakeBackend(
            {
                "-'": ("", ""),
                "church": ("tʃɜːtʃ", "tʃɜːtʃ"),
                "word": ("wɜːd", "wɜːd"),
            }
        ),
    )

    assert tuple(result.normal_entries) == ("church", "word")
    assert tuple(result.piper_entries) == ("church", "word")
    assert result.skipped_keys == ("-'",)
    report = result.shared_report["word_inventory"]
    assert report["union_entry_count"] == 3
    assert report["generated_entry_count"] == 2
    assert report["skipped_entry_count"] == 1
    assert report["skipped_keys"] == ["-'"]
    assert report["logical_sha256"] == report["generated_logical_sha256"]


def test_pair_rejects_mode_availability_mismatch() -> None:
    with pytest.raises(ValueError, match="availability differs between ipa and ipa3"):
        generate_espeak_pair(
            inventory=_inventory(),
            voice="en-us",
            backend=FakeBackend(
                {
                    "-'": ("", "ipa3-value"),
                    "church": ("tʃɜːtʃ", "tʃɜːtʃ"),
                    "word": ("wɜːd", "wɜːd"),
                }
            ),
        )
