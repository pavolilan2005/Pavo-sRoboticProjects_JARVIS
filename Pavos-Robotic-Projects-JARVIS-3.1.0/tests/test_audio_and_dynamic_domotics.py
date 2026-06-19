from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mark_core.adapters.audio import AudioSettingsAdapter
from mark_core.adapters.esp32 import ESP32Adapter
from mark_core.capabilities import CapabilityRegistry
from mark_core.event_bus import EventBus


class AudioAndDynamicDomoticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)

    def tearDown(self):
        self.bus.stop()
        self.temp.cleanup()

    def test_audio_settings_are_validated_and_callback_runs(self):
        adapter = AudioSettingsAdapter(self.base)
        calls = []
        adapter.bind_runtime(apply_callback=lambda cfg: calls.append(cfg))
        saved = adapter.save({
            "input_device": "4",
            "output_device": "",
            "sensitivity": 150,
            "input_gain": 8,
            "vad_enabled": False,
        })
        self.assertEqual(saved["input_device"], 4)
        self.assertIsNone(saved["output_device"])
        self.assertEqual(saved["sensitivity"], 100)
        self.assertEqual(saved["input_gain"], 4.0)
        self.assertFalse(saved["vad_enabled"])
        self.assertEqual(len(calls), 1)

    def test_arbitrary_device_names_and_rename(self):
        adapter = ESP32Adapter(self.registry, self.bus, self.base)
        adapter.nodes_store.save({
            "version": 1,
            "nodes": [{
                "id": "room",
                "name": "Habitación",
                "protocol": "jarvis-node-v1",
                "port": "COM7",
                "baudrate": 115200,
            }],
        })
        adapter.devices_store.save({"version": 1, "devices": []})
        adapter.scenes_store.save({
            "version": 1,
            "scenes": [{"id": "cool", "name": "Cool", "targets": [{"device": "gpio_2", "action": "on"}]}],
        })

        saved = adapter.save_device({
            "id": "gpio_2",
            "name": "Ventilador",
            "aliases": "abanico, ventilador del cuarto",
            "node": "room",
            "pin": 2,
            "type": "digital_output",
            "active_low": False,
            "capabilities": "on, off, toggle, status",
        })
        self.assertEqual(saved["pin"], 2)
        self.assertEqual(adapter.get_device("prende el ventilador del cuarto")["id"], "gpio_2")
        self.assertEqual(adapter.get_device("el abanico")["name"], "Ventilador")

        renamed = adapter.save_device({**saved, "id": "ventilador_principal"}, previous_id="gpio_2")
        self.assertEqual(renamed["id"], "ventilador_principal")
        self.assertEqual(len(adapter.list_devices()), 1)
        targets = adapter.scenes_store.load()["scenes"][0]["targets"]
        self.assertEqual(targets[0]["device"], "ventilador_principal")
        self.assertIn("Ventilador", adapter.describe_catalog())

    def test_device_list_capability_is_generic(self):
        adapter = ESP32Adapter(self.registry, self.bus, self.base)
        adapter.nodes_store.save({"version": 1, "nodes": [{"id": "n", "name": "N", "protocol": "jarvis-node-v1", "port": "COM1", "baudrate": 115200}]})
        adapter.devices_store.save({"version": 1, "devices": [{
            "id": "bomba",
            "name": "Bomba de agua",
            "aliases": ["bomba"],
            "node": "n",
            "pin": 4,
            "type": "digital_output",
            "active_low": False,
            "default_state": 0,
            "capabilities": ["on", "off", "status"],
        }]})
        result = adapter.list_capability({})
        self.assertTrue(result.ok)
        self.assertIn("Bomba de agua", result.message)


if __name__ == "__main__":
    unittest.main()
