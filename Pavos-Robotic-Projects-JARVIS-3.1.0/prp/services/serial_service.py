from __future__ import annotations
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable
from prp.core.config import ConfigStore
from prp.core.models import ActionResult

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

class SerialService:
    """Único propietario de todas las conexiones seriales del proyecto."""
    def __init__(self, config: ConfigStore, on_event: Callable[[dict[str, Any]], None] | None = None):
        self.config = config
        self.on_event = on_event
        self._connections: dict[str, Any] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._reader_threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()

    def list_ports(self) -> list[dict[str, str]]:
        if not list_ports:
            return []
        return [{"port": p.device, "description": p.description or p.device, "hwid": p.hwid or ""} for p in list_ports.comports()]

    def node_definitions(self) -> list[dict[str, Any]]:
        return (self.config.load("nodes.json", {}) or {}).get("nodes", [])

    def connect(self, node_id: str) -> ActionResult:
        node = next((n for n in self.node_definitions() if n.get("id") == node_id), None)
        if not node:
            return ActionResult.failure(f"Nodo no encontrado: {node_id}")
        if serial is None:
            return ActionResult.failure("PySerial no está instalado")
        port = str(node.get("port", "")).strip()
        if not port:
            return ActionResult.failure(f"El nodo {node_id} no tiene puerto configurado")
        lock = self._locks.setdefault(node_id, threading.RLock())
        with lock:
            conn = self._connections.get(node_id)
            if conn and conn.is_open:
                return ActionResult.success(f"{node_id} ya está conectado", port=port)
            try:
                settings = (self.config.load("integrations.json", {}) or {}).get("serial", {})
                conn = serial.Serial(port, int(node.get("baudrate", settings.get("baudrate", 115200))), timeout=0.15, write_timeout=0.8)
                time.sleep(1.4)
                conn.reset_input_buffer()
                self._connections[node_id] = conn
                self._start_reader(node_id)
                return ActionResult.success(f"Nodo conectado: {node_id}", port=port)
            except Exception as exc:
                self._connections.pop(node_id, None)
                return ActionResult.failure(f"No se pudo conectar {node_id}", str(exc))

    def disconnect(self, node_id: str) -> None:
        with self._locks.setdefault(node_id, threading.RLock()):
            conn = self._connections.pop(node_id, None)
            if conn:
                try: conn.close()
                except Exception: pass

    def send(self, node_id: str, payload: dict[str, Any], timeout: float = 1.2) -> ActionResult:
        connected = self.connect(node_id)
        if not connected.ok:
            return connected
        lock = self._locks.setdefault(node_id, threading.RLock())
        request_id = payload.setdefault("request_id", f"r{time.time_ns()}")
        with lock:
            conn = self._connections[node_id]
            try:
                conn.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                conn.flush()
            except Exception as exc:
                self.disconnect(node_id)
                return ActionResult.failure("Error enviando al nodo", str(exc))
        # Las respuestas también llegan por el lector. Para comandos síncronos esperamos una coincidencia corta.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cache = getattr(self, "_responses", {})
            if request_id in cache:
                response = cache.pop(request_id)
                return ActionResult.success(response.get("message", "Comando aceptado"), response=response)
            time.sleep(0.02)
        return ActionResult.failure("El nodo no respondió a tiempo")

    def _start_reader(self, node_id: str) -> None:
        existing = self._reader_threads.get(node_id)
        if existing and existing.is_alive():
            return
        thread = threading.Thread(target=self._reader, args=(node_id,), daemon=True, name=f"serial-{node_id}")
        self._reader_threads[node_id] = thread
        thread.start()

    def _reader(self, node_id: str) -> None:
        if not hasattr(self, "_responses"):
            self._responses = {}
        while not self._stop.is_set():
            conn = self._connections.get(node_id)
            if not conn or not conn.is_open:
                return
            try:
                raw = conn.readline()
                if not raw:
                    continue
                message = json.loads(raw.decode("utf-8", errors="replace"))
                request_id = message.get("request_id")
                if request_id:
                    self._responses[request_id] = message
                if self.on_event:
                    self.on_event({"node_id": node_id, **message})
            except json.JSONDecodeError:
                continue
            except Exception:
                self.disconnect(node_id)
                return

    def sync_node(self, node_id: str) -> ActionResult:
        devices = [d for d in (self.config.load("devices.json", {}) or {}).get("devices", []) if d.get("node_id") == node_id]
        return self.send(node_id, {"cmd": "configure", "devices": devices}, timeout=3.0)

    def control_device(self, device_id: str, action: str, value: Any = None) -> ActionResult:
        device = next((d for d in (self.config.load("devices.json", {}) or {}).get("devices", []) if d.get("id") == device_id), None)
        if not device:
            return ActionResult.failure(f"Dispositivo no encontrado: {device_id}")
        return self.send(str(device["node_id"]), {"cmd": "device", "device_id": device_id, "action": action, "value": value})

    def close(self) -> None:
        self._stop.set()
        for node_id in list(self._connections):
            self.disconnect(node_id)
