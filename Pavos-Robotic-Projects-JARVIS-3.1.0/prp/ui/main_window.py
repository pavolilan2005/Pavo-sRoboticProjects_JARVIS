from __future__ import annotations
import asyncio,threading
from PyQt6.QtCore import Qt,pyqtSignal,QObject,QTimer
from PyQt6.QtGui import QColor,QPainter,QPen,QFont
from PyQt6.QtWidgets import *

STYLE="""
QMainWindow,QWidget{background:#061018;color:#d8f8ff;font-family:Segoe UI;font-size:13px}
QTabWidget::pane{border:1px solid #123c4b;background:#08141d;border-radius:8px}
QTabBar::tab{background:#0a1b25;color:#78bfd1;padding:10px 18px;border:1px solid #123c4b}
QTabBar::tab:selected{color:#eaffff;background:#0c2b38;border-bottom:2px solid #00d9ff}
QPushButton{background:#0b2b38;border:1px solid #00b8d9;border-radius:6px;padding:8px 14px;color:#bff7ff}
QPushButton:hover{background:#104458;border-color:#4ce8ff}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit,QTableWidget,QListWidget{background:#081820;border:1px solid #175064;border-radius:5px;padding:6px;selection-background-color:#0b6d82}
QHeaderView::section{background:#0b2632;color:#7eeaff;padding:7px;border:0}
QProgressBar{background:#041018;border:1px solid #175064;border-radius:5px;text-align:center}
QProgressBar::chunk{background:#00d7ff;border-radius:4px}
QLabel#Title{font-size:22px;font-weight:700;color:#8ef3ff}
QLabel#State{font-size:14px;font-weight:700;color:#00e5ff}
QGroupBox{border:1px solid #17495b;border-radius:8px;margin-top:10px;padding-top:12px;color:#64dff3}
QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 5px}
"""
class Bridge(QObject):
    log=pyqtSignal(str); transcript=pyqtSignal(str,str); state=pyqtSignal(str); level=pyqtSignal(float,float)
class CoreOrb(QWidget):
    def __init__(self): super().__init__(); self.phase=0; self.level=0; self.setMinimumSize(180,180); t=QTimer(self);t.timeout.connect(self.tick);t.start(40)
    def tick(self): self.phase=(self.phase+3)%360;self.update()
    def set_level(self,v):self.level=v;self.update()
    def paintEvent(self,e):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);c=self.rect().center();r=min(self.width(),self.height())//2-18
        for i,a in enumerate([50,90,150]):
            p.setPen(QPen(QColor(0,210,255,a),2)); rr=r-i*18+int(self.level/16);p.drawEllipse(c,rr,rr)
        p.setPen(QPen(QColor('#00e5ff'),4));p.drawArc(c.x()-r,c.y()-r,2*r,2*r,self.phase*16,100*16)
        p.setBrush(QColor(0,210,255,35+int(self.level)));p.setPen(Qt.PenStyle.NoPen);p.drawEllipse(c,45,45)
class MainWindow(QMainWindow):
    def __init__(self,controller):
        super().__init__();self.controller=controller;self.live=None;self.loop=None;self.bridge=Bridge();self.setWindowTitle("Pavo's Robotic Projects — JARVIS");self.resize(1280,800);self.setStyleSheet(STYLE)
        self.bridge.log.connect(self._log);self.bridge.transcript.connect(self._transcript);self.bridge.state.connect(self._state);self.bridge.level.connect(self._level)
        self._build();self.refresh_audio_devices();self.load_all();controller.events.subscribe(lambda e:self.bridge.log.emit(f'[{e.time}] {e.topic}: {e.payload}'))
    def callbacks(self):
        class C:pass
        c=C();c.log=lambda x:self.bridge.log.emit(x);c.transcript=lambda w,t:self.bridge.transcript.emit(w,t);c.state=lambda s:self.bridge.state.emit(s);return c
    def attach_live(self,live,loop):self.live=live;self.loop=loop
    def _build(self):
        central=QWidget();self.setCentralWidget(central);root=QVBoxLayout(central);head=QHBoxLayout();title=QLabel("PAVO'S ROBOTIC PROJECTS // JARVIS");title.setObjectName('Title');self.state=QLabel('OFFLINE');self.state.setObjectName('State');head.addWidget(title);head.addStretch();head.addWidget(self.state);root.addLayout(head)
        self.tabs=QTabWidget();root.addWidget(self.tabs)
        self._assistant_tab();self._audio_tab();self._domotics_tab();self._routines_tab();self._tasks_tab();self._integrations_tab();self._activity_tab()
    def _assistant_tab(self):
        tab=QWidget();lay=QHBoxLayout(tab);left=QVBoxLayout();self.orb=CoreOrb();left.addWidget(self.orb,0,Qt.AlignmentFlag.AlignCenter);self.mic_meter=QProgressBar();self.mic_meter.setRange(0,100);left.addWidget(self.mic_meter);self.mute=QPushButton('SILENCIAR MICRÓFONO');self.mute.setCheckable(True);self.mute.toggled.connect(lambda v:(self.controller.audio.set_muted(v),self.mute.setText('ACTIVAR MICRÓFONO' if v else 'SILENCIAR MICRÓFONO')));left.addWidget(self.mute);left.addStretch();lay.addLayout(left,1)
        right=QVBoxLayout();self.transcript=QTextEdit();self.transcript.setReadOnly(True);right.addWidget(self.transcript);row=QHBoxLayout();self.command=QLineEdit();self.command.setPlaceholderText('Escribe una orden...');self.command.returnPressed.connect(self.send_text);send=QPushButton('EJECUTAR');send.clicked.connect(self.send_text);row.addWidget(self.command);row.addWidget(send);right.addLayout(row);lay.addLayout(right,4);self.tabs.addTab(tab,'ASISTENTE')
    def _audio_tab(self):
        tab=QWidget();lay=QVBoxLayout(tab);g=QGroupBox('DIAGNÓSTICO Y SELECCIÓN DE AUDIO');form=QFormLayout(g)
        self.input_combo=QComboBox();self.output_combo=QComboBox();refresh=QPushButton('ACTUALIZAR DISPOSITIVOS');refresh.clicked.connect(self.refresh_audio_devices);form.addRow('Micrófono',self.input_combo);form.addRow('Salida',self.output_combo);form.addRow(refresh)
        self.live_meter=QProgressBar();self.live_meter.setRange(0,100);form.addRow('Nivel en vivo',self.live_meter)
        self.sensitivity=QSpinBox();self.sensitivity.setRange(1,100);self.gain=QDoubleSpinBox();self.gain.setRange(.2,5);self.gain.setSingleStep(.1);form.addRow('Sensibilidad',self.sensitivity);form.addRow('Ganancia digital',self.gain)
        self.continuous=QCheckBox('Transmitir audio continuamente (recomendado; no exige gritar)');self.gate=QCheckBox('Usar compuerta de ruido experimental');form.addRow(self.continuous);form.addRow(self.gate)
        bar=QHBoxLayout();save=QPushButton('GUARDAR Y REINICIAR AUDIO');save.clicked.connect(self.save_audio);test=QPushButton('GRABAR Y ESCUCHAR 4 SEGUNDOS');test.clicked.connect(self.audio_test);bar.addWidget(save);bar.addWidget(test);form.addRow(bar);lay.addWidget(g)
        self.audio_status=QTextEdit();self.audio_status.setReadOnly(True);self.audio_status.setMaximumHeight(180);lay.addWidget(self.audio_status);lay.addStretch();self.tabs.addTab(tab,'AUDIO')
    def _domotics_tab(self):
        tab=QWidget();lay=QVBoxLayout(tab);top=QHBoxLayout();self.port_combo=QComboBox();scan=QPushButton('ESCANEAR PUERTOS');scan.clicked.connect(self.refresh_ports);top.addWidget(QLabel('Puerto nuevo:'));top.addWidget(self.port_combo);top.addWidget(scan);lay.addLayout(top)
        self.nodes=QTableWidget(0,4);self.nodes.setHorizontalHeaderLabels(['ID','Nombre','Puerto','Baudrate']);self.nodes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);lay.addWidget(self.nodes);b=QHBoxLayout();add=QPushButton('AGREGAR NODO');add.clicked.connect(self.add_node);save=QPushButton('GUARDAR NODOS');save.clicked.connect(self.save_nodes);test=QPushButton('PROBAR NODO');test.clicked.connect(self.test_node);b.addWidget(add);b.addWidget(save);b.addWidget(test);lay.addLayout(b)
        lay.addWidget(QLabel('DISPOSITIVOS Y GPIO'))
        self.devices=QTableWidget(0,7);self.devices.setHorizontalHeaderLabels(['ID','Nombre','Nodo','GPIO','Tipo','Activo bajo','Alias']);self.devices.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);lay.addWidget(self.devices)
        db=QHBoxLayout();da=QPushButton('AGREGAR DISPOSITIVO');da.clicked.connect(self.add_device);ds=QPushButton('GUARDAR DISPOSITIVOS');ds.clicked.connect(self.save_devices);sync=QPushButton('SINCRONIZAR NODO');sync.clicked.connect(self.sync_node);db.addWidget(da);db.addWidget(ds);db.addWidget(sync);lay.addLayout(db);self.tabs.addTab(tab,'DOMÓTICA')
    def _routines_tab(self):
        tab=QWidget();lay=QVBoxLayout(tab);self.routines=QListWidget();lay.addWidget(self.routines);run=QPushButton('EJECUTAR RUTINA');run.clicked.connect(self.run_routine);lay.addWidget(run);self.tabs.addTab(tab,'RUTINAS')
    def _tasks_tab(self):
        tab=QWidget();lay=QVBoxLayout(tab);self.task_list=QListWidget();lay.addWidget(self.task_list);row=QHBoxLayout();self.task_title=QLineEdit();self.task_title.setPlaceholderText('Nueva tarea');add=QPushButton('CREAR TAREA');add.clicked.connect(self.add_task);done=QPushButton('COMPLETAR');done.clicked.connect(self.complete_task);row.addWidget(self.task_title);row.addWidget(add);row.addWidget(done);lay.addLayout(row);self.tabs.addTab(tab,'TAREAS')
    def _integrations_tab(self):
        tab=QWidget();form=QFormLayout(tab);self.gkey=QLineEdit();self.gkey.setEchoMode(QLineEdit.EchoMode.Password);self.sid=QLineEdit();self.ssecret=QLineEdit();self.ssecret.setEchoMode(QLineEdit.EchoMode.Password);self.opass=QLineEdit();self.opass.setEchoMode(QLineEdit.EchoMode.Password);self.ohost=QLineEdit();self.oport=QSpinBox();self.oport.setMaximum(65535)
        for label,w in [('Gemini API key',self.gkey),('Spotify Client ID',self.sid),('Spotify Client Secret',self.ssecret),('OBS host',self.ohost),('OBS puerto',self.oport),('OBS contraseña',self.opass)]:form.addRow(label,w)
        save=QPushButton('GUARDAR CREDENCIALES');save.clicked.connect(self.save_integrations);form.addRow(save);self.tabs.addTab(tab,'INTEGRACIONES')
    def _activity_tab(self):
        tab=QWidget();lay=QVBoxLayout(tab);self.logs=QTextEdit();self.logs.setReadOnly(True);lay.addWidget(self.logs);self.tabs.addTab(tab,'ACTIVIDAD')
    def refresh_audio_devices(self):
        self.input_combo.clear();self.output_combo.clear()
        try:
            ds=self.controller.audio.devices()
            for d in ds:
                label=f'{d["index"]}: {d["name"]} ({d["rate"]}Hz)'
                if d['inputs']>0:self.input_combo.addItem(label,d['index'])
                if d['outputs']>0:self.output_combo.addItem(label,d['index'])
            cfg=(self.controller.config.load('app.json',{}) or {}).get('audio',{})
            for combo,key in [(self.input_combo,'input_device'),(self.output_combo,'output_device')]:
                idx=combo.findData(cfg.get(key)); combo.setCurrentIndex(idx if idx>=0 else 0)
            self.audio_status.append(f'Dispositivo predeterminado de sounddevice: {self.controller.audio.defaults()}')
        except Exception as e:self.audio_status.append(f'Error enumerando audio: {e}')
    def load_all(self):
        app=self.controller.config.load('app.json',{}) or {};a=app.get('audio',{});self.sensitivity.setValue(int(a.get('sensitivity',82)));self.gain.setValue(float(a.get('mic_gain',1)));self.continuous.setChecked(bool(a.get('stream_continuously',True)));self.gate.setChecked(bool(a.get('noise_gate_enabled',False)))
        sec=self.controller.config.secrets();integ=self.controller.config.load('integrations.json',{}) or {};self.gkey.setText(sec.get('gemini_api_key',''));self.sid.setText(sec.get('spotify_client_id',''));self.ssecret.setText(sec.get('spotify_client_secret',''));self.opass.setText(sec.get('obs_password',''));self.ohost.setText(integ.get('obs',{}).get('host','127.0.0.1'));self.oport.setValue(int(integ.get('obs',{}).get('port',4455)))
        self.nodes.setRowCount(0)
        for n in (self.controller.config.load('nodes.json',{}) or {}).get('nodes',[]):self._insert_node(n)
        self.routines.clear()
        for r in self.controller.routines.definitions():self.routines.addItem(f'{r.get("id")} — {r.get("name")}')
        self.refresh_devices();self.refresh_tasks();self.refresh_ports()
    def save_audio(self):
        s={'input_device':self.input_combo.currentData(),'output_device':self.output_combo.currentData(),'input_rate':16000,'model_output_rate':24000,'blocksize':1024,'stream_continuously':self.continuous.isChecked(),'noise_gate_enabled':self.gate.isChecked(),'sensitivity':self.sensitivity.value(),'mic_gain':self.gain.value()};self.controller.save_audio_settings(s)
        try:self.controller.audio.restart();self.audio_status.append('Audio reiniciado correctamente con el dispositivo seleccionado.')
        except Exception as e:self.audio_status.append(f'No se pudo reiniciar audio: {e}')
    def audio_test(self):
        self.audio_status.append('Grabando 4 segundos. Habla a volumen normal...')
        def work():
            try:
                rec,rate,peak,rms=self.controller.audio.record_test(4);self.bridge.log.emit(f'Prueba de micrófono: pico={peak}, RMS={rms:.1f}, rate={rate}');self.controller.audio.play_test(rec,rate);self.bridge.log.emit('Prueba reproducida. Si te escuchaste, el micrófono es correcto.')
            except Exception as e:self.bridge.log.emit(f'Error en prueba de audio: {e}')
        threading.Thread(target=work,daemon=True).start()
    def refresh_ports(self):
        self.port_combo.clear()
        try:
            for p in self.controller.serial.ports():self.port_combo.addItem(f'{p["port"]} — {p["description"]}',p['port'])
        except Exception as e:self._log(str(e))
    def _insert_node(self,n):
        r=self.nodes.rowCount();self.nodes.insertRow(r)
        for c,v in enumerate([n.get('id',''),n.get('name',''),n.get('port',''),str(n.get('baudrate',115200))]):self.nodes.setItem(r,c,QTableWidgetItem(v))
    def add_node(self):self._insert_node({'id':f'esp32_{self.nodes.rowCount()+1}','name':'ESP32','port':self.port_combo.currentData() or 'COM6','baudrate':115200})
    def save_nodes(self):
        arr=[]
        for r in range(self.nodes.rowCount()):
            vals=[self.nodes.item(r,c).text().strip() if self.nodes.item(r,c) else '' for c in range(4)]
            if vals[0]:arr.append({'id':vals[0],'name':vals[1],'port':vals[2],'baudrate':int(vals[3] or 115200)})
        self.controller.config.save('nodes.json',{'nodes':arr});self._log('Nodos guardados.')
    def test_node(self):
        r=self.nodes.currentRow()
        if r<0:return
        node=self.nodes.item(r,0).text();threading.Thread(target=lambda:self.bridge.log.emit(str(self.controller.serial.request(node,{'cmd':'ping'}))),daemon=True).start()
    def refresh_devices(self):
        self.devices.setRowCount(0)
        for d in (self.controller.config.load('devices.json',{}) or {}).get('devices',[]):
            r=self.devices.rowCount();self.devices.insertRow(r);vals=[d.get('id',''),d.get('name',''),d.get('node_id',''),str(d.get('pin','')),d.get('type','digital_output'),str(d.get('active_low',False)),', '.join(d.get('aliases',[]))]
            for c,v in enumerate(vals):self.devices.setItem(r,c,QTableWidgetItem(v))
    def add_device(self):
        r=self.devices.rowCount();self.devices.insertRow(r);vals=[f'device_{r+1}','Nuevo dispositivo','esp32_1','23','digital_output','False','']
        for c,v in enumerate(vals):self.devices.setItem(r,c,QTableWidgetItem(v))
    def save_devices(self):
        arr=[]
        for r in range(self.devices.rowCount()):
            get=lambda c:self.devices.item(r,c).text().strip() if self.devices.item(r,c) else ''
            try:pin=int(get(3))
            except:continue
            if get(0):arr.append({'id':get(0),'name':get(1),'node_id':get(2),'pin':pin,'type':get(4) or 'digital_output','active_low':get(5).lower() in {'true','1','sí','si'},'aliases':[x.strip() for x in get(6).split(',') if x.strip()]})
        self.controller.config.save('devices.json',{'devices':arr});self._log('Dispositivos guardados.')
    def sync_node(self):
        self.save_devices();r=self.nodes.currentRow()
        if r<0:self._log('Selecciona un nodo para sincronizar.');return
        node=self.nodes.item(r,0).text();asyncio.run_coroutine_threadsafe(self.controller.execute('node.sync',{'node_id':node}),self.loop) if self.loop else None
    def refresh_tasks(self):
        self.task_list.clear()
        for t in self.controller.tasks.list():
            item=QListWidgetItem(('✓ ' if t.get('done') else '• ')+t.get('title',''));item.setData(Qt.ItemDataRole.UserRole,t.get('id'));self.task_list.addItem(item)
    def add_task(self):
        title=self.task_title.text().strip();self.task_title.clear()
        if title:self.controller.tasks.add(title);self.refresh_tasks()
    def complete_task(self):
        item=self.task_list.currentItem()
        if item:self.controller.tasks.complete(item.data(Qt.ItemDataRole.UserRole));self.refresh_tasks()
    def run_routine(self):
        item=self.routines.currentItem()
        if item and self.loop:
            rid=item.text().split(' — ')[0];asyncio.run_coroutine_threadsafe(self.controller.execute('routine.run',{'routine_id':rid}),self.loop)
    def save_integrations(self):
        sec=self.controller.config.secrets();sec.update({'gemini_api_key':self.gkey.text().strip(),'spotify_client_id':self.sid.text().strip(),'spotify_client_secret':self.ssecret.text().strip(),'spotify_redirect_uri':'http://127.0.0.1:8888/callback','obs_password':self.opass.text()});self.controller.config.save('secrets.json',sec)
        cfg=self.controller.config.load('integrations.json',{}) or {};cfg.setdefault('obs',{}).update({'host':self.ohost.text().strip() or '127.0.0.1','port':self.oport.value(),'enabled':True});cfg.setdefault('spotify',{})['enabled']=True;self.controller.config.save('integrations.json',cfg);self._log('Integraciones guardadas. Reinicia JARVIS para renovar Gemini.')
    def send_text(self):
        t=self.command.text().strip();self.command.clear()
        if t and self.live and self.loop:asyncio.run_coroutine_threadsafe(self.live.send_text(t),self.loop)
    def _log(self,t):self.logs.append(t);self.audio_status.append(t) if hasattr(self,'audio_status') and ('audio' in t.lower() or 'mic' in t.lower()) else None
    def _transcript(self,w,t):self.transcript.append(f'<span style="color:#00dfff"><b>{w}</b></span><br>{t}<br>')
    def _state(self,s):self.state.setText(s)
    def _level(self,v,rms):self.mic_meter.setValue(int(v));self.live_meter.setValue(int(v));self.orb.set_level(v)
    def closeEvent(self,e):self.controller.close();super().closeEvent(e)
