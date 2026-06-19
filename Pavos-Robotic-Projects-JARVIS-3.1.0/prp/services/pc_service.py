from __future__ import annotations
import os
import subprocess
import webbrowser
from pathlib import Path
import psutil
from prp.core.models import ActionResult

class PcService:
    APP_ALIASES = {
        "obs": ["obs64.exe", "obs.exe"],
        "spotify": ["spotify.exe"],
        "chrome": ["chrome.exe"],
        "edge": ["msedge.exe"],
        "notepad": ["notepad.exe"]
    }
    def open_app(self, name: str) -> ActionResult:
        key = name.lower().strip()
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", "start", "", key], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([key], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult.success(f"Abriendo {name}")
        except Exception as exc:
            return ActionResult.failure(f"No pude abrir {name}", str(exc))
    def open_url(self, url: str) -> ActionResult:
        return ActionResult.success("Navegador abierto", url=url) if webbrowser.open(url) else ActionResult.failure("No se pudo abrir el navegador")
    def status(self) -> ActionResult:
        data = {"cpu": psutil.cpu_percent(interval=0.2), "ram": psutil.virtual_memory().percent, "disk": psutil.disk_usage(str(Path.home())).percent}
        battery = psutil.sensors_battery()
        if battery: data["battery"] = battery.percent
        return ActionResult.success(f"CPU {data['cpu']:.0f}%, RAM {data['ram']:.0f}%, disco {data['disk']:.0f}%", **data)
