from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from typing import Any,Callable

@dataclass(slots=True)
class Event:
    topic:str
    payload:dict[str,Any]=field(default_factory=dict)
    time:str=field(default_factory=lambda:datetime.now().strftime('%H:%M:%S'))

class EventBus:
    def __init__(self): self._subs=[]; self._history=[]
    def subscribe(self,callback:Callable[[Event],None]): self._subs.append(callback)
    def publish(self,topic:str,**payload):
        e=Event(topic,payload); self._history.append(e); self._history=self._history[-1000:]
        for cb in list(self._subs):
            try: cb(e)
            except Exception: pass
        return e
    def history(self): return list(self._history)
