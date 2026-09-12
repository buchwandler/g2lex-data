from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

from g2lex_data import build as build_module
from g2lex_data.config import AssetConfig
from g2lex_data.inventory import WordInventory
from g2lex_data.transforms.espeak import EspeakPairResult


def _record(
    identifier: str,
    name: str,
    *,
    source_provider: str = "file",
    source_ids: tuple[str, ...] = (),
    language: str = "Test",
    voice: str | None = None,
) -> AssetConfig:
    inputs = None if voice is None else {
        "voice": voice,
        "piper_version": "3",
        "espeak_git_revision": "revision",
        "expected_espeak_version": "1.52.0.1",
        "output_mode": "ipa" if name == "espeak" else "ipa3",
    }
    return AssetConfig(
        id=identifier,
        language=language,
        name=name,
        display_name=identifier,
        kind="pronunciation",
        source="" if source_provider == "g2lex-assets" else "fixture.txt",
        source_format="g2lex" if source_provider == "g2lex-assets" else "words",
        source_id=identifier,
        source_sha256=None,
        source_size=None,
        phoneme_encoding="ipa" if name == "espeak" else "espeak-ipa3",
        provider="test",
        revision="revision",
        license_expression="MIT",
        license_url="https://example.test/license",
        attribution="test",
        transform="g2lex-espeak-ipa-v1" if name == "espeak" else "g2lex-espeak-piper-ipa3-v1",
        transform_inputs=inputs,
        source_provider=source_provider,
        source_ids=source_ids,
    )


def _config(records: tuple[AssetConfig, ...]) -> SimpleNamespace:
    by_id = {record.id: record for record in records}
    return SimpleNamespace(assets=records, asset=by_id.__getitem__)


def _inventory(locale: str, source_ids: tuple[str, ...]) -> WordInventory:
    return WordInventory(locale, source_ids, {source_id: 1 for source_id in source_ids}, ("word",), 0, "hash")


def test_pair_members_and_parent_are_built_once(monkeypatch) -> None:
    parent = _record("aa:lexhint", "lexhint")
    normal = _record(
        "aa:espeak", "espeak", source_provider="g2lex-assets", source_ids=(parent.id,), voice="voice-aa"
    )
    piper = _record(
        "aa:espeak-piper",
        "espeak-piper",
        source_provider="g2lex-assets",
        source_ids=(parent.id,),
        voice="voice-aa",
    )
    monkeypatch.setattr(build_module, "load_config", lambda: _config((parent, normal, piper)))

    source_builds: list[str] = []
    monkeypatch.setattr(
        build_module,
        "_build_source_record",
        lambda record, *, data_version: source_builds.append(record.id) or {"id": record.id},
    )
    monkeypatch.setattr(
        build_module,
        "build_word_inventory",
        lambda source_paths, *, locale: _inventory(locale, tuple(source_paths)),
    )
    generated = {"calls": 0}

    class FakeBackend:
        def __init__(self, **kwargs):
            generated["backend_inits"] = generated.get("backend_inits", 0) + 1
            self.voices: list[str] = []
            self.closed = 0

        def set_voice(self, voice: str) -> None:
            self.voices.append(voice)

        def close(self) -> None:
            self.closed += 1

    backend_holder: list[FakeBackend] = []

    def backend_factory(**kwargs):
        backend = FakeBackend(**kwargs)
        backend_holder.append(backend)
        return backend

    monkeypatch.setattr(build_module, "EspeakBackend", backend_factory)

    def generate(*, inventory, voice, backend):
        generated["calls"] += 1
        backend.set_voice(voice)
        return EspeakPairResult({}, {}, (), {"generator": {}}, {}, {})

    monkeypatch.setattr(build_module, "generate_espeak_pair", generate)
    writes: list[str] = []
    monkeypatch.setattr(
        build_module,
        "_write_espeak_variant",
        lambda record, **kwargs: writes.append(record.id) or {"id": record.id},
    )

    session = build_module.BuildSession(data_version="test")
    assert session.build_record(normal) == {"id": normal.id}
    assert session.build_record(piper) == {"id": piper.id}
    session.close()
    session.close()

    assert source_builds == [parent.id]
    assert generated["calls"] == 1
    assert generated["backend_inits"] == 1
    assert writes == [normal.id, piper.id]
    assert backend_holder[0].voices == ["voice-aa"]
    assert backend_holder[0].closed == 1


def test_multiple_locale_pairs_reuse_backend_in_requested_order(monkeypatch) -> None:
    records: list[AssetConfig] = []
    for locale in ("aa", "bb"):
        parent = _record(f"{locale}:lexhint", "lexhint", language=locale)
        normal = _record(
            f"{locale}:espeak",
            "espeak",
            source_provider="g2lex-assets",
            source_ids=(parent.id,),
            language=locale,
            voice=f"voice-{locale}",
        )
        piper = _record(
            f"{locale}:espeak-piper",
            "espeak-piper",
            source_provider="g2lex-assets",
            source_ids=(parent.id,),
            language=locale,
            voice=f"voice-{locale}",
        )
        records.extend((parent, normal, piper))
    monkeypatch.setattr(build_module, "load_config", lambda: _config(tuple(records)))
    monkeypatch.setattr(
        build_module,
        "_build_source_record",
        lambda record, *, data_version: {"id": record.id},
    )
    monkeypatch.setattr(
        build_module,
        "build_word_inventory",
        lambda source_paths, *, locale: _inventory(locale, tuple(source_paths)),
    )
    monkeypatch.setattr(
        build_module,
        "_write_espeak_variant",
        lambda record, **kwargs: {"id": record.id},
    )

    class FakeBackend:
        instances: ClassVar[list[FakeBackend]] = []

        def __init__(self, **kwargs):
            self.voices: list[str] = []
            self.closed = 0
            self.instances.append(self)

        def close(self) -> None:
            self.closed += 1

    monkeypatch.setattr(build_module, "EspeakBackend", FakeBackend)
    monkeypatch.setattr(
        build_module,
        "generate_espeak_pair",
        lambda *, inventory, voice, backend: (
            backend.voices.append(voice)
            or EspeakPairResult({}, {}, (), {"generator": {}}, {}, {})
        ),
    )

    manifests = build_module.build_espeak_pairs(["bb", "aa"], data_version="test")

    assert [manifest["id"] for manifest in manifests] == [
        "bb:espeak",
        "bb:espeak-piper",
        "aa:espeak",
        "aa:espeak-piper",
    ]
    assert len(FakeBackend.instances) == 1
    assert FakeBackend.instances[0].voices == ["voice-bb", "voice-aa"]
    assert FakeBackend.instances[0].closed == 1
