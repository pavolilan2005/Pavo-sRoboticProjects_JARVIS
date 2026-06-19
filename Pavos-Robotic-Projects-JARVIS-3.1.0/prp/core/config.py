from __future__ import annotations
import json
from pathlib import Path
from threading import RLock
from typing import Any

class ConfigStore:
    def __init__(self, root: Path):
        self.root=root
        self.config_dir=root/'config'
        self._lock=RLock()
    def path(self,name:str)->Path: return self.config_dir/name
    def load(self,name:str,default:Any=None)->Any:
        with self._lock:
            p=self.path(name)
            if not p.exists(): return default
            try: return json.loads(p.read_text(encoding='utf-8'))
            except Exception: return default
    def save(self,name:str,value:Any)->None:
        with self._lock:
            p=self.path(name); p.parent.mkdir(parents=True,exist_ok=True)
            tmp=p.with_suffix(p.suffix+'.tmp')
            tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            tmp.replace(p)
    def secrets(self)->dict[str,Any]:
        return self.load('secrets.json',{}) or {}
