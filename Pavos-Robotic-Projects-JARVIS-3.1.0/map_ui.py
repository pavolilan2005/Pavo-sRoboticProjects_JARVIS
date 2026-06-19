from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except Exception:  # pragma: no cover - runtime dependency
    QWebEnginePage = object  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]
    WEBENGINE_AVAILABLE = False


CYAN = "#00eaff"
ICE = "#d7f8ff"
GREEN = "#39ff88"
BLUE = "#4aa8ff"
RED = "#ff315f"
VOID = "#020a12"
PANEL = "#071523"
LINE = "#1d5d87"
TEXT_DIM = "#6da8bb"


def _button_style(color: str = CYAN, bg: str = "#04131f") -> str:
    return f"""
        QPushButton {{
            color: {color};
            background: {bg};
            border: 1px solid {color};
            border-radius: 12px;
            padding: 7px 10px;
        }}
        QPushButton:hover {{
            background: #0a2a3d;
            color: #ffffff;
            border: 1px solid #ffffff;
        }}
        QPushButton:pressed {{ background: {color}; color: #020a12; }}
    """


if WEBENGINE_AVAILABLE:
    class _MapPage(QWebEnginePage):
        event_received = pyqtSignal(str, object)

        def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # noqa: N802
            prefix = "PRP_MAP_EVENT:"
            if str(message).startswith(prefix):
                try:
                    payload = json.loads(str(message)[len(prefix):])
                    self.event_received.emit(str(payload.get("type", "event")), payload.get("payload", {}))
                    return
                except Exception:
                    pass
            super().javaScriptConsoleMessage(level, message, line_number, source_id)


class CesiumMapView(QWidget):
    map_ready = pyqtSignal()
    map_clicked = pyqtSignal(float, float, float)
    event_received = pyqtSignal(str, object)

    def __init__(self, html_path: Path, parent=None):
        super().__init__(parent)
        self._ready = False
        self._pending: list[str] = []
        self._html_path = Path(html_path)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not WEBENGINE_AVAILABLE:
            fallback = QFrame()
            fallback.setStyleSheet(f"background:{VOID}; border:1px solid {LINE}; border-radius:18px;")
            fl = QVBoxLayout(fallback)
            title = QLabel("MÓDULO HOLOMAP NO DISPONIBLE")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
            title.setStyleSheet(f"color:{RED}; border:none;")
            body = QLabel(
                "Falta PyQt6-WebEngine. Ejecuta INSTALAR_JARVIS.bat o:\n\n"
                ".venv\\Scripts\\python.exe -m pip install PyQt6-WebEngine"
            )
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setWordWrap(True)
            body.setStyleSheet(f"color:{ICE}; border:none;")
            button = QPushButton("ABRIR OPENSTREETMAP EN EL NAVEGADOR")
            button.setStyleSheet(_button_style())
            button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.openstreetmap.org")))
            fl.addStretch(); fl.addWidget(title); fl.addWidget(body); fl.addWidget(button); fl.addStretch()
            layout.addWidget(fallback)
            self._view = None
            return

        self._view = QWebEngineView(self)
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        page = _MapPage(self._view)
        page.event_received.connect(self._on_event)
        self._view.setPage(page)
        try:
            page.profile().setHttpUserAgent(
                "PavosRoboticProjects-JARVIS/3.2.0 QtWebEngine HolographicNavigation"
            )
        except Exception:
            pass
        self._view.loadFinished.connect(self._on_loaded)
        self._view.setUrl(QUrl.fromLocalFile(str(self._html_path.resolve())))
        layout.addWidget(self._view)

    def _on_loaded(self, ok: bool):
        if not ok:
            return
        self._ready = True
        for script in self._pending:
            self._view.page().runJavaScript(script)
        self._pending.clear()

    def _run(self, script: str):
        if self._view is None:
            return
        if self._ready:
            self._view.page().runJavaScript(script)
        else:
            self._pending.append(script)

    def _on_event(self, event_type: str, payload: object):
        data = payload if isinstance(payload, dict) else {}
        if event_type == "ready":
            self.map_ready.emit()
        if event_type == "clicked":
            try:
                self.map_clicked.emit(float(data["lat"]), float(data["lon"]), float(data.get("height", 0)))
            except Exception:
                pass
        self.event_received.emit(event_type, payload)

    @staticmethod
    def _js_string(value: Any) -> str:
        return json.dumps(str(value or ""), ensure_ascii=False)

    def fly_to(self, lat: float, lon: float, height: float = 120000.0, label: str = ""):
        self._run(
            f"window.prpMap && window.prpMap.flyTo({float(lat)}, {float(lon)}, "
            f"{float(height)}, {self._js_string(label)});"
        )

    def global_view(self):
        self._run("window.prpMap && window.prpMap.globalView();")

    def add_marker(self, lat: float, lon: float, label: str = "PUNTO", focus: bool = False):
        self._run(
            f"window.prpMap && window.prpMap.addMarker({float(lat)}, {float(lon)}, "
            f"{self._js_string(label)}, {str(bool(focus)).lower()});"
        )

    def clear_markers(self):
        self._run("window.prpMap && window.prpMap.clearMarkers();")

    def set_orbit(self, enabled: bool):
        self._run(f"window.prpMap && window.prpMap.setOrbit({str(bool(enabled)).lower()});")

    def set_street_style(self, enabled: bool):
        self._run(f"window.prpMap && window.prpMap.setStreetStyle({str(bool(enabled)).lower()});")


class HolographicMapWidget(QWidget):
    search_requested = pyqtSignal(str)
    home_requested = pyqtSignal()
    set_home_requested = pyqtSignal(float, float, str)
    save_requested = pyqtSignal(float, float, str)
    core_requested = pyqtSignal()
    reverse_requested = pyqtSignal(float, float)

    def __init__(self, base_dir: Path, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self._selected: dict[str, Any] | None = None
        self._orbit = False
        self._street = False
        self._results: list[dict[str, Any]] = []

        self.setStyleSheet(f"background:{VOID};")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Build the renderer first because the control panel connects directly
        # to its navigation methods.
        self.map_view = CesiumMapView(self.base_dir / "assets" / "map" / "cesium_prp.html")
        root.addWidget(self._build_control_panel(), 0)

        map_frame = QFrame()
        map_frame.setStyleSheet(f"background:{VOID}; border:1px solid {CYAN}; border-radius:20px;")
        ml = QVBoxLayout(map_frame)
        ml.setContentsMargins(3, 3, 3, 3)
        self.map_view.map_clicked.connect(self._on_map_clicked)
        self.map_view.map_ready.connect(lambda: self.set_status("GLOBO EN LÍNEA", GREEN))
        ml.addWidget(self.map_view)
        root.addWidget(map_frame, 1)

        self._pulse = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._animate_status)
        self._pulse_timer.start(45)

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(315)
        panel.setStyleSheet(f"background:{PANEL}; border:1px solid {LINE}; border-radius:20px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("PRP // HOLOGRAPHIC\nNAVIGATION SYSTEM")
        title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{CYAN}; border:none;")
        layout.addWidget(title)

        self._status = QLabel("INICIALIZANDO GLOBO...")
        self._status.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._status.setStyleSheet(f"color:{GREEN}; border:none;")
        layout.addWidget(self._status)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Lugar, monumento o coordenadas...")
        self._search.setFixedHeight(40)
        self._search.setStyleSheet(f"""
            QLineEdit {{ background:#030c16; color:{ICE}; border:1px solid {LINE};
                border-radius:13px; padding:8px 11px; }}
            QLineEdit:focus {{ border:1px solid {GREEN}; }}
        """)
        self._search.returnPressed.connect(self._emit_search)
        layout.addWidget(self._search)

        search_button = QPushButton("BUSCAR Y NAVEGAR")
        search_button.setStyleSheet(_button_style(GREEN, "#062016"))
        search_button.clicked.connect(self._emit_search)
        layout.addWidget(search_button)

        row = QHBoxLayout()
        global_btn = QPushButton("GLOBAL")
        global_btn.setStyleSheet(_button_style(CYAN))
        global_btn.clicked.connect(self.map_view.global_view)
        home_btn = QPushButton("CASA")
        home_btn.setStyleSheet(_button_style(ICE))
        home_btn.clicked.connect(self.home_requested.emit)
        row.addWidget(global_btn); row.addWidget(home_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self._orbit_btn = QPushButton("ÓRBITA: OFF")
        self._orbit_btn.setStyleSheet(_button_style(BLUE))
        self._orbit_btn.clicked.connect(self._toggle_orbit)
        self._style_btn = QPushButton("VISTA: HOLO")
        self._style_btn.setStyleSheet(_button_style(CYAN))
        self._style_btn.clicked.connect(self._toggle_style)
        row2.addWidget(self._orbit_btn); row2.addWidget(self._style_btn)
        layout.addLayout(row2)

        section = QLabel("RESULTADOS DE BÚSQUEDA")
        section.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        section.setStyleSheet(f"color:{TEXT_DIM}; border:none; margin-top:6px;")
        layout.addWidget(section)

        self._results_list = QListWidget()
        self._results_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._results_list.setStyleSheet(f"""
            QListWidget {{ background:#030c16; color:{ICE}; border:1px solid {LINE}; border-radius:14px; padding:5px; }}
            QListWidget::item {{ padding:8px; border-bottom:1px solid #0c2940; }}
            QListWidget::item:selected {{ background:#0b3442; color:{GREEN}; }}
            QListWidget::item:hover {{ background:#082437; }}
        """)
        self._results_list.itemClicked.connect(self._select_result)
        layout.addWidget(self._results_list, 1)

        self._coords = QLabel("PUNTO SELECCIONADO\nLAT --\nLON --")
        self._coords.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._coords.setStyleSheet(f"color:{ICE}; background:#030c16; border:1px solid {LINE}; border-radius:12px; padding:9px;")
        layout.addWidget(self._coords)

        action_row = QHBoxLayout()
        save_btn = QPushButton("GUARDAR")
        save_btn.setStyleSheet(_button_style(GREEN))
        save_btn.clicked.connect(self._save_selected)
        set_home_btn = QPushButton("FIJAR CASA")
        set_home_btn.setStyleSheet(_button_style(ICE))
        set_home_btn.clicked.connect(self._set_home)
        action_row.addWidget(save_btn); action_row.addWidget(set_home_btn)
        layout.addLayout(action_row)

        clear_btn = QPushButton("LIMPIAR MARCADORES")
        clear_btn.setStyleSheet(_button_style(RED, "#180710"))
        clear_btn.clicked.connect(self.map_view.clear_markers)
        layout.addWidget(clear_btn)

        core_btn = QPushButton("◀ VOLVER AL NÚCLEO")
        core_btn.setStyleSheet(_button_style(CYAN))
        core_btn.clicked.connect(self.core_requested.emit)
        layout.addWidget(core_btn)
        return panel

    def _emit_search(self):
        query = self._search.text().strip()
        if query:
            self.set_status("BUSCANDO COORDENADAS...", GREEN)
            self.search_requested.emit(query)

    def _toggle_orbit(self):
        self._orbit = not self._orbit
        self.map_view.set_orbit(self._orbit)
        self._orbit_btn.setText(f"ÓRBITA: {'ON' if self._orbit else 'OFF'}")

    def _toggle_style(self):
        self._street = not self._street
        self.map_view.set_street_style(self._street)
        self._style_btn.setText(f"VISTA: {'CALLES' if self._street else 'HOLO'}")

    def _on_map_clicked(self, lat: float, lon: float, height: float):
        self._selected = {"lat": lat, "lon": lon, "height": height, "name": "Punto seleccionado"}
        self._coords.setText(f"PUNTO SELECCIONADO\nLAT {lat:.6f}\nLON {lon:.6f}")
        self.map_view.add_marker(lat, lon, "PUNTO", False)
        self.reverse_requested.emit(lat, lon)

    def _select_result(self, item: QListWidgetItem):
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        try:
            result = self._results[int(index)]
            self._selected = dict(result)
            self._coords.setText(
                f"OBJETIVO SELECCIONADO\nLAT {float(result['lat']):.6f}\nLON {float(result['lon']):.6f}"
            )
            self.map_view.fly_to(
                float(result["lat"]), float(result["lon"]), float(result.get("height", 90000)), str(result.get("name", ""))
            )
        except Exception:
            pass

    def _save_selected(self):
        if not self._selected:
            QMessageBox.information(self, "PRP HOLOMAP", "Selecciona un punto o resultado primero.")
            return
        default = str(self._selected.get("name") or "Ubicación")
        name, ok = QInputDialog.getText(self, "Guardar ubicación", "Nombre:", text=default)
        if ok and name.strip():
            self.save_requested.emit(float(self._selected["lat"]), float(self._selected["lon"]), name.strip())

    def _set_home(self):
        if not self._selected:
            QMessageBox.information(self, "PRP HOLOMAP", "Selecciona un punto o resultado primero.")
            return
        default = str(self._selected.get("name") or "Casa")
        name, ok = QInputDialog.getText(self, "Fijar ubicación principal", "Nombre:", text=default)
        if ok and name.strip():
            self.set_home_requested.emit(float(self._selected["lat"]), float(self._selected["lon"]), name.strip())

    def _animate_status(self):
        self._pulse += 0.08
        alpha = int(155 + 80 * (0.5 + 0.5 * math.sin(self._pulse)))
        color = self._status.property("prp_color") or GREEN
        q = QColor(str(color)); q.setAlpha(alpha)
        self._status.setStyleSheet(f"color:rgba({q.red()},{q.green()},{q.blue()},{q.alpha()}); border:none;")

    def set_status(self, text: str, color: str = GREEN):
        self._status.setText(str(text).upper())
        self._status.setProperty("prp_color", color)

    def set_results(self, results: list[dict[str, Any]], query: str = ""):
        self._results = [dict(item) for item in results]
        self._results_list.clear()
        for index, result in enumerate(self._results):
            name = str(result.get("name") or result.get("display_name") or "Resultado")
            type_name = str(result.get("type") or result.get("category") or "lugar").upper()
            item = QListWidgetItem(f"{name}\n{type_name} · {float(result['lat']):.4f}, {float(result['lon']):.4f}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._results_list.addItem(item)
        if self._results:
            first = self._results[0]
            self._selected = dict(first)
            self.map_view.fly_to(float(first["lat"]), float(first["lon"]), float(first.get("height", 90000)), str(first.get("name", query)))
            self.set_status(f"OBJETIVO LOCALIZADO · {len(self._results)} RESULTADOS", GREEN)
        else:
            self.set_status("SIN COINCIDENCIAS", RED)

    def fly_to(self, lat: float, lon: float, height: float, label: str = ""):
        self._selected = {"lat": lat, "lon": lon, "height": height, "name": label or "Objetivo"}
        self.map_view.fly_to(lat, lon, height, label)
        self._coords.setText(f"OBJETIVO ACTIVO\nLAT {lat:.6f}\nLON {lon:.6f}")
        self.set_status("NAVEGANDO", GREEN)

    def add_marker(self, lat: float, lon: float, label: str = "PUNTO"):
        self.map_view.add_marker(lat, lon, label, False)

    def clear_markers(self):
        self.map_view.clear_markers()

    def fade_in(self):
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(260)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setGraphicsEffect(None))
        self._fade_animation = animation
        animation.start()
