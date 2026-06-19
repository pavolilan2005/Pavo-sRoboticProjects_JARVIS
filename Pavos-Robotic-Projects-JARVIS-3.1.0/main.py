from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from prp.core.controller import Controller
from prp.services.gemini_live import GeminiLiveService
from prp.ui.main_window import MainWindow


def main() -> int:
    root = Path(__file__).resolve().parent
    app = QApplication(sys.argv)
    app.setApplicationName("Pavo's Robotic Projects — JARVIS")

    controller = Controller(root)
    window = MainWindow(controller)
    live = GeminiLiveService(controller, window.callbacks())

    loop_ready = threading.Event()
    holder: dict[str, object] = {}

    def runner() -> None:
        async def boot() -> None:
            loop = asyncio.get_running_loop()
            holder["loop"] = loop
            loop_ready.set()
            try:
                try:
                    controller.audio.start(
                        live.push_mic,
                        lambda level, rms: window.bridge.level.emit(level, rms),
                    )
                except Exception as error:
                    window.bridge.log.emit(
                        'No se pudo abrir el micrófono: '
                        f'{type(error).__name__}: {error}. '
                        'Selecciona otro dispositivo en AUDIO y pulsa GUARDAR Y REINICIAR AUDIO.'
                    )
                await live.run()
            finally:
                # El micrófono debe detenerse antes de cerrar el event loop.
                controller.audio.stop()

        try:
            asyncio.run(boot())
        except Exception as error:
            window.bridge.log.emit(
                f"Error fatal del núcleo: {type(error).__name__}: {error}"
            )
            window.bridge.state.emit("OFFLINE")

    worker = threading.Thread(
        target=runner,
        name="PRP-Async-Core",
        daemon=True,
    )
    worker.start()
    loop_ready.wait(5)

    window.attach_live(live, holder.get("loop"))

    def shutdown() -> None:
        # Primero impedimos nuevos envíos de audio; luego cancelamos Gemini.
        controller.audio.stop()
        live.request_stop()
        controller.serial.close()

    app.aboutToQuit.connect(shutdown)
    window.show()
    exit_code = app.exec()

    shutdown()
    worker.join(timeout=2.5)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
