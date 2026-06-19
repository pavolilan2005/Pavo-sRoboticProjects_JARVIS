from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


BG = "#020a12"
PANEL = "#071523"
LINE = "#1d5d87"
CYAN = "#00eaff"
TEXT = "#e4fbff"
DIM = "#6da8bb"
RED = "#ff315f"


def button(text: str, danger: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(32)
    color = RED if danger else CYAN
    b.setStyleSheet(
        f"QPushButton{{background:#071523;color:{color};border:1px solid {color};border-radius:9px;padding:5px 10px;}}"
        f"QPushButton:hover{{background:#0b2638;color:{TEXT};}}"
    )
    return b


def line_edit(text: str = "", secret: bool = False) -> QLineEdit:
    w = QLineEdit(text)
    if secret:
        w.setEchoMode(QLineEdit.EchoMode.Password)
    w.setStyleSheet(f"background:#03111d;color:{TEXT};border:1px solid {LINE};border-radius:7px;padding:6px;")
    return w


class ControlCenterDialog(QDialog):
    log_signal = pyqtSignal(str)
    refresh_signal = pyqtSignal()

    def __init__(self, platform, parent=None):
        super().__init__(parent)
        self.platform = platform
        self.setWindowTitle("Pavo's Robotic Projects // Centro de Control")
        self.resize(1180, 760)
        self.setMinimumSize(980, 620)
        self.setStyleSheet(f"background:{BG};color:{TEXT};")
        self._routine_cache: dict[str, dict[str, Any]] = {}
        self._mode_cache: dict[str, dict[str, Any]] = {}
        self._automation_cache: dict[str, dict[str, Any]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("PAVO'S ROBOTIC PROJECTS // JARVIS CONTROL CENTER")
        title.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{CYAN};padding:6px;")
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {LINE};background:{PANEL};}}"
            f"QTabBar::tab{{background:#04111d;color:{DIM};padding:9px 14px;border:1px solid {LINE};}}"
            f"QTabBar::tab:selected{{color:{CYAN};background:{PANEL};}}"
        )
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_dashboard(), "INICIO")
        self.tabs.addTab(self._build_audio(), "AUDIO")
        self.tabs.addTab(self._build_nodes(), "NODOS ESP32")
        self.tabs.addTab(self._build_devices(), "DISPOSITIVOS")
        self.tabs.addTab(self._build_routines(), "RUTINAS")
        self.tabs.addTab(self._build_modes(), "MODOS")
        self.tabs.addTab(self._build_automations(), "AUTOMATIZACIONES")
        self.tabs.addTab(self._build_integrations(), "INTEGRACIONES")
        self.tabs.addTab(self._build_activity(), "ACTIVIDAD")

        self.status = QLabel("Listo.")
        self.status.setStyleSheet(f"color:{DIM};padding:5px;")
        root.addWidget(self.status)

        self.log_signal.connect(self._show_status)
        self.refresh_signal.connect(self.refresh_all)
        self.refresh_all()

    # ---------------------------- dashboard ----------------------------
    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.dashboard_summary = QTextEdit()
        self.dashboard_summary.setReadOnly(True)
        self.dashboard_summary.setStyleSheet(self._text_style())
        lay.addWidget(self.dashboard_summary, 1)
        row = QHBoxLayout()
        for text, callback in [
            ("ACTUALIZAR", self.refresh_all),
            ("MODO STREAM", lambda: self._run_background(lambda: self.platform.manage_mode("start", "stream"))),
            ("DETENER STREAM", lambda: self._run_background(lambda: self.platform.manage_mode("stop", "stream"))),
            ("MODO ESTUDIO", lambda: self._run_background(lambda: self.platform.manage_mode("start", "estudio"))),
            ("ESTADO PC", lambda: self._run_background(lambda: self.platform.execute("pc.status"))),
        ]:
            b = button(text)
            b.clicked.connect(callback)
            row.addWidget(b)
        lay.addLayout(row)
        return page

    # ------------------------------ audio -------------------------------
    def _build_audio(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        info = QLabel(
            "Selecciona explícitamente el micrófono y la salida. Al guardar, JARVIS "
            "reinicia únicamente su sesión de audio/Gemini para aplicar los cambios."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{DIM};")
        lay.addWidget(info)

        devices_box = self._section("Dispositivos de audio")
        form = QFormLayout(devices_box)
        self.audio_input = QComboBox()
        self.audio_output = QComboBox()
        self.audio_input.setStyleSheet(self._combo_style())
        self.audio_output.setStyleSheet(self._combo_style())
        form.addRow("Micrófono", self.audio_input)
        form.addRow("Bocinas / audífonos", self.audio_output)
        lay.addWidget(devices_box)

        tuning_box = self._section("Sensibilidad y detección")
        tuning = QFormLayout(tuning_box)
        self.audio_sensitivity = QSpinBox()
        self.audio_sensitivity.setRange(1, 100)
        self.audio_sensitivity.setSuffix(" %")
        self.audio_gain = QDoubleSpinBox()
        self.audio_gain.setRange(0.25, 4.0)
        self.audio_gain.setSingleStep(0.05)
        self.audio_gain.setDecimals(2)
        self.audio_vad = QCheckBox("Filtrar silencio y ruido ambiente")
        self.audio_min_rms = QDoubleSpinBox()
        self.audio_min_rms.setRange(1.0, 2000.0)
        self.audio_min_rms.setDecimals(1)
        self.audio_calibration = QDoubleSpinBox()
        self.audio_calibration.setRange(0.25, 5.0)
        self.audio_calibration.setSingleStep(0.1)
        self.audio_calibration.setSuffix(" s")
        self.audio_trail = QDoubleSpinBox()
        self.audio_trail.setRange(0.25, 4.0)
        self.audio_trail.setSingleStep(0.05)
        self.audio_trail.setSuffix(" s")
        for widget in (self.audio_sensitivity, self.audio_gain, self.audio_min_rms, self.audio_calibration, self.audio_trail):
            widget.setStyleSheet(self._spin_style())
        tuning.addRow("Sensibilidad", self.audio_sensitivity)
        tuning.addRow("Ganancia digital", self.audio_gain)
        tuning.addRow("Filtro adaptativo", self.audio_vad)
        tuning.addRow("Umbral mínimo RMS", self.audio_min_rms)
        tuning.addRow("Calibración", self.audio_calibration)
        tuning.addRow("Cola de voz", self.audio_trail)
        lay.addWidget(tuning_box)

        self.audio_runtime = QLabel("Audio todavía no inicializado.")
        self.audio_runtime.setWordWrap(True)
        self.audio_runtime.setStyleSheet(f"color:{CYAN};background:#03111d;border:1px solid {LINE};border-radius:8px;padding:10px;")
        lay.addWidget(self.audio_runtime)

        row = QHBoxLayout()
        for text, callback in [
            ("ACTUALIZAR DISPOSITIVOS", self._load_audio),
            ("GUARDAR Y APLICAR", self._save_audio),
            ("RECALIBRAR MICRÓFONO", self._calibrate_audio),
        ]:
            b = button(text)
            b.clicked.connect(callback)
            row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()
        return page

    def _load_audio(self):
        if not hasattr(self.platform, "audio"):
            self.audio_runtime.setText("Esta instalación no expone el servicio de audio.")
            return
        catalog = self.platform.audio.list_devices()
        settings = self.platform.audio.load()
        current_input = settings.get("input_device")
        current_output = settings.get("output_device")

        self.audio_input.blockSignals(True)
        self.audio_output.blockSignals(True)
        self.audio_input.clear()
        self.audio_output.clear()
        self.audio_input.addItem("Predeterminado de Windows", None)
        self.audio_output.addItem("Predeterminado de Windows", None)
        for device in catalog.get("inputs", []):
            label = f"{device['index']} · {device['name']} · {device['default_samplerate']} Hz"
            self.audio_input.addItem(label, device["index"])
        for device in catalog.get("outputs", []):
            label = f"{device['index']} · {device['name']} · {device['default_samplerate']} Hz"
            self.audio_output.addItem(label, device["index"])
        self._select_combo_data(self.audio_input, current_input)
        self._select_combo_data(self.audio_output, current_output)
        self.audio_input.blockSignals(False)
        self.audio_output.blockSignals(False)

        self.audio_sensitivity.setValue(int(settings.get("sensitivity", 82)))
        self.audio_gain.setValue(float(settings.get("input_gain", 1.2)))
        self.audio_vad.setChecked(bool(settings.get("vad_enabled", True)))
        self.audio_min_rms.setValue(float(settings.get("min_rms", 12.0)))
        self.audio_calibration.setValue(float(settings.get("calibration_seconds", 1.2)))
        self.audio_trail.setValue(float(settings.get("speech_trail_seconds", 1.25)))

        runtime = self.platform.audio.runtime_status()
        if runtime:
            self.audio_runtime.setText(
                f"Micrófono activo: {runtime.get('input_device_name', 'sin abrir')} | "
                f"Salida: {runtime.get('output_device_name', 'sin abrir')} | "
                f"Ruido: {runtime.get('noise_floor', 0):.1f} | "
                f"Umbral: {runtime.get('threshold', 0):.1f} | "
                f"RMS actual: {runtime.get('rms', 0):.1f}"
            )
        elif catalog.get("error"):
            self.audio_runtime.setText(f"Error al consultar audio: {catalog['error']}")
        else:
            self.audio_runtime.setText("Guarda para aplicar. JARVIS reiniciará su enlace de audio automáticamente.")

    def _save_audio(self):
        try:
            settings = self.platform.audio.save({
                "input_device": self.audio_input.currentData(),
                "output_device": self.audio_output.currentData(),
                "sensitivity": self.audio_sensitivity.value(),
                "input_gain": self.audio_gain.value(),
                "vad_enabled": self.audio_vad.isChecked(),
                "min_rms": self.audio_min_rms.value(),
                "calibration_seconds": self.audio_calibration.value(),
                "speech_trail_seconds": self.audio_trail.value(),
            })
            self._show_status(
                f"Audio guardado: sensibilidad {settings['sensitivity']} %, "
                f"ganancia {settings['input_gain']:.2f}. Reiniciando audio..."
            )
        except Exception as exc:
            QMessageBox.critical(self, "No pude guardar audio", str(exc))

    def _calibrate_audio(self):
        try:
            self.platform.audio.request_calibration()
            self._show_status("Calibración solicitada. Guarda silencio durante unos segundos.")
        except Exception as exc:
            QMessageBox.critical(self, "No pude calibrar", str(exc))

    # ------------------------------ nodes -------------------------------
    def _build_nodes(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        info = QLabel("Cada nodo representa una ESP32 con protocolo 'jarvis-node-v1'. La conexión serial pertenece únicamente al núcleo PRP.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{DIM};")
        lay.addWidget(info)
        self.nodes_table = QTableWidget(0, 8)
        self.nodes_table.setHorizontalHeaderLabels(["ID", "Nombre", "Puerto", "Baud", "Protocolo", "Activo", "En línea", "Último error"])
        self._style_table(self.nodes_table)
        lay.addWidget(self.nodes_table, 1)
        row = QHBoxLayout()
        actions = [
            ("AGREGAR", self._add_node_row),
            ("ELIMINAR", self._delete_node_row),
            ("GUARDAR", self._save_nodes),
            ("CONECTAR", self._connect_selected_node),
            ("SINCRONIZAR PINES", self._sync_selected_node),
            ("ACTUALIZAR", self._load_nodes),
        ]
        for text, cb in actions:
            b = button(text, danger=text == "ELIMINAR")
            b.clicked.connect(cb)
            row.addWidget(b)
        lay.addLayout(row)
        return page

    def _load_nodes(self):
        nodes = self.platform.esp32.list_nodes()
        self.nodes_table.setRowCount(0)
        for node in nodes:
            row = self.nodes_table.rowCount()
            self.nodes_table.insertRow(row)
            values = [
                node.get("id", ""), node.get("name", ""), node.get("port", ""),
                node.get("baudrate", 115200), node.get("protocol", "jarvis-node-v1"),
                "sí" if node.get("enabled", True) else "no",
                "ONLINE" if node.get("online") else "OFFLINE",
                node.get("last_error", ""),
            ]
            for col, value in enumerate(values):
                self.nodes_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _add_node_row(self):
        row = self.nodes_table.rowCount()
        self.nodes_table.insertRow(row)
        defaults = [f"esp32_{row+1}", f"ESP32 {row+1}", "COM6", "115200", "jarvis-node-v1", "sí", "OFFLINE", ""]
        for col, value in enumerate(defaults):
            self.nodes_table.setItem(row, col, QTableWidgetItem(value))

    def _delete_node_row(self):
        row = self.nodes_table.currentRow()
        if row < 0:
            return
        node_id = self._cell(self.nodes_table, row, 0)
        if node_id and QMessageBox.question(self, "Eliminar nodo", f"¿Eliminar {node_id}?") == QMessageBox.StandardButton.Yes:
            self.platform.esp32.delete_node(node_id)
        self.nodes_table.removeRow(row)
        self._load_node_choices()

    def _save_nodes(self):
        try:
            for row in range(self.nodes_table.rowCount()):
                self.platform.esp32.save_node({
                    "id": self._cell(self.nodes_table, row, 0),
                    "name": self._cell(self.nodes_table, row, 1),
                    "port": self._cell(self.nodes_table, row, 2),
                    "baudrate": int(self._cell(self.nodes_table, row, 3) or 115200),
                    "protocol": self._cell(self.nodes_table, row, 4) or "jarvis-node-v1",
                    "enabled": self._cell(self.nodes_table, row, 5).lower() not in {"no", "false", "0"},
                    "transport": "serial",
                })
            self._show_status("Nodos guardados.")
            self._load_nodes()
            self._load_node_choices()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _selected_node_id(self) -> str:
        row = self.nodes_table.currentRow()
        return self._cell(self.nodes_table, row, 0) if row >= 0 else ""

    def _connect_selected_node(self):
        node_id = self._selected_node_id()
        if node_id:
            self._run_background(lambda: self.platform.esp32.connect(node_id))

    def _sync_selected_node(self):
        node_id = self._selected_node_id()
        if not node_id:
            return
        if QMessageBox.question(self, "Sincronizar GPIO", "Esto reemplazará la configuración de pines guardada en la ESP32. ¿Continuar?") == QMessageBox.StandardButton.Yes:
            self._run_background(lambda: self.platform.execute("esp32.sync", {"node": node_id}, confirmed=True))

    # ----------------------------- devices ------------------------------
    def _build_devices(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.devices_table = QTableWidget(0, 8)
        self.devices_table.setHorizontalHeaderLabels(["ID", "Nombre", "Alias", "Nodo", "GPIO", "Tipo", "Activo bajo", "Funciones"])
        self._style_table(self.devices_table)
        lay.addWidget(self.devices_table, 1)
        row = QHBoxLayout()
        for text, cb in [
            ("AGREGAR", self._add_device_row),
            ("ELIMINAR", self._delete_device_row),
            ("GUARDAR", self._save_devices),
            ("GUARDAR + SINCRONIZAR", self._save_and_sync_devices),
            ("ENCENDER", lambda: self._test_device("on")),
            ("APAGAR", lambda: self._test_device("off")),
            ("ALTERNAR", lambda: self._test_device("toggle")),
            ("ESTADO", lambda: self._test_device("status")),
            ("ACTUALIZAR", self._load_devices),
        ]:
            b = button(text, danger=text == "ELIMINAR")
            b.clicked.connect(cb)
            row.addWidget(b)
        lay.addLayout(row)
        note = QLabel("Cambiar GPIO aquí no requiere modificar JARVIS. Con firmware jarvis-node-v1, guarda y luego sincroniza el nodo.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{DIM};")
        lay.addWidget(note)
        return page

    def _load_devices(self):
        devices = self.platform.esp32.list_devices()
        self.devices_table.setRowCount(0)
        for device in devices:
            row = self.devices_table.rowCount()
            self.devices_table.insertRow(row)
            values = [
                device.get("id", ""), device.get("name", ""), ", ".join(device.get("aliases", [])),
                device.get("node", ""), device.get("pin", ""), device.get("type", ""),
                "sí" if device.get("active_low") else "no", ", ".join(device.get("capabilities", [])),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(device.get("id", "")))
                self.devices_table.setItem(row, col, item)

    def _add_device_row(self):
        row = self.devices_table.rowCount()
        self.devices_table.insertRow(row)
        nodes = self.platform.esp32.list_nodes()
        default_node = nodes[0]["id"] if nodes else "esp32_principal"
        defaults = [f"dispositivo_{row+1}", f"Dispositivo {row+1}", "", default_node, "23", "digital_output", "no", "on, off, toggle, status"]
        for col, value in enumerate(defaults):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, "")
            self.devices_table.setItem(row, col, item)

    def _delete_device_row(self):
        row = self.devices_table.currentRow()
        if row < 0:
            return
        device_id = self._cell(self.devices_table, row, 0)
        if device_id and QMessageBox.question(self, "Eliminar dispositivo", f"¿Eliminar {device_id}?") == QMessageBox.StandardButton.Yes:
            self.platform.esp32.delete_device(device_id)
        self.devices_table.removeRow(row)

    def _save_devices(self):
        try:
            node_ids: set[str] = set()
            for row in range(self.devices_table.rowCount()):
                id_item = self.devices_table.item(row, 0)
                previous_id = str(id_item.data(Qt.ItemDataRole.UserRole) or "") if id_item else ""
                saved = self.platform.esp32.save_device({
                    "id": self._cell(self.devices_table, row, 0),
                    "name": self._cell(self.devices_table, row, 1),
                    "aliases": self._cell(self.devices_table, row, 2),
                    "node": self._cell(self.devices_table, row, 3),
                    "pin": int(self._cell(self.devices_table, row, 4)),
                    "type": self._cell(self.devices_table, row, 5),
                    "active_low": self._cell(self.devices_table, row, 6).lower() in {"sí", "si", "true", "1", "yes"},
                    "capabilities": self._cell(self.devices_table, row, 7),
                }, previous_id=previous_id or None)
                node_ids.add(str(saved.get("node", "")))
            self._show_status("Dispositivos guardados.")
            self._load_devices()
            return {node_id for node_id in node_ids if node_id}
        except Exception as exc:
            QMessageBox.critical(self, "Configuración de dispositivo inválida", str(exc))
            return set()

    def _save_and_sync_devices(self):
        node_ids = self._save_devices()
        if not node_ids:
            return

        def worker():
            messages = []
            for node_id in sorted(node_ids):
                result = self.platform.execute("esp32.sync", {"node": node_id}, confirmed=True)
                messages.append(result.message)
            return " | ".join(messages)

        self._run_background(worker)

    def _test_device(self, action: str):
        row = self.devices_table.currentRow()
        if row < 0:
            return
        device_id = self._cell(self.devices_table, row, 0)
        self._run_background(lambda: self.platform.execute("domotics.control", {"device": device_id, "action": action}))

    # ----------------------------- routines -----------------------------
    def _build_routines(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        left_l = QVBoxLayout(left)
        self.routine_list = QListWidget()
        self.routine_list.currentTextChanged.connect(self._select_routine)
        self.routine_list.setStyleSheet(self._list_style())
        left_l.addWidget(self.routine_list, 1)
        new_b = button("NUEVA RUTINA")
        new_b.clicked.connect(self._new_routine)
        left_l.addWidget(new_b)
        splitter.addWidget(left)

        right = QWidget()
        rlay = QVBoxLayout(right)
        form = QFormLayout()
        self.routine_id = line_edit()
        self.routine_name = line_edit()
        self.routine_aliases = line_edit()
        self.routine_description = line_edit()
        form.addRow("ID", self.routine_id)
        form.addRow("Nombre", self.routine_name)
        form.addRow("Frases/alias", self.routine_aliases)
        form.addRow("Descripción", self.routine_description)
        rlay.addLayout(form)

        self.steps_table = QTableWidget(0, 6)
        self.steps_table.setHorizontalHeaderLabels(["Tipo", "Capacidad / segundos", "Parámetros JSON", "Crítico", "Reintentos", "Espera después"])
        self._style_table(self.steps_table)
        rlay.addWidget(self.steps_table, 1)
        row = QHBoxLayout()
        for text, cb in [
            ("+ ACCIÓN", lambda: self._add_step("action")),
            ("+ ESPERA", lambda: self._add_step("wait")),
            ("+ PARALELO JSON", lambda: self._add_step("parallel")),
            ("ELIMINAR PASO", self._delete_step),
            ("SUBIR", lambda: self._move_step(-1)),
            ("BAJAR", lambda: self._move_step(1)),
        ]:
            b = button(text, danger=text == "ELIMINAR PASO")
            b.clicked.connect(cb)
            row.addWidget(b)
        rlay.addLayout(row)
        row2 = QHBoxLayout()
        for text, cb in [
            ("GUARDAR RUTINA", self._save_routine),
            ("EJECUTAR", self._run_selected_routine),
            ("ELIMINAR RUTINA", self._delete_routine),
        ]:
            b = button(text, danger=text == "ELIMINAR RUTINA")
            b.clicked.connect(cb)
            row2.addWidget(b)
        rlay.addLayout(row2)
        splitter.addWidget(right)
        splitter.setSizes([250, 850])
        return page

    def _load_routines(self):
        self._routine_cache = {r["id"]: r for r in self.platform.routines.list()}
        current = self.routine_id.text() if hasattr(self, "routine_id") else ""
        self.routine_list.clear()
        for routine in self._routine_cache.values():
            self.routine_list.addItem(f"{routine['id']} | {routine.get('name', '')}")
        if current:
            for i in range(self.routine_list.count()):
                if self.routine_list.item(i).text().startswith(current + " |"):
                    self.routine_list.setCurrentRow(i)
                    break

    def _select_routine(self, text: str):
        routine_id = text.split(" |", 1)[0].strip()
        routine = self._routine_cache.get(routine_id)
        if not routine:
            return
        self.routine_id.setText(routine.get("id", ""))
        self.routine_name.setText(routine.get("name", ""))
        self.routine_aliases.setText(", ".join(routine.get("aliases", [])))
        self.routine_description.setText(routine.get("description", ""))
        self.steps_table.setRowCount(0)
        for step in routine.get("steps", []):
            self._append_step_from_dict(step)

    def _new_routine(self):
        self.routine_list.clearSelection()
        self.routine_id.clear()
        self.routine_name.setText("Nueva rutina")
        self.routine_aliases.clear()
        self.routine_description.clear()
        self.steps_table.setRowCount(0)

    def _add_step(self, kind: str):
        row = self.steps_table.rowCount()
        self.steps_table.insertRow(row)
        if kind == "wait":
            values = ["wait", "1", "{}", "sí", "0", "0"]
        elif kind == "parallel":
            values = ["parallel", "", '[{"capability":"apps.open","params":{"app_name":"Spotify"},"critical":false}]', "sí", "0", "0"]
        else:
            values = ["action", "apps.open", '{"app_name":"Spotify"}', "sí", "0", "0"]
        for col, value in enumerate(values):
            self.steps_table.setItem(row, col, QTableWidgetItem(value))

    def _append_step_from_dict(self, step: dict[str, Any]):
        row = self.steps_table.rowCount()
        self.steps_table.insertRow(row)
        if "wait" in step:
            values = ["wait", str(step.get("wait", 1)), "{}", "sí" if step.get("critical", True) else "no", str(step.get("retries", 0)), str(step.get("delay_after", 0))]
        elif "parallel" in step:
            values = ["parallel", "", json.dumps(step.get("parallel", []), ensure_ascii=False), "sí" if step.get("critical", True) else "no", "0", "0"]
        elif "if" in step:
            values = ["condition", "", json.dumps(step, ensure_ascii=False), "sí" if step.get("critical", True) else "no", "0", "0"]
        else:
            values = ["action", str(step.get("capability", "")), json.dumps(step.get("params", {}), ensure_ascii=False), "sí" if step.get("critical", True) else "no", str(step.get("retries", 0)), str(step.get("delay_after", 0))]
        for col, value in enumerate(values):
            self.steps_table.setItem(row, col, QTableWidgetItem(value))

    def _steps_from_table(self) -> list[dict[str, Any]]:
        steps = []
        for row in range(self.steps_table.rowCount()):
            kind = self._cell(self.steps_table, row, 0).lower()
            subject = self._cell(self.steps_table, row, 1)
            raw_params = self._cell(self.steps_table, row, 2) or "{}"
            critical = self._cell(self.steps_table, row, 3).lower() not in {"no", "false", "0"}
            retries = int(self._cell(self.steps_table, row, 4) or 0)
            delay = float(self._cell(self.steps_table, row, 5) or 0)
            if kind == "wait":
                steps.append({"wait": float(subject or 1), "critical": critical})
            elif kind == "parallel":
                steps.append({"parallel": json.loads(raw_params), "critical": critical})
            elif kind == "condition":
                steps.append(json.loads(raw_params))
            else:
                step = {"capability": subject, "params": json.loads(raw_params), "critical": critical}
                if retries:
                    step["retries"] = retries
                if delay:
                    step["delay_after"] = delay
                steps.append(step)
        return steps

    def _save_routine(self):
        try:
            routine = {
                "id": self.routine_id.text().strip(),
                "name": self.routine_name.text().strip(),
                "aliases": [a.strip() for a in self.routine_aliases.text().split(",") if a.strip()],
                "description": self.routine_description.text().strip(),
                "steps": self._steps_from_table(),
            }
            saved = self.platform.routines.save(routine)
            self.routine_id.setText(saved["id"])
            self._load_routines()
            self._show_status(f"Rutina {saved['name']} guardada.")
        except Exception as exc:
            QMessageBox.critical(self, "Rutina inválida", str(exc))

    def _run_selected_routine(self):
        name = self.routine_id.text().strip()
        if name:
            self._run_background(lambda: self.platform.run_routine(name))

    def _delete_routine(self):
        routine_id = self.routine_id.text().strip()
        if routine_id and QMessageBox.question(self, "Eliminar rutina", f"¿Eliminar {routine_id}?") == QMessageBox.StandardButton.Yes:
            self.platform.routines.delete(routine_id)
            self._new_routine()
            self._load_routines()

    def _delete_step(self):
        row = self.steps_table.currentRow()
        if row >= 0:
            self.steps_table.removeRow(row)

    def _move_step(self, delta: int):
        row = self.steps_table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.steps_table.rowCount():
            return
        values = [self._cell(self.steps_table, row, c) for c in range(self.steps_table.columnCount())]
        target_values = [self._cell(self.steps_table, target, c) for c in range(self.steps_table.columnCount())]
        for c, value in enumerate(target_values):
            self.steps_table.setItem(row, c, QTableWidgetItem(value))
        for c, value in enumerate(values):
            self.steps_table.setItem(target, c, QTableWidgetItem(value))
        self.steps_table.selectRow(target)

    # ------------------------------- modes ------------------------------
    def _build_modes(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        self.mode_list = QListWidget()
        self.mode_list.setStyleSheet(self._list_style())
        self.mode_list.currentTextChanged.connect(self._select_mode)
        root.addWidget(self.mode_list, 1)
        right = QWidget()
        lay = QVBoxLayout(right)
        form = QFormLayout()
        self.mode_id = line_edit()
        self.mode_name = line_edit()
        self.mode_aliases = line_edit()
        self.mode_enter = line_edit()
        self.mode_exit = line_edit()
        self.mode_group = line_edit("activity")
        self.mode_active = QLabel("INACTIVO")
        for label, widget in [
            ("ID", self.mode_id), ("Nombre", self.mode_name), ("Alias", self.mode_aliases),
            ("Rutina de entrada", self.mode_enter), ("Rutina de salida", self.mode_exit),
            ("Grupo exclusivo", self.mode_group), ("Estado", self.mode_active),
        ]:
            form.addRow(label, widget)
        lay.addLayout(form)
        self.mode_monitors = QTextEdit()
        self.mode_monitors.setPlaceholderText("Monitores JSON (lista)")
        self.mode_monitors.setStyleSheet(self._text_style())
        lay.addWidget(QLabel("Monitores persistentes (JSON)"))
        lay.addWidget(self.mode_monitors, 1)
        row = QHBoxLayout()
        for text, cb in [
            ("NUEVO", self._new_mode), ("GUARDAR", self._save_mode),
            ("ACTIVAR", lambda: self._mode_operation("start")),
            ("DESACTIVAR", lambda: self._mode_operation("stop")),
            ("ELIMINAR", self._delete_mode),
        ]:
            b = button(text, danger=text == "ELIMINAR")
            b.clicked.connect(cb)
            row.addWidget(b)
        lay.addLayout(row)
        root.addWidget(right, 3)
        return page

    def _load_modes(self):
        self._mode_cache = {m["id"]: m for m in self.platform.modes.list()}
        self.mode_list.clear()
        for mode in self._mode_cache.values():
            marker = "●" if mode.get("active") else "○"
            self.mode_list.addItem(f"{mode['id']} | {marker} {mode.get('name', '')}")

    def _select_mode(self, text: str):
        mode_id = text.split(" |", 1)[0]
        mode = self._mode_cache.get(mode_id)
        if not mode:
            return
        self.mode_id.setText(mode.get("id", ""))
        self.mode_name.setText(mode.get("name", ""))
        self.mode_aliases.setText(", ".join(mode.get("aliases", [])))
        self.mode_enter.setText(mode.get("enter_routine", ""))
        self.mode_exit.setText(mode.get("exit_routine", ""))
        self.mode_group.setText(mode.get("exclusive_group", ""))
        self.mode_active.setText("ACTIVO" if mode.get("active") else "INACTIVO")
        self.mode_active.setStyleSheet(f"color:{CYAN if mode.get('active') else DIM};")
        self.mode_monitors.setPlainText(json.dumps(mode.get("monitors", []), indent=2, ensure_ascii=False))

    def _new_mode(self):
        self.mode_id.clear(); self.mode_name.setText("Nuevo modo"); self.mode_aliases.clear()
        self.mode_enter.clear(); self.mode_exit.clear(); self.mode_group.setText("activity")
        self.mode_monitors.setPlainText("[]")

    def _save_mode(self):
        try:
            mode = {
                "id": self.mode_id.text().strip(), "name": self.mode_name.text().strip(),
                "aliases": [a.strip() for a in self.mode_aliases.text().split(",") if a.strip()],
                "enter_routine": self.mode_enter.text().strip(), "exit_routine": self.mode_exit.text().strip(),
                "exclusive_group": self.mode_group.text().strip(),
                "monitors": json.loads(self.mode_monitors.toPlainText() or "[]"),
            }
            saved = self.platform.modes.save(mode)
            self.mode_id.setText(saved["id"])
            self._load_modes()
            self._show_status("Modo guardado.")
        except Exception as exc:
            QMessageBox.critical(self, "Modo inválido", str(exc))

    def _mode_operation(self, operation: str):
        mode_id = self.mode_id.text().strip()
        if mode_id:
            self._run_background(lambda: self.platform.manage_mode(operation, mode_id))

    def _delete_mode(self):
        # ModeManager intentionally exposes save/list/start/stop; direct file deletion
        # is kept here for advanced configuration through the modes JSON store.
        mode_id = self.mode_id.text().strip()
        if not mode_id:
            return
        data = self.platform.modes.store.load()
        data["modes"] = [m for m in data.get("modes", []) if m.get("id") != mode_id]
        self.platform.modes.store.save(data)
        self._new_mode(); self._load_modes()

    # --------------------------- automations ----------------------------
    def _build_automations(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        self.automation_list = QListWidget()
        self.automation_list.setStyleSheet(self._list_style())
        self.automation_list.currentTextChanged.connect(self._select_automation)
        root.addWidget(self.automation_list, 1)
        right = QWidget()
        lay = QVBoxLayout(right)
        help_lbl = QLabel("Editor avanzado. Una automatización responde a eventos o intervalos y ejecuta capacidades, rutinas o modos.")
        help_lbl.setWordWrap(True); help_lbl.setStyleSheet(f"color:{DIM};")
        lay.addWidget(help_lbl)
        self.automation_json = QTextEdit()
        self.automation_json.setStyleSheet(self._text_style())
        lay.addWidget(self.automation_json, 1)
        row = QHBoxLayout()
        for text, cb in [
            ("NUEVA", self._new_automation), ("GUARDAR", self._save_automation),
            ("PROBAR", self._test_automation), ("ACTIVAR/DESACTIVAR", self._toggle_automation),
            ("ELIMINAR", self._delete_automation),
        ]:
            b = button(text, danger=text == "ELIMINAR")
            b.clicked.connect(cb)
            row.addWidget(b)
        lay.addLayout(row)
        root.addWidget(right, 3)
        return page

    def _load_automations(self):
        self._automation_cache = {a["id"]: a for a in self.platform.automations.list()}
        self.automation_list.clear()
        for rule in self._automation_cache.values():
            self.automation_list.addItem(f"{rule['id']} | {'ON' if rule.get('enabled', True) else 'OFF'} | {rule.get('name', '')}")

    def _select_automation(self, text: str):
        rule_id = text.split(" |", 1)[0]
        rule = self._automation_cache.get(rule_id)
        if rule:
            self.automation_json.setPlainText(json.dumps(rule, indent=2, ensure_ascii=False))

    def _new_automation(self):
        template = {
            "id": "nueva_automatizacion", "name": "Nueva automatización", "enabled": True,
            "trigger": {"type": "event", "topic": "esp32.event.device_changed"},
            "conditions": [],
            "actions": [{"capability": "notifications.emit", "params": {"title": "JARVIS", "message": "Evento detectado"}}],
            "cooldown": 5,
        }
        self.automation_json.setPlainText(json.dumps(template, indent=2, ensure_ascii=False))

    def _save_automation(self):
        try:
            rule = json.loads(self.automation_json.toPlainText())
            self.platform.automations.save(rule)
            self._load_automations()
            self._show_status("Automatización guardada.")
        except Exception as exc:
            QMessageBox.critical(self, "JSON inválido", str(exc))

    def _test_automation(self):
        try:
            rule = json.loads(self.automation_json.toPlainText())
            self.platform.automations.save(rule)
            self._run_background(lambda: self.platform.automations.test(rule["id"]))
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _toggle_automation(self):
        try:
            rule = json.loads(self.automation_json.toPlainText())
            rule["enabled"] = not bool(rule.get("enabled", True))
            self.platform.automations.save(rule)
            self.automation_json.setPlainText(json.dumps(rule, indent=2, ensure_ascii=False))
            self._load_automations()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _delete_automation(self):
        try:
            rule = json.loads(self.automation_json.toPlainText())
            self.platform.automations.delete(rule["id"])
            self.automation_json.clear(); self._load_automations()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    # --------------------------- integrations ---------------------------
    def _build_integrations(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.integration_widgets: dict[str, QLineEdit] = {}

        obs_box = self._section("OBS WebSocket 5.x")
        obs_form = QFormLayout(obs_box)
        for key, label, secret in [("obs.host", "Host", False), ("obs.port", "Puerto", False), ("obs.password", "Contraseña", True)]:
            w = line_edit(secret=secret); self.integration_widgets[key] = w; obs_form.addRow(label, w)
        lay.addWidget(obs_box)

        spotify_box = self._section("Spotify Web API")
        spotify_form = QFormLayout(spotify_box)
        for key, label, secret in [
            ("spotify.client_id", "Client ID", False), ("spotify.client_secret", "Client Secret", True),
            ("spotify.redirect_uri", "Redirect URI", False), ("spotify.preferred_device", "Dispositivo preferido", False),
        ]:
            w = line_edit(secret=secret); self.integration_widgets[key] = w; spotify_form.addRow(label, w)
        lay.addWidget(spotify_box)

        gmail_box = self._section("Gmail API")
        gmail_form = QFormLayout(gmail_box)
        for key, label in [("gmail.credentials_path", "Credenciales OAuth"), ("gmail.token_path", "Token")]:
            w = line_edit(); self.integration_widgets[key] = w; gmail_form.addRow(label, w)
        lay.addWidget(gmail_box)

        row = QHBoxLayout()
        save = button("GUARDAR INTEGRACIONES"); save.clicked.connect(self._save_integrations); row.addWidget(save)
        test_obs = button("PROBAR OBS"); test_obs.clicked.connect(lambda: self._run_background(lambda: self.platform.execute("obs.status"))); row.addWidget(test_obs)
        test_sp = button("PROBAR SPOTIFY"); test_sp.clicked.connect(lambda: self._run_background(lambda: self.platform.execute("spotify.status"))); row.addWidget(test_sp)
        test_mail = button("AUTORIZAR/PROBAR GMAIL"); test_mail.clicked.connect(lambda: self._run_background(lambda: self.platform.execute("gmail.status"))); row.addWidget(test_mail)
        lay.addLayout(row)
        lay.addStretch()
        return page

    def _load_integrations(self):
        cfg = self.platform.get_integrations()
        for path, widget in self.integration_widgets.items():
            section, key = path.split(".", 1)
            widget.setText(str((cfg.get(section) or {}).get(key, "")))

    def _save_integrations(self):
        cfg = deepcopy(self.platform.get_integrations())
        for path, widget in self.integration_widgets.items():
            section, key = path.split(".", 1)
            cfg.setdefault(section, {})[key] = widget.text().strip()
        try:
            cfg["obs"]["port"] = int(cfg["obs"].get("port", 4455))
        except Exception:
            cfg["obs"]["port"] = 4455
        self.platform.save_integrations(cfg)
        self._show_status("Integraciones guardadas.")

    # ----------------------------- activity -----------------------------
    def _build_activity(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.activity_text = QTextEdit()
        self.activity_text.setReadOnly(True)
        self.activity_text.setStyleSheet(self._text_style())
        lay.addWidget(self.activity_text, 1)
        refresh = button("ACTUALIZAR ACTIVIDAD")
        refresh.clicked.connect(self._load_activity)
        lay.addWidget(refresh)
        return page

    def _load_activity(self):
        events = self.platform.event_bus.history("*", 150)
        self.activity_text.setPlainText("\n".join(json.dumps(e, ensure_ascii=False) for e in events))

    # ----------------------------- helpers ------------------------------
    def refresh_all(self):
        self._load_audio()
        self._load_nodes()
        self._load_devices()
        self._load_routines()
        self._load_modes()
        self._load_automations()
        self._load_integrations()
        self._load_activity()
        status = self.platform.status()
        active_modes = [m["name"] for m in status["modes"] if m.get("active")]
        self.dashboard_summary.setPlainText(
            "PAVO'S ROBOTIC PROJECTS // JARVIS\n\n"
            f"Capacidades registradas: {status['capabilities']}\n"
            f"Rutinas: {status['routines']}\n"
            f"Automatizaciones: {status['automations']}\n"
            f"Modos activos: {', '.join(active_modes) or 'ninguno'}\n"
            f"Nodos ESP32: {len(status['nodes'])}\n"
            f"Dispositivos domóticos: {len(status['devices'])}\n\n"
            "Desde este panel puedes cambiar GPIO, nombres, alias y funciones; crear rutinas; "
            "activar modos persistentes; y configurar OBS, Spotify y Gmail sin editar Python."
        )

    def _run_background(self, fn):
        self._show_status("Ejecutando...")

        def worker():
            try:
                result = fn()
                if hasattr(result, "message"):
                    message = result.message
                    if getattr(result, "warnings", None):
                        message += " | " + " | ".join(result.warnings)
                else:
                    message = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                self.log_signal.emit(message)
            except Exception as exc:
                self.log_signal.emit(f"ERROR: {exc}")
            self.refresh_signal.emit()

        threading.Thread(target=worker, daemon=True, name="ControlCenterAction").start()

    def _show_status(self, text: str):
        self.status.setText(text)

    def _load_node_choices(self):
        pass

    @staticmethod
    def _cell(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _style_table(table: QTableWidget):
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setStyleSheet(
            f"QTableWidget{{background:#03111d;color:{TEXT};gridline-color:{LINE};alternate-background-color:#061827;}}"
            f"QHeaderView::section{{background:#071523;color:{CYAN};border:1px solid {LINE};padding:6px;}}"
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)

    @staticmethod
    def _text_style() -> str:
        return f"background:#03111d;color:{TEXT};border:1px solid {LINE};border-radius:8px;font-family:Consolas;"

    @staticmethod
    def _list_style() -> str:
        return f"QListWidget{{background:#03111d;color:{TEXT};border:1px solid {LINE};}} QListWidget::item:selected{{background:#0b3448;color:{CYAN};}}"

    @staticmethod
    def _combo_style() -> str:
        return f"QComboBox{{background:#03111d;color:{TEXT};border:1px solid {LINE};border-radius:7px;padding:6px;}} QComboBox QAbstractItemView{{background:#03111d;color:{TEXT};selection-background-color:#0b3448;}}"

    @staticmethod
    def _spin_style() -> str:
        return f"QSpinBox,QDoubleSpinBox{{background:#03111d;color:{TEXT};border:1px solid {LINE};border-radius:7px;padding:6px;}}"

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: Any) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    @staticmethod
    def _section(title: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"QFrame{{background:{PANEL};border:1px solid {LINE};border-radius:10px;padding:8px;}} QLabel{{border:none;}}")
        frame.setToolTip(title)
        return frame
