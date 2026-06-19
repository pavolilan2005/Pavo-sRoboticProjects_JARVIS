from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .capabilities import CapabilityRegistry
from .event_bus import EventBus
from .models import ActionResult
from .routines import RoutineEngine
from .storage import JsonStore


DEFAULT_MODES = {
    "version": 1,
    "modes": [
        {
            "id": "stream",
            "name": "Modo Stream",
            "aliases": ["stream", "directo"],
            "enter_routine": "modo_stream",
            "exit_routine": "terminar_stream",
            "exclusive_group": "activity",
            "monitors": [
                {
                    "id": "thermal_guard",
                    "interval": 15,
                    "capability": "pc.status",
                    "field": "cpu_percent",
                    "operator": ">=",
                    "value": 90,
                    "action": "notifications.emit",
                    "params": {},
                    "action_params": {"title": "JARVIS", "message": "Carga de CPU superior al 90 % durante el stream.", "priority": "high"},
                    "cooldown": 120,
                }
            ],
        },
        {
            "id": "estudio",
            "name": "Modo Estudio",
            "aliases": ["estudio", "concentración"],
            "enter_routine": "modo_estudio",
            "exit_routine": "",
            "exclusive_group": "activity",
            "monitors": [],
        },
    ],
}


class ModeManager:
    OPS = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "contains": lambda a, b: b in a,
    }

    def __init__(self, routines: RoutineEngine, registry: CapabilityRegistry, event_bus: EventBus, modes_path, state_path):
        self.routines = routines
        self.registry = registry
        self.event_bus = event_bus
        self.store = JsonStore(modes_path, DEFAULT_MODES)
        self.state_store = JsonStore(state_path, {"active": []})
        self._lock = threading.RLock()
        self._active: set[str] = set(self.state_store.load().get("active", []))
        self._last_monitor: dict[str, float] = {}
        self._last_trigger: dict[str, float] = {}
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="JarvisModeMonitor")
        self._thread.start()

    def list(self) -> list[dict[str, Any]]:
        active = set(self._active)
        items = copy.deepcopy(self.store.load().get("modes", []))
        for item in items:
            item["active"] = item.get("id") in active
        return items

    def get(self, name: str) -> dict[str, Any] | None:
        needle = self._norm(name)
        for mode in self.store.load().get("modes", []):
            candidates = [mode.get("id", ""), mode.get("name", ""), *(mode.get("aliases") or [])]
            if needle in {self._norm(x) for x in candidates}:
                return copy.deepcopy(mode)
        return None

    def save(self, mode: dict[str, Any]) -> dict[str, Any]:
        if not mode.get("id"):
            mode["id"] = self._slug(mode.get("name", "modo"))
        mode.setdefault("name", mode["id"])
        mode.setdefault("aliases", [])
        mode.setdefault("monitors", [])
        data = self.store.load()
        items = data.setdefault("modes", [])
        for index, existing in enumerate(items):
            if existing.get("id") == mode["id"]:
                items[index] = copy.deepcopy(mode)
                break
        else:
            items.append(copy.deepcopy(mode))
        self.store.save(data)
        return mode

    def start(self, name: str) -> ActionResult:
        mode = self.get(name)
        if not mode:
            return ActionResult.failure(f"No encontré el modo '{name}'.", error="mode_not_found")
        mode_id = mode["id"]
        with self._lock:
            if mode_id in self._active:
                return ActionResult.success(f"{mode['name']} ya está activo.", mode=mode)

        group = mode.get("exclusive_group")
        if group:
            for other in self.list():
                if other.get("active") and other.get("exclusive_group") == group and other.get("id") != mode_id:
                    self.stop(other["id"])

        routine_id = mode.get("enter_routine")
        if routine_id:
            result = self.routines.run(routine_id)
            if not result.ok:
                return ActionResult.failure(
                    f"No pude activar {mode['name']}: {result.message}",
                    error=result.error,
                    routine=result.to_dict(),
                )
        with self._lock:
            self._active.add(mode_id)
            self._persist()
        self.event_bus.publish("mode.started", {"mode": mode}, "mode_manager")
        return ActionResult.success(f"{mode['name']} activado.", mode=mode)

    def stop(self, name: str) -> ActionResult:
        mode = self.get(name)
        if not mode:
            return ActionResult.failure(f"No encontré el modo '{name}'.", error="mode_not_found")
        mode_id = mode["id"]
        with self._lock:
            if mode_id not in self._active:
                return ActionResult.success(f"{mode['name']} ya está inactivo.", mode=mode)
        routine_id = mode.get("exit_routine")
        warning = ""
        if routine_id:
            result = self.routines.run(routine_id)
            if not result.ok:
                warning = result.message
        with self._lock:
            self._active.discard(mode_id)
            self._persist()
        self.event_bus.publish("mode.stopped", {"mode": mode, "warning": warning}, "mode_manager")
        result = ActionResult.success(f"{mode['name']} desactivado.", mode=mode)
        if warning:
            result.warnings.append(warning)
        return result

    def status(self, name: str = "") -> ActionResult:
        if name:
            mode = self.get(name)
            if not mode:
                return ActionResult.failure(f"No encontré el modo '{name}'.")
            mode["active"] = mode["id"] in self._active
            return ActionResult.success(
                f"{mode['name']} está {'activo' if mode['active'] else 'inactivo'}.", mode=mode
            )
        active = [m for m in self.list() if m.get("active")]
        names = ", ".join(m["name"] for m in active) or "ninguno"
        return ActionResult.success(f"Modos activos: {names}.", active=active)

    def _monitor_loop(self) -> None:
        while self._running:
            now = time.monotonic()
            active_modes = [m for m in self.list() if m.get("active")]
            for mode in active_modes:
                for monitor in mode.get("monitors", []):
                    key = f"{mode['id']}:{monitor.get('id', id(monitor))}"
                    interval = max(1.0, float(monitor.get("interval", 10)))
                    if now - self._last_monitor.get(key, 0) < interval:
                        continue
                    self._last_monitor[key] = now
                    try:
                        result = self.registry.execute(str(monitor.get("capability")), monitor.get("params", {}))
                        field = monitor.get("field")
                        actual: Any = result.data.get(field) if field else result.ok
                        op = self.OPS.get(str(monitor.get("operator", "==")))
                        if not op:
                            continue
                        if op(actual, monitor.get("value")):
                            cooldown = float(monitor.get("cooldown", 60))
                            if now - self._last_trigger.get(key, 0) >= cooldown:
                                self._last_trigger[key] = now
                                self.registry.execute(str(monitor.get("action")), monitor.get("action_params", monitor.get("params", {})), confirmed=True)
                                self.event_bus.publish("mode.monitor_triggered", {"mode": mode["id"], "monitor": monitor, "actual": actual}, "mode_manager")
                    except Exception:
                        pass
            time.sleep(1.0)

    def shutdown(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _persist(self) -> None:
        self.state_store.save({"active": sorted(self._active)})

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _slug(value: str) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
        return "_".join(part for part in raw.split("_") if part) or "modo"
