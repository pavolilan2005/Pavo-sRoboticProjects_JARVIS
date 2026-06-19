from __future__ import annotations
import asyncio
import json
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)
from prp.core.controller import PrpController

class UiBridge(QObject):
    log_signal = pyqtSignal(str)
    transcript_signal = pyqtSignal(str, str)
    state_signal = pyqtSignal(str)

class MainWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__()
        self.root_path = root
        self.bridge = UiBridge()
        self.bridge.log_signal.connect(self._append_log)
        self.bridge.transcript_signal.connect(self._append_transcript)
        self.bridge.state_signal.connect(self._set_state)
        self.controller = PrpController(root, self.log)
        self.live = None
        self.async_loop = None
        self.setWindowTitle("Pavo's Robotic Projects Assistant")
        self.resize(1100, 720)
        self._build()
        self.refresh_all()

    def _build(self):
        tabs = QTabWidget(); self.setCentralWidget(tabs)
        # Assistant
        assistant = QWidget(); layout = QVBoxLayout(assistant)
        head = QHBoxLayout(); self.state_label = QLabel("OFFLINE"); head.addWidget(QLabel("Pavo's Robotic Projects — JARVIS")); head.addStretch(); head.addWidget(self.state_label); layout.addLayout(head)
        self.transcript = QTextEdit(); self.transcript.setReadOnly(True); layout.addWidget(self.transcript)
        row = QHBoxLayout(); self.command = QLineEdit(); self.command.setPlaceholderText("Escribe una orden..."); send = QPushButton("Enviar"); send.clicked.connect(self._send_text); row.addWidget(self.command); row.addWidget(send); layout.addLayout(row)
        tabs.addTab(assistant, "Asistente")
        # Nodes
        nodes = QWidget(); nl = QVBoxLayout(nodes); nbar = QHBoxLayout(); nadd=QPushButton("Agregar nodo"); nadd.clicked.connect(self.add_node); nsave=QPushButton("Guardar nodos"); nsave.clicked.connect(self.save_nodes); nbar.addWidget(nadd); nbar.addWidget(nsave); nbar.addStretch(); nl.addLayout(nbar)
        self.node_table=QTableWidget(0,4); self.node_table.setHorizontalHeaderLabels(["ID","Nombre","Puerto","Baudrate"]); nl.addWidget(self.node_table); tabs.addTab(nodes,"Nodos ESP32")
        # Devices
        devices = QWidget(); dl = QVBoxLayout(devices); controls = QHBoxLayout(); refresh = QPushButton("Actualizar"); refresh.clicked.connect(self.refresh_devices); add = QPushButton("Agregar dispositivo"); add.clicked.connect(self.add_device); sync = QPushButton("Sincronizar nodo"); sync.clicked.connect(self.sync_selected_node); save_dev=QPushButton("Guardar dispositivos"); save_dev.clicked.connect(self._save_device_table); controls.addWidget(refresh); controls.addWidget(add); controls.addWidget(save_dev); controls.addWidget(sync); controls.addStretch(); dl.addLayout(controls)
        self.device_table = QTableWidget(0, 7); self.device_table.setHorizontalHeaderLabels(["ID","Nombre","Nodo","GPIO","Tipo","Activo bajo","Alias"]); dl.addWidget(self.device_table); tabs.addTab(devices, "Domótica")
        # Routines
        routines = QWidget(); rl=QVBoxLayout(routines); self.routine_list=QListWidget(); rl.addWidget(self.routine_list); run=QPushButton("Ejecutar rutina"); run.clicked.connect(self.run_selected_routine); rl.addWidget(run); tabs.addTab(routines,"Rutinas")
        # Integrations
        integrations=QWidget(); il=QFormLayout(integrations)
        self.sp_id=QLineEdit(); self.sp_secret=QLineEdit(); self.sp_secret.setEchoMode(QLineEdit.EchoMode.Password); self.obs_host=QLineEdit(); self.obs_port=QSpinBox(); self.obs_port.setMaximum(65535); self.obs_pass=QLineEdit(); self.obs_pass.setEchoMode(QLineEdit.EchoMode.Password)
        il.addRow("Spotify Client ID",self.sp_id); il.addRow("Spotify Client Secret",self.sp_secret); il.addRow("OBS host",self.obs_host); il.addRow("OBS puerto",self.obs_port); il.addRow("OBS contraseña",self.obs_pass)
        save=QPushButton("Guardar integraciones"); save.clicked.connect(self.save_integrations); il.addRow(save); tabs.addTab(integrations,"Integraciones")
        # Audio
        audio=QWidget(); al=QFormLayout(audio); self.sensitivity=QSpinBox(); self.sensitivity.setRange(1,100); al.addRow("Sensibilidad del micrófono",self.sensitivity); save_audio=QPushButton("Guardar sensibilidad"); save_audio.clicked.connect(self.save_audio); al.addRow(save_audio); tabs.addTab(audio,"Audio")
        # Multimedia aliases
        media=QWidget(); ml=QVBoxLayout(media); mbar=QHBoxLayout(); madd=QPushButton("Agregar alias"); madd.clicked.connect(self.add_media_alias); msave=QPushButton("Guardar alias"); msave.clicked.connect(self.save_media_aliases); mbar.addWidget(madd); mbar.addWidget(msave); mbar.addStretch(); ml.addLayout(mbar)
        self.media_table=QTableWidget(0,5); self.media_table.setHorizontalHeaderLabels(["ID","Frases (coma)","Tipo","Destino","URI opcional"]); ml.addWidget(self.media_table); tabs.addTab(media,"Multimedia")
        # Tasks
        tasks=QWidget(); tl=QVBoxLayout(tasks); self.task_list=QListWidget(); tl.addWidget(self.task_list); trow=QHBoxLayout(); self.task_title=QLineEdit(); self.task_title.setPlaceholderText("Nueva tarea"); tadd=QPushButton("Agregar"); tadd.clicked.connect(self.add_task); trow.addWidget(self.task_title); trow.addWidget(tadd); tl.addLayout(trow); tabs.addTab(tasks,"Tareas")
        # Logs
        logs=QWidget(); ll=QVBoxLayout(logs); self.logs=QTextEdit(); self.logs.setReadOnly(True); ll.addWidget(self.logs); tabs.addTab(logs,"Actividad")

    def attach_live(self, live, loop): self.live=live; self.async_loop=loop
    def log(self, text:str): self.bridge.log_signal.emit(text)
    def transcript_line(self, who:str,text:str): self.bridge.transcript_signal.emit(who,text)
    def set_state(self,state:str): self.bridge.state_signal.emit(state)
    def _append_log(self,text): self.logs.append(text)
    def _append_transcript(self,who,text): self.transcript.append(f"<b>{who}:</b> {text}")
    def _set_state(self,state): self.state_label.setText(state)
    def _send_text(self):
        text=self.command.text().strip(); self.command.clear()
        if text and self.live and self.async_loop:
            asyncio.run_coroutine_threadsafe(self.live.send_text(text), self.async_loop)
    def refresh_all(self):
        self.refresh_nodes(); self.refresh_devices(); self.refresh_routines(); self.refresh_media_aliases(); self.refresh_tasks(); self.load_integrations(); app=self.controller.config.load("app.json",{}) or {}; self.sensitivity.setValue(int(app.get("microphone",{}).get("sensitivity",78)))
    def refresh_nodes(self):
        data=(self.controller.config.load("nodes.json",{}) or {}).get("nodes",[]); self.node_table.setRowCount(len(data))
        for r,n in enumerate(data):
            for c,v in enumerate([n.get("id",""),n.get("name",""),n.get("port",""),str(n.get("baudrate",115200))]): self.node_table.setItem(r,c,QTableWidgetItem(v))
    def add_node(self):
        r=self.node_table.rowCount(); self.node_table.insertRow(r)
        for c,v in enumerate([f"esp32_{r+1}",f"ESP32 {r+1}","COM6","115200"]): self.node_table.setItem(r,c,QTableWidgetItem(v))
    def save_nodes(self):
        nodes=[]
        for r in range(self.node_table.rowCount()):
            get=lambda c:(self.node_table.item(r,c).text().strip() if self.node_table.item(r,c) else "")
            try: baud=int(get(3) or 115200)
            except ValueError: baud=115200
            if get(0): nodes.append({"id":get(0),"name":get(1),"port":get(2),"baudrate":baud})
        self.controller.config.save("nodes.json",{"nodes":nodes}); QMessageBox.information(self,"Nodos","Nodos guardados.")
    def refresh_devices(self):
        data=(self.controller.config.load("devices.json",{}) or {}).get("devices",[]); self.device_table.setRowCount(len(data))
        for r,d in enumerate(data):
            vals=[d.get("id",""),d.get("name",""),d.get("node_id",""),str(d.get("pin","")),d.get("type",""),str(d.get("active_low",False)),", ".join(d.get("aliases",[]))]
            for c,v in enumerate(vals): self.device_table.setItem(r,c,QTableWidgetItem(v))
    def add_device(self):
        row=self.device_table.rowCount(); self.device_table.insertRow(row)
        defaults=[f"device_{row+1}","Nuevo dispositivo","esp32_habitacion","23","digital_output","False",""]
        for c,v in enumerate(defaults): self.device_table.setItem(row,c,QTableWidgetItem(v))
        self._save_device_table()
    def _save_device_table(self):
        items=[]
        for r in range(self.device_table.rowCount()):
            get=lambda c:(self.device_table.item(r,c).text().strip() if self.device_table.item(r,c) else "")
            try: pin=int(get(3))
            except ValueError: continue
            items.append({"id":get(0),"name":get(1),"node_id":get(2),"pin":pin,"type":get(4) or "digital_output","active_low":get(5).lower() in {"true","1","si","sí"},"aliases":[x.strip() for x in get(6).split(",") if x.strip()]})
        self.controller.config.save("devices.json",{"devices":items})
    def sync_selected_node(self):
        self._save_device_table(); row=self.device_table.currentRow()
        if row<0: QMessageBox.information(self,"Nodo","Selecciona un dispositivo del nodo a sincronizar."); return
        node=self.device_table.item(row,2).text();
        if self.async_loop: asyncio.run_coroutine_threadsafe(self.controller.execute("node.sync",{"node_id":node}),self.async_loop)
    def refresh_routines(self):
        self.routine_list.clear()
        for r in self.controller.routines.definitions(): self.routine_list.addItem(f"{r.get('id')} — {r.get('name')}")
    def run_selected_routine(self):
        item=self.routine_list.currentItem()
        if item and self.async_loop:
            rid=item.text().split(" — ",1)[0]; asyncio.run_coroutine_threadsafe(self.controller.execute("routine.run",{"routine_id_or_alias":rid}),self.async_loop)
    def refresh_media_aliases(self):
        data=(self.controller.config.load("media_aliases.json",{}) or {}).get("aliases",[]); self.media_table.setRowCount(len(data))
        for r,a in enumerate(data):
            vals=[a.get("id",""),", ".join(a.get("phrases",[])),a.get("type","playlist"),a.get("target",""),a.get("uri","")]
            for c,v in enumerate(vals): self.media_table.setItem(r,c,QTableWidgetItem(str(v)))
    def add_media_alias(self):
        r=self.media_table.rowCount(); self.media_table.insertRow(r)
        for c,v in enumerate([f"alias_{r+1}","", "playlist", "", ""]): self.media_table.setItem(r,c,QTableWidgetItem(v))
    def save_media_aliases(self):
        aliases=[]
        for r in range(self.media_table.rowCount()):
            get=lambda c:(self.media_table.item(r,c).text().strip() if self.media_table.item(r,c) else "")
            if get(0): aliases.append({"id":get(0),"phrases":[x.strip() for x in get(1).split(",") if x.strip()],"type":get(2) or "playlist","target":get(3),"uri":get(4)})
        self.controller.config.save("media_aliases.json",{"aliases":aliases}); QMessageBox.information(self,"Multimedia","Alias guardados.")
    def refresh_tasks(self):
        self.task_list.clear()
        for t in (self.controller.config.load("tasks.json",{}) or {}).get("tasks",[]):
            self.task_list.addItem(("✓ " if t.get("done") else "• ")+t.get("title",""))
    def add_task(self):
        title=self.task_title.text().strip(); self.task_title.clear()
        if title:
            self.controller.tasks.add(title); self.refresh_tasks()
    def load_integrations(self):
        cfg=self.controller.config.load("integrations.json",{}) or {}; sec=self.controller.config.secrets(); sp=cfg.get("spotify",{}); obs=cfg.get("obs",{})
        self.sp_id.setText(sec.get("spotify_client_id","")); self.sp_secret.setText(sec.get("spotify_client_secret","")); self.obs_host.setText(obs.get("host","127.0.0.1")); self.obs_port.setValue(int(obs.get("port",4455))); self.obs_pass.setText(sec.get("obs_password",""))
    def save_integrations(self):
        cfg=self.controller.config.load("integrations.json",{}) or {}; cfg.setdefault("spotify",{})["enabled"]=True; cfg.setdefault("obs",{}).update({"enabled":True,"host":self.obs_host.text().strip() or "127.0.0.1","port":self.obs_port.value()}); self.controller.config.save("integrations.json",cfg)
        sec=self.controller.config.secrets(); sec.update({"spotify_client_id":self.sp_id.text().strip(),"spotify_client_secret":self.sp_secret.text().strip(),"obs_password":self.obs_pass.text()}); self.controller.config.save("secrets.json",sec); QMessageBox.information(self,"Integraciones","Configuración guardada.")
    def save_audio(self):
        cfg=self.controller.config.load("app.json",{}) or {}; cfg.setdefault("microphone",{})["sensitivity"]=self.sensitivity.value(); self.controller.config.save("app.json",cfg); QMessageBox.information(self,"Audio","Sensibilidad guardada. Reinicia para aplicarla.")
    def closeEvent(self,event): self.controller.close(); super().closeEvent(event)
