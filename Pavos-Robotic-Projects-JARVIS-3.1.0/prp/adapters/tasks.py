from __future__ import annotations

import time
import uuid
from typing import Any

from prp.core.models import ActionResult
from prp.core.storage import JsonStore


DEFAULT_TASKS = {"version": 1, "tasks": []}


class TasksAdapter:
    def __init__(self, registry, event_bus, base_dir):
        self.registry = registry
        self.event_bus = event_bus
        self.store = JsonStore(base_dir / "config" / "tasks.json", DEFAULT_TASKS)

    def register(self) -> None:
        r = self.registry.register_handler
        r("tasks.create", "Crea una tarea local.", self.create, tags=("tasks",))
        r("tasks.list", "Lista tareas locales.", self.list_capability, tags=("tasks",))
        r("tasks.complete", "Marca una tarea como completada.", self.complete, tags=("tasks",))
        r("tasks.delete", "Elimina una tarea local.", self.delete, tags=("tasks",))

    def list(self) -> list[dict[str, Any]]:
        return list(self.store.load().get("tasks", []))

    def create(self, params: dict[str, Any]) -> ActionResult:
        title = str(params.get("title") or params.get("task") or "").strip()
        if not title:
            return ActionResult.failure("La tarea necesita un título.")
        task = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "notes": str(params.get("notes", "")),
            "due": str(params.get("due", "")),
            "priority": str(params.get("priority", "normal")),
            "completed": False,
            "created_at": time.time(),
        }
        data = self.store.load()
        data.setdefault("tasks", []).append(task)
        self.store.save(data)
        self.event_bus.publish("tasks.created", {"task": task}, "tasks")
        return ActionResult.success(f"Tarea creada: {title}.", task=task)

    def list_capability(self, params: dict[str, Any]) -> ActionResult:
        include_completed = bool(params.get("include_completed", False))
        tasks = [t for t in self.list() if include_completed or not t.get("completed")]
        return ActionResult.success(f"Hay {len(tasks)} tareas.", tasks=tasks)

    def complete(self, params: dict[str, Any]) -> ActionResult:
        task_id = str(params.get("id", "")).strip()
        title = str(params.get("title", "")).strip().lower()
        data = self.store.load()
        for task in data.get("tasks", []):
            if task.get("id") == task_id or (title and title in str(task.get("title", "")).lower()):
                task["completed"] = True
                task["completed_at"] = time.time()
                self.store.save(data)
                self.event_bus.publish("tasks.completed", {"task": task}, "tasks")
                return ActionResult.success(f"Tarea completada: {task.get('title')}.", task=task)
        return ActionResult.failure("No encontré esa tarea.")

    def delete(self, params: dict[str, Any]) -> ActionResult:
        task_id = str(params.get("id", "")).strip()
        data = self.store.load()
        before = len(data.get("tasks", []))
        data["tasks"] = [t for t in data.get("tasks", []) if t.get("id") != task_id]
        if len(data["tasks"]) == before:
            return ActionResult.failure("No encontré esa tarea.")
        self.store.save(data)
        self.event_bus.publish("tasks.deleted", {"id": task_id}, "tasks")
        return ActionResult.success("Tarea eliminada.")
