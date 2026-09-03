from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping

SELECTOR_ORDER = (
    "DEFAULT",
    "DET",
    "PRON",
    "NOUN",
    "PROPN",
    "VERB",
    "AUX",
    "ADJ",
    "ADV",
    "ADP",
    "NUM",
    "CCONJ",
    "SCONJ",
    "PART",
    "INTJ",
    "X",
)

LEXHINT_TO_G2LEX_POS = {
    "determiner": "DET",
    "det": "DET",
    "pronoun": "PRON",
    "pron": "PRON",
    "noun": "NOUN",
    "proper noun": "PROPN",
    "proper_noun": "PROPN",
    "propn": "PROPN",
    "verb": "VERB",
    "auxiliary": "AUX",
    "aux": "AUX",
    "adjective": "ADJ",
    "adj": "ADJ",
    "adverb": "ADV",
    "adv": "ADV",
    "adposition": "ADP",
    "preposition": "ADP",
    "postposition": "ADP",
    "numeral": "NUM",
    "num": "NUM",
    "particle": "PART",
    "interjection": "INTJ",
}
KNOWN_POS = frozenset(LEXHINT_TO_G2LEX_POS) | frozenset(SELECTOR_ORDER)


def normalize_key(word: str) -> str:
    return unicodedata.normalize("NFC", word).lower()


def normalize_pos(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip().lower().replace("-", " ")
    return LEXHINT_TO_G2LEX_POS.get(normalized, normalized.upper())


def ordered_selectors(selectors: Mapping[str, object]) -> dict[str, object]:
    order = {selector: index for index, selector in enumerate(SELECTOR_ORDER)}
    return dict(sorted(selectors.items(), key=lambda item: (order.get(item[0], len(order)), item[0])))


def plain_value(pronunciations: list[str]) -> str | tuple[str, ...]:
    if len(pronunciations) == 1:
        return pronunciations[0]
    return tuple(pronunciations)


def serialize_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: serialize_value(value[key]) for key in ordered_selectors(value)}
    if isinstance(value, tuple):
        return list(value)
    return value


def serialize_entries(entries: Mapping[str, object]) -> str:
    ordered = {key: serialize_value(entries[key]) for key in sorted(entries)}
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n"
