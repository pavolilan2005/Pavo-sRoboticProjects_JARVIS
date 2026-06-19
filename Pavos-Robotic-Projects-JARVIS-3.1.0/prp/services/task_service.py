from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from prp.core.capabilities import Result
class TaskService:
    def __init__(self,config): self.config=config
    def list(self): return (self.config.load("tasks.json",{}) or {}).get("tasks",[])
    def add(self,title,notes=""):
        data=self.list(); item={"id":uuid4().hex[:10],"title":title,"notes":notes,"done":False,"created":datetime.now().isoformat(timespec="seconds")}; data.append(item); self.config.save("tasks.json",{"tasks":data}); return Result(True,f"Tarea creada: {title}",item)
    def complete(self,task_id):
        data=self.list(); found=False
        for item in data:
            if item.get("id")==task_id: item["done"]=True; found=True
        self.config.save("tasks.json",{"tasks":data}); return Result(found,"Tarea completada" if found else "Tarea no encontrada")
