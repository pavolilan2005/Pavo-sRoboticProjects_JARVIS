from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prp.core.models import ActionResult, RiskLevel
from prp.core.storage import JsonStore

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None


DEFAULT_NODES = {
    "version": 1,
    "nodes": [
        {
            "id": "esp32_principal",
            "name": "ESP32 Principal",
            "transport": "serial",
            "protocol": "prp-node-v1",
            "port": "COM6",
            "baudrate": 115200,
            "boot_wait": 1.3,
            "enabled": True,
            "auto_sync": True,
        }
    ],
}

DEFAULT_DEVICES = {
    "version": 1,
    "devices": [
        {
            "id": "foco",
            "name": "Foco",
            "aliases": ["luz", "lámpara", "lampara", "led", "foco del cuarto"],
            "node": "esp32_principal",
            "pin": 23,
            "type": "digital_output",
            "active_low": False,
            "default_state": 0,
            "capabilities": ["on", "off", "toggle", "status"],
        }
    ],
}

DEFAULT_SCENES = {
    "version": 1,
    "scenes": [
        {"id": "normal", "name": "Normal", "targets": [{"device": "foco", "action": "off"}]},
        {"id": "stream", "name": "Stream", "targets": [{"device": "foco", "action": "on"}]},
        {"id": "estudio", "name": "Estudio", "targets": [{"device": "foco", "action": "on"}]},
    ],
}


@dataclass
class NodeConnection:
    node_id: str
    port: str
    baudrate: int
    handle: Any = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_seen: float = 0.0
    last_error: str = ""
    hello: dict[str, Any] = field(default_factory=dict)
    synced_signature: str = ""


class ESP32Adapter:
    """Single owner of all ESP32 serial links and logical GPIO mappings."""

    VALID_TYPES = {"digital_output", "digital_input", "pwm_output", "analog_input"}
    RESERVED_ESP32_PINS = {6, 7, 8, 9, 10, 11}
    INPUT_ONLY_ESP32_PINS = {34, 35, 36, 39}

    def __init__(self, registry, event_bus, base_dir: Path, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.base_dir = Path(base_dir)
        self.ui = ui
        self.nodes_store = JsonStore(self.base_dir / "config" / "nodes.json", DEFAULT_NODES)
        self.devices_store = JsonStore(self.base_dir / "config" / "devices.json", DEFAULT_DEVICES)
        self.scenes_store = JsonStore(self.base_dir / "config" / "scenes.json", DEFAULT_SCENES)
        self._connections: dict[str, NodeConnection] = {}
        self._connections_lock = threading.RLock()
        self._last_state: dict[str, Any] = {}

    def register(self) -> None:
        r = self.registry.register_handler
        r("domotics.control", "Controla o consulta un dispositivo domótico por nombre lógico.", self.control, tags=("domotics", "esp32"))
        r("domotics.status", "Consulta el estado de un dispositivo domótico.", self.status, tags=("domotics", "esp32"))
        r("domotics.activate_scene", "Aplica una escena domótica.", self.activate_scene, tags=("domotics", "esp32"))
        r("esp32.nodes", "Lista nodos ESP32 y su estado.", self.nodes_status, tags=("domotics", "esp32"))
        r("esp32.sync", "Sincroniza GPIO y dispositivos con una ESP32.", self.sync_node, risk=RiskLevel.HIGH, requires_confirmation=True, tags=("domotics", "esp32", "configuration"))
        r("esp32.disconnect", "Desconecta una ESP32.", self.disconnect_capability, tags=("domotics", "esp32"))

    # ----------------------------- configuration -----------------------------
    def list_ports(self) -> list[dict[str, str]]:
        if list_ports is None:
            return []
        return [
            {"port": p.device, "description": p.description or p.device, "hwid": p.hwid or ""}
            for p in list_ports.comports()
        ]

    def list_nodes(self) -> list[dict[str, Any]]:
        nodes = self.nodes_store.load().get("nodes", [])
        with self._connections_lock:
            conns = dict(self._connections)
        result = []
        for raw in nodes:
            node = dict(raw)
            conn = conns.get(node.get("id"))
            node["online"] = bool(conn and conn.handle and getattr(conn.handle, "is_open", False))
            node["last_seen"] = conn.last_seen if conn else 0.0
            node["last_error"] = conn.last_error if conn else ""
            node["firmware"] = (conn.hello or {}).get("firmware", "") if conn else ""
            result.append(node)
        return result

    def save_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node = dict(node)
        node["id"] = self._slug(node.get("id") or node.get("name") or "esp32")
        node.setdefault("name", node["id"])
        node["port"] = str(node.get("port", "")).strip()
        node["baudrate"] = int(node.get("baudrate", 115200))
        node["protocol"] = "prp-node-v1"
        node.setdefault("transport", "serial")
        node.setdefault("boot_wait", 1.3)
        node.setdefault("enabled", True)
        node.setdefault("auto_sync", True)

        data = self.nodes_store.load()
        items = data.setdefault("nodes", [])
        previous = next((n for n in items if n.get("id") == node["id"]), None)
        if previous and (previous.get("port") != node.get("port") or int(previous.get("baudrate", 115200)) != node["baudrate"]):
            self.disconnect(node["id"])
        for index, existing in enumerate(items):
            if existing.get("id") == node["id"]:
                items[index] = node
                break
        else:
            items.append(node)
        self.nodes_store.save(data)
        self.event_bus.publish("esp32.node.saved", {"node": node}, "esp32")
        return node

    def set_primary_port(self, port: str) -> dict[str, Any]:
        nodes = self.nodes_store.load().get("nodes", [])
        node = next((dict(n) for n in nodes if n.get("id") == "esp32_principal"), None)
        if node is None:
            node = dict(DEFAULT_NODES["nodes"][0])
        node["port"] = str(port).strip()
        return self.save_node(node)

    def delete_node(self, node_id: str) -> bool:
        self.disconnect(node_id)
        data = self.nodes_store.load()
        before = len(data.get("nodes", []))
        data["nodes"] = [n for n in data.get("nodes", []) if n.get("id") != node_id]
        self.nodes_store.save(data)
        return len(data["nodes"]) < before

    def list_devices(self) -> list[dict[str, Any]]:
        return list(self.devices_store.load().get("devices", []))

    def get_device(self, name: str) -> dict[str, Any] | None:
        needle = self._norm(name)
        for device in self.list_devices():
            candidates = [device.get("id", ""), device.get("name", ""), *(device.get("aliases") or [])]
            if needle in {self._norm(v) for v in candidates}:
                return dict(device)
        return None

    def save_device(self, device: dict[str, Any]) -> dict[str, Any]:
        device = dict(device)
        device["id"] = self._slug(device.get("id") or device.get("name") or "device")
        device.setdefault("name", device["id"])
        aliases = device.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]
        device["aliases"] = aliases
        device["pin"] = int(device.get("pin", -1))
        device.setdefault("type", "digital_output")
        device["active_low"] = bool(device.get("active_low", False))
        device.setdefault("default_state", 0)
        capabilities = device.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [a.strip() for a in capabilities.split(",") if a.strip()]
        device["capabilities"] = capabilities or self._default_capabilities(device["type"])
        self.validate_device(device)

        data = self.devices_store.load()
        items = data.setdefault("devices", [])
        for index, existing in enumerate(items):
            if existing.get("id") == device["id"]:
                items[index] = device
                break
        else:
            items.append(device)
        self.devices_store.save(data)
        self._invalidate_node_sync(str(device.get("node", "")))
        self.event_bus.publish("domotics.device.saved", {"device": device}, "esp32")
        return device

    def delete_device(self, device_id: str) -> bool:
        data = self.devices_store.load()
        deleted = next((d for d in data.get("devices", []) if d.get("id") == device_id), None)
        before = len(data.get("devices", []))
        data["devices"] = [d for d in data.get("devices", []) if d.get("id") != device_id]
        self.devices_store.save(data)
        if deleted:
            self._invalidate_node_sync(str(deleted.get("node", "")))
        return len(data["devices"]) < before

    def validate_device(self, device: dict[str, Any]) -> None:
        node_id = str(device.get("node", ""))
        if not any(n.get("id") == node_id for n in self.nodes_store.load().get("nodes", [])):
            raise ValueError(f"El nodo '{node_id}' no existe.")
        pin = int(device.get("pin", -1))
        if pin < 0 or pin > 39:
            raise ValueError("GPIO debe estar entre 0 y 39.")
        if pin in self.RESERVED_ESP32_PINS:
            raise ValueError(f"GPIO {pin} está reservado para la memoria flash.")
        kind = str(device.get("type", ""))
        if kind not in self.VALID_TYPES:
            raise ValueError(f"Tipo de dispositivo inválido: {kind}")
        if kind in {"digital_output", "pwm_output"} and pin in self.INPUT_ONLY_ESP32_PINS:
            raise ValueError(f"GPIO {pin} es solo de entrada.")
        for existing in self.list_devices():
            if existing.get("id") != device.get("id") and existing.get("node") == node_id and int(existing.get("pin", -2)) == pin:
                raise ValueError(f"GPIO {pin} ya está asignado a '{existing.get('name')}'.")

    # ------------------------------- transport -------------------------------
    def connect(self, node_id: str, *, auto_sync: bool = True) -> ActionResult:
        node = self._get_node(node_id)
        if not node:
            return ActionResult.failure(f"No existe el nodo '{node_id}'.")
        if serial is None:
            return ActionResult.failure("PySerial no está instalado.")
        port = str(node.get("port", "")).strip()
        if not port:
            return ActionResult.failure(f"El nodo {node_id} no tiene puerto configurado.")

        with self._connections_lock:
            conn = self._connections.get(node_id)
            if conn is None:
                conn = NodeConnection(node_id=node_id, port=port, baudrate=int(node.get("baudrate", 115200)))
                self._connections[node_id] = conn

        with conn.lock:
            try:
                if conn.handle and conn.handle.is_open and conn.port == port and conn.baudrate == int(node.get("baudrate", 115200)):
                    if auto_sync and bool(node.get("auto_sync", True)):
                        sync = self._ensure_synced_locked(conn, node)
                        if not sync.get("ok", False):
                            return ActionResult.failure(f"La ESP32 está conectada, pero rechazó la configuración: {sync}")
                    return ActionResult.success(f"{node.get('name')} ya está conectada.", node=node, hello=conn.hello)

                self._close_connection(conn)
                conn.port = port
                conn.baudrate = int(node.get("baudrate", 115200))
                conn.handle = serial.Serial(port, conn.baudrate, timeout=0.12, write_timeout=1.0)
                time.sleep(float(node.get("boot_wait", 1.3)))
                self._drain_events_locked(conn)
                hello = self._request_locked(conn, {"op": "hello"}, timeout=2.5)
                if not hello.get("ok", False):
                    raise RuntimeError(hello.get("error", "La placa rechazó el saludo."))
                if hello.get("protocol") != "prp-node-v1":
                    raise RuntimeError(f"Protocolo incompatible: {hello.get('protocol')}")
                conn.hello = hello
                conn.last_seen = time.time()
                conn.last_error = ""
                if auto_sync and bool(node.get("auto_sync", True)):
                    sync = self._ensure_synced_locked(conn, node, force=True)
                    if not sync.get("ok", False):
                        raise RuntimeError(sync.get("error", "La placa rechazó la configuración."))
                self.event_bus.publish("esp32.node.online", {"node": node, "hello": hello}, "esp32")
                return ActionResult.success(f"{node.get('name')} conectada en {port}.", node=node, hello=hello)
            except Exception as exc:
                conn.last_error = str(exc)
                self._close_connection(conn)
                self.event_bus.publish("esp32.node.offline", {"node_id": node_id, "error": str(exc)}, "esp32")
                return ActionResult.failure(f"No pude conectar {node.get('name')} en {port}: {exc}", error=str(exc))

    def disconnect(self, node_id: str) -> None:
        with self._connections_lock:
            conn = self._connections.pop(node_id, None)
        if conn:
            with conn.lock:
                self._close_connection(conn)
            self.event_bus.publish("esp32.node.offline", {"node_id": node_id}, "esp32")

    def disconnect_capability(self, params: dict[str, Any]) -> ActionResult:
        node_id = str(params.get("node", ""))
        self.disconnect(node_id)
        return ActionResult.success(f"Nodo {node_id} desconectado.")

    def sync_node(self, params: dict[str, Any]) -> ActionResult:
        node_id = str(params.get("node", "")).strip()
        connected = self.connect(node_id, auto_sync=False)
        if not connected.ok:
            return connected
        node = self._get_node(node_id)
        conn = self._connections[node_id]
        with conn.lock:
            try:
                reply = self._ensure_synced_locked(conn, node or {}, force=True)
                if not reply.get("ok", False):
                    return ActionResult.failure(f"La ESP32 rechazó la configuración: {reply}")
                count = len([d for d in self.list_devices() if d.get("node") == node_id])
                return ActionResult.success(f"Configuración enviada a {node.get('name', node_id)}: {count} dispositivos.", reply=reply)
            except Exception as exc:
                return ActionResult.failure(f"No pude sincronizar el nodo: {exc}", error=str(exc))

    def _ensure_synced_locked(self, conn: NodeConnection, node: dict[str, Any], force: bool = False) -> dict[str, Any]:
        devices = [self._firmware_device(d) for d in self.list_devices() if d.get("node") == conn.node_id]
        signature = hashlib.sha256(json.dumps(devices, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if not force and conn.synced_signature == signature:
            return {"ok": True, "configured": len(devices), "unchanged": True}
        reply = self._request_locked(conn, {"op": "configure", "devices": devices}, timeout=4.0)
        if reply.get("ok", False):
            conn.synced_signature = signature
            self.event_bus.publish("esp32.node.synced", {"node_id": conn.node_id, "devices": len(devices)}, "esp32")
        return reply

    def _request_locked(self, conn: NodeConnection, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        if not conn.handle or not conn.handle.is_open:
            raise RuntimeError("El puerto serial no está abierto.")
        request_id = str(uuid.uuid4())[:8]
        packet = dict(payload)
        packet["id"] = request_id
        self._drain_events_locked(conn)
        raw = (json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        conn.handle.write(raw)
        conn.handle.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = conn.handle.readline()
            if not line:
                continue
            message = self._parse_message(line)
            if message is None:
                continue
            if message.get("event"):
                self.event_bus.publish(f"esp32.event.{message['event']}", message, conn.node_id)
                continue
            if message.get("reply_to") == request_id or message.get("id") == request_id:
                conn.last_seen = time.time()
                conn.last_error = ""
                return message
        raise TimeoutError(f"El nodo {conn.node_id} no respondió a {payload.get('op')}.")

    def _drain_events_locked(self, conn: NodeConnection) -> None:
        try:
            while conn.handle and conn.handle.is_open and conn.handle.in_waiting:
                line = conn.handle.readline()
                message = self._parse_message(line)
                if message and message.get("event"):
                    self.event_bus.publish(f"esp32.event.{message['event']}", message, conn.node_id)
        except Exception:
            pass

    @staticmethod
    def _parse_message(line: bytes) -> dict[str, Any] | None:
        try:
            value = json.loads(line.decode("utf-8", errors="replace").strip())
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    # -------------------------------- control --------------------------------
    def control(self, params: dict[str, Any]) -> ActionResult:
        device_name = str(params.get("device", "")).strip()
        action = self._normalize_action(str(params.get("action", "status")))
        value = params.get("value")
        device = self.get_device(device_name)
        if not device:
            return ActionResult.failure(f"No existe el dispositivo '{device_name}'.", error="device_not_found")
        if action not in set(device.get("capabilities", [])) and action not in {"set", "status"}:
            return ActionResult.failure(f"{device['name']} no soporta la acción '{action}'.")
        node_id = str(device.get("node", ""))
        connected = self.connect(node_id, auto_sync=True)
        if not connected.ok:
            return connected
        conn = self._connections[node_id]
        payload: dict[str, Any]
        if action == "on":
            payload = {"op": "set", "device": device["id"], "value": 1}
        elif action == "off":
            payload = {"op": "set", "device": device["id"], "value": 0}
        elif action == "status":
            payload = {"op": "get", "device": device["id"]}
        elif action == "toggle":
            payload = {"op": "toggle", "device": device["id"]}
        else:
            payload = {"op": "set", "device": device["id"], "value": value}
        try:
            with conn.lock:
                reply = self._request_locked(conn, payload, timeout=float(params.get("timeout", 2.0)))
            if not reply.get("ok", False):
                return ActionResult.failure(f"{device['name']} rechazó la orden: {reply.get('error', reply)}", reply=reply)
            state = reply.get("value", reply.get("state"))
            self._last_state[device["id"]] = state
            self.event_bus.publish("domotics.device.changed", {"device": device, "action": action, "state": state, "reply": reply}, "esp32")
            return ActionResult.success(self._human_message(device, action, state), device=device, action=action, state=state, reply=reply)
        except Exception as exc:
            self.disconnect(node_id)
            return ActionResult.failure(f"No pude controlar {device['name']}: {exc}", error=str(exc))

    def status(self, params: dict[str, Any]) -> ActionResult:
        return self.control({"device": params.get("device"), "action": "status"})

    def activate_scene(self, params: dict[str, Any]) -> ActionResult:
        needle = self._norm(str(params.get("scene", "")))
        scene = next((s for s in self.scenes_store.load().get("scenes", []) if needle in {self._norm(s.get("id", "")), self._norm(s.get("name", ""))}), None)
        if not scene:
            return ActionResult.failure(f"No existe la escena '{params.get('scene', '')}'.")
        results = []
        failures = []
        for target in scene.get("targets", []):
            result = self.control(target)
            results.append(result.to_dict())
            if not result.ok:
                failures.append(result.message)
        answer = ActionResult.success(f"Escena {scene['name']} aplicada{' parcialmente' if failures else ''}.", scene=scene, results=results)
        answer.warnings.extend(failures)
        return answer

    def nodes_status(self, _params: dict[str, Any]) -> ActionResult:
        nodes = self.list_nodes()
        online = sum(1 for n in nodes if n.get("online"))
        return ActionResult.success(f"Nodos ESP32: {online} en línea de {len(nodes)} configurados.", nodes=nodes, ports=self.list_ports())

    def poll_nodes(self) -> list[dict[str, Any]]:
        return self.list_nodes()

    def shutdown(self) -> None:
        with self._connections_lock:
            node_ids = list(self._connections)
        for node_id in node_ids:
            self.disconnect(node_id)

    # -------------------------------- helpers --------------------------------
    def _get_node(self, node_id: str) -> dict[str, Any] | None:
        return next((dict(n) for n in self.nodes_store.load().get("nodes", []) if n.get("id") == node_id), None)

    def _invalidate_node_sync(self, node_id: str) -> None:
        with self._connections_lock:
            conn = self._connections.get(node_id)
            if conn:
                conn.synced_signature = ""

    @staticmethod
    def _close_connection(conn: NodeConnection) -> None:
        try:
            if conn.handle:
                conn.handle.close()
        except Exception:
            pass
        conn.handle = None
        conn.synced_signature = ""

    @staticmethod
    def _firmware_device(device: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "pin", "type", "active_low", "default_state", "capabilities", "pull", "frequency")
        return {key: device.get(key) for key in keys if key in device}

    @staticmethod
    def _default_capabilities(device_type: str) -> list[str]:
        if device_type == "digital_output":
            return ["on", "off", "toggle", "status"]
        if device_type == "pwm_output":
            return ["set", "on", "off", "status"]
        return ["status"]

    @staticmethod
    def _normalize_action(action: str) -> str:
        aliases = {
            "prender": "on", "prende": "on", "encender": "on", "enciende": "on", "activar": "on", "on": "on",
            "apagar": "off", "apaga": "off", "desactivar": "off", "off": "off",
            "cambiar": "toggle", "alterna": "toggle", "alternar": "toggle", "toggle": "toggle",
            "estado": "status", "consultar": "status", "leer": "status", "status": "status",
            "nivel": "set", "set": "set",
        }
        return aliases.get(action.strip().lower(), action.strip().lower())

    @staticmethod
    def _human_message(device: dict[str, Any], action: str, state: Any) -> str:
        name = device.get("name", device.get("id", "Dispositivo"))
        if action == "on":
            return f"{name} encendido."
        if action == "off":
            return f"{name} apagado."
        if action == "toggle":
            return f"{name} alternado; estado actual: {state}."
        if action == "status":
            return f"Estado de {name}: {state}."
        return f"{name} actualizado a {state}."

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(str(value or "").lower().strip().split())

    @staticmethod
    def _slug(value: str) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
        return "_".join(part for part in raw.split("_") if part) or "item"
