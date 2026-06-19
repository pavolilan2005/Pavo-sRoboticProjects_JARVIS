from __future__ import annotations
import asyncio
from .capabilities import Result
class RoutineEngine:
    def __init__(self,config,registry,events): self.config=config; self.registry=registry; self.events=events
    def definitions(self): return (self.config.load('routines.json',{}) or {}).get('routines',[])
    def find(self,key):
        n=key.strip().lower()
        for r in self.definitions():
            vals={str(r.get('id','')).lower(),str(r.get('name','')).lower(),*[str(x).lower() for x in r.get('aliases',[])]}
            if n in vals:return r
    async def run(self,key):
        r=self.find(key)
        if not r:return Result(False,f'Rutina no encontrada: {key}')
        self.events.publish('routine.started',name=r.get('name'))
        for step in r.get('steps',[]):
            result=await self._step(step)
            if not result.ok and not step.get('optional',False):
                self.events.publish('routine.failed',message=result.message); return result
        self.events.publish('routine.completed',name=r.get('name'))
        return Result(True,f'Rutina completada: {r.get("name")}')
    async def _step(self,step):
        if 'parallel' in step:
            rs=await asyncio.gather(*(self._step(s) for s in step['parallel']))
            return next((x for x in rs if not x.ok),Result(True,'Bloque paralelo completado'))
        if 'wait' in step:
            await asyncio.sleep(float(step['wait'])); return Result(True,'Espera completada')
        return await self.registry.execute(step.get('capability',''),step.get('args',{}))
