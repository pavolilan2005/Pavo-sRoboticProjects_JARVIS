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


def main() -> None:
    root = Tk()
    root.withdraw()
    selected = filedialog.askdirectory(title="Selecciona la carpeta de tu JARVIS anterior")
    if not selected:
        return
    old = Path(selected)
    copied: list[str] = []
    candidates = [
        (old / "config" / "api_keys.json", ROOT / "config" / "api_keys.json"),
        (old / "memory" / "long_term.json", ROOT / "memory" / "long_term.json"),
        (old / "config" / "domotics_devices.json", ROOT / "config" / "domotics_devices.json"),
        (old / "config" / "esp32_serial.json", ROOT / "config" / "esp32_serial.json"),
    ]
    for source, destination in candidates:
        if copy_if_exists(source, destination):
            copied.append(str(destination.relative_to(ROOT)))
    if copied:
        messagebox.showinfo(
            "Migración terminada",
            "Se copiaron:\n\n" + "\n".join(copied) + "\n\nLas rutinas y dispositivos NEXUS nuevos no fueron reemplazados.",
        )
    else:
        messagebox.showwarning(
            "Sin datos",
            "No encontré archivos compatibles en la carpeta seleccionada.",
        )


if __name__ == "__main__":
    main()
