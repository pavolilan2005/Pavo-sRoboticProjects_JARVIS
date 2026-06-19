from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str = ""

    def finish(self) -> "ActionResult":
        if not self.finished_at:
            self.finished_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.finish())

    @classmethod
    def success(cls, message: str, **data: Any) -> "ActionResult":
        return cls(True, message, data=data).finish()

    @classmethod
    def failure(cls, message: str, error: str = "", **data: Any) -> "ActionResult":
        return cls(False, message, data=data, error=error or message).finish()


CapabilityHandler = Callable[[dict[str, Any]], ActionResult | dict[str, Any] | str | bool | None]
Verifier = Callable[[dict[str, Any], ActionResult], bool]


@dataclass(slots=True)
class Capability:
    name: str
    description: str
    handler: CapabilityHandler
    risk: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    timeout_seconds: float = 30.0
    tags: tuple[str, ...] = ()
    verifier: Verifier | None = None
    schema: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk.value,
            "requires_confirmation": self.requires_confirmation,
            "timeout_seconds": self.timeout_seconds,
            "tags": list(self.tags),
            "schema": self.schema,
        }


@dataclass(slots=True)
class Event:
    topic: str
    payload: dict[str, Any]
    source: str = "jarvis"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
