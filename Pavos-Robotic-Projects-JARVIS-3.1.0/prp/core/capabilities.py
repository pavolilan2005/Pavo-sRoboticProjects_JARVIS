from __future__ import annotations
import asyncio
from typing import Any
from .models import ActionResult, Capability

class CapabilityRegistry:
    def __init__(self):
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._items:
            raise ValueError(f"Capacidad duplicada: {capability.name}")
        self._items[capability.name] = capability

    def list(self) -> list[Capability]:
        return sorted(self._items.values(), key=lambda item: item.name)

    def get(self, name: str) -> Capability | None:
        return self._items.get(name)

    async def execute(self, name: str, args: dict[str, Any] | None = None) -> ActionResult:
        capability = self.get(name)
        if not capability:
            return ActionResult.failure(f"Capacidad desconocida: {name}")
        try:
            result = capability.handler(**(args or {}))
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, ActionResult):
                return result
            return ActionResult.success(str(result) if result is not None else "Completado")
        except Exception as exc:
            return ActionResult.failure(f"Falló {name}", error=f"{type(exc).__name__}: {exc}")
