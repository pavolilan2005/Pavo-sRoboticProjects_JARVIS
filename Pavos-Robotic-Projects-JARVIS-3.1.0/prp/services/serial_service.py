from __future__ import annotations
import json,threading,time
import serial
from serial.tools import list_ports

class SerialService:
    """Único propietario de todos los puertos seriales del proyecto."""
    def __init__(self,config,events): self.config=config; self.events=events; self._links={}; self._lock=threading.RLock()
    def ports(self): return [{'port':p.device,'description':p.description} for p in list_ports.comports()]
    def _nodes(self): return (self.config.load('nodes.json',{}) or {}).get('nodes',[])
    def node(self,node_id): return next((n for n in self._nodes() if n.get('id')==node_id),None)
    def connect(self,node_id):
        node=self.node(node_id)
        if not node: raise ValueError('Nodo no encontrado')
        with self._lock:
            old=self._links.pop(node_id,None)
            if old:
                try:old.close()
                except:pass
            link=serial.Serial(node['port'],int(node.get('baudrate',115200)),timeout=.5,write_timeout=.5)
            time.sleep(1.2); link.reset_input_buffer(); self._links[node_id]=link
        self.events.publish('serial.connected',node_id=node_id,port=node['port']); return True
    def request(self,node_id,payload:dict,timeout=1.5):
        with self._lock:
            link=self._links.get(node_id)
            if not link or not link.is_open:self.connect(node_id); link=self._links[node_id]
            PLACEHOLDER
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                line=link.readline().decode('utf-8',errors='replace').strip()
                if line:
                    try:return json.loads(line)
                    except:return {'ok':True,'raw':line}
            raise TimeoutError('La ESP32 no respondió')
    def close(self):
        for link in list(self._links.values()):
            try:link.close()
            except:pass
        self._links.clear()
