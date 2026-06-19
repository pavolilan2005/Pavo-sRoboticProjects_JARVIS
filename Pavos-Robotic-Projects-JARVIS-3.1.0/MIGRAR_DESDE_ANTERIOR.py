from __future__ import annotations

import json
import shutil
from pathlib import Path
from tkinter import Tk, filedialog, messagebox

ROOT = Path(__file__).resolve().parent


def copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def migrate_old_port(old: Path) -> bool:
    old_serial = old / "config" / "esp32_serial.json"
    target = ROOT / "config" / "nodes.json"
    if not old_serial.exists() or not target.exists():
        return False
    try:
        port = str(json.loads(old_serial.read_text(encoding="utf-8")).get("port", "")).strip()
        data = json.loads(target.read_text(encoding="utf-8"))
        nodes = data.setdefault("nodes", [])
        if not port or not nodes:
            return False
        nodes[0]["port"] = port
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False



def normalize_nodes() -> bool:
    target = ROOT / "config" / "nodes.json"
    if not target.exists():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        changed = False
        for node in data.get("nodes", []):
            if node.get("protocol") != "jarvis-node-v1":
                node["protocol"] = "jarvis-node-v1"
                changed = True
            node.setdefault("transport", "serial")
            node.setdefault("baudrate", 115200)
            node.setdefault("enabled", True)
        if changed:
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed
    except Exception:
        return False

def main() -> None:
    root = Tk()
    root.withdraw()
    selected = filedialog.askdirectory(title="Selecciona la carpeta de tu JARVIS anterior")
    if not selected:
        return

    old = Path(selected)
    copied: list[str] = []
    candidates = [
        "config/api_keys.json",
        "config/audio.json",
        "config/integrations.json",
        "config/nodes.json",
        "config/devices.json",
        "config/scenes.json",
        "config/routines.json",
        "config/modes.json",
        "config/automations.json",
        "memory/long_term.json",
    ]

    for relative in candidates:
        source = old / relative
        destination = ROOT / relative
        if copy_if_exists(source, destination):
            copied.append(relative)

    if "config/nodes.json" not in copied and migrate_old_port(old):
        copied.append("config/nodes.json (puerto migrado)")

    if normalize_nodes():
        copied.append("config/nodes.json (protocolo actualizado)")

    if copied:
        messagebox.showinfo(
            "Migración terminada",
            "Se copiaron:\n\n" + "\n".join(copied) +
            "\n\nNo se copiaron archivos Python ni componentes antiguos.",
        )
    else:
        messagebox.showwarning(
            "Sin datos",
            "No encontré archivos compatibles en la carpeta seleccionada.",
        )


if __name__ == "__main__":
    main()
