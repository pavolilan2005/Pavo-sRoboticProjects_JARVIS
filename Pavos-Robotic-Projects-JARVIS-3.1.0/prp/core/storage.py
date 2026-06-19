from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any


class JsonStore:
    """Thread-safe, atomic JSON storage with automatic backups."""

    def __init__(self, path: str | Path, default: Any):
        self.path = Path(path)
        self.default = default
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Any:
        with self._lock:
            if not self.path.exists():
                self.save(self.default)
                return self._clone(self.default)
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                backup = self.path.with_suffix(self.path.suffix + ".corrupt")
                try:
                    shutil.copy2(self.path, backup)
                except Exception:
                    pass
                self.save(self.default)
                return self._clone(self.default)

    def save(self, value: Any) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            raw = json.dumps(value, ensure_ascii=False, indent=2)
            tmp.write_text(raw, encoding="utf-8")
            os.replace(tmp, self.path)

    def update(self, mutator):
        with self._lock:
            value = self.load()
            result = mutator(value)
            self.save(value if result is None else result)
            return value if result is None else result

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))
