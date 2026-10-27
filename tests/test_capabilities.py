from __future__ import annotations

import pytest

from g2lex_data.capabilities import ResolutionCapability
from g2lex_data.config import load_config


def test_available_capability_serializes_index_metadata() -> None:
    capability = ResolutionCapability("available", index={"name": "index.json", "schema_version": 2})

    assert capability.to_dict() == {
        "status": "available",
        "index": {"name": "index.json", "schema_version": 2},
    }


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        ("unnecessary", "no_resolvable_same_pos_ambiguities"),
        ("unavailable", "source_has_no_sense_linked_pronunciation_mapping"),
    ),
)
def test_non_available_capability_serializes_reason(status: str, reason: str) -> None:
    capability = ResolutionCapability(status, reason=reason)  # type: ignore[arg-type]

    assert capability.to_dict() == {"status": status, "reason": reason}


def test_capability_rejects_inconsistent_state() -> None:
    with pytest.raises(ValueError, match="requires index metadata"):
        ResolutionCapability("available")
    with pytest.raises(ValueError, match="requires a reason"):
        ResolutionCapability("unnecessary")
    with pytest.raises(ValueError, match="cannot have index metadata"):
        ResolutionCapability("unavailable", reason="no mapping", index={"name": "x"})



def test_gold_source_declares_unavailable_capability() -> None:
    capability = load_config().asset("en-us:gold").resolution_capability

    assert capability is not None
    assert capability.to_dict() == {
        "status": "unavailable",
        "reason": "source_has_no_sense_linked_pronunciation_mapping",
    }
