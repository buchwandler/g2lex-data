from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

ResolutionStatus = Literal["available", "unnecessary", "unavailable"]
NO_RESOLVABLE_AMBIGUITIES = "no_resolvable_same_pos_ambiguities"
NO_SENSE_LINKED_MAPPING = "source_has_no_sense_linked_pronunciation_mapping"


@dataclass(frozen=True, slots=True)
class ResolutionCapability:
    """Explicit pronunciation-resolution capability for one pronunciation asset."""

    status: ResolutionStatus
    reason: str | None = None
    index: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"available", "unnecessary", "unavailable"}:
            raise ValueError(f"unsupported pronunciation-resolution status: {self.status}")
        if self.status == "available":
            if self.reason is not None:
                raise ValueError("available pronunciation resolution cannot have a reason")
            if not isinstance(self.index, Mapping) or not self.index:
                raise ValueError("available pronunciation resolution requires index metadata")
        else:
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError(f"{self.status} pronunciation resolution requires a reason")
            if self.index is not None:
                raise ValueError(f"{self.status} pronunciation resolution cannot have index metadata")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"status": self.status}
        if self.status == "available":
            assert self.index is not None
            value["index"] = dict(self.index)
        else:
            value["reason"] = self.reason
        return value


__all__ = [
    "NO_RESOLVABLE_AMBIGUITIES",
    "NO_SENSE_LINKED_MAPPING",
    "ResolutionCapability",
    "ResolutionStatus",
]
