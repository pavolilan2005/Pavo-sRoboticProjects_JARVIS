from __future__ import annotations

import fnmatch
import queue
import threading
from collections import deque
from typing import Callable

from .models import Event


class EventBus:
    """Small in-process event bus with wildcard subscriptions and history."""

    def __init__(self, history_size: int = 500):
        self._subs: list[tuple[str, Callable[[Event], None]]] = []
        self._history: deque[Event] = deque(maxlen=history_size)
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=2000)
        self._lock = threading.RLock()
        self._running = True
        self._worker = threading.Thread(target=self._loop, daemon=True, name="JarvisEventBus")
        self._worker.start()

    def subscribe(self, pattern: str, callback: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            item = (pattern, callback)
            self._subs.append(item)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(item)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, topic: str, payload: dict | None = None, source: str = "jarvis") -> Event:
        event = Event(topic=topic, payload=dict(payload or {}), source=source)
        with self._lock:
            self._history.append(event)
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except Exception:
                pass
        return event

    def history(self, topic: str = "*", limit: int = 50) -> list[dict]:
        with self._lock:
            items = [e for e in self._history if fnmatch.fnmatch(e.topic, topic)]
        return [e.to_dict() for e in items[-max(1, limit):]]

    def stop(self) -> None:
        self._running = False
        self.publish("system.event_bus.stop", {})

    def _loop(self) -> None:
        while self._running:
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                subscribers = list(self._subs)
            for pattern, callback in subscribers:
                if fnmatch.fnmatch(event.topic, pattern):
                    try:
                        callback(event)
                    except Exception:
                        # A subscriber must never take down the bus.
                        pass
