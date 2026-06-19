from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

import psutil

from prp.core.models import ActionResult, RiskLevel


class PCAdapter:
    def __init__(self, registry, event_bus, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.ui = ui

    def register(self) -> None:
        r = self.registry.register_handler
        r("pc.status", "Obtiene CPU, RAM, disco, batería, red y procesos principales.", self.status, tags=("pc", "status"))
        r("pc.process_running", "Comprueba si un proceso está ejecutándose.", self.process_running, tags=("pc", "status"))
        r("pc.close_process", "Cierra un proceso por nombre.", self.close_process, risk=RiskLevel.HIGH, requires_confirmation=True, tags=("pc", "process"))
        r("pc.open_path", "Abre una carpeta o archivo local.", self.open_path, tags=("pc", "files"))
        r("pc.wait_process", "Espera a que un proceso aparezca.", self.wait_process, tags=("pc", "status"))

    def status(self, _params: dict[str, Any]) -> ActionResult:
        cpu = psutil.cpu_percent(interval=0.15)
        mem = psutil.virtual_memory()
        disk_root = Path.home().anchor or "/"
        disk = psutil.disk_usage(disk_root)
        battery = None
        try:
            b = psutil.sensors_battery()
            if b:
                battery = {"percent": b.percent, "plugged": b.power_plugged, "seconds_left": b.secsleft}
        except Exception:
            pass
        processes = []
        for proc in sorted(
            psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]),
            key=lambda p: float(p.info.get("memory_percent") or 0),
            reverse=True,
        )[:8]:
            try:
                processes.append({
                    "pid": proc.info["pid"],
                    "name": proc.info.get("name") or "?",
                    "memory_percent": round(float(proc.info.get("memory_percent") or 0), 2),
                    "cpu_percent": round(float(proc.info.get("cpu_percent") or 0), 2),
                })
            except Exception:
                pass
        data = {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / 1024**3, 2),
            "memory_total_gb": round(mem.total / 1024**3, 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1024**3, 2),
            "battery": battery,
            "process_count": len(psutil.pids()),
            "top_processes": processes,
            "platform": platform.platform(),
        }
        return ActionResult.success(
            f"CPU {cpu:.0f} %, RAM {mem.percent:.0f} %, disco {disk.percent:.0f} %.",
            **data,
        )

    def process_running(self, params: dict[str, Any]) -> ActionResult:
        needle = str(params.get("name", "")).lower().strip()
        if not needle:
            return ActionResult.failure("Falta el nombre del proceso.")
        matches = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                exe = str(proc.info.get("exe") or "").lower()
                if needle in name or needle in exe:
                    matches.append({"pid": proc.pid, "name": proc.info.get("name"), "exe": proc.info.get("exe")})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return ActionResult.success(
            f"Proceso {'encontrado' if matches else 'no encontrado'}: {needle}.",
            running=bool(matches),
            matches=matches,
            result=bool(matches),
        )

    def close_process(self, params: dict[str, Any]) -> ActionResult:
        needle = str(params.get("name", "")).lower().strip()
        force = bool(params.get("force", False))
        if not needle:
            return ActionResult.failure("Falta el nombre del proceso.")
        closed = []
        denied = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if needle in str(proc.info.get("name") or "").lower() or needle in str(proc.info.get("exe") or "").lower():
                    (proc.kill() if force else proc.terminate())
                    closed.append({"pid": proc.pid, "name": proc.info.get("name")})
            except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
                denied.append(str(exc))
        if not closed:
            return ActionResult.failure(f"No encontré o no pude cerrar '{needle}'.", denied=denied)
        return ActionResult.success(f"Se cerraron {len(closed)} procesos.", closed=closed, denied=denied)

    def open_path(self, params: dict[str, Any]) -> ActionResult:
        raw = str(params.get("path", "")).strip()
        shortcuts = {
            "desktop": Path.home() / "Desktop",
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "home": Path.home(),
        }
        path = shortcuts.get(raw.lower(), Path(raw).expanduser())
        if not path.exists():
            return ActionResult.failure(f"No existe: {path}")
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif shutil.which("open"):
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
            return ActionResult.success(f"Abrí {path}.", path=str(path))
        except Exception as exc:
            return ActionResult.failure(f"No pude abrir {path}: {exc}", error=str(exc))

    def wait_process(self, params: dict[str, Any]) -> ActionResult:
        name = str(params.get("name", "")).strip()
        timeout = max(0.1, float(params.get("timeout", 15)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.process_running({"name": name})
            if result.data.get("running"):
                return result
            time.sleep(0.25)
        return ActionResult.failure(f"El proceso '{name}' no apareció en {timeout:.1f}s.", error="timeout")
