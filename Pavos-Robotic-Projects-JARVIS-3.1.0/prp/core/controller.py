from __future__ import annotations
from pathlib import Path
from .config import ConfigStore
from .events import EventBus
from .capabilities import CapabilityRegistry,Result
from .routines import RoutineEngine
from prp.services.audio import AudioService
from prp.services.serial_service import SerialService
from prp.services.pc import PCService
from prp.services.spotify_service import SpotifyService
from prp.services.obs_service import OBSService
from prp.services.task_service import TaskService
class Controller:
    def __init__(self,root:Path):
        self.root=root; self.config=ConfigStore(root); self.events=EventBus(); self.registry=CapabilityRegistry()
        app=self.config.load('app.json',{}) or {}; self.audio=AudioService(app.get('audio',{}),self.events); self.serial=SerialService(self.config,self.events)
        self.pc=PCService(); self.spotify=SpotifyService(self.config); self.obs=OBSService(self.config); self.tasks=TaskService(self.config)
        self.routines=RoutineEngine(self.config,self.registry,self.events); self._register()
    def _register(self):
        self.registry.register('pc.open_app',self.pc.open_app,'Abre una aplicación. Parámetro name.')
        self.registry.register('pc.open_url',self.pc.open_url,'Abre una URL. Parámetro url.')
        self.registry.register('spotify.play',self.spotify.play,'Reproduce música. Parámetros query y target_type.')
        self.registry.register('spotify.play_alias',self.spotify.play_alias,'Reproduce un alias. Parámetro alias.')
        self.registry.register('spotify.pause',self.spotify.pause,'Pausa Spotify.')
        self.registry.register('spotify.resume',self.spotify.resume,'Reanuda Spotify.')
        self.registry.register('spotify.next',self.spotify.next,'Siguiente canción.')
        self.registry.register('obs.status',self.obs.status,'Comprueba OBS.')
        self.registry.register('obs.set_scene',self.obs.set_scene,'Cambia escena. Parámetro scene.')
        self.registry.register('routine.run',lambda routine_id:self.routines.run(routine_id),'Ejecuta rutina. Parámetro routine_id.')
        self.registry.register('home.set',self.home_set,'Controla dispositivo. Parámetros device y state.')
        self.registry.register('node.sync',self.node_sync,'Sincroniza la configuración de dispositivos con una ESP32.')
        self.registry.register('task.add',self.tasks.add,'Crea una tarea. Parámetros title y notes.')
        self.registry.register('task.complete',self.tasks.complete,'Completa una tarea. Parámetro task_id.')
    async def node_sync(self,node_id):
        devices=[d for d in (self.config.load('devices.json',{}) or {}).get('devices',[]) if d.get('node_id')==node_id]
        out=self.serial.request(node_id,{'cmd':'configure','devices':devices},timeout=3.0)
        return Result(bool(out.get('ok',True)),out.get('message','Nodo sincronizado'),out)
    async def home_set(self,device,state):
        devices=(self.config.load('devices.json',{}) or {}).get('devices',[]); key=device.lower().strip()
        d=next((x for x in devices if key in {str(x.get('id','')).lower(),str(x.get('name','')).lower(),*[str(a).lower() for a in x.get('aliases',[])]}),None)
        if not d:return Result(False,f'Dispositivo no encontrado: {device}')
        out=self.serial.request(d['node_id'],{'cmd':'set','device':d['id'],'state':state}); return Result(bool(out.get('ok',True)),out.get('message','Comando enviado'),out)
    async def execute(self,name,args=None):
        result=await self.registry.execute(name,args); self.events.publish('capability.result',name=name,ok=result.ok,message=result.message); return result
    def save_audio_settings(self,settings):
        app=self.config.load('app.json',{}) or {}; app['audio']=settings; self.config.save('app.json',app); self.audio.settings=settings
    def close(self): self.audio.stop(); self.serial.close()
