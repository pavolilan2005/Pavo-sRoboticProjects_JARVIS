from __future__ import annotations
import asyncio,sys,threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from prp.core.controller import Controller
from prp.services.gemini_live import GeminiLiveService
from prp.ui.main_window import MainWindow

def main():
    root=Path(__file__).resolve().parent
    app=QApplication(sys.argv);app.setApplicationName("Pavo's Robotic Projects — JARVIS")
    controller=Controller(root);window=MainWindow(controller);live=GeminiLiveService(controller,window.callbacks())
    ready=threading.Event();holder={}
    def runner():
        async def boot():
            holder['loop']=asyncio.get_running_loop();ready.set()
            controller.audio.start(live.push_mic,lambda level,rms:window.bridge.level.emit(level,rms))
            await live.run()
        asyncio.run(boot())
    threading.Thread(target=runner,daemon=True).start();ready.wait(5);window.attach_live(live,holder.get('loop'));window.show();sys.exit(app.exec())
if __name__=='__main__':main()
