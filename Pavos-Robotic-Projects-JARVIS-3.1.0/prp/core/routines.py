from __future__ import annotations
import asyncio
from typing import Any
from .capabilities import CapabilityRegistry
from .config import ConfigStore
from .events import EventBus
from .models import ActionResult

class RoutineEngine:
    def __init__(self, config: ConfigStore, registry: CapabilityRegistry, events: EventBus):
        self.config = config
        self.registry = registry
        self.events = events
        self._tasks: dict[str, asyncio.Task] = {}

    def definitions(self) -> list[dict[str, Any]]:
        return (self.config.load("routines.json", {}) or {}).get("routines", [])

    def find(self, routine_id_or_alias: str) -> dict[str, Any] | None:
        needle = routine_id_or_alias.strip().lower()
        for routine in self.definitions():
            aliases = [str(x).lower() for x in routine.get("aliases", [])]
            if needle in {str(routine.get("id", "")).lower(), str(routine.get("name", "")).lower(), *aliases}:
                return routine
        return None

    async def run(self, routine_id_or_alias: str) -> ActionResult:
        routine = self.find(routine_id_or_alias)
        if not routine:
            return ActionResult.failure(f"Rutina no encontrada: {routine_id_or_alias}")
        run_id = str(routine.get("id"))
        await self.events.publish("routine.started", routine_id=run_id, name=routine.get("name"))
        completed: list[dict[str, Any]] = []
        for index, step in enumerate(routine.get("steps", [])):
            result = await self._run_step(step)
            await self.events.publish("routine.step", routine_id=run_id, index=index, ok=result.ok, message=result.message)
            if result.ok:
                completed.append(step)
                continue
            if step.get("optional", False):
                continue
            await self._rollback(completed)
            await self.events.publish("routine.failed", routine_id=run_id, message=result.message)
            return result
        await self.events.publish("routine.completed", routine_id=run_id)
        return ActionResult.success(f"Rutina completada: {routine.get('name', run_id)}")

    async def _run_step(self, step: dict[str, Any]) -> ActionResult:
        if "parallel" in step:
            results = await asyncio.gather(*(self._run_step(item) for item in step["parallel"]))
            failures = [r for r in results if not r.ok]
            return failures[0] if failures else ActionResult.success("Bloque paralelo completado")
        name = str(step.get("capability", ""))
        args = step.get("args", {}) or {}
        retries = max(0, int(step.get("retries", 0)))
        last = ActionResult.failure("Paso no ejecutado")
        for attempt in range(retries + 1):
            last = await self.registry.execute(name, args)
            if last.ok:
                return last
            if attempt < retries:
                await asyncio.sleep(float(step.get("retry_delay", 0.5)))
        return last

    async def _rollback(self, completed: list[dict[str, Any]]) -> None:
        for step in reversed(completed):
            rollback = step.get("rollback")
            if rollback:
                await self._run_step(rollback)
