from __future__ import annotations

import json
from pathlib import Path

import g2lex
import pytest

from g2lex_data.inventory import build_word_inventory


def _pack(path: Path, entries: dict[str, str], source_id: str) -> Path:
    source = path.with_suffix(".json")
    source.write_text(json.dumps(entries) + "\n", encoding="utf-8")
    g2lex.pack_file(source, path, input_format="json-map", source_id=source_id)
    return path


def test_inventory_unions_sources_and_counts_duplicates(tmp_path: Path) -> None:
    left = _pack(tmp_path / "left.g2lex", {"a": "a", "b": "b", "c": "c"}, "de-de:lexhint")
    right = _pack(tmp_path / "right.g2lex", {"b": "b", "c": "c", "d": "d"}, "de-de:lexhint-native")
    inventory = build_word_inventory(
        {"de-de:lexhint": left, "de-de:lexhint-native": right}, locale="de-de"
    )
    assert inventory.keys == ("a", "b", "c", "d")
    assert inventory.source_entry_counts == {"de-de:lexhint": 3, "de-de:lexhint-native": 3}
    assert inventory.duplicate_key_count == 2
    assert len(inventory.logical_sha256) == 64


def test_inventory_supports_one_source_and_empty_source(tmp_path: Path) -> None:
    path = _pack(tmp_path / "one.g2lex", {"word": "value"}, "en-us:lexhint")
    empty = _pack(tmp_path / "empty.g2lex", {}, "en-us:lexhint-native")
    inventory = build_word_inventory({"en-us:lexhint": path}, locale="en-us")
    assert inventory.keys == ("word",)
    assert build_word_inventory({"en-us:lexhint-native": empty}, locale="en-us").keys == ()


def test_inventory_rejects_wrong_locale(tmp_path: Path) -> None:
    path = _pack(tmp_path / "wrong.g2lex", {"word": "value"}, "fr:lexhint")
    with pytest.raises(ValueError, match="does not belong"):
        build_word_inventory({"fr:lexhint": path}, locale="en-us")
