# Pavo's Robotic Projects - ESP32 configurable node
# MicroPython, JSON Lines over USB serial
import sys, json, time
try:
    from machine import Pin, PWM, ADC
except ImportError:
    Pin = PWM = ADC = None

CONFIG_FILE = "prp_node_config.json"
FIRMWARE = "1.0.0"
devices = {}
objects = {}


def emit(payload):
    try:
        sys.stdout.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def load_config():
    global devices
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            devices = {d["id"]: d for d in data.get("devices", [])}
    except Exception:
        devices = {}
    apply_config()


def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({"devices": list(devices.values())}, f)


def apply_config():
    global objects
    objects = {}
    for device_id, d in devices.items():
        try:
            pin_no = int(d["pin"])
            kind = d.get("type", "digital_output")
            if kind == "digital_output":
                obj = Pin(pin_no, Pin.OUT)
                off = 1 if d.get("active_low", False) else 0
                obj.value(off)
            elif kind == "digital_input":
                pull = Pin.PULL_UP if d.get("pull", "up") == "up" else Pin.PULL_DOWN
                obj = Pin(pin_no, Pin.IN, pull)
            elif kind == "pwm_output":
                obj = PWM(Pin(pin_no), freq=int(d.get("frequency", 1000)), duty_u16=0)
            elif kind == "analog_input":
                obj = ADC(Pin(pin_no))
                try: obj.atten(ADC.ATTN_11DB)
                except Exception: pass
            else:
                continue
            objects[device_id] = obj
        except Exception as exc:
            emit({"event":"config_error","device_id":device_id,"message":str(exc)})


def logical_value(device_id):
    d = devices[device_id]; obj = objects[device_id]; kind = d.get("type")
    if kind in ("digital_output", "digital_input"):
        raw = obj.value()
        return (not bool(raw)) if d.get("active_low", False) else bool(raw)
    if kind == "analog_input": return obj.read()
    return None


def set_device(device_id, action, value=None):
    if device_id not in devices or device_id not in objects:
        raise ValueError("unknown_device")
    d = devices[device_id]; obj = objects[device_id]; kind = d.get("type", "")
    if kind == "digital_output":
        current = logical_value(device_id)
        logical = (not current) if action == "toggle" else action in ("on", "set") and (True if value is None else bool(value))
        raw = (not logical) if d.get("active_low", False) else logical
        obj.value(1 if raw else 0)
        return logical
    if kind == "pwm_output":
        level = max(0, min(100, int(value if value is not None else 0)))
        obj.duty_u16(round(level * 65535 / 100))
        return level
    if action in ("read", "status"):
        return logical_value(device_id)
    raise ValueError("unsupported_action")


def handle(msg):
    request_id = msg.get("request_id")
    cmd = msg.get("cmd")
    try:
        if cmd == "ping":
            return {"ok":True,"message":"pong","firmware":FIRMWARE,"request_id":request_id}
        if cmd == "configure":
            global devices
            devices = {d["id"]: d for d in msg.get("devices", [])}
            save_config(); apply_config()
            return {"ok":True,"message":"configuration_saved","count":len(devices),"request_id":request_id}
        if cmd == "device":
            result = set_device(msg["device_id"], msg.get("action", "status"), msg.get("value"))
            return {"ok":True,"message":"device_updated","device_id":msg["device_id"],"value":result,"request_id":request_id}
        if cmd == "list":
            return {"ok":True,"message":"device_list","devices":list(devices.values()),"request_id":request_id}
        raise ValueError("unknown_command")
    except Exception as exc:
        return {"ok":False,"message":str(exc),"request_id":request_id}

load_config()
emit({"event":"boot","brand":"Pavo's Robotic Projects","protocol":"prp-node-v1","firmware":FIRMWARE,"devices":len(devices)})
while True:
    try:
        line = sys.stdin.readline()
        if not line:
            time.sleep_ms(20); continue
        emit(handle(json.loads(line)))
    except Exception as exc:
        emit({"ok":False,"message":"invalid_request","detail":str(exc)})
