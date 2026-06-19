import os,subprocess,webbrowser,shutil
from pathlib import Path
from prp.core.capabilities import Result
class PCService:
    APPS={'obs':['obs64.exe','obs.exe'],'spotify':['spotify.exe'],'chrome':['chrome.exe'],'edge':['msedge.exe'],'notepad':['notepad.exe'],'vscode':['code.exe']}
    def open_app(self,name):
        key=name.lower().strip(); candidates=self.APPS.get(key,[name])
        for c in candidates:
            path=shutil.which(c)
            if path: subprocess.Popen([path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return Result(True,f'{name} abierto')
        try: os.startfile(name); return Result(True,f'{name} abierto')
        except Exception:return Result(False,f'No encontré la aplicación: {name}')
    def open_url(self,url): webbrowser.open(url); return Result(True,'Página abierta')
