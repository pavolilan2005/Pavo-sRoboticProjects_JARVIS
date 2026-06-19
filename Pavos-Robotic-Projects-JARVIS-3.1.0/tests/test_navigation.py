from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prp_core.adapters.navigation import NavigationAdapter
from prp_core.capabilities import CapabilityRegistry
from prp_core.event_bus import EventBus


class FakeUI:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
        return call


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)
        self.ui = FakeUI()
        self.adapter = NavigationAdapter(self.registry, self.bus, self.base, self.ui)
        self.adapter.register()

    def tearDown(self):
        self.adapter.shutdown()
        self.bus.stop()
        self.temp.cleanup()

    def test_map_capabilities_are_registered(self):
        names = {item["name"] for item in self.registry.list(tag="map")}
        self.assertIn("map.open", names)
        self.assertIn("map.search", names)
        self.assertIn("map.fly_to", names)

    def test_search_formats_results_and_opens_ui(self):
        self.adapter._throttled_get = lambda *_args, **_kwargs: [{
            "name": "Pirámides de Giza",
            "display_name": "Pirámides de Giza, Guiza, Egipto",
            "lat": "29.9792",
            "lon": "31.1342",
            "type": "attraction",
            "category": "tourism",
            "importance": 0.9,
            "address": {"country": "Egipto"},
        }]
        result = self.registry.execute("map.search", {"query": "pirámides de Giza"})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["location"]["name"], "Pirámides de Giza")
        called = [name for name, _args in self.ui.calls]
        self.assertIn("open_map", called)
        self.assertIn("map_show_results", called)

    def test_set_home_and_home_navigation(self):
        saved = self.registry.execute("map.set_home", {"lat": 22.77, "lon": -102.58, "name": "Base"})
        self.assertTrue(saved.ok)
        home = self.registry.execute("map.home", {})
        self.assertTrue(home.ok)
        called = [name for name, _args in self.ui.calls]
        self.assertIn("map_fly_to", called)


if __name__ == "__main__":
    unittest.main()
