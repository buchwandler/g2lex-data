from __future__ import annotations

from lexhint import Pronunciation, PronunciationEntry, PronunciationGroup

from g2lex_data.transforms.lexhint_pronunciations import (
    collapse_entry,
    normalize_ipa,
    normalize_key,
    serialize_entries,
    transform_lexhint,
)


def group(pos: str, *values: str, word: str | None = "word") -> PronunciationGroup:
    return PronunciationGroup(pos, tuple(Pronunciation(value) for value in values), word)


def entry(key: str, *groups: PronunciationGroup) -> PronunciationEntry:
    return PronunciationEntry(key, groups)


def test_normalization() -> None:
    assert normalize_key("Live") == "live"
    assert normalize_key("Straße") == "straße"
    assert normalize_ipa("[ˈlɪv]") == "ˈlɪv"
    assert normalize_ipa("/ˈlɪv/") == "ˈlɪv"
    assert normalize_ipa("[/a/b/]") == "/a/b/"


def test_one_ipa_across_pos_is_plain_string() -> None:
    item = entry("house", group("noun", "[a]"), group("verb", "[a]"))
    assert collapse_entry(item) == "a"


def test_one_pos_two_variants_is_ordered_tuple() -> None:
    assert collapse_entry(entry("word", group("noun", "[a]", "[b]"))) == ("a", "b")


def test_same_ordered_variants_across_pos_are_plain_tuple() -> None:
    item = entry("word", group("noun", "[a]", "[b]"), group("verb", "[a]", "[b]"))
    assert collapse_entry(item) == ("a", "b")


def test_different_pos_values_use_selectors() -> None:
    item = entry("live", group("verb", "[ˈlɪv]"), group("adj", "[ˈlaɪ̯v]"), group("adv", "[ˈlaɪ̯v]"))
    assert collapse_entry(item) == {
        "DEFAULT": "ˈlɪv",
        "VERB": "ˈlɪv",
        "ADJ": "ˈlaɪ̯v",
        "ADV": "ˈlaɪ̯v",
    }


def test_multi_variant_pos_remains_tuple() -> None:
    item = entry("live", group("verb", "[a]"), group("adj", "[b]", "[c]"))
    assert collapse_entry(item)["ADJ"] == ("b", "c")  # type: ignore[index]


def test_case_collision_preserves_all_evidence() -> None:
    item = entry(
        "die",
        group("det", "[diː]", word="die"),
        group("pron", "[diː]", word="die"),
        group("noun", "[daɪ]", word="Die"),
    )
    result = transform_lexhint([item])
    assert result.entries == {"die": {"DEFAULT": "diː", "DET": "diː", "PRON": "diː", "NOUN": "daɪ"}}
    assert result.report["case_collision_count"] == 1


def test_default_prefers_exact_lowercase_display_form() -> None:
    item = entry(
        "live", group("verb", "[title]", word="Live"), group("noun", "[lower]", word="live")
    )
    assert collapse_entry(item)["DEFAULT"] == "lower"  # type: ignore[index]


def test_unknown_pos_is_preserved_and_counted() -> None:
    result = transform_lexhint([entry("word", group("future-pos", "[a]"), group("noun", "[b]"))])
    assert result.entries["word"]["FUTURE POS"] == "a"  # type: ignore[index]
    assert result.report["unknown_pos_count"] == 1


def test_empty_ipa_is_skipped_and_counted() -> None:
    result = transform_lexhint([entry("word", group("noun", "[]", "[a]"))])
    assert result.entries == {"word": "a"}
    assert result.report["empty_ipa_count"] == 1


def test_live_fixture() -> None:
    item = PronunciationEntry(
        key="live",
        groups=(
            PronunciationGroup("verb", (Pronunciation("[ˈlɪv]", ()),), word="live"),
            PronunciationGroup(
                "adj",
                (
                    Pronunciation("[ˈlaɪ̯v]", ()),
                    Pronunciation("[ˈlaːv]", ("General-South-African",)),
                ),
                word="live",
            ),
            PronunciationGroup("adv", (Pronunciation("[ˈlaɪ̯v]", ()),), word="live"),
        ),
    )
    assert collapse_entry(item) == {
        "DEFAULT": "ˈlɪv",
        "VERB": "ˈlɪv",
        "ADJ": ("ˈlaɪ̯v", "ˈlaːv"),
        "ADV": "ˈlaɪ̯v",
    }


def test_serialization_is_deterministic() -> None:
    item = entry("word", group("verb", "[b]"), group("noun", "[a]"))
    first = serialize_entries({"word": collapse_entry(item)})
    second = serialize_entries({"word": collapse_entry(item)})
    assert first == second
    assert first == '{"word":{"DEFAULT":"b","NOUN":"a","VERB":"b"}}\n'
