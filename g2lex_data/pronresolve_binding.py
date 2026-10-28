"""Bind shared pronunciation rules to target-native G2Lex values.

Only the IPA comparator is built in. Other encodings require an explicit, reviewed
adapter supplied by the caller; the binder never guesses a conversion.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pronresolve import AmbiguityIndex, ExactEquivalence, PronunciationEquivalence
from pronresolve.equivalence import partition_pronunciations
from pronresolve.normalization import _is_pronunciation_candidate, normalize_ipa

from .transforms.common import normalize_key, ordered_selectors, plain_value

BindingStatus = Literal[
    "bound",
    "missing",
    "ambiguous",
    "unsupported_encoding",
    "unsafe_equivalence",
]
_BINDING_STATUSES: tuple[BindingStatus, ...] = (
    "bound",
    "missing",
    "ambiguous",
    "unsupported_encoding",
    "unsafe_equivalence",
)


class PronunciationComparator(Protocol):
    """Explicit adapter from one target-native pronunciation to comparable IPA."""

    def comparable_ipa(self, native_value: str) -> str | None:
        """Return reviewed IPA for a value, or ``None`` if it cannot be compared."""
        ...


@dataclass(frozen=True, slots=True)
class IPAComparator:
    """Normalize IPA values directly without applying an inferred codec."""

    def comparable_ipa(self, native_value: str) -> str | None:
        if not isinstance(native_value, str):
            return None
        value = normalize_ipa(native_value)
        if not value or not _is_pronunciation_candidate(value):
            return None
        return value


@dataclass(frozen=True, slots=True)
class ReadingBinding:
    reading_id: str
    word: str
    pos: str
    status: BindingStatus
    native_value: object | None = None
    native_values: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "reading_id": self.reading_id,
            "word": self.word,
            "pos": self.pos,
            "status": self.status,
        }
        if self.native_value is not None:
            result["native_value"] = _json_value(self.native_value)
        if self.native_values:
            result["native_values"] = list(self.native_values)
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True, slots=True)
class BindingReport:
    rules_id: str
    phoneme_encoding: str
    bindings: tuple[ReadingBinding, ...]

    def as_dict(self) -> dict[str, object]:
        counts = {
            status: sum(binding.status == status for binding in self.bindings)
            for status in _BINDING_STATUSES
        }
        return {
            "rules_id": self.rules_id,
            "phoneme_encoding": self.phoneme_encoding,
            "reading_count": len(self.bindings),
            "status_counts": counts,
            "bindings": [binding.to_dict() for binding in self.bindings],
        }


@dataclass(frozen=True, slots=True)
class BindingResult:
    entries: dict[str, object]
    report: BindingReport


@dataclass(frozen=True, slots=True)
class _TargetPronunciations:
    native_values: tuple[str, ...]
    native_by_ipa: Mapping[str, tuple[str, ...]]
    classes: tuple[tuple[str, ...], ...]
    unsafe_reason: str | None = None


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _native_values(value: object) -> tuple[list[str], bool]:
    found: list[str] = []
    invalid = False

    def visit(item: object) -> None:
        nonlocal invalid
        if item is None:
            return
        if isinstance(item, str):
            if item:
                if item not in found:
                    found.append(item)
            else:
                invalid = True
            return
        if isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (tuple, list)):
            for nested in item:
                visit(nested)
            return
        invalid = True

    visit(value)
    return found, invalid


def _target_pronunciations(
    value: object,
    comparator: PronunciationComparator,
    equivalence_policy: PronunciationEquivalence,
) -> _TargetPronunciations:
    native_values, has_invalid = _native_values(value)
    if has_invalid:
        return _TargetPronunciations((), {}, (), "target contains non-string pronunciation data")
    if not native_values:
        return _TargetPronunciations((), {}, ())

    native_by_ipa_mutable: dict[str, list[str]] = defaultdict(list)
    for native_value in native_values:
        try:
            comparable = comparator.comparable_ipa(native_value)
        except Exception as exc:  # noqa: BLE001 - fail closed on arbitrary adapter errors
            return _TargetPronunciations(
                tuple(native_values), {}, (), f"comparator failed: {type(exc).__name__}: {exc}"
            )
        if not isinstance(comparable, str):
            return _TargetPronunciations(
                tuple(native_values), {}, (), "target pronunciation is unsupported by comparator"
            )
        ipa = normalize_ipa(comparable)
        if not ipa or not _is_pronunciation_candidate(ipa):
            return _TargetPronunciations(
                tuple(native_values), {}, (), "comparator returned invalid IPA"
            )
        native_by_ipa_mutable[ipa].append(native_value)

    partition = partition_pronunciations(
        native_by_ipa_mutable,
        policy=equivalence_policy,
    )
    if partition.unsafe:
        return _TargetPronunciations(
            tuple(native_values),
            {key: tuple(values) for key, values in native_by_ipa_mutable.items()},
            (),
            partition.reason or "unsafe pronunciation equivalence",
        )
    return _TargetPronunciations(
        tuple(native_values),
        {key: tuple(values) for key, values in native_by_ipa_mutable.items()},
        tuple(item.pronunciations for item in partition.classes),
    )


def _target_index(entries: Mapping[str, object]) -> tuple[dict[str, str], dict[str, list[str]]]:
    normalized_to_original: dict[str, str] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)
    for original in entries:
        if not isinstance(original, str) or not normalize_key(original):
            continue
        normalized = normalize_key(original)
        prior = normalized_to_original.get(normalized)
        if prior is not None and prior != original:
            duplicates[normalized].extend((prior, original))
        else:
            normalized_to_original[normalized] = original
    return normalized_to_original, {
        key: sorted(set(values)) for key, values in duplicates.items()
    }


def bind_shared_rules(
    entries: Mapping[str, object],
    rules: AmbiguityIndex,
    *,
    phoneme_encoding: str,
    comparator: PronunciationComparator | None = None,
    equivalence_policy: PronunciationEquivalence | None = None,
) -> BindingResult:
    """Add safe ``READING:<r2-id>`` selectors to native target entries.

    The source rules are never modified and the binder never rewrites a target's
    existing values or selectors. Unsupported encodings and uncertain matching
    states are reported without adding a selector.
    """
    if not isinstance(entries, Mapping):
        raise TypeError("target entries must be a mapping")
    if not isinstance(rules, AmbiguityIndex) or rules.schema_version != 3:
        raise ValueError("shared rules must be a schema-v3 AmbiguityIndex")
    try:
        rules = AmbiguityIndex.from_dict(rules.to_dict())
    except (TypeError, ValueError) as exc:
        raise ValueError("shared rules failed schema-v3 validation") from exc
    if not isinstance(phoneme_encoding, str) or not phoneme_encoding.strip():
        raise ValueError("phoneme_encoding must be a non-empty string")

    encoding = phoneme_encoding.strip()
    selected_comparator = comparator
    if selected_comparator is None and encoding == "ipa":
        selected_comparator = IPAComparator()
    policy = equivalence_policy or ExactEquivalence()
    normalized_to_original, duplicate_keys = _target_index(entries)
    output = dict(entries)
    target_cache: dict[str, _TargetPronunciations] = {}
    bindings: list[ReadingBinding] = []

    for profile in sorted(
        rules.profiles,
        key=lambda item: (item.word, item.pos, item.reading_id),
    ):
        word = normalize_key(profile.word)
        common = {
            "reading_id": profile.reading_id,
            "word": profile.word,
            "pos": profile.pos,
        }
        if selected_comparator is None:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="unsupported_encoding",
                    reason=f"no reviewed comparator for phoneme encoding {encoding!r}",
                )
            )
            continue
        if word in duplicate_keys:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="ambiguous",
                    reason=f"multiple target keys normalize to {word!r}",
                )
            )
            continue
        original_key = normalized_to_original.get(word)
        if original_key is None:
            bindings.append(ReadingBinding(**common, status="missing", reason="target word is absent"))
            continue

        target = target_cache.get(word)
        if target is None:
            target = _target_pronunciations(
                entries[original_key], selected_comparator, policy
            )
            target_cache[word] = target
        if target.unsafe_reason is not None:
            status: BindingStatus = (
                "unsupported_encoding"
                if target.unsafe_reason.startswith(("comparator failed", "target pronunciation", "comparator returned"))
                else "unsafe_equivalence"
            )
            bindings.append(ReadingBinding(**common, status=status, reason=target.unsafe_reason))
            continue
        if not target.classes:
            bindings.append(ReadingBinding(**common, status="missing", reason="target has no pronunciations"))
            continue

        matched_classes: list[tuple[str, ...]] = []
        comparison_error: str | None = None
        for pronunciation_class in target.classes:
            outcomes: list[bool] = []
            for target_ipa in pronunciation_class:
                try:
                    outcomes.append(bool(policy.equivalent(profile.anchor_ipa, target_ipa)))
                except Exception as exc:  # noqa: BLE001 - fail closed on arbitrary policy errors
                    comparison_error = f"equivalence comparison failed: {type(exc).__name__}: {exc}"
                    break
            if comparison_error is not None:
                break
            if any(outcomes) and not all(outcomes):
                comparison_error = "source pronunciation matches only part of a target equivalence class"
                break
            if outcomes and all(outcomes):
                matched_classes.append(pronunciation_class)

        if comparison_error is not None:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="unsafe_equivalence",
                    reason=comparison_error,
                )
            )
            continue
        if not matched_classes:
            bindings.append(
                ReadingBinding(**common, status="missing", reason="no target pronunciation class matches")
            )
            continue
        if len(matched_classes) != 1:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="ambiguous",
                    reason="multiple distinct target pronunciation classes match",
                )
            )
            continue

        matched_ipa = set(matched_classes[0])
        native_matches = tuple(
            native
            for native in target.native_values
            if any(native in target.native_by_ipa.get(ipa, ()) for ipa in matched_ipa)
        )
        if not native_matches:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="unsafe_equivalence",
                    reason="matched target class has no native values",
                )
            )
            continue
        native_value = plain_value(list(native_matches))
        current_value = output[original_key]
        selectors = (
            dict(current_value)
            if isinstance(current_value, Mapping)
            else {"DEFAULT": current_value}
        )
        selector = f"READING:{profile.reading_id}"
        existing = selectors.get(selector)
        if existing is not None and existing != native_value:
            bindings.append(
                ReadingBinding(
                    **common,
                    status="ambiguous",
                    reason="existing reading selector conflicts with binding",
                )
            )
            continue
        selectors[selector] = native_value
        output[original_key] = ordered_selectors(selectors)
        bindings.append(
            ReadingBinding(
                **common,
                status="bound",
                native_value=native_value,
                native_values=native_matches,
            )
        )

    report = BindingReport(
        rules_id=rules.rules_id or "",
        phoneme_encoding=encoding,
        bindings=tuple(bindings),
    )
    return BindingResult(entries=output, report=report)


__all__ = [
    "BindingReport",
    "BindingResult",
    "BindingStatus",
    "IPAComparator",
    "PronunciationComparator",
    "ReadingBinding",
    "bind_shared_rules",
]
