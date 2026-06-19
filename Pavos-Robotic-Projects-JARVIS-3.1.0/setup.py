from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if sys.version_info < (3, 11):
    raise SystemExit("JARVIS necesita Python 3.11 o superior.")

print("Instalando dependencias...")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
    check=True,
)

print("Instalando Chromium para Playwright...")
subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)

print("\nInstalación completa. Ejecuta: python main.py")
