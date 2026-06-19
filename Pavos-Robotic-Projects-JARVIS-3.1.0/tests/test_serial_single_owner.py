from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from prp_core.adapters.esp32 import ESP32Adapter
from prp_core.capabilities import CapabilityRegistry
from prp_core.event_bus import EventBus


class FakeSerialHandle:
    created = 0

    def __init__(self, port, baudrate, timeout=0.15, write_timeout=1.0):
        type(self).created += 1
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.is_open = True
        self._responses: list[bytes] = []
        self.states: dict[str, object] = {}

    def reset_input_buffer(self):
        self._responses.clear()

    def reset_output_buffer(self):
        pass

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def write(self, raw: bytes):
        request = json.loads(raw.decode("utf-8"))
        operation = request.get("op")
        response = {"reply_to": request["id"], "ok": True}
        if operation in {"hello", "ping"}:
            response.update({"message": "pong", "protocol": "jarvis-node-v1"})
        elif operation == "configure":
            response.update({"configured": len(request.get("devices", []))})
        elif operation == "set":
            self.states[request["device"]] = request.get("value")
            response.update({"device": request["device"], "value": request.get("value")})
        elif operation == "get":
            response.update({"device": request["device"], "value": self.states.get(request["device"], 0)})
        elif operation == "toggle":
            value = 0 if self.states.get(request["device"], 0) else 1
            self.states[request["device"]] = value
            response.update({"device": request["device"], "value": value})
        self._responses.append((json.dumps(response) + "\n").encode("utf-8"))
        return len(raw)

    def readline(self):
        return self._responses.pop(0) if self._responses else b""


class SerialOwnershipTests(unittest.TestCase):
    def setUp(self):
        FakeSerialHandle.created = 0
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "config").mkdir()
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)
        self.adapter = ESP32Adapter(self.registry, self.bus, self.base)
        self.adapter.nodes_store.save({
            "version": 1,
            "nodes": [{
                "id": "esp32_principal",
                "name": "ESP32 Principal",
                "protocol": "jarvis-node-v1",
                "port": "COM5",
                "baudrate": 115200,
                "enabled": True,
                "boot_wait": 0,
            }],
        })
        self.adapter.devices_store.save({
            "version": 1,
            "devices": [{
                "id": "foco",
                "name": "Foco",
                "aliases": ["luz"],
                "node": "esp32_principal",
                "pin": 21,
                "type": "digital_output",
                "active_low": False,
                "default_state": 0,
                "capabilities": ["on", "off", "toggle", "status"],
            }],
        })

    def tearDown(self):
        self.adapter.shutdown()
        self.temp.cleanup()

    def test_one_handle_is_reused_for_connect_health_sync_and_control(self):
        fake_serial_module = SimpleNamespace(Serial=FakeSerialHandle)
        with patch("prp_core.adapters.esp32.serial", fake_serial_module):
            first = self.adapter.connect("esp32_principal")
            second = self.adapter.connect("esp32_principal")
            health = self.adapter.health_check("esp32_principal")
            synced = self.adapter.sync_node({"node": "esp32_principal"})
            on = self.adapter.control({"device": "luz", "action": "on"})
            status = self.adapter.control({"device": "foco", "action": "status"})

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertTrue(health.ok)
        self.assertTrue(synced.ok)
        self.assertTrue(on.ok)
        self.assertTrue(status.ok)
        self.assertEqual(status.data["state"], 1)
        self.assertEqual(FakeSerialHandle.created, 1)

    def test_only_adapter_imports_pyserial(self):
        project = Path(__file__).resolve().parents[1]
        owners = []
        for path in project.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            imports_serial = any(
                isinstance(node, ast.Import) and any(alias.name == "serial" for alias in node.names)
                or isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("serial")
                for node in ast.walk(tree)
            )
            if imports_serial:
                owners.append(path.relative_to(project).as_posix())
        self.assertEqual(owners, ["prp_core/adapters/esp32.py"])


if __name__ == "__main__":
    unittest.main()
