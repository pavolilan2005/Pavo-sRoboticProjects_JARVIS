from __future__ import annotations

import unittest

from prp.core.text import normalize_voice_text


class WakeTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_voice_text("¡JÁRVIS, prende la luz!"), "jarvis prende la luz")


if __name__ == "__main__":
    unittest.main()
