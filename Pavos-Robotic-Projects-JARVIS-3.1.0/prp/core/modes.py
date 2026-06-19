from __future__ import annotations
from typing import Any
from .config import ConfigStore
from .events import EventBus
from .models import ActionResult
from .routines import RoutineEngine

class ModeEngine:
    def __init__(self, config: ConfigStore, routines: RoutineEngine, events: EventBus):
        self.config = config
        self.routines = routines
        self.events = events
        self.active: set[str] = set()

    def definitions(self) -> list[dict[str, Any]]:
        return (self.config.load("modes.json", {}) or {}).get("modes", [])

    def find(self, mode_id: str) -> dict[str, Any] | None:
        needle = mode_id.lower().strip()
        for mode in self.definitions():
            if needle in {str(mode.get("id", "")).lower(), str(mode.get("name", "")).lower()}:
                return mode
        return None

    async def start(self, mode_id: str) -> ActionResult:
        mode = self.find(mode_id)
        if not mode:
            return ActionResult.failure(f"Modo no encontrado: {mode_id}")
        group = mode.get("exclusive_group")
        if group:
            for active_id in list(self.active):
                active_mode = self.find(active_id)
                if active_mode and active_mode.get("exclusive_group") == group:
                    await self.stop(active_id)
        result = await self.routines.run(mode.get("enter_routine", ""))
        if result.ok:
            self.active.add(str(mode["id"]))
            await self.events.publish("mode.started", mode_id=mode["id"])
        return result

    async def stop(self, mode_id: str) -> ActionResult:
        mode = self.find(mode_id)
        if not mode:
            return ActionResult.failure(f"Modo no encontrado: {mode_id}")
        routine = mode.get("exit_routine")
        result = await self.routines.run(routine) if routine else ActionResult.success("Modo detenido")
        self.active.discard(str(mode["id"]))
        await self.events.publish("mode.stopped", mode_id=mode["id"])
        return result
