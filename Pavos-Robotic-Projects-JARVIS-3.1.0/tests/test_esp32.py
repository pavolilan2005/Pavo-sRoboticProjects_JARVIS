from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prp.adapters import esp32 as esp32_module
from prp.adapters.esp32 import ESP32Adapter
from prp.core.capabilities import CapabilityRegistry
from prp.core.event_bus import EventBus


class FakeSerialPort:
    def __init__(self, port, baudrate, timeout=0.1, write_timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.is_open = True
        self.in_waiting = 0
        self._queue = []
        self.devices = {}

    def close(self):
        self.is_open = False

    def flush(self):
        pass

    def write(self, raw):
        request = json.loads(raw.decode("utf-8"))
        op = request.get("op")
        response = {"reply_to": request.get("id"), "ok": True}
        if op == "hello":
            response.update(protocol="prp-node-v1", firmware="test", device_count=len(self.devices))
        elif op == "configure":
            self.devices = {item["id"]: {**item, "value": int(bool(item.get("default_state", 0)))} for item in request.get("devices", [])}
            response["configured"] = len(self.devices)
        elif op == "set":
            self.devices[request["device"]]["value"] = request.get("value", 0)
            response.update(device=request["device"], value=self.devices[request["device"]]["value"])
        elif op == "get":
            response.update(device=request["device"], value=self.devices[request["device"]]["value"])
        elif op == "toggle":
            dev = self.devices[request["device"]]
            dev["value"] = 0 if dev["value"] else 1
            response.update(device=request["device"], value=dev["value"])
        else:
            response = {"reply_to": request.get("id"), "ok": False, "error": "bad op"}
        self._queue.append((json.dumps(response) + "\n").encode("utf-8"))
        self.in_waiting = sum(len(x) for x in self._queue)
        return len(raw)

    def readline(self):
        if not self._queue:
            self.in_waiting = 0
            return b""
        value = self._queue.pop(0)
        self.in_waiting = sum(len(x) for x in self._queue)
        return value


class FakeSerialModule:
    Serial = FakeSerialPort


class ESP32Tests(unittest.TestCase):
    def test_connect_auto_sync_and_light_control(self):
        original_serial = esp32_module.serial
        esp32_module.serial = FakeSerialModule
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "config").mkdir()
                bus = EventBus()
                registry = CapabilityRegistry(bus)
                adapter = ESP32Adapter(registry, bus, root)
                adapter.save_node({"id": "esp32_principal", "name": "ESP", "port": "COM9", "baudrate": 115200})
                adapter.save_device({
                    "id": "foco", "name": "Foco", "aliases": ["luz"], "node": "esp32_principal",
                    "pin": 23, "type": "digital_output", "active_low": False,
                    "default_state": 0, "capabilities": ["on", "off", "toggle", "status"],
                })
                connected = adapter.connect("esp32_principal", auto_sync=True)
                self.assertTrue(connected.ok, connected.message)
                on = adapter.control({"device": "luz", "action": "prender"})
                self.assertTrue(on.ok, on.message)
                self.assertEqual(on.data["state"], 1)
                off = adapter.control({"device": "foco", "action": "off"})
                self.assertTrue(off.ok, off.message)
                self.assertEqual(off.data["state"], 0)
                adapter.shutdown()
                bus.stop()
        finally:
            esp32_module.serial = original_serial


if __name__ == "__main__":
    unittest.main()
