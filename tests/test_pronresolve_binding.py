from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace

import g2lex
import pytest
from pronresolve import AmbiguityIndex, ReadingProfile, SemanticAnchor, reading_id_v2, save_index

from g2lex_data import build as build_module
from g2lex_data import validate as validate_module
from g2lex_data.config import load_config
from g2lex_data.pronresolve_binding import bind_shared_rules


class FixtureComparator:
    def __init__(self, values: Mapping[str, str]):
        self.values = values

    def comparable_ipa(self, native_value: str) -> str | None:
        return self.values.get(native_value)


def rules(word: str = "wug", *anchors: str) -> AmbiguityIndex:
    profiles = []
    for anchor_key in anchors:
        semantic_anchor = SemanticAnchor("fixture:en", (anchor_key,))
        profiles.append(
            ReadingProfile(
                word=word,
                pos="NOUN",
                reading_id=reading_id_v2("en", word, "NOUN", semantic_anchor),
                anchor_ipa=anchor_key,
            )
        )
    return AmbiguityIndex(
        language="en",
        locale="en-US",
        rules_id="en-us",
        profiles=tuple(profiles),
    )


def test_binder_adds_selectors_and_preserves_native_values_and_existing_selectors():
    shared = rules("wug", "a", "b")
    entries = {
        "wug": {
            "DEFAULT": ("native-a", "native-a-alt", "native-b"),
            "NOUN": ("native-a", "native-a-alt", "native-b"),
            "READING:r2-existing": "native-b",
        }
    }
    comparator = FixtureComparator(
        {"native-a": "a", "native-a-alt": "a", "native-b": "b"}
    )

    result = bind_shared_rules(
        entries,
        shared,
        phoneme_encoding="fixture-encoding",
        comparator=comparator,
    )

    bindings = {binding.reading_id: binding for binding in result.report.bindings}
    assert bindings[shared.profiles[0].reading_id].status == "bound"
    assert bindings[shared.profiles[0].reading_id].native_values == (
        "native-a",
        "native-a-alt",
    )
    assert bindings[shared.profiles[1].reading_id].native_value == "native-b"
    assert result.entries["wug"]["DEFAULT"] == entries["wug"]["DEFAULT"]
    assert result.entries["wug"]["NOUN"] == entries["wug"]["NOUN"]
    assert result.entries["wug"]["READING:r2-existing"] == "native-b"
    assert result.entries["wug"][f"READING:{shared.profiles[0].reading_id}"] == (
        "native-a",
        "native-a-alt",
    )
    assert result.report.as_dict()["status_counts"] == {
        "bound": 2,
        "missing": 0,
        "ambiguous": 0,
        "unsupported_encoding": 0,
        "unsafe_equivalence": 0,
    }


def test_ipa_is_the_only_implicit_adapter_and_unknown_encoding_abstains():
    shared = rules("wug", "a", "b")
    entries = {"wug": ("a", "b")}

    result = bind_shared_rules(entries, shared, phoneme_encoding="kokoro-v1")

    assert result.entries == entries
    assert {binding.status for binding in result.report.bindings} == {"unsupported_encoding"}
    assert bind_shared_rules(entries, shared, phoneme_encoding="ipa").report.as_dict()[
        "status_counts"
    ]["bound"] == 2


def test_target_matching_multiple_equivalence_classes_is_ambiguous():
    shared = rules("wug", "a", "b")

    class MatchBothPolicy:
        def equivalent(self, left: str, right: str) -> bool:
            return frozenset((left, right)) in {
                frozenset(("a", "x")),
                frozenset(("a", "y")),
            }

    result = bind_shared_rules(
        {"wug": ("x", "y")},
        shared,
        phoneme_encoding="ipa",
        equivalence_policy=MatchBothPolicy(),
    )

    bindings = {binding.reading_id: binding for binding in result.report.bindings}
    assert bindings[shared.profiles[0].reading_id].status == "ambiguous"
    assert bindings[shared.profiles[1].reading_id].status == "missing"
    assert not any(key.startswith("READING:") for key in result.entries["wug"])


def test_non_transitive_target_equivalence_is_unsafe_for_the_whole_word():
    shared = rules("wug", "a", "b")

    class ChainPolicy:
        def equivalent(self, left: str, right: str) -> bool:
            return frozenset((left, right)) in {
                frozenset(("x", "y")),
                frozenset(("y", "z")),
            }

    result = bind_shared_rules(
        {"wug": ("x", "y", "z")},
        shared,
        phoneme_encoding="ipa",
        equivalence_policy=ChainPolicy(),
    )

    assert {binding.status for binding in result.report.bindings} == {"unsafe_equivalence"}
    assert result.entries == {"wug": ("x", "y", "z")}


def test_missing_words_and_normalized_target_key_collisions_fail_closed():
    missing_rules = AmbiguityIndex(
        language="en",
        locale="en-US",
        rules_id="en-us",
        profiles=rules("wug", "a", "b").profiles,
    )
    missing = bind_shared_rules({}, missing_rules, phoneme_encoding="ipa")
    assert {binding.status for binding in missing.report.bindings} == {"missing"}

    shared = rules("wug", "a", "b")
    collision = bind_shared_rules(
        {"Wug": "a", "wug": "b"},
        shared,
        phoneme_encoding="ipa",
    )
    assert {binding.status for binding in collision.report.bindings} == {"ambiguous"}
    assert collision.entries == {"Wug": "a", "wug": "b"}


def test_binding_report_is_deterministic_under_target_value_order():
    shared = rules("wug", "a", "b")
    comparator = FixtureComparator({"native-a": "a", "native-b": "b"})
    first = bind_shared_rules(
        {"wug": ("native-a", "native-b")},
        shared,
        phoneme_encoding="fixture-encoding",
        comparator=comparator,
    )
    second = bind_shared_rules(
        {"wug": ("native-b", "native-a")},
        shared,
        phoneme_encoding="fixture-encoding",
        comparator=comparator,
    )

    assert first.report.as_dict() == second.report.as_dict()
    assert first.report.as_dict()["rules_id"] == "en-us"


def test_generic_build_binds_shared_rules_without_rewriting_target_values(monkeypatch, tmp_path):
    source = tmp_path / "target.json"
    source.write_text(
        json.dumps({"wug": {"DEFAULT": ["a", "b"], "NOUN": "a", "VERB": "b"}, "other": {"DEFAULT": "x", "NOUN": "y"}}),
        encoding="utf-8",
    )
    record = replace(
        load_config().asset("en-us:demo-cmu"),
        id="en-us:fixture-gold",
        name="gold",
        source=str(source),
        source_format="json-map",
        source_id="fixture:gold",
        source_sha256=None,
        source_size=None,
        phoneme_encoding="ipa",
        transform=None,
        transform_inputs=None,
    )
    assets = tmp_path / "assets"
    manifests = tmp_path / "manifests"
    reports = tmp_path / "reports"
    assets.mkdir()
    monkeypatch.setattr(build_module, "ASSET_DIR", assets)
    monkeypatch.setattr(build_module, "MANIFEST_DIR", manifests)
    monkeypatch.setattr(build_module, "REPORT_DIR", reports)
    monkeypatch.setattr(
        build_module,
        "resolve_source",
        lambda _record: SimpleNamespace(path=source, metadata={}),
    )
    monkeypatch.setattr(
        build_module,
        "validate_source",
        lambda *_args, **_kwargs: {"entry_count": 1, "logical_sha256": "fixture"},
    )
    shared = rules("wug", "a", "b")
    save_index(shared, assets / f"g2lex-{shared.rules_id}.pronresolve.json")

    manifest = build_module._build_source_record(
        record,
        data_version="test",
        shared_rules=shared,
    )

    monkeypatch.setattr(validate_module, "ASSET_DIR", assets)
    monkeypatch.setattr(validate_module, "REPORT_DIR", reports)
    validate_module._validate_resolver_index(record, assets / record.asset_name, manifest)
    binding_capability = manifest["capabilities"]["pronunciation_binding"]
    report_path = reports / binding_capability["report"]["path"]
    binding_report = json.loads(report_path.read_text(encoding="utf-8"))
    tampered_report = json.loads(json.dumps(binding_report))
    tampered_report["bindings"][0]["native_value"] = "not-the-packed-value"
    with pytest.raises(ValueError, match="shared rules selector mismatch"):
        build_module._verify_shared_rules_binding(
            assets / record.asset_name,
            record.id,
            tampered_report,
        )
    tampered_manifest = dict(manifest)
    tampered_capabilities = dict(manifest["capabilities"])
    tampered_binding = dict(binding_capability)
    tampered_binding["status_counts"] = {**binding_capability["status_counts"], "bound": 1}
    tampered_capabilities["pronunciation_binding"] = tampered_binding
    tampered_manifest["capabilities"] = tampered_capabilities
    with pytest.raises(ValueError, match="invalid pronunciation-binding summary"):
        validate_module._validate_resolver_index(
            record,
            assets / record.asset_name,
            tampered_manifest,
        )
    assert manifest["capabilities"]["pronunciation_binding"]["status_counts"]["bound"] == 2
    with g2lex.open(assets / record.asset_name) as packed:
        assert packed.lookup("wug", tag="NOUN") == "a"
        assert packed.lookup("wug", tag="VERB") == "b"
        assert packed.lookup("other", tag="DEFAULT") == "x"
        assert packed.lookup("other", tag="NOUN") == "y"
        for profile in shared.profiles:
            assert packed.lookup("wug", tag=f"READING:{profile.reading_id}") == profile.anchor_ipa
