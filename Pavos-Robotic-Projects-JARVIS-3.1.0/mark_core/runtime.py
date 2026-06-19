from __future__ import annotations

import threading

_lock = threading.RLock()
_platform = None


def set_platform(platform) -> None:
    global _platform
    with _lock:
        _platform = platform


def get_platform():
    with _lock:
        if _platform is None:
            raise RuntimeError("El núcleo NEXUS todavía no está inicializado.")
        return _platform
