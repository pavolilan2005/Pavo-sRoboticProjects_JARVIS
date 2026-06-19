from __future__ import annotations
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

@dataclass(slots=True)
class Event:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

Subscriber = Callable[[Event], Awaitable[None] | None]

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._history: list[Event] = []

    def subscribe(self, topic: str, callback: Subscriber) -> None:
        self._subscribers[topic].append(callback)

    async def publish(self, topic: str, **payload: Any) -> Event:
        event = Event(topic, payload)
        self._history.append(event)
        self._history = self._history[-500:]
        callbacks = self._subscribers.get(topic, []) + self._subscribers.get("*", [])
        for callback in callbacks:
            try:
                value = callback(event)
                if asyncio.iscoroutine(value):
                    await value
            except Exception:
                continue
        return event

    def history(self, limit: int = 100) -> list[Event]:
        return self._history[-limit:]
