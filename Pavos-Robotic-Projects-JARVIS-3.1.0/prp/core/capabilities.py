from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any,Callable

@dataclass(slots=True)
class Result:
    ok:bool
    message:str
    data:dict[str,Any]|None=None

class CapabilityRegistry:
    def __init__(self): self._items:dict[str,tuple[Callable,str]]={}
    def register(self,name:str,handler:Callable,description:str=''):
        if name in self._items: raise ValueError(f'Capacidad duplicada: {name}')
        self._items[name]=(handler,description)
    async def execute(self,name:str,args:dict|None=None)->Result:
        if name not in self._items: return Result(False,f'Capacidad desconocida: {name}')
        fn,_=self._items[name]
        try:
            out=fn(**(args or {}))
            if asyncio.iscoroutine(out): out=await out
            if isinstance(out,Result): return out
            return Result(True,str(out) if out is not None else 'Completado')
        except Exception as e: return Result(False,f'{type(e).__name__}: {e}')
    def declarations(self):
        return [{'name':n,'description':d or n,'parameters':{'type':'OBJECT','properties':{}}} for n,(_,d) in self._items.items()]
    def names(self): return sorted(self._items)
