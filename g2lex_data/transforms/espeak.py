from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..espeak import EspeakBackend
from ..inventory import WordInventory

NORMAL_TRANSFORM_ID = "g2lex-espeak-ipa-v1"
PIPER_TRANSFORM_ID = "g2lex-espeak-piper-ipa3-v1"


@dataclass(frozen=True, slots=True)
class EspeakPairResult:
    normal_entries: dict[str, str]
    piper_entries: dict[str, str]
    shared_report: dict[str, object]
    normal_report: dict[str, object]
    piper_report: dict[str, object]


def validate_espeak_value(value: str, *, mode: Literal["ipa", "ipa3"]) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"eSpeak {mode} output must be non-empty")
    if "\x00" in value:
        raise ValueError(f"eSpeak {mode} output contains NUL")
    if "\r" in value or "\n" in value:
        raise ValueError(f"eSpeak {mode} output contains an embedded line break")
    value.encode("utf-8")


def _inventory_report(inventory: WordInventory) -> dict[str, object]:
    return {
        "locale": inventory.locale,
        "source_ids": list(inventory.source_ids),
        "source_entry_counts": dict(inventory.source_entry_counts),
        "union_entry_count": len(inventory.keys),
        "duplicate_key_count": inventory.duplicate_key_count,
        "logical_sha256": inventory.logical_sha256,
    }


def _identity_report(backend: EspeakBackend) -> dict[str, object]:
    identity = backend.identity
    return {
        "name": "espeak-ng",
        "version": identity.version,
        "git_revision": identity.git_revision,
        "library_path": str(identity.library_path),
        "library_sha256": identity.library_sha256,
        "data_path": str(identity.data_path),
        "data_sha256": identity.data_sha256,
    }


def generate_espeak_pair(
    *,
    inventory: WordInventory,
    voice: str,
    backend: EspeakBackend,
) -> EspeakPairResult:
    backend.set_voice(voice)
    normal: dict[str, str] = {}
    piper: dict[str, str] = {}
    for word in inventory.keys:
        normal_value = backend.phonemize_ipa(word)
        piper_value = backend.phonemize_ipa3(word)
        validate_espeak_value(normal_value, mode="ipa")
        validate_espeak_value(piper_value, mode="ipa3")
        normal[word] = normal_value
        piper[word] = piper_value
    if tuple(normal) != inventory.keys or tuple(piper) != inventory.keys:
        raise AssertionError("generated eSpeak key order differs from inventory")
    identity = _identity_report(backend)
    inventory_report = _inventory_report(inventory)
    return EspeakPairResult(
        normal_entries=normal,
        piper_entries=piper,
        shared_report={"word_inventory": inventory_report, "generator": identity, "voice": voice},
        normal_report={
            "transform_id": NORMAL_TRANSFORM_ID,
            "output_mode": "ipa",
            "encoding": "ipa",
            "generator": identity,
        },
        piper_report={
            "transform_id": PIPER_TRANSFORM_ID,
            "output_mode": "ipa3",
            "encoding": "espeak-ipa3",
            "target": "piper-raw-phonemes",
            "generator": identity,
        },
    )


__all__ = [
    "NORMAL_TRANSFORM_ID",
    "PIPER_TRANSFORM_ID",
    "EspeakPairResult",
    "generate_espeak_pair",
    "validate_espeak_value",
]
