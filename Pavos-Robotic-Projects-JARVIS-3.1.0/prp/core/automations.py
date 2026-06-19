from __future__ import annotations
from typing import Any
from .capabilities import CapabilityRegistry
from .config import ConfigStore
from .events import Event, EventBus

class AutomationEngine:
    def __init__(self, config: ConfigStore, registry: CapabilityRegistry, events: EventBus):
        self.config=config; self.registry=registry; self.events=events; events.subscribe("*",self._handle)
    def definitions(self)->list[dict[str,Any]]: return (self.config.load("automations.json",{}) or {}).get("automations",[])
    async def _handle(self,event:Event):
        for rule in self.definitions():
            if not rule.get("enabled",True) or rule.get("event")!=event.topic: continue
            conditions=rule.get("conditions",{})
            if any(event.payload.get(k)!=v for k,v in conditions.items()): continue
            for action in rule.get("actions",[]):
                await self.registry.execute(action.get("capability",""),action.get("args",{}))
