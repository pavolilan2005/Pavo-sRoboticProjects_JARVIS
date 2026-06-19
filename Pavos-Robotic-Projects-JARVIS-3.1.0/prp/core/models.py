from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@dataclass(slots=True)
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, message: str, **data: Any) -> "ActionResult":
        return cls(True, message, data)

    @classmethod
    def failure(cls, message: str, error: str | None = None, **data: Any) -> "ActionResult":
        return cls(False, message, data, error)

@dataclass(slots=True)
class Capability:
    name: str
    description: str
    handler: Any
    risk: Risk = Risk.LOW
    requires_confirmation: bool = False
