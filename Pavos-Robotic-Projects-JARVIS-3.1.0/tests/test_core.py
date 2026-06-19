from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prp.core.capabilities import CapabilityRegistry
from prp.core.event_bus import EventBus
from prp.core.media_intelligence import MediaIntelligence
from prp.core.models import ActionResult


class FakeSpotify:
    def __init__(self):
        self.last = None

    def user_playlists(self, limit=100, refresh=False):
        return [{"type": "playlist", "name": "Stream Pavo", "uri": "spotify:playlist:1", "id": "1", "owner": "Pavo"}]

    def search_candidates(self, kind, query, artist="", limit=8):
        return []

    def play_candidate(self, candidate, params):
        self.last = dict(candidate)
        return ActionResult.success("ok", **candidate)

    def resume(self, params):
        return ActionResult.success("resume")

    def set_volume(self, params):
        return ActionResult.success("volume", volume=params.get("volume"))

    def play_another_by_artist(self, params):
        return ActionResult.success("another", artist=params.get("artist"))


class MediaTests(unittest.TestCase):
    def test_alias_is_resolved_without_public_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            bus = EventBus()
            spotify = FakeSpotify()
            intelligence = MediaIntelligence(root, spotify, bus)
            intelligence.replace_aliases([{
                "id": "stream", "phrases": ["la del stream"], "type": "playlist",
                "target": "Stream Pavo", "uri": "spotify:playlist:1", "volume": 22,
                "device": "", "enabled": True,
            }])
            result = intelligence.smart_play({"alias": "stream", "target_type": "alias"})
            self.assertTrue(result.ok, result.message)
            self.assertEqual(spotify.last["uri"], "spotify:playlist:1")
            bus.stop()


if __name__ == "__main__":
    unittest.main()
