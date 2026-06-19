from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "config"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    raw = input("Ruta de la instalación anterior: ").strip().strip('"')
    source = Path(raw).expanduser().resolve()
    source_config = source / "config"
    if not source_config.is_dir():
        print("[ERROR] No encontré la carpeta config en esa ruta.")
        return 1

    backup = ROOT / "backups" / datetime.now().strftime("config_%Y%m%d_%H%M%S")
    backup.mkdir(parents=True, exist_ok=True)
    for current in DEST.glob("*.json"):
        shutil.copy2(current, backup / current.name)

    copied = []
    for filename in ("api_keys.json", "integrations.json", "media_aliases.json"):
        src = source_config / filename
        if src.exists():
            # Parse before copying to avoid moving broken JSON.
            value = load_json(src)
            save_json(DEST / filename, value)
            copied.append(filename)

    nodes_src = source_config / "nodes.json"
    if nodes_src.exists():
        value = load_json(nodes_src)
        for node in value.get("nodes", []):
            node["protocol"] = "prp-node-v1"
            node.setdefault("auto_sync", True)
        save_json(DEST / "nodes.json", value)
        copied.append("nodes.json")

    for filename in ("devices.json", "scenes.json", "tasks.json"):
        src = source_config / filename
        if src.exists():
            value = load_json(src)
            save_json(DEST / filename, value)
            copied.append(filename)

    print("[OK] Configuración importada:", ", ".join(copied) or "ningún archivo compatible")
    print("Respaldo de la configuración nueva:", backup)
    print("No se copiaron archivos Python ni firmware antiguos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
