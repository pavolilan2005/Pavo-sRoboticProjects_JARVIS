from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QBrush,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1240, 760
_MIN_W, _MIN_H = 960, 640
_LEFT_W = 270
_RIGHT_W = 385
_OS = platform.system()


class C:
    # PRP palette: cyan / celeste tech interface.
    VOID = "#020a12"
    VOID2 = "#04111d"
    DEEP = "#071220"
    PANEL = "#071523"
    PANEL2 = "#0b1d2f"
    PANEL3 = "#081a2a"
    GLASS = "#082030"

    CYAN = "#00eaff"
    CYAN2 = "#b7f7ff"
    BLUE = "#4aa8ff"
    VIOLET = "#79c6ff"
    MAGENTA = "#7ddcff"
    EMERALD = "#67f7ff"
    LIME = "#d2fbff"
    GOLD = "#9edfff"
    ORANGE = "#5cc2ff"
    RED = "#ff315f"

    LINE = "#1d5d87"
    LINE2 = "#35b3e5"
    LINE3 = "#2f8fd6"

    TEXT = "#e4fbff"
    TEXT2 = "#8eeaff"
    TEXT_DIM = "#6da8bb"
    WHITE = "#f5fdff"


def qcol(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def _panel_style(border: str = C.LINE, bg: str = C.PANEL, radius: int = 18) -> str:
    return f"background: {bg}; border: 1px solid {border}; border-radius: {radius}px;"


def _button_style(fg: str, border: str, bg: str = "#060b18", hover: str = "#0d1d33", radius: int = 12) -> str:
    return f"""
        QPushButton {{
            background: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 5px 8px;
        }}
        QPushButton:hover {{
            background: {hover};
            border: 1px solid {fg};
        }}
        QPushButton:pressed {{
            background: {border};
            color: #020510;
        }}
    """


class _SysMetrics:
    """Background sampler. JARVIS never blocks if a metric is unavailable."""

    def __init__(self):
        self.cpu = 0.0
        self.mem = 0.0
        self.net = 0.0
        self.gpu = -1.0
        self.tmp = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.25)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc = psutil.net_io_counters()
        now = time.time()
        dt = max(0.001, now - self._last_net_t)
        net = ((nc.bytes_sent - self._last_net.bytes_sent) + (nc.bytes_recv - self._last_net.bytes_recv)) / dt
        net /= 1024 * 1024
        self._last_net = nc
        self._last_net_t = now

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = max(0.0, net)
            self.gpu = self._get_gpu()
            self.tmp = self._get_temp()

    def _get_gpu(self) -> float:
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                encoding=("mbcs" if _OS == "Windows" else None),
                errors="replace",
                timeout=2,
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.splitlines() if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        if _OS == "Linux":
            try:
                r = subprocess.run(["rocm-smi", "--showuse", "--csv"], capture_output=True, text=True, timeout=2)
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].replace("%", "").strip())
                            except ValueError:
                                pass
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            for key in ["coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower", "it8688"]:
                if key in temps and temps[key]:
                    return float(temps[key][0].current)
            for entries in temps.values():
                if entries:
                    return float(entries[0].current)
        except Exception:
            pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="mbcs",
                    errors="replace",
                    timeout=3,
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().splitlines()[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()


class PavoHudCanvas(QWidget):
    """
    Radical center HUD:
    - Peacock-feather reactor ring.
    - Holographic cyber grid.
    - Central face/core support.
    - State-aware colors.
    """

    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(450, 450)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted = False
        self.speaking = False
        self.state = "INITIALISING"

        self._tick = 0
        self._spin = 0.0
        self._spin2 = 180.0
        self._breath = 0.0
        self._amp = 0.28
        self._target_amp = 0.28
        self._bars = [random.random() for _ in range(58)]
        self._particles: list[list[float]] = []
        self._stars = [[random.random(), random.random(), random.random()] for _ in range(95)]
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)

    def _load_face(self, path: str):
        try:
            if not path or not Path(path).exists():
                self._face_px = None
                return

            from PIL import Image, ImageDraw
            import io

            img = Image.open(path).convert("RGBA")
            side = min(img.size)
            left = (img.width - side) // 2
            top = (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((1024, 1024), Image.LANCZOS)

            mask = Image.new("L", (1024, 1024), 0)
            draw = ImageDraw.Draw(mask)
            # Rounded-square hologram instead of classic circle.
            draw.rounded_rectangle((8, 8, 1016, 1016), radius=140, fill=255)
            img.putalpha(mask)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _state_color(self) -> str:
        state = "MUTED" if self.muted else self.state
        if state == "MUTED":
            return C.RED
        if state == "SPEAKING":
            return C.BLUE
        if state == "LISTENING":
            return C.CYAN2
        if state in ("PROCESSING", "THINKING"):
            return C.MAGENTA
        if state == "SLEEPING":
            return C.TEXT2
        return C.CYAN

    def _state_label(self) -> str:
        state = "MUTED" if self.muted else self.state
        return {
            "SPEAKING": "TRANSMITTING",
            "LISTENING": "ESCUCHANDO",
            "THINKING": "ANALIZANDO",
            "PROCESSING": "PROCESSING",
            "SLEEPING": "STANDBY",
            "MUTED": "MICRÓFONO EN SILENCIO",
            "INITIALISING": "BOOT SEQUENCE",
        }.get(state, state)

    def _step(self):
        self._tick += 1
        self._spin = (self._spin + (3.4 if self.speaking else 0.78)) % 360
        self._spin2 = (self._spin2 - (2.2 if self.speaking else 0.48)) % 360
        self._breath += 0.06 if self.speaking else 0.022

        if self.muted:
            self._target_amp = 0.08
        elif self.speaking:
            self._target_amp = random.uniform(0.82, 1.0)
        elif self.state in ("LISTENING", "PROCESSING", "THINKING"):
            self._target_amp = 0.64
        else:
            self._target_amp = 0.30
        self._amp += (self._target_amp - self._amp) * 0.14

        for i, v in enumerate(self._bars):
            if self.speaking:
                target = random.uniform(0.25, 1.0)
                speed = 0.62
            else:
                target = 0.22 + 0.23 * math.sin(self._tick * 0.045 + i * 0.42)
                speed = 0.12
            self._bars[i] += (target - v) * speed

        if (self.speaking or self.state in ("LISTENING", "PROCESSING", "THINKING")) and random.random() < 0.18:
            W, H = max(1, self.width()), max(1, self.height())
            cx, cy = W / 2, H / 2
            ang = random.random() * math.tau
            rr = min(W, H) * random.uniform(0.19, 0.42)
            self._particles.append([
                cx + math.cos(ang) * rr,
                cy + math.sin(ang) * rr,
                math.cos(ang) * random.uniform(0.7, 2.2),
                math.sin(ang) * random.uniform(0.7, 2.2),
                1.0,
                random.choice([C.CYAN, C.CYAN2, C.BLUE, C.MAGENTA, C.EMERALD]),
            ])

        self._particles = [
            [pt[0] + pt[2], pt[1] + pt[3], pt[2] * 0.985, pt[3] * 0.985, pt[4] - 0.018, pt[5]]
            for pt in self._particles
            if pt[4] > 0
        ]

        self.update()

    def _draw_octagon(self, p: QPainter, cx: float, cy: float, r: float):
        path = QPainterPath()
        for i in range(8):
            a = math.radians(22.5 + i * 45)
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        accent = self._state_color()

        # Deep cosmic background
        bg = QLinearGradient(0, 0, W, H)
        bg.setColorAt(0.0, qcol("#080318"))
        bg.setColorAt(0.36, qcol("#07172b"))
        bg.setColorAt(0.74, qcol("#0a0620"))
        bg.setColorAt(1.0, qcol("#02040a"))
        p.fillRect(self.rect(), QBrush(bg))

        # Starfield / data dust
        p.setPen(Qt.PenStyle.NoPen)
        for sx, sy, seed in self._stars:
            pulse = 0.45 + 0.55 * math.sin(self._tick * 0.018 + seed * 8)
            col = [C.CYAN, C.EMERALD, C.VIOLET][int(seed * 3) % 3]
            p.setBrush(QBrush(qcol(col, int(35 + 70 * pulse))))
            p.drawEllipse(QPointF(sx * W, sy * H), 1.0 + seed * 1.7, 1.0 + seed * 1.7)

        # Perspective grid
        p.setPen(QPen(qcol(C.LINE, 70), 1))
        spacing = 44
        skew = math.sin(self._tick * 0.01) * 9
        for x in range(-spacing, W + spacing, spacing):
            p.drawLine(QPointF(x + skew, 0), QPointF(x - skew, H))
        for y in range(0, H, spacing):
            p.drawLine(QPointF(0, y), QPointF(W, y + math.sin(y * 0.02 + self._tick * 0.01) * 3))

        # Hologram glow
        rg = QRadialGradient(QPointF(cx, cy), fw * 0.70)
        rg.setColorAt(0.00, qcol(accent, int(36 + 50 * self._amp)))
        rg.setColorAt(0.42, qcol(C.VIOLET, 22))
        rg.setColorAt(0.75, qcol(C.VOID, 52))
        rg.setColorAt(1.00, qcol("#000000", 145))
        p.fillRect(self.rect(), QBrush(rg))

        reactor_r = fw * 0.235
        feather_inner = reactor_r * 1.48
        feather_outer = reactor_r * 2.08

        # Peacock-feather reactor halo
        feather_count = 22
        for i in range(feather_count):
            angle = math.radians(i * (360 / feather_count) + self._spin * 0.18)
            mid_r = (feather_inner + feather_outer) / 2
            fx = cx + math.cos(angle) * mid_r
            fy = cy + math.sin(angle) * mid_r
            length = (feather_outer - feather_inner) * 0.82
            width = fw * 0.027
            colors = [C.CYAN2, C.CYAN, C.BLUE, C.MAGENTA, C.EMERALD]
            fcol = colors[i % len(colors)]

            p.save()
            p.translate(QPointF(fx, fy))
            p.rotate(math.degrees(angle) + 90)
            p.setPen(QPen(qcol(fcol, 85), 1))
            p.setBrush(QBrush(qcol(fcol, int(14 + 30 * self._amp))))
            p.drawEllipse(QRectF(-width, -length / 2, width * 2, length))
            # "Eye" of the feather
            p.setBrush(QBrush(qcol(C.BLUE, 145)))
            p.setPen(QPen(qcol(C.CYAN2, 130), 1))
            p.drawEllipse(QRectF(-width * 0.66, -length * 0.12, width * 1.32, width * 1.32))
            p.setBrush(QBrush(qcol(C.GOLD, 180)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(-width * 0.26, -length * 0.03, width * 0.52, width * 0.52))
            p.restore()

            # Feather stem line
            p.setPen(QPen(qcol(fcol, 55), 1))
            p.drawLine(
                QPointF(cx + math.cos(angle) * feather_inner, cy + math.sin(angle) * feather_inner),
                QPointF(cx + math.cos(angle) * feather_outer, cy + math.sin(angle) * feather_outer),
            )

        # Rotating segmented rings
        rings = [
            (reactor_r * 2.24, 4, 42, 20, self._spin, C.CYAN),
            (reactor_r * 1.96, 3, 72, 40, -self._spin2, C.EMERALD),
            (reactor_r * 1.56, 2, 36, 18, self._spin2, C.VIOLET),
            (reactor_r * 1.18, 2, 94, 46, -self._spin, accent),
        ]
        for rr, width, arc, gap, offset, col in rings:
            rect = QRectF(cx - rr, cy - rr, rr * 2, rr * 2)
            p.setPen(QPen(qcol(col, int(120 + 95 * self._amp)), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            start = offset
            while start < offset + 360:
                p.drawArc(rect, int(start * 16), int(arc * 16))
                start += arc + gap

        # Radial signal ticks
        p.setPen(QPen(qcol(C.CYAN2, 120), 1))
        r_in = reactor_r * 2.35
        r_out = reactor_r * 2.46
        for deg in range(0, 360, 4):
            if deg % 3:
                alpha = 55
                inner = r_out - 4
            else:
                alpha = 130
                inner = r_in
            p.setPen(QPen(qcol(accent if deg % 5 else C.EMERALD, alpha), 1))
            rad = math.radians(deg + self._spin * 0.04)
            p.drawLine(
                QPointF(cx + inner * math.cos(rad), cy + inner * math.sin(rad)),
                QPointF(cx + r_out * math.cos(rad), cy + r_out * math.sin(rad)),
            )

        # Central octagonal glass
        core_r = reactor_r * (1.02 + 0.02 * math.sin(self._breath))
        p.setBrush(QBrush(qcol("#071326", 232)))
        p.setPen(QPen(qcol(accent, 230), 2))
        self._draw_octagon(p, cx, cy, core_r)

        # Core crop area as rounded square face / fallback
        face_rect = QRectF(cx - core_r * 0.72, cy - core_r * 0.72, core_r * 1.44, core_r * 1.44)
        if self._face_px:
            pix = int(core_r * 1.45)
            px = self._face_px.scaled(
                pix,
                pix,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.setOpacity(0.95 if not self.muted else 0.42)
            p.drawPixmap(int(cx - pix / 2), int(cy - pix / 2), px)
            p.setOpacity(1.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qcol(accent, 220), 2))
            p.drawRoundedRect(face_rect, 22, 22)
        else:
            inner_g = QRadialGradient(QPointF(cx, cy), core_r)
            inner_g.setColorAt(0, qcol(accent, 120))
            inner_g.setColorAt(0.65, qcol(C.BLUE, 55))
            inner_g.setColorAt(1, qcol(C.VOID, 10))
            p.setBrush(QBrush(inner_g))
            p.setPen(QPen(qcol(accent, 230), 2))
            p.drawEllipse(QRectF(cx - core_r * 0.56, cy - core_r * 0.56, core_r * 1.12, core_r * 1.12))
            p.setFont(QFont("Courier New", max(15, int(fw * 0.027)), QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.WHITE), 1))
            p.drawText(face_rect, Qt.AlignmentFlag.AlignCenter, "PRP\nCORE")

        # Crosshair and data probes
        p.setPen(QPen(qcol(accent, 135), 1))
        gap = core_r * 1.16
        ext = reactor_r * 2.62
        p.drawLine(QPointF(cx - ext, cy), QPointF(cx - gap, cy))
        p.drawLine(QPointF(cx + gap, cy), QPointF(cx + ext, cy))
        p.drawLine(QPointF(cx, cy - ext), QPointF(cx, cy - gap))
        p.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + ext))

        # Orbiting particles
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            p.setBrush(QBrush(qcol(pt[5], int(max(0, min(255, pt[4] * 220))))))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.6, 2.6)

        # Bottom status card
        card_w = min(520, W * 0.68)
        card_h = 82
        card_y = min(H - card_h - 22, cy + reactor_r * 2.85)
        card = QRectF(cx - card_w / 2, card_y, card_w, card_h)

        p.setBrush(QBrush(qcol("#070d1c", 225)))
        p.setPen(QPen(qcol(accent, 155), 1.2))
        p.drawRoundedRect(card, 20, 20)

        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.setPen(QPen(qcol(accent), 1))
        p.drawText(QRectF(card.x(), card.y() + 9, card.width(), 20), Qt.AlignmentFlag.AlignCenter, self._state_label())

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(card.x(), card.y() + 30, card.width(), 14), Qt.AlignmentFlag.AlignCenter, "VOICE LINK · ESP32 SERIAL · DOMÓTICA")

        # Voice waveform
        bar_count = len(self._bars)
        bw = card.width() / bar_count
        baseline = card.y() + 66
        max_h = 19
        p.setPen(Qt.PenStyle.NoPen)
        for i, val in enumerate(self._bars):
            h = max(2, val * max_h * (0.58 + self._amp * 0.55))
            if self.muted:
                col = C.RED
                h = 2
            elif i % 5 == 0:
                col = C.MAGENTA
            elif i % 3 == 0:
                col = C.EMERALD
            else:
                col = accent
            p.setBrush(QBrush(qcol(col, 185)))
            p.drawRoundedRect(QRectF(card.x() + i * bw + 2, baseline - h, max(1.5, bw - 4), h), 2, 2)


class MetricOrb(QWidget):
    def __init__(self, label: str, color: str = C.CYAN, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._text = "--"
        self.setFixedHeight(74)
        self.setMinimumWidth(170)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, float(pct)))
        self._text = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        col = self._color
        if self._value >= 86:
            col = C.RED
        elif self._value >= 66:
            col = C.ORANGE

        bg = QLinearGradient(0, 0, W, H)
        bg.setColorAt(0, qcol("#090d1e"))
        bg.setColorAt(1, qcol("#081931"))
        p.setBrush(QBrush(bg))
        p.setPen(QPen(qcol(col, 120), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 18, 18)

        # Mini ring
        cx, cy = 42, H / 2
        rr = 20
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol("#08101d"), 5))
        p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))
        p.setPen(QPen(qcol(col, 210), 5))
        p.drawArc(QRectF(cx - rr, cy - rr, rr * 2, rr * 2), 90 * 16, int(-360 * 16 * (self._value / 100.0)))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.drawText(QRectF(cx - rr, cy - 7, rr * 2, 14), Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}")

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(78, 15, W - 92, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        p.setPen(QPen(qcol(col), 1))
        p.drawText(QRectF(78, 31, W - 92, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)


class PavoChip(QLabel):
    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background: #070b1b;
                border: 1px solid {color};
                border-radius: 14px;
                padding: 5px 10px;
            }}
        """)


class NeonSection(QLabel):
    def __init__(self, text: str, color: str = C.CYAN, parent=None):
        super().__init__(f"▰ {text}", parent)
        self.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self.setStyleSheet(f"color: {color}; background: transparent; border: none; padding: 2px 0;")


class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Mono" if _OS == "Windows" else "Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: #040817;
                color: {C.TEXT};
                border: 1px solid {C.LINE3};
                border-radius: 18px;
                padding: 12px;
                selection-background-color: #22336d;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.VIOLET};
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._queue: list[str] = []
        self._typing = False
        self._text = ""
        self._pos = 0
        self._tag = "sys"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self._queue.append(f"[{stamp}] {text}")
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text = self._queue.pop(0)
        self._pos = 0
        low = self._text.lower()
        if "you:" in low:
            self._tag = "you"
        elif "jarvis:" in low:
            self._tag = "ai"
        elif "file:" in low:
            self._tag = "file"
        elif "err" in low or "error" in low:
            self._tag = "err"
        else:
            self._tag = "sys"
        self._timer.start(3)

    def _step(self):
        if self._pos < len(self._text):
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            fmt = cur.charFormat()
            fmt.setForeground(QBrush({
                "you": qcol(C.WHITE),
                "ai": qcol(C.CYAN),
                "file": qcol(C.EMERALD),
                "err": qcol(C.RED),
                "sys": qcol(C.GOLD),
            }.get(self._tag, qcol(C.TEXT))))
            cur.insertText(self._text[self._pos], fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._timer.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(12, self._next)


_FILE_ICONS = {
    "image": ("🖼", C.CYAN),
    "video": ("🎬", C.ORANGE),
    "audio": ("🎵", C.MAGENTA),
    "pdf": ("📄", C.RED),
    "word": ("📝", C.BLUE),
    "excel": ("📊", C.EMERALD),
    "code": ("💻", C.GOLD),
    "archive": ("📦", C.ORANGE),
    "pptx": ("📊", C.ORANGE),
    "text": ("📃", C.TEXT2),
    "data": ("🔧", C.CYAN2),
    "unknown": ("📎", C.TEXT_DIM),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "svg", "ico"], "image"),
    **dict.fromkeys(["mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v"], "video"),
    **dict.fromkeys(["mp3", "wav", "ogg", "m4a", "aac", "flac", "wma", "opus"], "audio"),
    **dict.fromkeys(["pdf"], "pdf"),
    **dict.fromkeys(["doc", "docx"], "word"),
    **dict.fromkeys(["xls", "xlsx", "ods"], "excel"),
    **dict.fromkeys(["ppt", "pptx"], "pptx"),
    **dict.fromkeys(["py", "js", "ts", "jsx", "tsx", "html", "css", "java", "c", "cpp", "cs", "go", "rs", "rb", "php", "swift", "kt", "sh", "sql", "lua"], "code"),
    **dict.fromkeys(["zip", "rar", "tar", "gz", "7z", "bz2", "xz"], "archive"),
    **dict.fromkeys(["txt", "md", "rst", "log"], "text"),
    **dict.fromkeys(["csv", "tsv", "json", "xml"], "data"),
}


def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(118)
        self._current_file: str | None = None
        self._hovering = False
        self._drag_over = False
        self._dash = 0.0
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(35)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash = (self._dash + 1.2) % 26
        self._pulse = (self._pulse + 0.08) % math.tau
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True
        self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False
        self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None
        self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select payload for PAVO/JARVIS",
            str(Path.home()),
            "All Files (*.*);;Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;Documents (*.pdf *.docx *.txt *.md *.pptx);;Code (*.py *.js *.ts *.html *.css *.java *.cpp);;Data (*.csv *.xlsx *.json *.xml);;Audio (*.mp3 *.wav *.ogg *.m4a);;Video (*.mp4 *.avi *.mov *.mkv *.webm)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        z = self._z
        rect = QRectF(2, 2, W - 4, H - 4)

        bg = QLinearGradient(0, 0, W, H)
        if z._drag_over:
            bg.setColorAt(0, qcol("#122755"))
            bg.setColorAt(1, qcol("#082b30"))
        elif z._hovering:
            bg.setColorAt(0, qcol("#111d42"))
            bg.setColorAt(1, qcol("#062237"))
        else:
            bg.setColorAt(0, qcol("#070b1b"))
            bg.setColorAt(1, qcol("#051525"))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 18, 18)

        border = C.EMERALD if z._current_file else (C.MAGENTA if z._drag_over else (C.CYAN if z._hovering else C.LINE3))
        pen = QPen(qcol(border, 220), 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 18, 18)

        # small animated corner markers
        pulse_alpha = int(110 + 80 * math.sin(z._pulse))
        p.setPen(QPen(qcol(border, pulse_alpha), 2))
        corner = 18
        for x, y, sx, sy in [(8, 8, 1, 1), (W - 8, 8, -1, 1), (8, H - 8, 1, -1), (W - 8, H - 8, -1, -1)]:
            p.drawLine(QPointF(x, y), QPointF(x + sx * corner, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + sy * corner))

        if z._current_file:
            self._paint_file(p, W, H)
        elif z._drag_over:
            self._paint_drag(p, W, H)
        else:
            self._paint_idle(p, W, H)

    def _paint_idle(self, p: QPainter, W: int, H: int):
        p.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.MAGENTA, 205), 1))
        p.drawText(QRectF(0, 16, W, 28), Qt.AlignmentFlag.AlignCenter, "⬡")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.CYAN), 1))
        p.drawText(QRectF(0, 48, W, 18), Qt.AlignmentFlag.AlignCenter, "CARGAR PAYLOAD")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(16, 70, W - 32, 30), Qt.AlignmentFlag.AlignCenter, "Arrastra archivo o da click")

    def _paint_drag(self, p: QPainter, W: int, H: int):
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.EMERALD), 1))
        p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "SUELTA EL ARCHIVO, BRO")

    def _paint_file(self, p: QPainter, W: int, H: int):
        path = Path(self._z._current_file or "")
        try:
            size = _fmt_size(path.stat().st_size)
        except Exception:
            size = "--"
        cat = _file_category(path)
        icon, col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])

        p.setFont(QFont("Segoe UI Emoji" if _OS == "Windows" else "Arial", 25))
        p.setPen(QPen(qcol(col), 1))
        p.drawText(QRectF(16, 0, 56, H), Qt.AlignmentFlag.AlignCenter, icon)

        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(QRectF(82, 30, W - 122, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(82, 51, W - 122, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{path.suffix.upper().lstrip('.') or 'FILE'} · {size}")
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED), 1))
        p.drawText(QRectF(W - 38, 0, 32, H), Qt.AlignmentFlag.AlignCenter, "×")

    def mousePressEvent(self, e):
        if self._z._current_file and e.pos().x() > self.width() - 42:
            self._z.clear_file()
        else:
            self._z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(3, 2, 10, 248);
                border: 1px solid {C.MAGENTA};
                border-radius: 24px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        title = QLabel("J.A.R.V.I.S // PRP BOOT")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: none;")
        layout.addWidget(title)

        sub = QLabel("Configuración inicial del sistema")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        sub.setStyleSheet(f"color: {C.MAGENTA}; background: transparent; border: none;")
        layout.addWidget(sub)

        layout.addSpacing(10)
        layout.addWidget(self._field_label("GEMINI API KEY"))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza...")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(40)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #050817;
                color: {C.WHITE};
                border: 1px solid {C.LINE3};
                border-radius: 14px;
                padding: 7px 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.CYAN}; }}
        """)
        layout.addWidget(self._key_input)

        layout.addSpacing(10)
        layout.addWidget(self._field_label("SISTEMA OPERATIVO"))
        os_row = QHBoxLayout()
        os_row.setSpacing(9)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows", "⊞ WINDOWS"), ("mac", "MACOS"), ("linux", "LINUX")]:
            btn = QPushButton(label)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            self._os_btns[key] = btn
            os_row.addWidget(btn)
        layout.addLayout(os_row)
        self._sel(detected)

        layout.addStretch()
        init = QPushButton("INICIAR SISTEMA")
        init.setFixedHeight(44)
        init.setCursor(Qt.CursorShape.PointingHandCursor)
        init.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init.setStyleSheet(f"""
            QPushButton {{
                background: {C.CYAN2};
                color: #021019;
                border: none;
                border-radius: 16px;
            }}
            QPushButton:hover {{ background: {C.CYAN2}; }}
        """)
        init.clicked.connect(self._submit)
        layout.addWidget(init)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {C.TEXT2}; background: transparent; border: none;")
        return lbl

    def _sel(self, key: str):
        self._sel_os = key
        for k, btn in self._os_btns.items():
            if k == key:
                btn.setStyleSheet(f"background: {C.CYAN}; color: #021019; border: none; border-radius: 12px;")
            else:
                btn.setStyleSheet(f"background: #050817; color: {C.TEXT_DIM}; border: 1px solid {C.LINE3}; border-radius: 12px;")

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(self._key_input.styleSheet() + f" QLineEdit {{ border: 1px solid {C.RED}; }}")
            return
        self.done.emit(key, self._sel_os)


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _esp32_status_sig = pyqtSignal(str, str, str)
    _esp32_ports_sig = pyqtSignal(object, str)
    _confirm_sig = pyqtSignal(str, str, object)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S // Pavo's Robotic Projects")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - _DEFAULT_W) // 2, (geo.height() - _DEFAULT_H) // 2)

        self.on_text_command = None
        self.on_interrupt_command = None
        self.on_esp32_connect = None
        self.on_esp32_refresh_ports = None
        self.platform = None
        self._control_center = None
        self._muted = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.VOID};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(11)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(11)

        body.addWidget(self._build_left_panel(), stretch=0)

        center_frame = QFrame()
        center_frame.setStyleSheet(_panel_style(C.LINE3, C.VOID2, 24))
        center_lay = QVBoxLayout(center_frame)
        center_lay.setContentsMargins(9, 9, 9, 9)
        center_lay.setSpacing(8)

        self.hud = PavoHudCanvas(face_path)
        center_lay.addWidget(self.hud, stretch=1)

        body.addWidget(center_frame, stretch=1)
        body.addWidget(self._build_right_panel(), stretch=0)
        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(1700)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._esp32_status_sig.connect(self._apply_esp32_status)
        self._esp32_ports_sig.connect(self._apply_esp32_ports)
        self._confirm_sig.connect(self._apply_confirm)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()
        else:
            self._apply_state("SLEEPING")

        QShortcut(QKeySequence("F4"), self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self._interrupt_speech)
        QShortcut(QKeySequence("F11"), self).activated.connect(self._toggle_fullscreen)

    def _build_header(self) -> QWidget:
        w = QFrame()
        w.setFixedHeight(76)
        w.setStyleSheet(_panel_style(C.LINE3, C.DEEP, 22))
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        brand = QVBoxLayout()
        brand.setSpacing(1)
        title = QLabel("J.A.R.V.I.S  //  PAVO'S ROBOTIC PROJECTS")
        title.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: none;")
        brand.addWidget(title)
        sub = QLabel("Domótica · ESP32 Serial Link · Asistente de Voz · Pavo's Robotic Projects")
        sub.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        sub.setStyleSheet(f"color: {C.MAGENTA}; background: transparent; border: none;")
        brand.addWidget(sub)
        lay.addLayout(brand)

        lay.addStretch()
        lay.addWidget(PavoChip("PRP CORE", C.CYAN2))
        lay.addWidget(PavoChip("ESP32 LINK", C.CYAN))
        lay.addWidget(PavoChip("CYAN TECH", C.BLUE))

        clock_box = QVBoxLayout()
        clock_box.setSpacing(1)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._clock_lbl.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        clock_box.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("---")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._date_lbl.setFont(QFont("Courier New", 8))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        clock_box.addWidget(self._date_lbl)
        lay.addLayout(clock_box)

        return w

    def _build_left_panel(self) -> QWidget:
        w = QFrame()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(_panel_style(C.LINE3, C.PANEL, 24))
        lay = QVBoxLayout(w)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(10)

        lay.addWidget(NeonSection("TELEMETRÍA TECNOLÓGICA", C.CYAN))
        self._bar_cpu = MetricOrb("CPU LOAD", C.CYAN)
        self._bar_mem = MetricOrb("MEMORY", C.CYAN2)
        self._bar_net = MetricOrb("NETWORK", C.MAGENTA)
        self._bar_gpu = MetricOrb("GPU CORE", C.BLUE)
        self._bar_tmp = MetricOrb("THERMAL", C.RED)
        for bar in [self._bar_cpu, self._bar_mem, self._bar_net, self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        info = QFrame()
        info.setStyleSheet(_panel_style(C.LINE, "#050817", 18))
        info_l = QVBoxLayout(info)
        info_l.setContentsMargins(12, 10, 12, 10)
        info_l.setSpacing(7)

        self._uptime_lbl = self._mini_info("UPTIME", "--:--", C.CYAN2)
        self._proc_lbl = self._mini_info("PROC", "--", C.CYAN)
        os_name = {"Windows": "WINDOWS", "Darwin": "MACOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        self._os_lbl = self._mini_info("SYSTEM", os_name, C.MAGENTA)
        info_l.addWidget(self._uptime_lbl)
        info_l.addWidget(self._proc_lbl)
        info_l.addWidget(self._os_lbl)
        lay.addWidget(info)

        lay.addWidget(NeonSection("MÓDULOS ACTIVOS", C.CYAN2))
        for text, color in [
            ("WAKE WORD", C.CYAN2),
            ("VOICE ENGINE", C.CYAN),
            ("SERIAL ROUTER", C.MAGENTA),
            ("DOMOTIC CORE", C.BLUE),
        ]:
            chip = QLabel(f"◆  {text}")
            chip.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            chip.setStyleSheet(f"color: {color}; background: #050817; border: 1px solid {C.LINE3}; border-radius: 13px; padding: 8px;")
            lay.addWidget(chip)

        lay.addStretch()
        signature = QLabel("PAVO'S ROBOTIC PROJECTS\nTECH INTERFACE MK I")
        signature.setAlignment(Qt.AlignmentFlag.AlignCenter)
        signature.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        signature.setStyleSheet(f"color: {C.TEXT_DIM}; background: #050817; border: 1px solid {C.LINE}; border-radius: 14px; padding: 9px;")
        lay.addWidget(signature)

        return w

    def _build_right_panel(self) -> QWidget:
        w = QFrame()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(_panel_style(C.LINE3, C.PANEL, 24))
        lay = QVBoxLayout(w)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)

        lay.addWidget(NeonSection("ESP32 SERIAL LINK", C.CYAN2))
        lay.addWidget(self._build_esp32_panel())

        lay.addWidget(NeonSection("BITÁCORA DE MISIÓN", C.CYAN))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        lay.addWidget(NeonSection("PAYLOAD / ARCHIVO", C.BLUE))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("Sin payload cargado")
        self._file_hint.setWordWrap(True)
        self._file_hint.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(self._file_hint)

        lay.addWidget(NeonSection("LÍNEA DE COMANDO", C.CYAN2))
        lay.addLayout(self._build_input_row())

        control = QPushButton("CENTRO DE CONTROL NEXUS")
        control.setFixedHeight(38)
        control.setCursor(Qt.CursorShape.PointingHandCursor)
        control.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        control.setStyleSheet(_button_style(C.CYAN2, C.CYAN, "#04202a", "#073447", 13))
        control.clicked.connect(self._open_control_center)
        lay.addWidget(control)

        self._mute_btn = QPushButton()
        self._mute_btn.setFixedHeight(38)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        stop = QPushButton("DETENER VOZ  [ESC]")
        stop.setFixedHeight(34)
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        stop.setStyleSheet(_button_style(C.RED, C.RED, "#180710", "#2a0914", 13))
        stop.clicked.connect(self._interrupt_speech)
        lay.addWidget(stop)

        full = QPushButton("MODO CINE  [F11]")
        full.setFixedHeight(32)
        full.setCursor(Qt.CursorShape.PointingHandCursor)
        full.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        full.setStyleSheet(_button_style(C.CYAN, C.LINE3, "#050817", "#091c36", 13))
        full.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(full)

        return w

    def _build_esp32_panel(self) -> QWidget:
        box = QFrame()
        box.setStyleSheet(_panel_style(C.LINE, "#050817", 18))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 9, 10, 10)
        lay.setSpacing(7)

        self._esp32_status_lbl = QLabel("ESP32: SIN VERIFICAR")
        self._esp32_status_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._esp32_status_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(self._esp32_status_lbl)

        self._esp32_detail_lbl = QLabel("Selecciona un puerto COM y conecta")
        self._esp32_detail_lbl.setWordWrap(True)
        self._esp32_detail_lbl.setFont(QFont("Courier New", 7))
        self._esp32_detail_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(self._esp32_detail_lbl)

        self._esp32_port_combo = QComboBox()
        self._esp32_port_combo.setFixedHeight(34)
        self._esp32_port_combo.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._esp32_port_combo.setStyleSheet(f"""
            QComboBox {{
                background: #040817;
                color: {C.WHITE};
                border: 1px solid {C.LINE3};
                border-radius: 12px;
                padding: 5px 8px;
            }}
            QComboBox:hover {{ border: 1px solid {C.CYAN}; }}
            QComboBox QAbstractItemView {{
                background: #040817;
                color: {C.WHITE};
                selection-background-color: #0b3150;
                border: 1px solid {C.LINE3};
            }}
        """)
        lay.addWidget(self._esp32_port_combo)

        row = QHBoxLayout()
        row.setSpacing(7)

        refresh = QPushButton("REFRESCAR")
        refresh.setFixedHeight(30)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        refresh.setStyleSheet(_button_style(C.CYAN, C.LINE3, "#050817", "#091c36", 12))
        refresh.clicked.connect(self._refresh_esp32_ports)
        row.addWidget(refresh)

        connect = QPushButton("CONECTAR")
        connect.setFixedHeight(30)
        connect.setCursor(Qt.CursorShape.PointingHandCursor)
        connect.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        connect.setStyleSheet(_button_style(C.EMERALD, C.EMERALD, "#062016", "#0a2d1d", 12))
        connect.clicked.connect(self._connect_esp32_selected)
        row.addWidget(connect)

        lay.addLayout(row)
        return box

    def _refresh_esp32_ports(self):
        try:
            self._log.append_log("SYS: Buscando puertos seriales...")
        except Exception:
            pass
        if self.on_esp32_refresh_ports:
            threading.Thread(target=self.on_esp32_refresh_ports, daemon=True).start()

    def _connect_esp32_selected(self):
        if not hasattr(self, "_esp32_port_combo"):
            return
        port = self._esp32_port_combo.currentData() or self._esp32_port_combo.currentText().split(" ")[0].strip()
        if not port:
            self._apply_esp32_status("DISCONNECTED", "--", "no hay puerto seleccionado")
            return
        self._apply_esp32_status("CONNECTING", str(port), "probando enlace serial")
        if self.on_esp32_connect:
            threading.Thread(target=self.on_esp32_connect, args=(str(port),), daemon=True).start()

    def _apply_esp32_ports(self, ports, current_port: str):
        if not hasattr(self, "_esp32_port_combo"):
            return
        current_port = current_port or "COM6"
        previous = self._esp32_port_combo.currentData() or current_port
        self._esp32_port_combo.blockSignals(True)
        self._esp32_port_combo.clear()

        normalized = []
        for item in ports or []:
            if isinstance(item, dict):
                port = str(item.get("port", "")).strip()
                desc = str(item.get("description", port)).strip()
            else:
                port = str(item).strip()
                desc = port
            if port:
                normalized.append((port, desc))

        if not any(port == current_port for port, _ in normalized):
            normalized.insert(0, (current_port, "puerto guardado"))

        if not normalized:
            normalized = [("COM6", "manual/default")]

        selected_index = 0
        for i, (port, desc) in enumerate(normalized):
            label = f"{port}  ·  {desc}" if desc and desc != port else port
            self._esp32_port_combo.addItem(label, port)
            if port == previous or port == current_port:
                selected_index = i

        self._esp32_port_combo.setCurrentIndex(selected_index)
        self._esp32_port_combo.blockSignals(False)

    def _apply_esp32_status(self, status: str, port: str, message: str):
        status = (status or "UNKNOWN").upper()
        port = port or "--"
        message = (message or "").strip()

        if status == "ONLINE":
            text = f"ESP32: EN LÍNEA · {port}"
            color = C.EMERALD
        elif status == "CONNECTING":
            text = f"ESP32: CONECTANDO · {port}"
            color = C.CYAN
        elif status == "DISCONNECTED":
            text = f"ESP32: DESCONECTADA · {port}"
            color = C.RED
        else:
            text = f"ESP32: SIN VERIFICAR · {port}"
            color = C.TEXT_DIM

        self._esp32_status_lbl.setText(text)
        self._esp32_status_lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        self._esp32_detail_lbl.setText(message[:140] if message else "esperando comunicación serial")

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Ordena algo... ej. prende el foco")
        self._input.setFixedHeight(40)
        self._input.setFont(QFont("Courier New", 9))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #050817;
                color: {C.WHITE};
                border: 1px solid {C.LINE3};
                border-radius: 15px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.CYAN};
                background: #071225;
            }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("➤")
        send.setFixedSize(44, 40)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.CYAN};
                color: #021019;
                border: none;
                border-radius: 15px;
            }}
            QPushButton:hover {{
                background: {C.CYAN2};
                color: #021019;
            }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)

        return row

    def _build_footer(self) -> QWidget:
        w = QFrame()
        w.setFixedHeight(34)
        w.setStyleSheet(_panel_style(C.LINE3, C.DEEP, 16))
        lay = QHBoxLayout(w)
        lay.setContentsMargins(15, 0, 15, 0)

        left = QLabel("Wake word: 'Jarvis' · F4 mute · ESC stop · F11 modo cine")
        left.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        left.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(left)

        lay.addStretch()

        right = QLabel("PAVO'S ROBOTIC PROJECTS · CYAN TECH INTERFACE")
        right.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        right.setStyleSheet(f"color: {C.MAGENTA}; background: transparent; border: none;")
        lay.addWidget(right)

        return w

    def _mini_info(self, label: str, value: str, color: str) -> QLabel:
        lbl = QLabel(f"{label:<8}  {value}")
        lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        return lbl

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y").upper())

    def _update_metrics(self):
        snap = _metrics.snapshot()
        cpu = snap["cpu"]
        mem = snap["mem"]
        net = snap["net"]
        gpu = snap["gpu"]
        tmp = snap["tmp"]

        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")
        self._bar_mem.set_value(mem, f"{mem:.0f}%")
        net_text = f"{net * 1024:.0f}KB/s" if net < 1 else f"{net:.1f}MB/s"
        self._bar_net.set_value(min(100, net * 10), net_text)
        self._bar_gpu.set_value(gpu if gpu >= 0 else 0, f"{gpu:.0f}%" if gpu >= 0 else "N/A")
        self._bar_tmp.set_value(min(100, tmp) if tmp >= 0 else 0, f"{tmp:.0f}°C" if tmp >= 0 else "N/A")

        try:
            elapsed = time.time() - psutil.boot_time()
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"{'UPTIME':<8}  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText(f"{'UPTIME':<8}  --:--")

        try:
            self._proc_lbl.setText(f"{'PROC':<8}  {len(psutil.pids())}")
        except Exception:
            self._proc_lbl.setText(f"{'PROC':<8}  --")

    def _on_file_selected(self, path: str):
        self._current_file = path
        p = Path(path)
        cat = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        try:
            size = _fmt_size(p.stat().st_size)
        except Exception:
            size = "--"
        self._file_hint.setText(f"{icon}  {p.name} · {size} · listo para análisis")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' ({size}) has been uploaded "
                f"and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _open_control_center(self):
        if self.platform is None:
            self._log.append_log("SYS: El núcleo NEXUS todavía no está conectado.")
            return
        try:
            from control_center_ui import ControlCenterDialog
            if self._control_center is None:
                self._control_center = ControlCenterDialog(self.platform, self)
            self._control_center.refresh_all()
            self._control_center.show()
            self._control_center.raise_()
            self._control_center.activateWindow()
        except Exception as exc:
            self._log.append_log(f"ERR: No pude abrir el Centro de Control: {exc}")

    def _apply_confirm(self, title: str, message: str, holder: object):
        try:
            answer = QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            holder["value"] = answer == QMessageBox.StandardButton.Yes
        except Exception:
            holder["value"] = False
        finally:
            holder["event"].set()

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            self._place_overlay()

    def _place_overlay(self):
        if not self._overlay:
            return
        cw = self.centralWidget()
        ow, oh = 540, 430
        self._overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("SLEEPING")
            self._log.append_log("SYS: Microphone active. Say 'Jarvis' to wake.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("MICRÓFONO MUTED  [F4]")
            self._mute_btn.setStyleSheet(_button_style(C.RED, C.RED, "#210510", "#320819", 14))
        else:
            self._mute_btn.setText("MICRÓFONO ACTIVE  [F4]")
            self._mute_btn.setStyleSheet(_button_style(C.EMERALD, C.EMERALD, "#062016", "#0a2d1d", 14))

    def _interrupt_speech(self):
        self._log.append_log("SYS: Stop/interrupt requested.")
        if self.on_interrupt_command:
            threading.Thread(target=self.on_interrupt_command, daemon=True).start()

    def _send(self):
        txt = self._input.text().strip()
        if not txt:
            return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state = state
        self.hud.speaking = state == "SPEAKING"
        if state == "MUTED":
            self.hud.muted = True
        elif not self._muted:
            self.hud.muted = False

    def _check_config(self) -> bool:
        if not API_FILE.exists():
            return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        self._overlay = SetupOverlay(self.centralWidget())
        self._overlay.done.connect(self._on_setup_done)
        self._place_overlay()
        self._overlay.show()

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4), encoding="utf-8")
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("SLEEPING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. PRP/JARVIS online. Say 'Jarvis' to wake.")


class _RootShim:
    """Small Tk-like adapter used by the rest of JARVIS.

    The assistant was originally written against ``tkinter.Tk`` and still
    expects ``root.mainloop()`` and ``root.after()``.  This adapter maps those
    calls to Qt without allowing worker threads to touch widgets directly.
    """

    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def after(self, delay_ms: int, callback=None, *args):
        """Schedule *callback* on Qt's GUI event loop.

        ``QTimer.singleShot`` may be registered before ``app.exec()`` starts;
        Qt executes it once the event loop is running.  The return value is
        intentionally unused by JARVIS, matching the small compatibility
        surface required here.
        """
        if callback is None:
            return None

        try:
            delay = max(0, int(delay_ms))
        except (TypeError, ValueError):
            delay = 0

        QTimer.singleShot(delay, lambda: callback(*args))
        return None

    def protocol(self, *_):
        pass


class JarvisUI:
    """
    Drop-in compatible wrapper for the rest of your assistant.

    Expected usage remains:
        ui = JarvisUI(face_path)
        ui.on_text_command = callback
        ui.on_interrupt_command = stop_callback
        ui.root.mainloop()
    """

    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        if size:
            try:
                self._win.resize(QSize(size[0], size[1]))
            except Exception:
                pass
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if bool(v) != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_interrupt_command(self):
        return self._win.on_interrupt_command

    @on_interrupt_command.setter
    def on_interrupt_command(self, cb):
        self._win.on_interrupt_command = cb

    @property
    def on_esp32_connect(self):
        return self._win.on_esp32_connect

    @on_esp32_connect.setter
    def on_esp32_connect(self, cb):
        self._win.on_esp32_connect = cb

    @property
    def on_esp32_refresh_ports(self):
        return self._win.on_esp32_refresh_ports

    @on_esp32_refresh_ports.setter
    def on_esp32_refresh_ports(self, cb):
        self._win.on_esp32_refresh_ports = cb

    def update_esp32_ports(self, ports, current_port: str = ""):
        self._win._esp32_ports_sig.emit(ports, current_port)

    def set_esp32_status(self, status: str, port: str = "", message: str = ""):
        self._win._esp32_status_sig.emit(status, port, message)

    def attach_platform(self, platform):
        self._win.platform = platform

    def open_control_center(self):
        self._win._open_control_center()

    def confirm_action(self, title: str, message: str, timeout: float = 60.0) -> bool:
        event = threading.Event()
        holder = {"event": event, "value": False}
        self._win._confirm_sig.emit(str(title), str(message), holder)
        event.wait(timeout=max(1.0, float(timeout)))
        return bool(holder.get("value", False))

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("SLEEPING")
