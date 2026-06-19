from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from prp.core.config import ConfigStore
from prp.core.models import ActionResult

class TaskService:
    def __init__(self, config: ConfigStore): self.config=config
    def add(self, title: str, due: str = "", notes: str = "") -> ActionResult:
        data=self.config.load("tasks.json",{"tasks":[]}) or {"tasks":[]}
        item={"id":uuid4().hex[:8],"title":title.strip(),"due":due.strip(),"notes":notes.strip(),"done":False,"created":datetime.now().isoformat(timespec="seconds")}
        if not item["title"]: return ActionResult.failure("La tarea necesita título")
        data.setdefault("tasks",[]).append(item); self.config.save("tasks.json",data)
        return ActionResult.success(f"Tarea creada: {item['title']}",task=item)
    def list(self, include_done: bool=False) -> ActionResult:
        tasks=(self.config.load("tasks.json",{}) or {}).get("tasks",[])
        visible=tasks if include_done else [t for t in tasks if not t.get("done")]
        return ActionResult.success(f"Tienes {len(visible)} tareas pendientes",tasks=visible)
    def complete(self, task_id: str) -> ActionResult:
        data=self.config.load("tasks.json",{"tasks":[]}) or {"tasks":[]}
        item=next((t for t in data.get("tasks",[]) if t.get("id")==task_id),None)
        if not item: return ActionResult.failure("Tarea no encontrada")
        item["done"]=True; self.config.save("tasks.json",data)
        return ActionResult.success(f"Tarea completada: {item.get('title')}")
