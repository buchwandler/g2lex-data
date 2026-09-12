from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..espeak import EspeakBackend
from ..inventory import WordInventory, logical_sha256_for_keys

NORMAL_TRANSFORM_ID = "g2lex-espeak-ipa-v1"
PIPER_TRANSFORM_ID = "g2lex-espeak-piper-ipa3-v1"


@dataclass(frozen=True, slots=True)
class EspeakPairResult:
    normal_entries: dict[str, str]
    piper_entries: dict[str, str]
    skipped_keys: tuple[str, ...]
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



def _inventory_report(
    inventory: WordInventory,
    generated_keys: tuple[str, ...],
    skipped_keys: tuple[str, ...],
) -> dict[str, object]:
    generated_sha256 = logical_sha256_for_keys(generated_keys)
    return {
        "locale": inventory.locale,
        "source_ids": list(inventory.source_ids),
        "source_entry_counts": dict(inventory.source_entry_counts),
        "union_entry_count": len(inventory.keys),
        "union_logical_sha256": inventory.logical_sha256,
        "duplicate_key_count": inventory.duplicate_key_count,
        "generated_entry_count": len(generated_keys),
        "generated_logical_sha256": generated_sha256,
        "logical_sha256": generated_sha256,
        "skipped_entry_count": len(skipped_keys),
        "skipped_keys": list(skipped_keys),
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
    skipped_keys: list[str] = []
    for word in inventory.keys:
        normal_value = backend.phonemize_ipa(word)
        piper_value = backend.phonemize_ipa3(word)
        if not normal_value and not piper_value:
            skipped_keys.append(word)
            continue
        if not normal_value or not piper_value:
            raise ValueError(
                f"eSpeak output availability differs between ipa and ipa3 for {word!r}"
            )
        validate_espeak_value(normal_value, mode="ipa")
        validate_espeak_value(piper_value, mode="ipa3")
        normal[word] = normal_value
        piper[word] = piper_value
    generated_keys = tuple(normal)
    if generated_keys != tuple(piper):
        raise AssertionError("generated eSpeak key order differs between variants")
    identity = _identity_report(backend)
    inventory_report = _inventory_report(
        inventory, generated_keys, tuple(skipped_keys)
    )
    return EspeakPairResult(
        normal_entries=normal,
        piper_entries=piper,
        skipped_keys=tuple(skipped_keys),
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
