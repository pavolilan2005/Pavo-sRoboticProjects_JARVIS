from __future__ import annotations
import asyncio
import sys
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from prp.services.audio_service import AudioService
from prp.services.gemini_live import GeminiLiveService
from prp.ui.main_window import MainWindow

ROOT=Path(__file__).resolve().parent

def main():
    app=QApplication(sys.argv)
    window=MainWindow(ROOT)
    settings=window.controller.config.load("app.json",{}) or {}
    audio=AudioService(settings,window.log)
    live=GeminiLiveService(window.controller,audio,window.set_state,window.transcript_line,window.log)
    ready=threading.Event(); holder={}
    def runner():
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop); holder["loop"]=loop; ready.set(); loop.run_until_complete(live.run())
    thread=threading.Thread(target=runner,daemon=True,name="prp-live"); thread.start(); ready.wait(2); window.attach_live(live,holder.get("loop")); window.show(); sys.exit(app.exec())
if __name__=="__main__": main()
