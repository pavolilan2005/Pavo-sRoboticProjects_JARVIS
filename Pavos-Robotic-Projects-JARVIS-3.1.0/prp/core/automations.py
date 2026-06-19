from __future__ import annotations

import copy
import fnmatch
import threading
import time
from typing import Any

from .capabilities import CapabilityRegistry
from .event_bus import EventBus
from .routines import RoutineEngine
from .modes import ModeManager
from .storage import JsonStore


DEFAULT_AUTOMATIONS = {
    "version": 1,
    "automations": [
        {
            "id": "avisar_esp32_offline",
            "name": "Avisar cuando un nodo ESP32 se desconecta",
            "enabled": True,
            "trigger": {"type": "event", "topic": "esp32.node.offline"},
            "conditions": [],
            "actions": [
                {
                    "capability": "notifications.emit",
                    "params": {
                        "title": "ESP32 desconectada",
                        "message": "Un nodo domótico perdió la conexión.",
                        "priority": "high",
                    },
                }
            ],
            "cooldown": 30,
        }
    ],
}


class AutomationEngine:
    """Event and interval automation engine.

    Rules live in config/automations.json and can launch capabilities, routines,
    or modes without embedding behavior in Python.
    """

    OPS = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "contains": lambda a, b: b in a,
        "exists": lambda a, _b: a is not None,
    }

    def __init__(self, registry: CapabilityRegistry, routines: RoutineEngine, modes: ModeManager, event_bus: EventBus, path):
        self.registry = registry
        self.routines = routines
        self.modes = modes
        self.event_bus = event_bus
        self.store = JsonStore(path, DEFAULT_AUTOMATIONS)
        self._last_run: dict[str, float] = {}
        self._interval_last: dict[str, float] = {}
        self._lock = threading.RLock()
        self._running = True
        self._unsubscribe = event_bus.subscribe("*", self._on_event)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="JarvisAutomations")
        self._thread.start()

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.store.load().get("automations", []))

    def save(self, rule: dict[str, Any]) -> dict[str, Any]:
        rule = dict(rule)
        if not rule.get("id"):
            rule["id"] = self._slug(rule.get("name", "automation"))
        rule.setdefault("name", rule["id"])
        rule.setdefault("enabled", True)
        rule.setdefault("conditions", [])
        rule.setdefault("actions", [])
        rule.setdefault("cooldown", 0)
        data = self.store.load()
        items = data.setdefault("automations", [])
        for i, existing in enumerate(items):
            if existing.get("id") == rule["id"]:
                items[i] = rule
                break
        else:
            items.append(rule)
        self.store.save(data)
        return rule

    def delete(self, rule_id: str) -> bool:
        data = self.store.load()
        before = len(data.get("automations", []))
        data["automations"] = [r for r in data.get("automations", []) if r.get("id") != rule_id]
        self.store.save(data)
        return len(data["automations"]) < before

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        data = self.store.load()
        found = False
        for rule in data.get("automations", []):
            if rule.get("id") == rule_id:
                rule["enabled"] = bool(enabled)
                found = True
        if found:
            self.store.save(data)
        return found

    def test(self, rule_id: str) -> dict[str, Any]:
        rule = next((r for r in self.list() if r.get("id") == rule_id), None)
        if not rule:
            return {"ok": False, "message": "Automatización no encontrada."}
        return self._execute_rule(rule, {"test": True}, force=True)

    def _on_event(self, event) -> None:
        # Do not let automation-generated bookkeeping trigger itself forever.
        if event.topic.startswith("automation."):
            return
        for rule in self.list():
            trigger = rule.get("trigger") or {}
            if not rule.get("enabled", True) or trigger.get("type") != "event":
                continue
            if fnmatch.fnmatch(event.topic, str(trigger.get("topic", ""))):
                threading.Thread(
                    target=self._execute_rule,
                    args=(rule, {"event": event.to_dict()}),
                    daemon=True,
                    name=f"Automation-{rule.get('id')}",
                ).start()

    def _loop(self) -> None:
        while self._running:
            now = time.monotonic()
            for rule in self.list():
                trigger = rule.get("trigger") or {}
                if not rule.get("enabled", True) or trigger.get("type") != "interval":
                    continue
                interval = max(1.0, float(trigger.get("seconds", 60)))
                rule_id = str(rule.get("id"))
                if now - self._interval_last.get(rule_id, 0) >= interval:
                    self._interval_last[rule_id] = now
                    threading.Thread(
                        target=self._execute_rule,
                        args=(rule, {"interval": interval}),
                        daemon=True,
                        name=f"Automation-{rule_id}",
                    ).start()
            time.sleep(1.0)

    def _execute_rule(self, rule: dict[str, Any], context: dict[str, Any], force: bool = False) -> dict[str, Any]:
        rule_id = str(rule.get("id"))
        now = time.monotonic()
        cooldown = max(0.0, float(rule.get("cooldown", 0)))
        with self._lock:
            if not force and now - self._last_run.get(rule_id, -10**9) < cooldown:
                return {"ok": False, "message": "cooldown"}
            if not self._conditions(rule.get("conditions", []), context):
                return {"ok": False, "message": "conditions_not_met"}
            self._last_run[rule_id] = now

        self.event_bus.publish("automation.started", {"rule": rule, "context": context}, "automation_engine")
        results = []
        ok = True
        for action in rule.get("actions", []):
            if "capability" in action:
                result = self.registry.execute(
                    str(action.get("capability")),
                    self._render(action.get("params", {}), context),
                    confirmed=bool(action.get("confirmed", False)),
                )
                item = result.to_dict()
                ok = ok and (result.ok or not action.get("critical", False))
            elif "routine" in action:
                result = self.routines.run(str(action.get("routine")), self._render(action.get("variables", {}), context), asynchronous=bool(action.get("asynchronous", False)))
                item = result.to_dict()
                ok = ok and result.ok
            elif "mode" in action:
                operation = str(action.get("operation", "start"))
                result = self.modes.start(str(action.get("mode"))) if operation == "start" else self.modes.stop(str(action.get("mode")))
                item = result.to_dict()
                ok = ok and result.ok
            else:
                item = {"ok": False, "message": "Acción inválida"}
                ok = False
            results.append(item)
            if not ok and action.get("critical", False):
                break
        payload = {"rule_id": rule_id, "ok": ok, "results": results}
        self.event_bus.publish("automation.finished", payload, "automation_engine")
        return payload

    def shutdown(self) -> None:
        self._running = False
        try:
            self._unsubscribe()
        except Exception:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _conditions(self, conditions: list[dict[str, Any]], context: dict[str, Any]) -> bool:
        for condition in conditions:
            actual = self._lookup(context, str(condition.get("path", "")))
            op = self.OPS.get(str(condition.get("operator", "==")))
            if not op:
                return False
            try:
                if not op(actual, condition.get("value")):
                    return False
            except Exception:
                return False
        return True

    @classmethod
    def _render(cls, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {k: cls._render(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._render(v, context) for v in value]
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return cls._lookup(context, value[2:-1])
        return value

    @staticmethod
    def _lookup(data: Any, path: str) -> Any:
        current = data
        if not path:
            return current
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _slug(value: str) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
        return "_".join(part for part in raw.split("_") if part) or "automation"
