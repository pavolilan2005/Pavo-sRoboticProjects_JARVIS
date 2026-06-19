"""Pavo's Robotic Projects generic ESP32 node firmware (MicroPython).

Protocol: newline-delimited JSON over USB serial.
The PC sends logical device IDs; this firmware stores the pin map in
``jarvis_node_config.json`` so GPIO changes do not require editing this file.
"""

try:
    import ujson as json
except ImportError:
    import json

import sys
import time
from machine import Pin, PWM, ADC

try:
    import uselect as select
except ImportError:
    import select

CONFIG_FILE = "jarvis_node_config.json"
PROTOCOL = "jarvis-node-v1"
FIRMWARE_VERSION = "1.1.0"
RESERVED_PINS = {6, 7, 8, 9, 10, 11}
INPUT_ONLY_PINS = {34, 35, 36, 39}

DEFAULT_CONFIG = {"version": 1, "devices": []}


class Device:
    def __init__(self, spec):
        self.spec = spec
        self.id = str(spec["id"])
        self.pin_number = int(spec["pin"])
        self.kind = str(spec.get("type", "digital_output"))
        self.active_low = bool(spec.get("active_low", False))
        self.default_state = spec.get("default_state", 0)
        self.last_value = None
        self.io = None
        self._configure()

    def _configure(self):
        validate_spec(self.spec)
        if self.kind == "digital_output":
            initial = self._physical(self.default_state)
            self.io = Pin(self.pin_number, Pin.OUT, value=int(bool(initial)))
            self.last_value = int(bool(self.default_state))
        elif self.kind == "digital_input":
            pull_name = str(self.spec.get("pull", "none")).lower()
            pull = Pin.PULL_UP if pull_name == "up" else Pin.PULL_DOWN if pull_name == "down" else None
            self.io = Pin(self.pin_number, Pin.IN, pull)
            self.last_value = self.read()
        elif self.kind == "pwm_output":
            pin = Pin(self.pin_number, Pin.OUT)
            self.io = PWM(pin, freq=int(self.spec.get("frequency", 1000)))
            self.write(self.default_state)
        elif self.kind == "analog_input":
            self.io = ADC(Pin(self.pin_number))
            try:
                self.io.atten(ADC.ATTN_11DB)
            except Exception:
                pass
            self.last_value = self.read()
        else:
            raise ValueError("unsupported device type: " + self.kind)

    def _physical(self, logical):
        value = int(bool(logical))
        return 1 - value if self.active_low else value

    def _logical(self, physical):
        value = int(bool(physical))
        return 1 - value if self.active_low else value

    def read(self):
        if self.kind == "digital_output" or self.kind == "digital_input":
            value = self._logical(self.io.value())
        elif self.kind == "pwm_output":
            value = self.last_value if self.last_value is not None else 0
        elif self.kind == "analog_input":
            try:
                value = self.io.read_u16()
            except AttributeError:
                value = self.io.read()
        else:
            value = None
        self.last_value = value
        return value

    def write(self, value):
        if self.kind == "digital_output":
            logical = int(bool(value))
            self.io.value(self._physical(logical))
            self.last_value = logical
            return logical
        if self.kind == "pwm_output":
            level = max(0, min(100, int(value)))
            duty = int(level * 65535 / 100)
            try:
                self.io.duty_u16(duty)
            except AttributeError:
                self.io.duty(int(level * 1023 / 100))
            self.last_value = level
            return level
        raise ValueError("device is not writable")

    def toggle(self):
        if self.kind != "digital_output":
            raise ValueError("toggle only works on digital outputs")
        return self.write(0 if self.read() else 1)

    def deinit(self):
        try:
            if self.kind == "pwm_output":
                self.io.deinit()
        except Exception:
            pass


def validate_spec(spec):
    device_id = str(spec.get("id", "")).strip()
    if not device_id:
        raise ValueError("device id is required")
    pin = int(spec.get("pin", -1))
    if pin < 0 or pin > 39:
        raise ValueError("pin must be between 0 and 39")
    if pin in RESERVED_PINS:
        raise ValueError("pin {} is reserved for flash".format(pin))
    kind = str(spec.get("type", "digital_output"))
    if kind in ("digital_output", "pwm_output") and pin in INPUT_ONLY_PINS:
        raise ValueError("pin {} is input only".format(pin))


def load_config():
    try:
        with open(CONFIG_FILE, "r") as handle:
            data = json.loads(handle.read())
            if isinstance(data.get("devices"), list):
                return data
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    temp = CONFIG_FILE + ".tmp"
    with open(temp, "w") as handle:
        handle.write(json.dumps(config))
    try:
        import os
        try:
            os.remove(CONFIG_FILE)
        except OSError:
            pass
        os.rename(temp, CONFIG_FILE)
    except Exception:
        with open(CONFIG_FILE, "w") as handle:
            handle.write(json.dumps(config))


def emit(payload):
    # MicroPython's TextIOWrapper does not always expose flush(). A newline is
    # enough for the USB REPL/serial transport and avoids crashing the node.
    try:
        sys.stdout.write(json.dumps(payload) + "\n")
    except Exception:
        try:
            print(json.dumps(payload))
        except Exception:
            pass


def reply(request, ok=True, **extra):
    payload = {"reply_to": request.get("id"), "ok": bool(ok)}
    payload.update(extra)
    emit(payload)


class Node:
    def __init__(self):
        self.devices = {}
        self.config = load_config()
        self.configure(self.config.get("devices", []), persist=False)
        self.last_poll = time.ticks_ms()

    def configure(self, specs, persist=True):
        pins = set()
        ids = set()
        for spec in specs:
            validate_spec(spec)
            pin = int(spec["pin"])
            device_id = str(spec["id"])
            if pin in pins:
                raise ValueError("duplicate pin {}".format(pin))
            if device_id in ids:
                raise ValueError("duplicate device id {}".format(device_id))
            pins.add(pin)
            ids.add(device_id)

        new_devices = {}
        try:
            for spec in specs:
                new_devices[str(spec["id"])] = Device(spec)
        except Exception:
            for device in new_devices.values():
                device.deinit()
            raise

        for device in self.devices.values():
            device.deinit()
        self.devices = new_devices
        self.config = {"version": 1, "devices": specs}
        if persist:
            save_config(self.config)

    def handle(self, request):
        op = str(request.get("op", ""))
        try:
            if op == "hello":
                reply(
                    request,
                    True,
                    protocol=PROTOCOL,
                    firmware=FIRMWARE_VERSION,
                    device_count=len(self.devices),
                    uptime_ms=time.ticks_ms(),
                )
            elif op == "configure":
                specs = request.get("devices") or []
                self.configure(specs, persist=True)
                reply(request, True, configured=len(specs))
            elif op in ("get", "status"):
                device = self._device(request)
                reply(request, True, device=device.id, value=device.read())
            elif op == "set":
                device = self._device(request)
                value = device.write(request.get("value", 0))
                reply(request, True, device=device.id, value=value)
            elif op == "toggle":
                device = self._device(request)
                value = device.toggle()
                reply(request, True, device=device.id, value=value)
            elif op == "list":
                reply(request, True, devices=[d.spec for d in self.devices.values()])
            elif op == "ping":
                reply(request, True, pong=True, uptime_ms=time.ticks_ms())
            else:
                reply(request, False, error="unknown operation: " + op)
        except Exception as exc:
            reply(request, False, error=str(exc))

    def _device(self, request):
        device_id = str(request.get("device", ""))
        if device_id not in self.devices:
            raise ValueError("unknown device: " + device_id)
        return self.devices[device_id]

    def poll_inputs(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_poll) < 100:
            return
        self.last_poll = now
        for device in self.devices.values():
            if device.kind not in ("digital_input", "analog_input"):
                continue
            previous = device.last_value
            value = device.read()
            if value != previous:
                emit({"event": "device_changed", "device": device.id, "value": value, "timestamp_ms": now})


node = Node()
emit({"event": "boot", "protocol": PROTOCOL, "firmware": FIRMWARE_VERSION, "devices": len(node.devices)})

poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

while True:
    node.poll_inputs()
    events = poller.poll(20)
    if not events:
        continue
    try:
        line = sys.stdin.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        if not isinstance(request, dict):
            emit({"ok": False, "error": "request must be a JSON object"})
            continue
        node.handle(request)
    except Exception as exc:
        emit({"ok": False, "error": str(exc)})
