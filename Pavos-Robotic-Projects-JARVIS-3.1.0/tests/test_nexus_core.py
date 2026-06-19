from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from mark_core.capabilities import CapabilityRegistry
from mark_core.event_bus import EventBus
from mark_core.models import ActionResult
from mark_core.routines import RoutineEngine
from mark_core.modes import ModeManager
from mark_core.automations import AutomationEngine
from mark_core.adapters.esp32 import ESP32Adapter


class NexusCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)
        self.values = []
        self.registry.register_handler(
            "test.append",
            "append",
            lambda p: self._append(p),
        )
        self.registry.register_handler(
            "test.value",
            "value",
            lambda p: ActionResult.success("value", result=p.get("value"), value=p.get("value")),
        )
        self.routines = RoutineEngine(self.registry, self.bus, self.base / "routines.json")
        self.modes = ModeManager(
            self.routines,
            self.registry,
            self.bus,
            self.base / "modes.json",
            self.base / "state.json",
        )

    def tearDown(self):
        self.bus.stop()
        self.temp.cleanup()

    def _append(self, params):
        self.values.append(params.get("value"))
        return ActionResult.success("added", value=params.get("value"))

    def test_capability_and_event_bus(self):
        seen = []
        self.bus.subscribe("capability.finished", lambda event: seen.append(event.topic))
        result = self.registry.execute("test.append", {"value": 1})
        self.assertTrue(result.ok)
        time.sleep(0.05)
        self.assertEqual(self.values, [1])
        self.assertIn("capability.finished", seen)

    def test_routine_parallel_wait_and_condition(self):
        routine = {
            "id": "test_routine",
            "name": "Test",
            "steps": [
                {"capability": "test.append", "params": {"value": "a"}},
                {"parallel": [
                    {"capability": "test.append", "params": {"value": "b"}},
                    {"capability": "test.append", "params": {"value": "c"}},
                ]},
                {"wait": 0.01},
                {
                    "if": {"capability": "test.value", "params": {"value": 5}, "field": "value", "operator": ">", "equals": 3},
                    "then": [{"capability": "test.append", "params": {"value": "d"}}],
                },
            ],
        }
        self.routines.save(routine)
        result = self.routines.run("test_routine")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(set(self.values), {"a", "b", "c", "d"})

    def test_mode_entry_and_exit(self):
        self.routines.save({"id": "enter", "name": "Enter", "steps": [{"capability": "test.append", "params": {"value": "on"}}]})
        self.routines.save({"id": "exit", "name": "Exit", "steps": [{"capability": "test.append", "params": {"value": "off"}}]})
        self.modes.save({"id": "demo", "name": "Demo", "enter_routine": "enter", "exit_routine": "exit", "monitors": []})
        self.assertTrue(self.modes.start("demo").ok)
        self.assertTrue(self.modes.status("demo").data["mode"]["active"])
        self.assertTrue(self.modes.stop("demo").ok)
        self.assertEqual(self.values, ["on", "off"])

    def test_automation_from_event(self):
        engine = AutomationEngine(self.registry, self.routines, self.modes, self.bus, self.base / "automations.json")
        engine.save({
            "id": "event_test",
            "name": "Event test",
            "enabled": True,
            "trigger": {"type": "event", "topic": "sensor.test"},
            "conditions": [],
            "actions": [{"capability": "test.append", "params": {"value": "event"}}],
            "cooldown": 0,
        })
        self.bus.publish("sensor.test", {"value": 1})
        deadline = time.time() + 1
        while "event" not in self.values and time.time() < deadline:
            time.sleep(0.02)
        self.assertIn("event", self.values)

    def test_esp32_device_registry_and_legacy_control(self):
        adapter = ESP32Adapter(
            self.registry,
            self.bus,
            self.base,
            legacy_controller=lambda p: f"legacy:{p['device']}:{p['action']}",
        )
        adapter.register()
        adapter.nodes_store.save({"version": 1, "nodes": [{"id": "legacy", "name": "Legacy", "protocol": "legacy", "port": "COM1", "baudrate": 115200}]})
        adapter.devices_store.save({"version": 1, "devices": []})
        saved = adapter.save_device({
            "id": "light", "name": "Light", "aliases": "luz, foco", "node": "legacy",
            "pin": 23, "type": "digital_output", "active_low": False,
            "capabilities": "on, off, toggle, status",
        })
        self.assertEqual(saved["pin"], 23)
        result = adapter.control({"device": "luz", "action": "on"})
        self.assertTrue(result.ok)
        with self.assertRaises(ValueError):
            adapter.save_device({
                "id": "bad", "name": "Bad", "node": "legacy", "pin": 23,
                "type": "digital_output", "capabilities": "on",
            })


if __name__ == "__main__":
    unittest.main()
