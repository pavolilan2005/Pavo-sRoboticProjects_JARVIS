from __future__ import annotations

import json
import re
import threading
import unicodedata
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from mark_core.models import ActionResult, RiskLevel
from mark_core.storage import JsonStore

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - handled at runtime
    serial = None
    list_ports = None


DEFAULT_NODES = {
    "version": 1,
    "nodes": [
        {
            "id": "esp32_principal",
            "name": "ESP32 Principal",
            "transport": "serial",
            "protocol": "jarvis-node-v1",
            "port": "COM6",
            "baudrate": 115200,
            "enabled": True,
        }
    ],
}

DEFAULT_DEVICES = {
    "version": 1,
    "devices": [
        {
            "id": "foco",
            "name": "Foco",
            "aliases": ["luz", "lámpara", "led", "foco del cuarto"],
            "node": "esp32_principal",
            "pin": 23,
            "type": "digital_output",
            "active_low": False,
            "default_state": 0,
            "capabilities": ["on", "off", "toggle", "status"],
            "legacy_commands": {"on": "C", "off": "A", "toggle": "T", "status": "E"},
        },
        {
            "id": "ventilador",
            "name": "Ventilador",
            "aliases": ["ventilador del cuarto", "abanico", "fan"],
            "node": "esp32_principal",
            "pin": 2,
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


class ESP32Adapter:
    """Configurable ESP32 node manager.

    New nodes use newline-delimited JSON protocol ``jarvis-node-v1``. Existing
    single-character firmware remains available through protocol ``legacy``.
    """

    VALID_TYPES = {"digital_output", "digital_input", "pwm_output", "analog_input"}
    RESERVED_ESP32_PINS = {6, 7, 8, 9, 10, 11}
    INPUT_ONLY_ESP32_PINS = {34, 35, 36, 39}

    def __init__(
        self,
        registry,
        event_bus,
        base_dir: Path,
        legacy_controller: Callable[[dict[str, Any]], str] | None = None,
        ui=None,
    ):
        self.registry = registry
        self.event_bus = event_bus
        self.base_dir = base_dir
        self.ui = ui
        self.legacy_controller = legacy_controller
        self.nodes_store = JsonStore(base_dir / "config" / "nodes.json", DEFAULT_NODES)
        self.devices_store = JsonStore(base_dir / "config" / "devices.json", DEFAULT_DEVICES)
        self.scenes_store = JsonStore(base_dir / "config" / "scenes.json", DEFAULT_SCENES)
        self._connections: dict[str, NodeConnection] = {}
        self._connections_lock = threading.RLock()
        self._last_state: dict[str, Any] = {}

    def register(self) -> None:
        r = self.registry.register_handler
        r("domotics.control", "Controla o consulta un dispositivo domótico por nombre lógico.", self.control, tags=("domotics", "esp32"))
        r("domotics.status", "Consulta el estado conocido de un dispositivo.", self.status, tags=("domotics", "esp32"))
        r("domotics.list", "Lista todos los dispositivos domóticos configurados, sus nombres, alias, GPIO y funciones.", self.list_capability, tags=("domotics", "esp32"))
        r("domotics.activate_scene", "Aplica una escena a varios dispositivos.", self.activate_scene, tags=("domotics", "esp32"))
        r("esp32.nodes", "Lista nodos ESP32 y su estado.", self.nodes_status, tags=("domotics", "esp32"))
        r("esp32.sync", "Envía la configuración de pines al nodo ESP32.", self.sync_node, risk=RiskLevel.HIGH, requires_confirmation=True, tags=("domotics", "esp32", "configuration"))
        r("esp32.disconnect", "Desconecta un nodo ESP32.", self.disconnect_capability, tags=("domotics", "esp32"))

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
        for node in nodes:
            item = dict(node)
            conn = conns.get(node.get("id"))
            item["online"] = bool(conn and conn.handle and getattr(conn.handle, "is_open", False))
            item["last_seen"] = conn.last_seen if conn else 0
            item["last_error"] = conn.last_error if conn else ""
            result.append(item)
        return result

    def save_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node = dict(node)
        node["id"] = self._slug(node.get("id") or node.get("name") or "esp32")
        node.setdefault("name", node["id"])
        node.setdefault("transport", "serial")
        node.setdefault("protocol", "jarvis-node-v1")
        node.setdefault("baudrate", 115200)
        node.setdefault("enabled", True)
        data = self.nodes_store.load()
        items = data.setdefault("nodes", [])
        for i, existing in enumerate(items):
            if existing.get("id") == node["id"]:
                if existing.get("port") != node.get("port") or existing.get("baudrate") != node.get("baudrate"):
                    self.disconnect(node["id"])
                items[i] = node
                break
        else:
            items.append(node)
        self.nodes_store.save(data)
        self.event_bus.publish("esp32.node.saved", {"node": node}, "esp32")
        return node

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
        """Resolve a spoken/logical name against IDs, names and aliases.

        Exact matches win. Natural phrases such as ``el ventilador del cuarto``
        are also accepted as long as they identify a single configured device.
        """
        needle = self._norm(name)
        if not needle:
            return None

        exact: list[dict[str, Any]] = []
        contained: list[tuple[int, dict[str, Any]]] = []
        needle_tokens = set(needle.split())
        for device in self.list_devices():
            candidates = [device.get("id", ""), device.get("name", ""), *(device.get("aliases") or [])]
            normalized = {self._norm(v) for v in candidates if str(v).strip()}
            if needle in normalized:
                exact.append(dict(device))
                continue
            for candidate in normalized:
                if not candidate:
                    continue
                candidate_tokens = set(candidate.split())
                if candidate in needle or needle in candidate:
                    contained.append((len(candidate_tokens), dict(device)))
                    break
                if candidate_tokens and candidate_tokens.issubset(needle_tokens):
                    contained.append((len(candidate_tokens), dict(device)))
                    break

        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
        if contained:
            contained.sort(key=lambda item: item[0], reverse=True)
            best_score = contained[0][0]
            best = [item[1] for item in contained if item[0] == best_score]
            unique = {item.get("id"): item for item in best}
            if len(unique) == 1:
                return next(iter(unique.values()))
        return None

    def save_device(self, device: dict[str, Any], previous_id: str | None = None) -> dict[str, Any]:
        device = dict(device)
        device["id"] = self._slug(device.get("id") or device.get("name") or "device")
        device.setdefault("name", device["id"])
        aliases = device.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]
        automatic_aliases = [str(device.get("name", "")).strip(), str(device.get("id", "")).strip()]
        merged_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in [*aliases, *automatic_aliases]:
            alias = str(alias).strip()
            key = self._norm(alias)
            if alias and key and key not in seen_aliases:
                seen_aliases.add(key)
                merged_aliases.append(alias)
        device["aliases"] = merged_aliases
        device["pin"] = int(device.get("pin", -1))
        device.setdefault("type", "digital_output")
        device["active_low"] = bool(device.get("active_low", False))
        device.setdefault("default_state", 0)
        capabilities = device.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [a.strip() for a in capabilities.split(",") if a.strip()]
        device["capabilities"] = capabilities or self._default_capabilities(device["type"])
        self.validate_device(device, previous_id=previous_id)
        data = self.devices_store.load()
        items = data.setdefault("devices", [])
        old_id = self._slug(previous_id) if previous_id else device["id"]
        replaced = False
        for i, existing in enumerate(items):
            if existing.get("id") in {old_id, device["id"]}:
                items[i] = device
                replaced = True
                break
        if not replaced:
            items.append(device)
        self.devices_store.save(data)
        if old_id != device["id"]:
            self._rename_device_references(old_id, device["id"])
            self._last_state.pop(old_id, None)
        self.event_bus.publish("domotics.device.saved", {"device": device, "previous_id": old_id}, "esp32")
        return device

    def delete_device(self, device_id: str) -> bool:
        data = self.devices_store.load()
        before = len(data.get("devices", []))
        data["devices"] = [d for d in data.get("devices", []) if d.get("id") != device_id]
        self.devices_store.save(data)
        return len(data["devices"]) < before

    def validate_device(self, device: dict[str, Any], previous_id: str | None = None) -> None:
        node_id = str(device.get("node", ""))
        if not any(n.get("id") == node_id for n in self.nodes_store.load().get("nodes", [])):
            raise ValueError(f"El nodo '{node_id}' no existe.")
        pin = int(device.get("pin", -1))
        if pin < 0 or pin > 39:
            raise ValueError("GPIO debe estar entre 0 y 39 para el perfil ESP32 clásico.")
        if pin in self.RESERVED_ESP32_PINS:
            raise ValueError(f"GPIO {pin} está reservado para la memoria flash.")
        device_type = str(device.get("type", ""))
        if device_type not in self.VALID_TYPES:
            raise ValueError(f"Tipo de dispositivo inválido: {device_type}")
        if device_type in {"digital_output", "pwm_output"} and pin in self.INPUT_ONLY_ESP32_PINS:
            raise ValueError(f"GPIO {pin} es solo de entrada.")
        ignored_ids = {str(device.get("id", ""))}
        if previous_id:
            ignored_ids.add(self._slug(previous_id))
        for existing in self.list_devices():
            if existing.get("id") not in ignored_ids and existing.get("node") == node_id and int(existing.get("pin", -2)) == pin:
                raise ValueError(f"GPIO {pin} ya está asignado a '{existing.get('name')}'.")

    def connect(self, node_id: str) -> ActionResult:
        node = self._get_node(node_id)
        if not node:
            return ActionResult.failure(f"No existe el nodo '{node_id}'.")
        if node.get("protocol") == "legacy":
            return ActionResult.success("El nodo legacy usa el enlace serial compatible existente.", node=node)
        if serial is None:
            return ActionResult.failure("PySerial no está instalado.")
        port = str(node.get("port", "")).strip()
        if not port:
            return ActionResult.failure(f"El nodo {node_id} no tiene puerto configurado.")
        with self._connections_lock:
            conn = self._connections.get(node_id)
            if not conn:
                conn = NodeConnection(node_id=node_id, port=port, baudrate=int(node.get("baudrate", 115200)))
                self._connections[node_id] = conn
        with conn.lock:
            try:
                if conn.handle and conn.handle.is_open:
                    return ActionResult.success(f"{node.get('name')} ya está conectado.", node=node)
                conn.handle = serial.Serial(port, conn.baudrate, timeout=0.15, write_timeout=1.0)
                time.sleep(float(node.get("boot_wait", 1.2)))
                conn.handle.reset_input_buffer()
                hello = self._request(conn, {"op": "hello"}, timeout=2.0)
                conn.last_seen = time.time()
                conn.last_error = ""
                self.event_bus.publish("esp32.node.online", {"node": node, "hello": hello}, "esp32")
                return ActionResult.success(f"{node.get('name')} conectado en {port}.", node=node, hello=hello)
            except Exception as exc:
                conn.last_error = str(exc)
                self._close_connection(conn)
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
        node = self._get_node(node_id)
        if not node:
            return ActionResult.failure(f"No existe el nodo '{node_id}'.")
        if node.get("protocol") == "legacy":
            return ActionResult.failure("El firmware legacy no acepta configuración remota. Instala firmware/esp32_node/main.py para modificar pines sin reprogramar.")
        connected = self.connect(node_id)
        if not connected.ok:
            return connected
        devices = [self._firmware_device(d) for d in self.list_devices() if d.get("node") == node_id]
        conn = self._connections[node_id]
        try:
            reply = self._request(conn, {"op": "configure", "devices": devices}, timeout=4.0)
            if not reply.get("ok", False):
                return ActionResult.failure(f"El nodo rechazó la configuración: {reply}")
            return ActionResult.success(f"Configuración enviada a {node.get('name')}: {len(devices)} dispositivos.", reply=reply, devices=devices)
        except Exception as exc:
            return ActionResult.failure(f"No pude sincronizar el nodo: {exc}", error=str(exc))

    def control(self, params: dict[str, Any]) -> ActionResult:
        device_name = str(params.get("device", "")).strip()
        action = self._normalize_action(str(params.get("action", "status")))
        value = params.get("value")
        if action == "list" or self._norm(device_name) in {"todos", "todo", "all", "dispositivos"}:
            return self.list_capability(params)
        device = self.get_device(device_name)
        if not device:
            available = ", ".join(d.get("name", d.get("id", "")) for d in self.list_devices()) or "ninguno"
            return ActionResult.failure(
                f"No encontré el dispositivo '{device_name}'. Configurados: {available}.",
                error="device_not_found",
                devices=self.list_devices(),
            )
        if action not in set(device.get("capabilities", [])) and action not in {"set", "status"}:
            return ActionResult.failure(f"{device['name']} no soporta la acción '{action}'.")
        node = self._get_node(str(device.get("node")))
        if not node:
            return ActionResult.failure(f"El nodo de {device['name']} no existe.")

        if node.get("protocol") == "legacy":
            if not self.legacy_controller:
                return ActionResult.failure("No hay controlador legacy conectado.")
            try:
                raw = self.legacy_controller({"device": device.get("id"), "action": action})
                ok = not str(raw).lower().startswith(("no pude", "error"))
                return ActionResult(ok, str(raw), data={"device": device, "action": action}).finish()
            except Exception as exc:
                return ActionResult.failure(f"Falló el controlador legacy: {exc}", error=str(exc))

        connected = self.connect(node["id"])
        if not connected.ok:
            return connected
        conn = self._connections[node["id"]]
        payload: dict[str, Any] = {"op": action, "device": device["id"]}
        if action == "on":
            payload = {"op": "set", "device": device["id"], "value": 1}
        elif action == "off":
            payload = {"op": "set", "device": device["id"], "value": 0}
        elif action == "status":
            payload["op"] = "get"
        elif action == "set":
            payload["value"] = value
        try:
            reply = self._request(conn, payload, timeout=float(params.get("timeout", 2.0)))
            if not reply.get("ok", False):
                return ActionResult.failure(f"{device['name']} rechazó la orden: {reply.get('error', reply)}", reply=reply)
            state = reply.get("value", reply.get("state"))
            self._last_state[device["id"]] = state
            self.event_bus.publish("domotics.device.changed", {"device": device, "action": action, "state": state, "reply": reply}, "esp32")
            return ActionResult.success(self._human_message(device, action, state), device=device, action=action, state=state, reply=reply)
        except Exception as exc:
            self.disconnect(node["id"])
            return ActionResult.failure(f"No pude controlar {device['name']}: {exc}", error=str(exc))

    def status(self, params: dict[str, Any]) -> ActionResult:
        return self.control({"device": params.get("device"), "action": "status"})

    def list_capability(self, _params: dict[str, Any] | None = None) -> ActionResult:
        devices = self.list_devices()
        if not devices:
            return ActionResult.success("No hay dispositivos domóticos configurados.", devices=[])
        summary = "; ".join(
            f"{d.get('name', d.get('id'))} (GPIO {d.get('pin')}, alias: {', '.join(d.get('aliases', [])) or 'ninguno'})"
            for d in devices
        )
        return ActionResult.success(f"Dispositivos configurados: {summary}.", devices=devices)

    def describe_catalog(self) -> str:
        devices = self.list_devices()
        if not devices:
            return "No hay dispositivos domóticos configurados."
        lines = []
        for device in devices:
            aliases = ", ".join(device.get("aliases", [])) or "sin alias"
            actions = ", ".join(device.get("capabilities", [])) or "status"
            lines.append(
                f"- id={device.get('id')}; nombre={device.get('name')}; alias={aliases}; "
                f"GPIO={device.get('pin')}; tipo={device.get('type')}; acciones={actions}"
            )
        return "\n".join(lines)

    def activate_scene(self, params: dict[str, Any]) -> ActionResult:
        name = self._norm(str(params.get("scene", "")))
        scene = None
        for item in self.scenes_store.load().get("scenes", []):
            if name in {self._norm(item.get("id", "")), self._norm(item.get("name", ""))}:
                scene = item
                break
        if not scene:
            return ActionResult.failure(f"No existe la escena '{params.get('scene', '')}'.")
        results = []
        failures = []
        for target in scene.get("targets", []):
            result = self.control(target)
            results.append(result.to_dict())
            if not result.ok:
                failures.append(result.message)
        if failures:
            answer = ActionResult.success(f"Escena {scene['name']} aplicada parcialmente.", scene=scene, results=results)
            answer.warnings.extend(failures)
            return answer
        return ActionResult.success(f"Escena {scene['name']} aplicada.", scene=scene, results=results)


    def _rename_device_references(self, old_id: str, new_id: str) -> None:
        if not old_id or old_id == new_id:
            return
        scenes = self.scenes_store.load()
        changed = False
        for scene in scenes.get("scenes", []):
            for target in scene.get("targets", []):
                if target.get("device") == old_id:
                    target["device"] = new_id
                    changed = True
        if changed:
            self.scenes_store.save(scenes)

    def shutdown(self) -> None:
        with self._connections_lock:
            node_ids = list(self._connections)
        for node_id in node_ids:
            self.disconnect(node_id)

    def nodes_status(self, _params: dict[str, Any]) -> ActionResult:
        nodes = self.list_nodes()
        online = sum(1 for n in nodes if n.get("online"))
        return ActionResult.success(f"Nodos ESP32: {online} en línea de {len(nodes)} configurados.", nodes=nodes, ports=self.list_ports())

    def poll_nodes(self) -> list[dict[str, Any]]:
        # Non-invasive health report. It does not auto-open every port.
        return self.list_nodes()

    def _request(self, conn: NodeConnection, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        request_id = str(uuid.uuid4())[:8]
        packet = dict(payload)
        packet["id"] = request_id
        raw = (json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with conn.lock:
            conn.handle.reset_input_buffer()
            conn.handle.write(raw)
            conn.handle.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = conn.handle.readline()
                if not line:
                    continue
                try:
                    message = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if message.get("event"):
                    self.event_bus.publish(f"esp32.event.{message['event']}", message, conn.node_id)
                    continue
                if message.get("reply_to") == request_id or message.get("id") == request_id:
                    conn.last_seen = time.time()
                    return message
            raise TimeoutError(f"El nodo {conn.node_id} no respondió a {payload.get('op')}.")

    @staticmethod
    def _close_connection(conn: NodeConnection) -> None:
        try:
            if conn.handle:
                conn.handle.close()
        except Exception:
            pass
        conn.handle = None

    def _get_node(self, node_id: str) -> dict[str, Any] | None:
        for node in self.nodes_store.load().get("nodes", []):
            if node.get("id") == node_id:
                return dict(node)
        return None

    @staticmethod
    def _firmware_device(device: dict[str, Any]) -> dict[str, Any]:
        return {k: device.get(k) for k in ("id", "pin", "type", "active_low", "default_state", "capabilities")}

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
            "prender": "on", "encender": "on", "activar": "on", "on": "on",
            "apagar": "off", "desactivar": "off", "off": "off",
            "cambiar": "toggle", "alternar": "toggle", "toggle": "toggle",
            "estado": "status", "consultar": "status", "leer": "status", "status": "status",
            "nivel": "set", "velocidad": "set", "potencia": "set", "set": "set",
            "listar": "list", "lista": "list", "dispositivos": "list", "list": "list",
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
        if action in {"status", "get"}:
            return f"Estado de {name}: {state}."
        return f"{name} actualizado a {state}."

    @staticmethod
    def _norm(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text)
        stopwords = {"el", "la", "los", "las", "un", "una", "mi", "mis", "del", "de"}
        words = [word for word in text.split() if word not in stopwords]
        return " ".join(words)

    @staticmethod
    def _slug(value: str) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
        return "_".join(part for part in raw.split("_") if part) or "item"
