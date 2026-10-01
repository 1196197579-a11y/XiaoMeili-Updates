# -*- coding: utf-8 -*-
import os, sys, json, shutil, logging, traceback, subprocess, threading, time, ctypes, re, gc, random, tempfile, zipfile, urllib.request, hashlib, uuid
# Limit math/image libraries to one worker thread. The previous build could let
# OpenCV/ONNX fan out across many cores during frequent HUD scans.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
from difflib import SequenceMatcher
import shutil
from pathlib import Path
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import QRect
import psutil
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, Signal, QObject, QTimer, QThread, QSize, QRect, QRectF, QPointF
from PySide6.QtGui import QIcon, QAction, QKeySequence, QCursor, QImage, QMovie, QPixmap, QFontDatabase, QFont, QPainter, QColor, QFontMetrics, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QStackedLayout, QGraphicsOpacityEffect,
    QSystemTrayIcon, QMenu, QDialog, QTabWidget, QFormLayout, QCheckBox, QSlider,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QKeySequenceEdit, QHeaderView, QSpinBox, QGroupBox, QGridLayout, QLineEdit, QComboBox, QListWidget, QListWidgetItem, QProgressDialog, QDoubleSpinBox, QInputDialog, QProgressBar, QTextEdit, QStackedWidget, QFrame, QScrollArea, QSizePolicy
)
from PIL import Image, ImageOps, ImageDraw
import keyboard
import cv2
import numpy as np

from ability_sidebar import AbilitySidebar, AbilityNode, FEATURES as ABILITY_FEATURES

APP_NAME = "小美丽 V0.10.0.2｜Beauty Ability Sidebar"
APP_VERSION = "0.10.0.2"
APP_UPDATE_VERSION = "0.10.0.2"
UPDATE_PROTOCOL_VERSION = 1
ORG_NAME = "XiaoMeili"
ASSET_RNG = random.SystemRandom()  # independent draw with replacement; consecutive repeats are allowed
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
MAX_ASSETS_PER_STATE = 20

STATE_NAMES = {
    "idle": "待机",
    "low_hp": "低血量",
    "kill": "击杀",
    "dead": "被击杀",
    "victory": "获胜",
    "defeat": "失败",
    "report": "战报",
}

DEFAULT_HOTKEYS = {
    "idle": "ctrl+alt+1",
    "low_hp": "ctrl+alt+2",
    "kill": "ctrl+alt+3",
    "dead": "ctrl+alt+4",
    "victory": "ctrl+alt+5",
    "defeat": "ctrl+alt+6",
    "toggle_lock": "ctrl+alt+l",
    "settings": "ctrl+alt+s",
    "show_hide": "ctrl+alt+h",
}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_root() -> Path:
    if sys.platform == "win32":
        base = os.getenv("PUBLIC") or r"C:\Users\Public"
        p = Path(base) / "XiaoMeiliData"
    else:
        p = Path.home() / ".xiaomeili"
    p.mkdir(parents=True, exist_ok=True)
    return p


ROOT = app_root()
USER = user_root()
LOG_DIR = USER / "logs"
CACHE_DIR = USER / "assets"
DEBUG_DIR = USER / "vision_debug"
REPORT_DEBUG_DIR = DEBUG_DIR / "report_debug"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = USER / "config.json"
UPDATE_DIR = USER / "updates"
UPDATE_DIR.mkdir(parents=True, exist_ok=True)
UPDATE_LOG_DIR = LOG_DIR / "update"
DIAGNOSTIC_DIR = LOG_DIR / "diagnostics"
APP_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "app"
UPDATE_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "update"
STORAGE_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "storage"
for _dir in (UPDATE_LOG_DIR, DIAGNOSTIC_DIR, APP_DIAGNOSTIC_DIR, UPDATE_DIAGNOSTIC_DIR, STORAGE_DIAGNOSTIC_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def desktop_dir() -> Path:
    """Return the real Windows Desktop path when possible, including OneDrive/localized setups."""
    if sys.platform == "win32":
        try:
            buf = ctypes.create_unicode_buffer(1024)
            # CSIDL_DESKTOPDIRECTORY = 0x10
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    p = Path.home() / "Desktop"
    p.mkdir(parents=True, exist_ok=True)
    return p


DESKTOP_ERROR_LOG = APP_DIAGNOSTIC_DIR / "xiaomeili_errors.log"  # compatibility name; no longer on Desktop




DEFAULT_REPORT_LAYOUT = {
    # Normalized to the complete pet canvas. The supplied whiteboard is stationary,
    # so one rectangle is enough and no per-frame tracking is required.
    "x": 0.105, "y": 0.675, "w": 0.790, "h": 0.235,
    "offset_x": 0.0, "offset_y": 0.0,
    "line1_scale": 1.00, "line2_scale": 1.00,
    "line_spacing": 0.02,
    "text_color": "#08423A",
    "outline_color": "#F6FFF9",
    "outline_width": 0.0,
    "auto_fill": True,
    "max_eval_lines": 2,
}


def report_layout_key(path_value):
    try:
        p = Path(str(path_value or ""))
        return p.name or "__default_report__"
    except Exception:
        return "__default_report__"


def normalized_report_layout(value=None):
    out = dict(DEFAULT_REPORT_LAYOUT)
    if isinstance(value, dict):
        for k in out:
            if k in value:
                out[k] = value[k]
    # Clamp user-editable geometry so a malformed config cannot hide text forever.
    try:
        out["x"] = max(0.0, min(0.95, float(out["x"])))
        out["y"] = max(0.0, min(0.95, float(out["y"])))
        out["w"] = max(0.05, min(1.0 - out["x"], float(out["w"])))
        out["h"] = max(0.05, min(1.0 - out["y"], float(out["h"])))
        out["offset_x"] = max(-0.3, min(0.3, float(out["offset_x"])))
        out["offset_y"] = max(-0.3, min(0.3, float(out["offset_y"])))
        out["line1_scale"] = max(0.45, min(2.2, float(out["line1_scale"])))
        out["line2_scale"] = max(0.45, min(2.2, float(out["line2_scale"])))
        out["line_spacing"] = max(-0.10, min(0.25, float(out["line_spacing"])))
        out["outline_width"] = max(0.0, min(5.0, float(out["outline_width"])))
        out["max_eval_lines"] = 2 if int(out.get("max_eval_lines", 2)) >= 2 else 1
        out["auto_fill"] = bool(out.get("auto_fill", True))
    except Exception:
        return dict(DEFAULT_REPORT_LAYOUT)
    return out


def get_report_layout(cfg, asset_path=None):
    layouts = cfg.get("report_layouts", {}) if isinstance(cfg.get("report_layouts"), dict) else {}
    return normalized_report_layout(layouts.get(report_layout_key(asset_path), {}))


def set_report_layout(cfg, asset_path, layout):
    if not isinstance(cfg.get("report_layouts"), dict):
        cfg["report_layouts"] = {}
    cfg["report_layouts"][report_layout_key(asset_path)] = normalized_report_layout(layout)


def _split_eval_candidates(text):
    text = str(text or "").strip()
    if not text:
        return [[""]]
    out = [[text]]
    # Prefer semantic punctuation; also consider a balanced hard split as fallback.
    positions = [m.end() for m in re.finditer(r"[，,。！？!?；;]", text) if 1 < m.end() < len(text)-1]
    positions += [i for i in range(max(2, len(text)//2-3), min(len(text)-1, len(text)//2+4))]
    seen = set()
    for pos in positions:
        a, b = text[:pos].strip(), text[pos:].strip()
        key=(a,b)
        if a and b and key not in seen:
            seen.add(key); out.append([a,b])
    return out


def _max_font_px(font_family, lines, max_width, max_height, max_px=180):
    lines = list(lines or [""])
    lo, hi, best = 6, max(8, int(max_px)), 6
    while lo <= hi:
        mid=(lo+hi)//2
        f=QFont(font_family); f.setPixelSize(mid)
        fm=QFontMetrics(f)
        widest=max((fm.horizontalAdvance(x) for x in lines), default=0)
        total=len(lines)*fm.height()
        if widest <= max_width and total <= max_height:
            best=mid; lo=mid+1
        else:
            hi=mid-1
    return best


def _best_eval_layout(font_family, text, max_width, max_height, max_lines=2):
    candidates=_split_eval_candidates(text)
    best_lines=[text]; best_px=6
    for lines in candidates:
        if len(lines)>max_lines:
            continue
        px=_max_font_px(font_family, lines, max_width, max_height)
        # Prefer visually larger lettering; a tiny bias keeps one-line text intact when close.
        score=px + (0.25 if len(lines)==1 else 0.0)
        if score > best_px:
            best_px=score; best_lines=lines
    return best_lines, int(best_px)


def _draw_path_text(painter, rect, text, font, fill, outline=None, outline_width=0.0):
    fm=QFontMetrics(font)
    x=rect.x() + (rect.width()-fm.horizontalAdvance(text))/2
    baseline=rect.y() + (rect.height()-fm.height())/2 + fm.ascent()
    path=QPainterPath(); path.addText(QPointF(float(x), float(baseline)), font, text)
    if outline_width and outline_width>0:
        painter.setPen(QPen(outline or QColor("#F6FFF9"), float(outline_width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill); painter.drawPath(path)


def render_report_text_pixmap(width, height, layout, kills, evaluation, font_family):
    width=max(1,int(width)); height=max(1,int(height)); layout=normalized_report_layout(layout)
    pix=QPixmap(width,height); pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing,True); p.setRenderHint(QPainter.RenderHint.TextAntialiasing,True)
    rx=(layout["x"]+layout["offset_x"])*width; ry=(layout["y"]+layout["offset_y"])*height
    rw=layout["w"]*width; rh=layout["h"]*height
    # Small internal safety margin. Auto-fit then expands text until it nearly fills this region.
    mx=max(2.0,rw*0.025); my=max(2.0,rh*0.025)
    inner=QRect(int(rx+mx),int(ry+my),max(1,int(rw-2*mx)),max(1,int(rh-2*my)))
    gap=max(-4,int(rh*float(layout.get("line_spacing",0.02))))
    line1_h=max(18,int(inner.height()*0.34)); eval_h=max(18,inner.height()-line1_h-gap)
    r1=QRect(inner.x(),inner.y(),inner.width(),line1_h)
    r2=QRect(inner.x(),inner.y()+line1_h+gap,inner.width(),eval_h)
    fill=QColor(str(layout.get("text_color","#08423A"))); outline=QColor(str(layout.get("outline_color","#F6FFF9")))
    line1=f"击杀数：{max(0,int(kills))}个"
    if bool(layout.get("auto_fill",True)):
        p1=_max_font_px(font_family,[line1],int(r1.width()*0.98),int(r1.height()*0.96),max_px=max(20,int(height*0.35)))
    else:
        p1=max(8,int(r1.height()*0.62))
    p1=max(8,int(p1*float(layout.get("line1_scale",1.0))))
    f1=QFont(font_family); f1.setPixelSize(p1)
    _draw_path_text(p,r1,line1,f1,fill,outline,float(layout.get("outline_width",0.0)))
    lines,p2=_best_eval_layout(font_family,str(evaluation or ""),int(r2.width()*0.98),int(r2.height()*0.96),int(layout.get("max_eval_lines",2)))
    if not bool(layout.get("auto_fill",True)):
        p2=max(8,min(p2,int(r2.height()*0.40)))
    p2=max(8,int(p2*float(layout.get("line2_scale",1.0))))
    f2=QFont(font_family); f2.setPixelSize(p2); fm2=QFontMetrics(f2)
    total=len(lines)*fm2.height(); start_y=r2.y()+(r2.height()-total)//2
    for i,line in enumerate(lines):
        rr=QRect(r2.x(),start_y+i*fm2.height(),r2.width(),fm2.height())
        _draw_path_text(p,rr,line,f2,fill,outline,float(layout.get("outline_width",0.0)))
    p.end(); return pix

class DesktopErrorHandler(logging.Handler):
    """Mirror ERROR+ into the internal diagnostics folder; never litter the Desktop."""
    _lock = threading.Lock()

    def emit(self, record):
        if record.levelno < logging.ERROR:
            return
        try:
            with self._lock:
                DESKTOP_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
                lines = [
                    "=" * 72,
                    f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"版本: {APP_VERSION}",
                    f"系统: {sys.platform}",
                    f"程序目录: {ROOT}",
                    f"用户数据: {USER}",
                    f"错误级别: {record.levelname}",
                    f"错误: {record.getMessage()}",
                ]
                if record.exc_info:
                    lines.append("异常堆栈:\n" + "".join(traceback.format_exception(*record.exc_info)))
                lines.append(f"完整运行日志: {CURRENT_LOG if 'CURRENT_LOG' in globals() else '初始化中'}")
                lines.append("")
                with open(DESKTOP_ERROR_LOG, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
        except Exception:
            pass


def setup_logging():
    logfile = LOG_DIR / f"xiaomeili_{time.strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("xiaomeili")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = RotatingFileHandler(logfile, maxBytes=3_000_000, backupCount=8, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    dh = DesktopErrorHandler()
    dh.setLevel(logging.ERROR)
    dh.setFormatter(fmt)
    logger.addHandler(dh)
    logger.info("=== %s 启动 ===", APP_NAME)
    logger.info("ROOT=%s", ROOT)
    logger.info("USER=%s", USER)
    logger.info("Python=%s", sys.version.replace("\n", " "))
    logger.info("Platform=%s", sys.platform)
    return logger, logfile


LOGGER, CURRENT_LOG = setup_logging()


def resource(rel: str) -> str:
    return str(ROOT / rel)


def bundled_assets():
    # Every state owns a pool. Imported videos replace the placeholder pool and
    # up to 20 clips can be rotated randomly.
    out = {k: [resource(f"assets/states/{k}.gif")] for k in STATE_NAMES}
    out["report"] = [resource("assets/states/report.webp")]
    return out


def _asset_list(value):
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str) and value:
        return [value]
    return []


def default_config():
    return {
        "config_version": 24,
        "always_on_top": True,
        "click_through": False,
        "lock_position": False,
        "opacity": 100,
        "pet_width": 280,
        "x": 1200,
        "y": 500,
        "last_state": "idle",
        "transition_ms": 220,
        "hotkeys": DEFAULT_HOTKEYS.copy(),
        "assets": bundled_assets(),
        "report_font_path": "",
        "report_duration_ms": 10000,
        "report_layouts": {},
        "ability_sidebar": {
            "enabled": True,
            "voice_enabled": True,
            "voice_command_enabled": True,
            "voice_phrases": {
                "beauty_lock": "",
                "beauty_insight": "",
                "power_20": "",
                "power_50": "",
                "beauty_god": "",
            },
            "states": {
                "beauty_lock": False,
                "beauty_insight": False,
                "power_20": False,
                "power_50": False,
                "beauty_god": False,
            },
        },
        "mouse_interaction": {
            "enabled": True,
            "attention_radius": 1.85,
            "interaction_radius": 1.18,
            "enter_delay_ms": 260,
            "inner_enter_delay_ms": 120,
            "exit_delay_ms": 900,
            "idle_timeout_ms": 12000,
            "poll_interval_ms": 20,
            "smoothing": 0.18,
            "eye_x_px": 3.2,
            "eye_y_px": 2.0,
            "head_x_px": 8.5,
            "head_y_px": 5.0,
            "body_x_px": 3.2,
            "body_y_px": 1.7,
            "front_x_px": 6.4,
            "front_y_px": 3.6,
            "back_x_px": 2.4,
            "back_y_px": 1.8,
            "head_rot_deg": 4.2,
            "body_rot_deg": 1.5,
            "front_rot_deg": 4.6,
            "back_rot_deg": 1.9,
            "pupil_reduce_when_head_turn": 0.80,
        },
        "voice": {
            "enabled": True,
            "voice_id": "",
            "speed": 1.0,
            "test_text": "美丽美丽，我在呢。今天又想让我陪你干嘛？",
            "output_device": "default",
        },
        "speech": {
            "enabled": True,
            "wake_word": "美丽美丽",
            "input_device": "default",
            "wake_replies": ["干嘛？", "咋滴了？", "有事你就说！"],
            "phrase_voice_overrides": {
                "干嘛": "这两个字必须保持明显的小女孩年龄感，音色清亮偏高、短促、轻快，带一点傲娇和疑问感。不要压低声线，不要成熟成年女性感，不要御姐腔。",
            },
            "listen_timeout_ms": 15000,
            "indicator_enabled": True,
            "whiteboard_enabled": True,
        },
        "whiteboard": {
            "x": 0.075,
            "y": 0.655,
            "w": 0.850,
            "h": 0.300,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "min_font_px": 13,
            "max_font_px": 42,
            "font_scale": 1.0,
            "line_spacing": 1.02,
            "max_lines": 4,
            "text_color": "#08423A",
            "outline_color": "#F6FFF9",
            "outline_width": 0.0,
            "auto_fill": True,
            "hold_ms": 3000,
        },
        "brain": {
            "enabled": True,
            "auto_speak": True,
            "temperature": 0.78,
            "max_tokens": 220,
            "context_turns": 6,
            "persona": DEFAULT_PERSONA,
            "download_mode": "ndm",
            "ndm_download_dir": str(Path.home() / "Downloads"),
        },
        "updates": {
            "enabled": True,
            "manifest_url": "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest_safe.json",
            "auto_check": True,
        },
        "vision": {
            "enabled": True,
            "scan_interval_ms": 350,
            "mode": "ultra_low",
            "pause_when_background": True,
            "low_hp_threshold": 50,
            "alive_threshold": 0.74,
            "kill_threshold": 0.78,
            "result_threshold": 0.75,
            "kill_show_ms": 1400,
            "result_show_ms": 2800,
            "player_nickname": "",
            "ocr_interval_ms": 650,
            "nickname_ocr_fallback": True,
            "prefer_dxcam": True,
            "context_threshold": 2,
            "death_fallback_seconds": 2.2,
            # HP stability guard: a single bad frame must never trigger LOW_HP.
            "hp_vote_window": 5,
            "hp_enter_votes": 3,
            "hp_exit_votes": 3,
            "hp_exit_margin": 10,
            "hp_min_conf": 0.56,
            "hp_occlusion_guard": True,
            "report_enabled": True,
            # V0.4.9.9 report watcher: OCR still sleeps during the live match.
            # After the live HUD disappears we enter a long-lived, low-power
            # layout wait (~2 Hz).  Only after a result-like frame appears do we
            # temporarily switch to a short burst scanner for cleaner retries.
            "report_scan_interval_ms": 1400,
            "report_wait_interval_ms": 450,  # legacy key retained for old configs
            "report_wait_fast_interval_ms": 100,
            "report_wait_slow_interval_ms": 850,
            "report_wait_fast_seconds": 20,
            "report_capture_interval_ms": 160,
            "report_capture_window_ms": 3000,
            "report_settle_min_hits": 2,
            "report_settle_min_candidate_hits": 2,
            "report_settle_diff_threshold": 2.6,
            "report_candidate_cache_seconds": 2.8,
        },
    }


def _is_user_asset(path_value):
    if not path_value:
        return False
    try:
        p = Path(path_value)
        return CACHE_DIR in p.parents or p.parent == CACHE_DIR
    except Exception:
        return False


def load_config():
    cfg = default_config()
    old_data = {}
    if CONFIG_FILE.exists():
        try:
            old_data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            LOGGER.exception("读取配置失败，使用默认配置")
            old_data = {}

    # General fields + forward-compatible extension blocks.
    # User-created feature state must survive EXE/version replacement even when
    # a later feature was not yet added to default_config() in the old base.
    _schema_sections = {
        "hotkeys", "assets", "vision", "mouse_interaction",
        "voice", "speech", "whiteboard", "brain", "updates", "ability_sidebar",
    }
    for k, v in old_data.items():
        if k in _schema_sections:
            continue
        cfg[k] = v

    # Migrate hotkeys. New six-state layout gets clean defaults unless a matching key exists.
    old_hk = old_data.get("hotkeys", {}) if isinstance(old_data.get("hotkeys"), dict) else {}
    for k in cfg["hotkeys"]:
        if k in old_hk:
            cfg["hotkeys"][k] = str(old_hk[k] or "")

    # Migrate old single-asset configs into V0.4 pools. User clips are kept,
    # while old built-in placeholders are replaced by the new bundled placeholder.
    old_assets = old_data.get("assets", {}) if isinstance(old_data.get("assets"), dict) else {}
    aliases = {
        "idle": ("idle",),
        "low_hp": ("low_hp",),
        "kill": ("kill", "happy"),
        "dead": ("dead",),
        "victory": ("victory", "celebrate"),
        "defeat": ("defeat", "angry"),
        "report": ("report",),
    }
    for new_key, old_keys in aliases.items():
        migrated = []
        for old_key in old_keys:
            for item in _asset_list(old_assets.get(old_key)):
                if _is_user_asset(item) and Path(item).exists() and item not in migrated:
                    migrated.append(item)
        if migrated:
            cfg["assets"][new_key] = migrated[:MAX_ASSETS_PER_STATE]

    old_mouse = old_data.get("mouse_interaction", {}) if isinstance(old_data.get("mouse_interaction"), dict) else {}
    cfg["mouse_interaction"].update({k: v for k, v in old_mouse.items() if k in cfg["mouse_interaction"]})
    try:
        old_ver = int(old_data.get("config_version", 0) or 0)
    except Exception:
        old_ver = 0
    if old_ver < 15:
        cfg["mouse_interaction"]["eye_x_px"] = 3.0
        cfg["mouse_interaction"]["eye_y_px"] = 1.8

    old_voice = old_data.get("voice", {}) if isinstance(old_data.get("voice"), dict) else {}
    cfg["voice"].update({k: v for k, v in old_voice.items() if k in cfg["voice"]})
    if str(cfg["voice"].get("voice_id", "")).startswith("zf_"):
        cfg["voice"]["voice_id"] = ""

    old_speech = old_data.get("speech", {}) if isinstance(old_data.get("speech"), dict) else {}
    cfg["speech"].update({k: v for k, v in old_speech.items() if k in cfg["speech"]})
    if isinstance(old_speech.get("wake_replies"), list):
        replies = [str(x).strip() for x in old_speech.get("wake_replies", []) if str(x).strip()]
        if replies:
            cfg["speech"]["wake_replies"] = replies[:12]
    old_whiteboard = old_data.get("whiteboard", {}) if isinstance(old_data.get("whiteboard"), dict) else {}
    cfg["whiteboard"].update({k: v for k, v in old_whiteboard.items() if k in cfg["whiteboard"]})

    old_ability = old_data.get("ability_sidebar", {}) if isinstance(old_data.get("ability_sidebar"), dict) else {}
    for _key in ("enabled", "voice_enabled", "voice_command_enabled"):
        if _key in old_ability:
            cfg["ability_sidebar"][_key] = bool(old_ability[_key])
    # V0.10.0 compatibility: old experimental voice_feedback maps to the final setting.
    if "voice_feedback" in old_ability and "voice_enabled" not in old_ability:
        cfg["ability_sidebar"]["voice_enabled"] = bool(old_ability.get("voice_feedback", True))
    if isinstance(old_ability.get("voice_phrases"), dict):
        cfg["ability_sidebar"]["voice_phrases"].update({
            k: str(v or "") for k, v in old_ability["voice_phrases"].items()
            if k in cfg["ability_sidebar"]["voice_phrases"]
        })
    # Every launch intentionally starts all five cosmetic abilities OFF.
    for _ability_key in tuple(cfg["ability_sidebar"]["states"].keys()):
        cfg["ability_sidebar"]["states"][_ability_key] = False

    old_brain = old_data.get("brain", {}) if isinstance(old_data.get("brain"), dict) else {}
    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})
    if "spoken_text" in str(cfg["brain"].get("persona", "")) and "board_text" in str(cfg["brain"].get("persona", "")):
        cfg["brain"]["persona"] = DEFAULT_PERSONA

    old_updates = old_data.get("updates", {}) if isinstance(old_data.get("updates"), dict) else {}
    cfg["updates"].update({k: v for k, v in old_updates.items() if k in cfg["updates"]})

    old_vision = old_data.get("vision", {}) if isinstance(old_data.get("vision"), dict) else {}
    cfg["vision"].update({k: v for k, v in old_vision.items() if k in cfg["vision"]})
    if cfg["vision"].get("mode") == "low_power":
        cfg["vision"]["mode"] = "ultra_low"
    # V0.4.10.2 migration: old configs must not keep the slower 200ms + 4-hit
    # settle rule, otherwise a user who clicks Continue within ~0.5s can escape
    # before the result frame is owned by XiaoMeili.
    try:
        old_ver = int(old_data.get("config_version", 0) or 0)
    except Exception:
        old_ver = 0
    if old_ver < 13:
        cfg["vision"]["report_wait_fast_interval_ms"] = 100
        cfg["vision"]["report_settle_min_hits"] = 2
        cfg["vision"]["report_settle_min_candidate_hits"] = 2
        cfg["vision"]["report_settle_diff_threshold"] = 2.6
        cfg["vision"]["report_candidate_cache_seconds"] = 2.8

    locked = bool(old_data.get("click_through", False) or old_data.get("lock_position", False))
    cfg["click_through"] = locked
    cfg["lock_position"] = locked
    if cfg.get("last_state") not in STATE_NAMES:
        cfg["last_state"] = "idle"
    cfg.setdefault("updates", {})["manifest_url"] = "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest_safe.json"
    # Mark the migrated file as the current schema only after all old values
    # have been carried through. This does not remove any unknown user fields.
    try:
        cfg["config_version"] = max(24, int(cfg.get("config_version", 0) or 0))
    except Exception:
        cfg["config_version"] = 24

    return cfg


def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        LOGGER.exception("保存配置失败")


REPORT_FONT_FILENAME = "MaokenAssortedSans-Lite.otf"
REPORT_FONT_DIR = USER / "fonts"
REPORT_FONT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FONT_LOCAL = REPORT_FONT_DIR / REPORT_FONT_FILENAME
THUMB_DIR = USER / "thumbnails"
THUMB_DIR.mkdir(parents=True, exist_ok=True)


def maybe_adopt_report_font(cfg):
    """Find the user's Maoken font once without bundling it with XiaoMeili.
    The selected font is copied into XiaoMeiliData so future EXE upgrades keep it.
    """
    current = str(cfg.get("report_font_path", "") or "").strip()
    if current and Path(current).exists():
        return current
    if REPORT_FONT_LOCAL.exists():
        cfg["report_font_path"] = str(REPORT_FONT_LOCAL)
        save_config(cfg)
        return str(REPORT_FONT_LOCAL)
    if sys.platform == "win32":
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        candidates = [
            home / "Downloads" / REPORT_FONT_FILENAME,
            home / "Desktop" / REPORT_FONT_FILENAME,
            home / "Documents" / REPORT_FONT_FILENAME,
        ]
        for src in candidates:
            try:
                if src.exists():
                    shutil.copy2(src, REPORT_FONT_LOCAL)
                    cfg["report_font_path"] = str(REPORT_FONT_LOCAL)
                    save_config(cfg)
                    LOGGER.info("自动找到并导入战报字体: %s", src)
                    return str(REPORT_FONT_LOCAL)
            except Exception:
                LOGGER.exception("自动导入战报字体失败: %s", src)
    return ""


def report_evaluation(kills):
    k = max(0, int(kills))
    if k <= 5:
        return "不愧是医者，不愿杀生是吗？"
    if k <= 15:
        return "你不配做我美丽的徒弟！"
    if k <= 25:
        return "我将收你为关门弟子，但只能看大门。"
    return "我的两成功力如何？"


def asset_thumbnail(path_value, size=96):
    """Create/cached PNG preview from first frame of an imported animation."""
    try:
        src = Path(path_value)
        if not src.exists():
            return None
        key = f"{src.stem}_{int(src.stat().st_mtime)}_{src.stat().st_size}.png"
        out = THUMB_DIR / key
        if out.exists():
            return str(out)
        im = Image.open(src)
        try:
            im.seek(0)
            frame = im.convert("RGBA")
            frame.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (246, 246, 246, 255))
            x = (size - frame.width) // 2
            y = (size - frame.height) // 2
            canvas.alpha_composite(frame, (x, y))
            canvas.save(out, "PNG")
        finally:
            try: im.close()
            except Exception: pass
        return str(out)
    except Exception:
        LOGGER.exception("生成素材缩略图失败: %s", path_value)
        return None


def save_rgba_gif(frames, dst, duration=67):
    pal_frames = []
    for frame in frames:
        im = frame.convert("RGBA")
        alpha = im.getchannel("A")
        pal = im.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        palette = pal.getpalette()[:255 * 3] + [0, 0, 0]
        pal.putpalette(palette)
        mask = alpha.point(lambda x: 255 if x < 72 else 0)
        pal.paste(255, mask=mask)
        pal.info["transparency"] = 255
        pal.info["disposal"] = 2
        pal_frames.append(pal)
    pal_frames[0].save(
        dst, save_all=True, append_images=pal_frames[1:], duration=duration,
        loop=0, transparency=255, disposal=2, optimize=False
    )


def set_windows_app_identity():
    """Give Windows a stable app identity so the taskbar/settings window uses
    the XiaoMeili icon instead of grouping under Python/pythonw.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("XiaoMeili.DesktopPet.V0_6")
    except Exception:
        LOGGER.exception("设置 Windows AppUserModelID 失败")


class Bridge(QObject):
    trigger_state = Signal(str)
    open_settings = Signal()
    toggle_lock = Signal()
    show_hide = Signal()


class HotkeyManager:
    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.registered = []

    def unregister_all(self):
        old = list(self.registered)
        self.registered = []
        for combo in old:
            try:
                keyboard.remove_hotkey(combo)
            except Exception:
                LOGGER.info("快捷键解除失败但已忽略: %s", combo)

    def register(self, cfg):
        self.unregister_all()
        hk = cfg.get("hotkeys", {})
        callbacks = {
            "idle": lambda: self.bridge.trigger_state.emit("idle"),
            "low_hp": lambda: self.bridge.trigger_state.emit("low_hp"),
            "kill": lambda: self.bridge.trigger_state.emit("kill"),
            "dead": lambda: self.bridge.trigger_state.emit("dead"),
            "victory": lambda: self.bridge.trigger_state.emit("victory"),
            "defeat": lambda: self.bridge.trigger_state.emit("defeat"),
            "toggle_lock": lambda: self.bridge.toggle_lock.emit(),
            "settings": lambda: self.bridge.open_settings.emit(),
            "show_hide": lambda: self.bridge.show_hide.emit(),
        }
        for key, cb in callbacks.items():
            combo = str(hk.get(key, "")).strip().lower()
            if not combo:
                continue
            try:
                keyboard.add_hotkey(combo, cb, suppress=False, trigger_on_release=False)
                self.registered.append(combo)
            except Exception:
                LOGGER.exception("注册快捷键失败: %s=%s", key, combo)
        LOGGER.info("已注册快捷键: %s", self.registered)


class HelpBadge(QPushButton):
    def __init__(self, help_text, parent=None):
        super().__init__("?", parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setToolTip(help_text)
        self.setStyleSheet(
            "QPushButton{border:1px solid #b7b7b7;border-radius:10px;background:#f7f7f7;color:#555;font-weight:700;}"
            "QPushButton:hover{background:#e9f7f3;border-color:#53bba6;color:#18745f;}"
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class ReportTextOverlay(QWidget):
    """Cached report lettering painted over the stationary report whiteboard."""
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg=cfg; self.kill_count=None; self.evaluation=""; self.asset_path=None
        self.font_family="Microsoft YaHei"; self._cache=QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.hide(); self.reload_font()

    def reload_font(self):
        family=None; font_path=str(self.cfg.get("report_font_path","") or "")
        if font_path and Path(font_path).exists():
            try:
                fid=QFontDatabase.addApplicationFont(font_path)
                if fid>=0:
                    fams=QFontDatabase.applicationFontFamilies(fid); family=fams[0] if fams else None
            except Exception: LOGGER.exception("加载战报字体失败: %s",font_path)
        if not family:
            try:
                fams=set(QFontDatabase.families())
                for candidate in ("MaokenAssortedSans-Lite","猫啃什锦黑-轻量版"):
                    if candidate in fams: family=candidate; break
            except Exception: pass
        self.font_family=family or "Microsoft YaHei"; self._rebuild_cache()

    def set_asset(self,path):
        self.asset_path=str(path or ""); self._rebuild_cache()

    def set_report(self,kills,evaluation):
        self.kill_count=max(0,int(kills)); self.evaluation=str(evaluation or "")
        self.reload_font(); self.show(); self.raise_(); self._rebuild_cache(); self.update()

    def clear_report(self):
        self.kill_count=None; self.evaluation=""; self._cache=QPixmap(); self.hide()

    def _rebuild_cache(self):
        if self.kill_count is None or self.width()<=0 or self.height()<=0: return
        layout=get_report_layout(self.cfg,self.asset_path)
        self._cache=render_report_text_pixmap(self.width(),self.height(),layout,self.kill_count,self.evaluation,self.font_family)
        self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event); self._rebuild_cache()

    def paintEvent(self,event):
        if self.kill_count is None or self._cache.isNull(): return
        p=QPainter(self); p.drawPixmap(0,0,self._cache); p.end()




DEFAULT_WHITEBOARD_LAYOUT = {
    "x": 0.075, "y": 0.655, "w": 0.850, "h": 0.300,
    "offset_x": 0.0, "offset_y": 0.0,
    "min_font_px": 13, "max_font_px": 42, "font_scale": 1.0,
    "line_spacing": 1.02, "max_lines": 4,
    "text_color": "#08423A", "outline_color": "#F6FFF9", "outline_width": 0.0,
    "auto_fill": True, "hold_ms": 3000,
}


def normalized_whiteboard_layout(value):
    out = dict(DEFAULT_WHITEBOARD_LAYOUT)
    if isinstance(value, dict):
        for key in out:
            if key in value:
                out[key] = value[key]
    for key in ("x", "y", "w", "h", "offset_x", "offset_y"):
        try: out[key] = float(out[key])
        except Exception: out[key] = float(DEFAULT_WHITEBOARD_LAYOUT[key])
    out["x"] = max(0.0, min(0.95, out["x"])); out["y"] = max(0.0, min(0.95, out["y"]))
    out["w"] = max(0.05, min(1.0 - out["x"], out["w"])); out["h"] = max(0.05, min(1.0 - out["y"], out["h"]))
    out["offset_x"] = max(-0.30, min(0.30, out["offset_x"])); out["offset_y"] = max(-0.30, min(0.30, out["offset_y"]))
    for key, lo, hi in (("min_font_px", 8, 48), ("max_font_px", 12, 88), ("max_lines", 1, 7), ("hold_ms", 500, 8000)):
        try: out[key] = int(out[key])
        except Exception: out[key] = int(DEFAULT_WHITEBOARD_LAYOUT[key])
        out[key] = max(lo, min(hi, out[key]))
    if out["max_font_px"] < out["min_font_px"]:
        out["max_font_px"] = out["min_font_px"]
    try: out["font_scale"] = max(0.50, min(1.80, float(out["font_scale"])))
    except Exception: out["font_scale"] = 1.0
    try: out["line_spacing"] = max(0.85, min(1.50, float(out["line_spacing"])))
    except Exception: out["line_spacing"] = 1.02
    try: out["outline_width"] = max(0.0, min(4.0, float(out["outline_width"])))
    except Exception: out["outline_width"] = 0.0
    out["auto_fill"] = bool(out.get("auto_fill", True))
    out["text_color"] = str(out.get("text_color") or "#08423A")
    out["outline_color"] = str(out.get("outline_color") or "#F6FFF9")
    return out


DEFAULT_HIGHLIGHT_TEXT_LAYOUT = {
    "x": 0.10, "y": 0.57, "w": 0.80, "h": 0.30,
    "offset_x": 0.0, "offset_y": 0.0,
    "min_font_px": 13, "max_font_px": 42, "font_scale": 1.0,
    "line_spacing": 1.02, "max_lines": 4,
    "text_color": "#08423A", "outline_color": "#F6FFF9", "outline_width": 0.0,
    "auto_fill": True, "hold_ms": 3000,
}


def normalized_highlight_text_layout(value, whiteboard_style=None):
    """Normalize V0.9.2.2 highlight text boxes to the same layout engine as dialogue whiteboards.

    V0.9.1.1/V0.9.2.1 stored x/y/w/h and font_pct as percentages.  Keep those
    positions when migrating, but intentionally adopt the dialogue-board font
    family/fitting rules requested for V0.9.2.2.
    """
    raw = dict(value) if isinstance(value, dict) else {}
    base = dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)
    wb = normalized_whiteboard_layout(whiteboard_style or {})
    for key in ("min_font_px", "max_font_px", "font_scale", "line_spacing", "max_lines",
                "text_color", "outline_color", "outline_width", "auto_fill"):
        base[key] = wb.get(key, base[key])

    legacy_percent = False
    for key in ("x", "y", "w", "h"):
        try:
            if float(raw.get(key, 0.0)) > 1.0:
                legacy_percent = True
                break
        except Exception:
            pass
    if legacy_percent:
        for key in ("x", "y", "w", "h"):
            if key in raw:
                try: base[key] = float(raw[key]) / 100.0
                except Exception: pass
        # Legacy color was independent of the dialogue template.  V0.9.2.2
        # intentionally follows the dialogue-board typography by default.
    else:
        for key in base:
            if key in raw:
                base[key] = raw[key]
    return normalized_whiteboard_layout(base)


def _dialogue_wrap_lines(text, metrics, max_width):
    lines = []
    current = ""
    for ch in str(text or ""):
        if ch == "\n":
            lines.append(current); current = ""; continue
        trial = current + ch
        if current and metrics.horizontalAdvance(trial) > max_width:
            lines.append(current); current = ch
        else:
            current = trial
    if current or not lines:
        lines.append(current)
    return lines


def _dialogue_font_and_lines(text, rect, layout, font_family, canvas_width):
    scale = max(0.45, float(canvas_width) / 280.0)
    min_px = max(7, int(round(float(layout.get("min_font_px", 13)) * scale)))
    max_px = max(min_px, int(round(float(layout.get("max_font_px", 42)) * scale * float(layout.get("font_scale", 1.0)))))
    max_lines = max(1, int(layout.get("max_lines", 4)))
    spacing = float(layout.get("line_spacing", 1.02))
    chosen = None
    for px in range(max_px, min_px - 1, -1):
        font = QFont(str(font_family or "Microsoft YaHei")); font.setPixelSize(px); font.setBold(True)
        fm = QFontMetrics(font)
        lines = _dialogue_wrap_lines(text, fm, max(10, int(rect.width())))
        total_h = len(lines) * fm.height() * spacing
        if len(lines) <= max_lines and total_h <= rect.height():
            chosen = (font, fm, lines); break
    if chosen is None:
        font = QFont(str(font_family or "Microsoft YaHei")); font.setPixelSize(min_px); font.setBold(True)
        fm = QFontMetrics(font); lines = _dialogue_wrap_lines(text, fm, max(10, int(rect.width())))
        chosen = (font, fm, lines[:max_lines])
    return chosen


def render_dialogue_text_pixmap(width, height, layout, text, font_family, reveal_count=None):
    width=max(1,int(width)); height=max(1,int(height)); layout=normalized_whiteboard_layout(layout)
    pm=QPixmap(width,height); pm.fill(Qt.GlobalColor.transparent)
    text=str(text or "")
    if not text: return pm
    x=(layout["x"]+layout["offset_x"])*width; y=(layout["y"]+layout["offset_y"])*height
    rect=QRectF(x,y,layout["w"]*width,layout["h"]*height)
    font,fm,lines=_dialogue_font_and_lines(text,rect,layout,font_family,width)
    spacing=float(layout.get("line_spacing",1.02)); line_h=fm.height()*spacing
    total_h=len(lines)*line_h; y0=rect.y()+(rect.height()-total_h)/2.0
    shown=len(text) if reveal_count is None else max(0,min(len(text),int(reveal_count)))
    p=QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing,True); p.setFont(font)
    color=QColor(str(layout.get("text_color") or "#08423A")); outline=QColor(str(layout.get("outline_color") or "#F6FFF9"))
    ow=float(layout.get("outline_width",0.0))*max(0.5,width/280.0)
    consumed=0
    for idx,line in enumerate(lines):
        fullw=fm.horizontalAdvance(line); lx=rect.x()+(rect.width()-fullw)/2.0
        remaining=max(0,shown-consumed); part=line[:remaining]
        consumed += len(line)
        if not part: continue
        baseline=y0+idx*line_h+fm.ascent()
        if ow>0:
            path=QPainterPath(); path.addText(QPointF(lx,baseline),font,part)
            p.setPen(QPen(outline,ow*2.0)); p.setBrush(color); p.drawPath(path)
        else:
            p.setPen(color); p.drawText(QPointF(lx,baseline),part)
    p.end(); return pm


class DialogueBoardOverlay(QWidget):
    """Dynamic typewriter text over XiaoMeili's fixed speech-bubble whiteboard."""
    def __init__(self,cfg,parent=None):
        super().__init__(parent); self.cfg=cfg; self.text=""; self.reveal_count=0
        self.font_family="Microsoft YaHei"; self._started=0.0; self._duration_ms=1; self._weights=[]; self._total_weight=1.0
        self.timer=QTimer(self); self.timer.setInterval(32); self.timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True); self.hide(); self.reload_font()

    def reload_font(self):
        family=None; font_path=str(self.cfg.get("report_font_path","") or "")
        if font_path and Path(font_path).exists():
            try:
                fid=QFontDatabase.addApplicationFont(font_path)
                if fid>=0:
                    fams=QFontDatabase.applicationFontFamilies(fid); family=fams[0] if fams else None
            except Exception: pass
        self.font_family=family or "Microsoft YaHei"; self.update()

    def layout(self): return normalized_whiteboard_layout(self.cfg.get("whiteboard",{}))

    def set_dialogue(self,text,duration_ms):
        self.text=str(text or "").strip(); self.reveal_count=0; self._duration_ms=max(180,int(duration_ms or 1)); self._started=time.monotonic()
        self._weights=[]
        for ch in self.text:
            if ch in "，、,": w=1.65
            elif ch in "。！？?!；;……": w=2.35
            elif ch.isspace(): w=0.25
            else: w=1.0
            self._weights.append(w)
        self._total_weight=max(1.0,sum(self._weights)); self.show(); self.raise_(); self.timer.start(); self.update()

    def _tick(self):
        if not self.text: self.timer.stop(); return
        ratio=min(1.0,max(0.0,(time.monotonic()-self._started)*1000.0/self._duration_ms)); target=ratio*self._total_weight
        acc=0.0; count=0
        for w in self._weights:
            if acc+w > target and ratio < 1.0: break
            acc += w; count += 1
        if count != self.reveal_count:
            self.reveal_count=count; self.update()
        if ratio>=1.0:
            self.reveal_count=len(self.text); self.timer.stop(); self.update()

    def complete(self):
        self.timer.stop(); self.reveal_count=len(self.text); self.update()

    def clear_dialogue(self):
        self.timer.stop(); self.text=""; self.reveal_count=0; self.hide(); self.update()

    def paintEvent(self,event):
        if not self.text: return
        pm=render_dialogue_text_pixmap(self.width(),self.height(),self.layout(),self.text,self.font_family,self.reveal_count)
        p=QPainter(self); p.drawPixmap(0,0,pm); p.end()


class DialogueIndicator(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self._phase=0.0; self._active=False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.timer=QTimer(self); self.timer.setInterval(80); self.timer.timeout.connect(self._pulse); self.hide()
    def set_active(self,active):
        self._active=bool(active)
        if self._active: self.show(); self.raise_(); self.timer.start(); self.update()
        else: self.timer.stop(); self.hide()
    def _pulse(self): self._phase+=0.22; self.update()
    def paintEvent(self,event):
        if not self._active:return
        m=__import__('math'); pulse=0.72+0.20*(0.5+0.5*m.sin(self._phase)); p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        c=self.rect().center(); base=max(4,min(self.width(),self.height())//7)
        for mul,alpha in ((2.8,22),(2.1,34),(1.55,60)):
            r=base*mul*pulse; p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(69,224,184,alpha)); p.drawEllipse(QPointF(c),r,r)
        r=base*pulse; p.setBrush(QColor(62,211,171,235)); p.drawEllipse(QPointF(c),r,r); p.end()

class MouseInteractionLayer(QWidget):
    """Continuous layered XiaoMeili driven by global mouse position.

    V2 abandons any discrete direction sprite switching.  The same PSD-derived
    layered XiaoMeili is driven continuously by mouse position: pupils react
    first, then head, then body, while hair and earrings trail slightly behind.
    """
    ASSET_FILES = {
        "back": "hair_back.png",
        "body": "body.png",
        "head": "head.png",
        "brows": "brows.png",
        "eye_l": "eye_white_left.png",
        "eye_r": "eye_white_right.png",
        "pupil_l": "pupil_left.png",
        "pupil_r": "pupil_right.png",
        "blink_l": "blink_left.png",
        "blink_r": "blink_right.png",
        "mask_l": "eye_mask_left.png",
        "mask_r": "eye_mask_right.png",
        "front": "hair_front.png",
        "ear_l": "earring_left.png",
        "ear_r": "earring_right.png",
    }

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.pix = {}
        for key, filename in self.ASSET_FILES.items():
            p = resource(f"assets/mouse_interaction/{filename}")
            pm = QPixmap(p)
            if pm.isNull():
                LOGGER.error("鼠标互动图层加载失败: %s", p)
            self.pix[key] = pm

        self.target_x = 0.0
        self.target_y = 0.0
        self.look_x = 0.0
        self.look_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.head_vel_x = 0.0
        self.head_vel_y = 0.0

        self.blinking = False
        self.blink_until = 0.0
        self.next_blink = time.monotonic() + random.uniform(2.8, 5.2)

    def set_target(self, nx, ny):
        self.target_x = max(-1.0, min(1.0, float(nx)))
        self.target_y = max(-1.0, min(1.0, float(ny)))

    def reset_pose(self):
        self.target_x = self.target_y = 0.0
        self.look_x = self.look_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.head_vel_x = self.head_vel_y = 0.0
        self.blinking = False
        self.blink_until = 0.0
        self.next_blink = time.monotonic() + random.uniform(2.8, 5.2)
        self.update()

    def force_blink(self):
        now = time.monotonic()
        self.blinking = True
        self.blink_until = now + 0.13
        self.next_blink = now + random.uniform(2.5, 4.8)
        self.update()

    @staticmethod
    def _follow(current, target, smooth):
        return current + (target - current) * smooth

    def step(self, now=None):
        now = time.monotonic() if now is None else float(now)
        micfg = self.cfg.get("mouse_interaction", {})
        smooth = max(0.05, min(0.55, float(micfg.get("smoothing", 0.18))))
        base_mul = 1.35 if abs(self.target_x) + abs(self.target_y) < 0.08 else 1.0

        self.look_x = self._follow(self.look_x, self.target_x, smooth * 1.15 * base_mul)
        self.look_y = self._follow(self.look_y, self.target_y, smooth * 1.08 * base_mul)

        prev_head_x, prev_head_y = self.head_x, self.head_y
        self.head_x = self._follow(self.head_x, self.look_x, 0.28 * base_mul)
        self.head_y = self._follow(self.head_y, self.look_y, 0.24 * base_mul)
        # Body intentionally reacts less and a little slower, so the pet feels like
        # she shifts her weight after the eyes/head have already looked.
        self.body_x = self._follow(self.body_x, self.look_x * 0.58, 0.15 * base_mul)
        self.body_y = self._follow(self.body_y, self.look_y * 0.42, 0.13 * base_mul)
        # Front hair stays close to the head but still drags slightly.
        self.front_x = self._follow(self.front_x, self.head_x, 0.20 * base_mul)
        self.front_y = self._follow(self.front_y, self.head_y, 0.18 * base_mul)
        # Ponytail / back hair should feel heavier.
        self.back_x = self._follow(self.back_x, self.head_x * 0.72, 0.11 * base_mul)
        self.back_y = self._follow(self.back_y, self.head_y * 0.70, 0.10 * base_mul)
        # Earrings are the loosest pieces; they pick up a bit of inertia.
        self.ear_x = self._follow(self.ear_x, self.head_x, 0.12 * base_mul)
        self.ear_y = self._follow(self.ear_y, self.head_y, 0.12 * base_mul)

        self.head_vel_x = self.head_x - prev_head_x
        self.head_vel_y = self.head_y - prev_head_y

        if self.blinking and now >= self.blink_until:
            self.blinking = False
            self.next_blink = now + random.uniform(2.8, 5.5)
        elif not self.blinking and now >= self.next_blink:
            self.blinking = True
            self.blink_until = now + random.uniform(0.105, 0.145)
        self.update()

    def _draw_layer(self, painter, key, dx=0.0, dy=0.0):
        pm = self.pix.get(key)
        if pm is None or pm.isNull():
            return
        target = QRectF(float(dx), float(dy), float(self.width()), float(self.height()))
        source = QRectF(0.0, 0.0, float(pm.width()), float(pm.height()))
        painter.drawPixmap(target, pm, source)

    def _draw_pixmap_transformed(self, painter, pixmap, dx=0.0, dy=0.0, rot_deg=0.0, scale_x=1.0, scale_y=1.0, pivot=(0.5, 0.5)):
        if pixmap is None or pixmap.isNull():
            return
        px = float(self.width()) * float(pivot[0])
        py = float(self.height()) * float(pivot[1])
        painter.save()
        painter.translate(px + float(dx), py + float(dy))
        if rot_deg:
            painter.rotate(float(rot_deg))
        if scale_x != 1.0 or scale_y != 1.0:
            painter.scale(float(scale_x), float(scale_y))
        painter.translate(-px, -py)
        target = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        source = QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height()))
        painter.drawPixmap(target, pixmap, source)
        painter.restore()

    def _draw_layer_transformed(self, painter, key, dx=0.0, dy=0.0, rot_deg=0.0, scale_x=1.0, scale_y=1.0, pivot=(0.5, 0.5)):
        self._draw_pixmap_transformed(painter, self.pix.get(key), dx, dy, rot_deg, scale_x, scale_y, pivot)

    def _draw_clipped_pupil(self, painter, pupil_key, mask_key, pupil_dx, pupil_dy, mask_dx, mask_dy):
        pupil = self.pix.get(pupil_key); mask = self.pix.get(mask_key)
        if pupil is None or pupil.isNull() or mask is None or mask.isNull():
            return
        temp = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_RGBA8888)
        temp.fill(Qt.GlobalColor.transparent)
        tp = QPainter(temp)
        tp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRectF(float(pupil_dx), float(pupil_dy), float(self.width()), float(self.height()))
        source = QRectF(0.0, 0.0, float(pupil.width()), float(pupil.height()))
        tp.drawPixmap(target, pupil, source)
        tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mt = QRectF(float(mask_dx), float(mask_dy), float(self.width()), float(self.height()))
        ms = QRectF(0.0, 0.0, float(mask.width()), float(mask.height()))
        tp.drawPixmap(mt, mask, ms)
        tp.end()
        painter.drawImage(0, 0, temp)

    @staticmethod
    def _qimage_rgba_array(image):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        h, w = image.height(), image.width()
        bpl = image.bytesPerLine()
        arr = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        arr = arr.reshape((h, bpl // 4, 4))[:, :w, :].copy()
        return arr

    def _compose_head_group(self, eye_dx, eye_dy, ear_dx, ear_dy):
        img = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw_layer(p, "head", 0.0, 0.0)
        self._draw_layer(p, "brows", 0.0, 0.0)
        self._draw_layer(p, "ear_l", ear_dx, ear_dy)
        self._draw_layer(p, "ear_r", ear_dx, ear_dy)
        if self.blinking:
            self._draw_layer(p, "blink_l", 0.0, 0.0)
            self._draw_layer(p, "blink_r", 0.0, 0.0)
        else:
            self._draw_layer(p, "eye_l", 0.0, 0.0)
            self._draw_layer(p, "eye_r", 0.0, 0.0)
            self._draw_clipped_pupil(p, "pupil_l", "mask_l", eye_dx, eye_dy, 0.0, 0.0)
            self._draw_clipped_pupil(p, "pupil_r", "mask_r", eye_dx, eye_dy, 0.0, 0.0)
        p.end()
        return img

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        micfg = self.cfg.get("mouse_interaction", {})
        sx = self.width() / 280.0
        sy = self.height() / max(1.0, 280.0 * 660.0 / 620.0)

        strength = max(0.55, min(1.55, float(micfg.get("strength", 1.0))))
        body_dx = self.body_x * float(micfg.get("body_x_px", 3.2)) * sx * strength
        body_dy = self.body_y * float(micfg.get("body_y_px", 1.7)) * sy * strength
        head_dx = self.head_x * float(micfg.get("head_x_px", 8.5)) * sx * strength
        head_dy = self.head_y * float(micfg.get("head_y_px", 5.0)) * sy * strength
        front_dx = self.front_x * float(micfg.get("front_x_px", 6.4)) * sx * strength
        front_dy = self.front_y * float(micfg.get("front_y_px", 3.6)) * sy * strength
        back_dx = self.back_x * float(micfg.get("back_x_px", 2.4)) * sx * strength
        back_dy = self.back_y * float(micfg.get("back_y_px", 1.8)) * sy * strength

        body_rot = self.body_x * float(micfg.get("body_rot_deg", 1.5)) * strength
        head_rot = (self.head_x * float(micfg.get("head_rot_deg", 4.2)) + self.head_y * 0.7) * strength
        front_rot = (self.front_x * float(micfg.get("front_rot_deg", 4.6)) + self.head_vel_x * 14.0) * strength
        back_rot = (self.back_x * float(micfg.get("back_rot_deg", 1.9)) - self.head_vel_x * 10.0) * strength

        pupil_reduce = max(0.35, min(1.0, float(micfg.get("pupil_reduce_when_head_turn", 0.80))))
        pupil_gain = 1.0 - (1.0 - pupil_reduce) * min(1.0, abs(self.head_x))
        eye_dx = self.look_x * float(micfg.get("eye_x_px", 3.2)) * sx * pupil_gain * strength
        eye_dy = self.look_y * float(micfg.get("eye_y_px", 2.0)) * sy * pupil_gain * strength
        ear_dx = (self.ear_x * 2.4 + self.head_vel_x * 9.0) * sx * strength
        ear_dy = (self.ear_y * 1.3 + self.head_vel_y * 4.0) * sy * strength

        body_scale_x = 1.0 - abs(self.body_x) * 0.012
        body_scale_y = 1.0 + max(-self.body_y, 0.0) * 0.010 - max(self.body_y, 0.0) * 0.006
        head_scale_y = 1.0 + max(-self.head_y, 0.0) * 0.018 - max(self.head_y, 0.0) * 0.010
        front_scale_y = 1.0 + max(-self.front_y, 0.0) * 0.010

        head_img = self._compose_head_group(eye_dx, eye_dy, ear_dx, ear_dy)

        canvas = QImage(self.width(), self.height(), QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)
        cp = QPainter(canvas)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw_layer_transformed(cp, "back", back_dx, back_dy, back_rot, 1.0, 1.0, pivot=(0.50, 0.46))
        self._draw_layer_transformed(cp, "body", body_dx, body_dy, body_rot, body_scale_x, body_scale_y, pivot=(0.50, 0.82))
        self._draw_pixmap_transformed(cp, QPixmap.fromImage(head_img), head_dx, head_dy, head_rot, 1.0, head_scale_y, pivot=(0.50, 0.60))
        self._draw_layer_transformed(cp, "front", front_dx, front_dy, front_rot, 1.0, front_scale_y, pivot=(0.50, 0.58))
        cp.end()

        rgba = self._qimage_rgba_array(canvas)
        rgba = _add_soft_white_glow(rgba, outline_px=1, glow_px=4,
                                    outline_strength=0.42, glow_strength=0.24)
        rgba = np.ascontiguousarray(rgba)
        final_img = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
                           QImage.Format.Format_RGBA8888).copy()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(0, 0, final_img)
        p.end()


class LockBubble(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(38, 38)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.btn = QPushButton("🔒")
        self.btn.setFixedSize(34, 34)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            "QPushButton { background: rgba(18,24,28,220); color: white; border: 1px solid rgba(64,220,194,210); "
            "border-radius: 17px; font-size: 17px; } "
            "QPushButton:hover { background: rgba(25,44,45,235); border: 1px solid rgba(93,255,224,255); }"
        )
        self.btn.clicked.connect(self.clicked.emit)
        lay.addWidget(self.btn)
        self.hide()

    def set_locked(self, locked: bool):
        self.btn.setText("🔒" if locked else "🔓")
        self.btn.setToolTip("当前：已锁定（固定位置 + 点击穿透），点击可解锁" if locked else "当前：已解锁（可拖动 / 可右键），点击可锁定")



class DragInteractionLayer(QWidget):
    """V0.7.7.1 layered drag pose.

    Fixes:
    * hair_front2 is rendered UNDER the face, matching the supplied layer relationship;
    * the eye whites are restored over the baked head-group pupils, then two pupil layers
      move independently so the dragged pose has live gaze;
    * body/head/front hair/ponytail/earrings use stronger but still subtle inertia.
    """
    settled = Signal()

    ASSET_FILES = {
        "back": "hair_back.webp",
        "body": "body.webp",
        "head": "head_group.webp",
        "earrings": "earrings.webp",
        "front2": "hair_front2.webp",
        "front": "hair_front.webp",
        "eye_white_left": "eye_white_left.webp",
        "eye_white_right": "eye_white_right.webp",
        "pupil_left": "pupil_left.webp",
        "pupil_right": "pupil_right.webp",
    }

    # Crops are stored tightly to keep the update lightweight. Coordinates are from
    # the user's original 1254x1254 drag PSD/PNG canvas.
    EYE_CROPS = {
        "eye_white_left": (246, 710, 378, 828),
        "eye_white_right": (422, 742, 614, 848),
        "pupil_left": (295, 741, 354, 798),
        "pupil_right": (455, 765, 532, 827),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.pix = {}
        for key, filename in self.ASSET_FILES.items():
            p = resource(f"assets/drag_interaction/{filename}")
            pm = QPixmap(p)
            if pm.isNull():
                LOGGER.error("拖拽互动图层加载失败: %s", p)
            self.pix[key] = pm

        self.active = False
        self.recovering = False
        self.recover_started = 0.0

        self.target_x = self.target_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.front2_x = self.front2_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.swing_x = 0.0

        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_bias_x = self.gaze_bias_y = 0.0
        self.gaze_motion_x = self.gaze_motion_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.phase = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.hide()

    @staticmethod
    def _follow(current, target, smooth):
        return current + (target - current) * smooth

    def reset_pose(self):
        self.target_x = self.target_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.front2_x = self.front2_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.swing_x = 0.0
        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_bias_x = self.gaze_bias_y = 0.0
        self.gaze_motion_x = self.gaze_motion_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.phase = 0.0
        self.recovering = False
        self.recover_started = 0.0
        self.update()

    def start_drag(self):
        self.reset_pose()
        self.active = True
        self.recovering = False
        self.show()
        self.raise_()
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def set_cursor_focus(self, local_x, local_y, width, height):
        """Keep the dragged pose looking at the grab point, just like the V2 mouse-follow feel."""
        if not self.active:
            return
        try:
            w = max(1.0, float(width))
            h = max(1.0, float(height))
            # Eye centre in the supplied dangling-pose canvas.
            nx = (float(local_x) / w - 0.37) / 0.36
            ny = (float(local_y) / h - 0.61) / 0.34
            self.gaze_bias_x = max(-1.0, min(1.0, nx))
            self.gaze_bias_y = max(-1.0, min(1.0, ny))
        except Exception:
            pass

    def feed_motion(self, dx, dy):
        if not self.active:
            return

        # Use real drag velocity as an impulse. V0.7.7.1 normalised by 16 px and then
        # faded too quickly, so ordinary slow dragging was visually almost static.
        vx = max(-2.4, min(2.4, float(dx) / 7.0))
        vy = max(-2.0, min(2.0, float(dy) / 7.0))

        self.target_x = max(-2.6, min(2.6, self.target_x * 0.30 - vx * 1.15))
        self.target_y = max(-2.2, min(2.2, self.target_y * 0.30 - vy * 1.00))
        self.swing_x = max(-2.6, min(2.6, self.swing_x * 0.42 - vx * 1.35))

        # Motion is also injected into the eyes. The stable bias still points to the
        # cursor/grab position; velocity only adds a small lively glance.
        self.gaze_motion_x = max(-0.70, min(0.70, vx * 0.28))
        self.gaze_motion_y = max(-0.50, min(0.50, vy * 0.22))
        self.motion_energy = min(
            1.0,
            max(self.motion_energy * 0.82, min(1.0, (abs(vx) + abs(vy)) * 0.42)),
        )

    def begin_recover(self):
        if not self.active:
            return
        self.recovering = True
        self.recover_started = time.monotonic()
        self.target_x = self.target_y = 0.0
        self.gaze_target_x = self.gaze_target_y = 0.0
        if not self.timer.isActive():
            self.timer.start()

    def cancel(self):
        self.active = False
        self.recovering = False
        self.timer.stop()
        self.reset_pose()
        self.hide()

    def _tick(self):
        if not self.active:
            self.timer.stop()
            return

        # Momentum persists long enough to be readable at normal desktop drag speeds.
        self.target_x *= 0.925
        self.target_y *= 0.925
        self.swing_x *= 0.935
        self.gaze_motion_x *= 0.88
        self.gaze_motion_y *= 0.88
        self.motion_energy *= 0.965
        self.phase += 0.16

        wave = __import__("math").sin(self.phase) * self.motion_energy
        wave2 = __import__("math").sin(self.phase * 0.73 + 0.9) * self.motion_energy

        self.body_x = self._follow(self.body_x, self.target_x * 0.52 + wave * 0.12, 0.13)
        self.body_y = self._follow(self.body_y, self.target_y * 0.34 + wave2 * 0.08, 0.12)

        self.head_x = self._follow(self.head_x, self.target_x * 0.72 + wave * 0.18, 0.17)
        self.head_y = self._follow(self.head_y, self.target_y * 0.46 + wave2 * 0.10, 0.16)

        self.front2_x = self._follow(self.front2_x, self.target_x * 0.90 + wave * 0.28, 0.13)
        self.front2_y = self._follow(self.front2_y, self.target_y * 0.58 + wave2 * 0.15, 0.12)
        self.front_x = self._follow(self.front_x, self.target_x * 1.08 + wave * 0.36, 0.115)
        self.front_y = self._follow(self.front_y, self.target_y * 0.68 + wave2 * 0.18, 0.105)

        self.back_x = self._follow(self.back_x, self.target_x * 1.72 + wave * 0.62, 0.075)
        self.back_y = self._follow(self.back_y, self.target_y * 1.05 + wave2 * 0.24, 0.08)
        self.ear_x = self._follow(self.ear_x, self.target_x * 1.82 + wave * 0.70, 0.082)
        self.ear_y = self._follow(self.ear_y, self.target_y * 1.10 + wave2 * 0.30, 0.085)

        self.gaze_target_x = max(-1.0, min(1.0, self.gaze_bias_x * 0.82 + self.gaze_motion_x))
        self.gaze_target_y = max(-1.0, min(1.0, self.gaze_bias_y * 0.74 + self.gaze_motion_y))
        self.gaze_x = self._follow(self.gaze_x, self.gaze_target_x, 0.24)
        self.gaze_y = self._follow(self.gaze_y, self.gaze_target_y, 0.22)

        self.update()

        if self.recovering:
            # During release, also relax the stable cursor bias toward centre.
            self.gaze_bias_x *= 0.84
            self.gaze_bias_y *= 0.84
            values = (
                self.body_x, self.body_y, self.head_x, self.head_y,
                self.front_x, self.front_y, self.front2_x, self.front2_y,
                self.back_x, self.back_y, self.ear_x, self.ear_y,
                self.swing_x, self.gaze_x, self.gaze_y,
            )
            elapsed = time.monotonic() - self.recover_started
            if elapsed >= 0.38 or max(abs(v) for v in values) < 0.010:
                self.active = False
                self.recovering = False
                self.timer.stop()
                self.reset_pose()
                self.hide()
                self.settled.emit()

    def _draw(self, painter, key, base_x, base_y, side, nx=0.0, ny=0.0,
              rot=0.0, pivot=(0.5, 0.5), extra_px_x=0.0, extra_px_y=0.0):
        pm = self.pix.get(key)
        if pm is None or pm.isNull():
            return
        dx = float(nx) * side * 0.070 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.052 + float(extra_px_y) * (side / 512.0)
        px = base_x + side * float(pivot[0])
        py = base_y + side * float(pivot[1])
        painter.save()
        painter.translate(px + dx, py + dy)
        if rot:
            painter.rotate(float(rot))
        painter.translate(-px, -py)
        painter.drawPixmap(
            QRectF(base_x, base_y, side, side),
            pm,
            QRectF(0.0, 0.0, float(pm.width()), float(pm.height())),
        )
        painter.restore()

    def _draw_crop(self, painter, key, base_x, base_y, side, nx=0.0, ny=0.0,
                   rot=0.0, pivot=(0.46, 0.42), extra_px_x=0.0, extra_px_y=0.0):
        pm = self.pix.get(key)
        bbox = self.EYE_CROPS.get(key)
        if pm is None or pm.isNull() or not bbox:
            return
        sx = side / 1254.0
        left, top, right, bottom = bbox
        rx = base_x + float(left) * sx
        ry = base_y + float(top) * sx
        rw = float(right - left) * sx
        rh = float(bottom - top) * sx

        dx = float(nx) * side * 0.070 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.052 + float(extra_px_y) * (side / 512.0)
        px = base_x + side * float(pivot[0])
        py = base_y + side * float(pivot[1])

        painter.save()
        painter.translate(px + dx, py + dy)
        if rot:
            painter.rotate(float(rot))
        painter.translate(-px, -py)
        painter.drawPixmap(
            QRectF(rx, ry, rw, rh),
            pm,
            QRectF(0.0, 0.0, float(pm.width()), float(pm.height())),
        )
        painter.restore()

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return

        canvas = QImage(self.width(), self.height(), QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)
        cp = QPainter(canvas)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        side = float(min(self.width(), self.height()))
        x0 = (float(self.width()) - side) * 0.5
        y0 = (float(self.height()) - side) * 0.5

        # Correct PSD-style z order:
        # back hair -> body -> tiny front2 lock BEHIND face -> head/eyes -> earrings -> main front hair.
        self._draw(cp, "back", x0, y0, side, self.back_x, self.back_y,
                   rot=self.back_x * 8.2 + self.swing_x * 4.0
                       + __import__("math").sin(self.phase) * self.motion_energy * 3.6,
                   pivot=(0.62, 0.28))
        self._draw(cp, "body", x0, y0, side, self.body_x, self.body_y,
                   rot=self.body_x * 3.1
                       + __import__("math").sin(self.phase * 0.72 + 1.1) * self.motion_energy * 0.9,
                   pivot=(0.52, 0.48))
        self._draw(cp, "front2", x0, y0, side, self.front2_x, self.front2_y,
                   rot=self.front2_x * 3.2 + self.swing_x * 1.2, pivot=(0.30, 0.70))

        # Earrings are physically behind the face. In V0.7.7.1 they were painted after
        # the eyes/head, which put the viewer-left turquoise earring on top of the cheek.
        self._draw(cp, "earrings", x0, y0, side, self.ear_x, self.ear_y,
                   rot=self.ear_x * 8.5 + self.swing_x * 3.0, pivot=(0.50, 0.48))

        head_rot = self.head_x * 4.0 + __import__("math").sin(self.phase * 0.82) * self.motion_energy * 1.1
        self._draw(cp, "head", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))

        # Eye whites cover the pupils baked into the old head_group, then live pupils are redrawn.
        self._draw_crop(cp, "eye_white_left", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42))
        self._draw_crop(cp, "eye_white_right", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42))

        eye_dx = max(-5.2, min(5.2, self.gaze_x * 5.2))
        eye_dy = max(-3.2, min(3.2, self.gaze_y * 3.2))
        self._draw_crop(cp, "pupil_left", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42), extra_px_x=eye_dx, extra_px_y=eye_dy)
        self._draw_crop(cp, "pupil_right", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42), extra_px_x=eye_dx, extra_px_y=eye_dy)

        self._draw(cp, "front", x0, y0, side, self.front_x, self.front_y,
                   rot=self.front_x * 6.4 + self.swing_x * 2.8
                       + __import__("math").sin(self.phase * 0.94 + 0.4) * self.motion_energy * 1.8,
                   pivot=(0.45, 0.36))
        cp.end()

        rgba = MouseInteractionLayer._qimage_rgba_array(canvas)
        rgba = _add_soft_white_glow(
            rgba, outline_px=1, glow_px=4,
            outline_strength=0.42, glow_strength=0.24,
        )
        rgba = np.ascontiguousarray(rgba)
        final_img = QImage(
            rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
            QImage.Format.Format_RGBA8888,
        ).copy()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(0, 0, final_img)
        p.end()



class AbilityAuraOverlay(QWidget):
    """Static, ultra-light cosmetic aura for XiaoMeili abilities.

    No ability-specific frame timer exists in V0.10.0. The overlay repaints only
    when a switch changes or the pet is resized.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._states = {}
        self.hide()

    def set_states(self, states):
        self._states = dict(states or {})
        active = any(bool(v) for v in self._states.values())
        self.setVisible(active)
        if active:
            self.raise_()
        self.update()

    def paintEvent(self, event):
        if not any(bool(v) for v in self._states.values()):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        strength = 0.16
        if self._states.get('power_20'):
            strength = max(strength, 0.28)
        if self._states.get('power_50'):
            strength = max(strength, 0.42)
        if self._states.get('beauty_god'):
            strength = 0.64

        aura_rect = QRectF(w * 0.12, h * 0.055, w * 0.76, h * 0.90)
        for extra, alpha, width in ((9, 15, 6), (5, 28, 3), (0, 78, 1.4)):
            rr = aura_rect.adjusted(-extra, -extra, extra, extra)
            pen = QPen(QColor(59, 239, 221, int(alpha * strength)))
            pen.setWidthF(float(width))
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rr)

        if self._states.get('beauty_lock'):
            lock_rect = QRectF(w * 0.29, h * 0.12, w * 0.42, h * 0.42)
            p.setPen(QPen(QColor(126, 255, 242, 82), 1.3))
            p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(lock_rect)

        if self._states.get('beauty_insight'):
            y = int(h * 0.43)
            p.setPen(QPen(QColor(92, 248, 236, 82), 1.0))
            p.drawLine(int(w * 0.23), y, int(w * 0.77), y)

        if self._states.get('beauty_god'):
            p.setPen(QPen(QColor(84, 251, 237, 90), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(w * 0.16, h * 0.075, w * 0.68, h * 0.86))
        p.end()


class PetWindow(QWidget):
    request_settings = Signal()
    request_abilities = Signal()
    config_changed = Signal()
    ability_hover_entered = Signal()
    ability_hover_left = Signal()
    ability_geometry_changed = Signal()
    dialogue_asset_ready = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.drag_offset = None
        self.drag_press_global = None
        self.drag_last_global = None
        self.drag_visual_active = False
        self.current_state = None
        self.current_slot = 0
        self.anim_group = None
        self.movies = [None, None]
        self.current_asset_path = None
        self.last_asset_by_state = {}
        self.movie_generation = 0
        self.mouse_interaction_active = False
        self._mouse_inside_since = None
        self._mouse_outside_since = None
        self._mouse_last_pos = None
        self._mouse_last_move_time = time.monotonic()
        self._mouse_transition_group = None
        # V0.7.7.7: lock is a real game-safe input passthrough state.
        # The old floating bubble remains hidden for shutdown compatibility.
        locked_boot = bool(self.cfg.get("lock_position", False))
        changed_boot = (
            bool(self.cfg.get("click_through", False)) != locked_boot
            or int(self.cfg.get("opacity", 100)) != 100
        )
        self.cfg["click_through"] = locked_boot
        self.cfg["opacity"] = 100
        if changed_boot:
            save_config(self.cfg)
        self.lock_bubble = LockBubble()
        self.lock_bubble.hide()
        self._hover_last_seen = 0.0
        self._v0777_right_was_down = False
        self._v0778_unlock_pending = False
        self._hit_image = QImage(resource("assets/xiaomeili_base.png"))

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        self.apply_window_flags(first=True)

        self.stack = QStackedLayout(self)
        self.stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.labels, self.effects = [], []
        for i in range(2):
            lab = QLabel(self)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setScaledContents(True)
            eff = QGraphicsOpacityEffect(lab)
            eff.setOpacity(1.0 if i == 0 else 0.0)
            lab.setGraphicsEffect(eff)
            self.stack.addWidget(lab)
            self.labels.append(lab)
            self.effects.append(eff)

        # V0.10.0.2 ability form: the user's green-screen video is pre-keyed
        # with the same white rim/glow pipeline used by imported action clips.
        # Runtime never edits, moves, or deletes the user's original MP4.
        self._ability_form_requested = False
        self.ability_form_label = QLabel(self)
        self.ability_form_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ability_form_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._ability_form_path = resource("assets/xiaomeili_ability_form_v01002.webp")
        self._ability_form_movie = QMovie(self._ability_form_path)
        self._ability_form_movie.setCacheMode(QMovie.CacheMode.CacheNone)
        self._ability_form_movie.finished.connect(self._restart_ability_form_movie)
        self.ability_form_label.setMovie(self._ability_form_movie)
        self.stack.addWidget(self.ability_form_label)
        self.ability_form_label.hide()

        self.mouse_layer = MouseInteractionLayer(self.cfg, self)
        self.mouse_layer.setGeometry(0, 0, self.width(), self.height())
        self.mouse_effect = QGraphicsOpacityEffect(self.mouse_layer)
        self.mouse_effect.setOpacity(0.0)
        self.mouse_layer.setGraphicsEffect(self.mouse_effect)
        self.mouse_layer.hide()

        self.drag_layer = DragInteractionLayer(self)
        self.drag_layer.setGeometry(0, 0, self.width(), self.height())
        self.drag_layer.settled.connect(self._finish_drag_interaction)
        self.drag_layer.hide()

        self.ability_aura = AbilityAuraOverlay(self)
        self.ability_aura.setGeometry(0, 0, self.width(), self.height())
        self.ability_aura.set_states(self.cfg.get("ability_sidebar", {}).get("states", {}))

        self.report_overlay = ReportTextOverlay(self.cfg, self)
        self.report_active = False
        self.report_timer = QTimer(self)
        self.report_timer.setSingleShot(True)
        self.report_timer.timeout.connect(self._end_report)

        # V0.8.8 unified speech-board layer. The supplied 15-second green-screen
        # video is converted once to a transparent WebP in XiaoMeiliData, then
        # reused for wake acknowledgements and every voice answer.
        self.dialogue_overlay = DialogueBoardOverlay(self.cfg, self)
        self.dialogue_indicator = DialogueIndicator(self)
        self.dialogue_board_active = False
        self.dialogue_visual_generation = 0
        self.dialogue_asset_path = ""
        self._dialogue_return_state = "idle"
        self._dialogue_pending_state = None
        self._dialogue_pending_report = None
        self.dialogue_asset_ready.connect(self._on_dialogue_asset_ready)

        self.setWindowOpacity(max(0.2, min(1.0, self.cfg.get("opacity", 100) / 100.0)))
        self.resize_pet()
        self.move(int(self.cfg.get("x", 1200)), int(self.cfg.get("y", 500)))
        self.ensure_on_screen()
        self.play_state(self.cfg.get("last_state", "idle"), immediate=True)
        if "--settings-ui-self-test" not in sys.argv:
            QTimer.singleShot(250, self._prepare_dialogue_asset_async)

        self.hover_timer = QTimer(self)
        self.hover_timer.setInterval(70)
        self.hover_timer.timeout.connect(self.poll_hover_lock_button)
        self.hover_timer.start()

        self.mouse_interaction_timer = QTimer(self)
        self.mouse_interaction_timer.setInterval(max(20, min(80, int(self.cfg.get("mouse_interaction", {}).get("poll_interval_ms", 33)))))
        self.mouse_interaction_timer.timeout.connect(self.poll_mouse_interaction)
        self.mouse_interaction_timer.start()

    def apply_window_flags(self, first=False):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if not first:
            self.show()
        QTimer.singleShot(30, self.apply_clickthrough_native)

    def apply_clickthrough_native(self):
        locked = bool(self.cfg.get("lock_position", False) or self.cfg.get("click_through", False))
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        except Exception:
            pass
        if sys.platform != "win32" or not self.winId():
            return
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if locked:
                style |= (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style &= ~WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            LOGGER.info("游戏防误触锁定=%s | 原生点击穿透=%s", locked, locked)
        except Exception:
            LOGGER.exception("切换游戏防误触锁定失败")

    def resize_pet(self):
        w = int(self.cfg.get("pet_width", 280))
        h = int(w * 660 / 620)
        self.setFixedSize(w, h)
        for lab in self.labels:
            lab.setFixedSize(w, h)
        if hasattr(self, "ability_form_label"):
            self.ability_form_label.setFixedSize(w, h)
            movie = getattr(self, "_ability_form_movie", None)
            if movie is not None:
                side = max(1, int(min(w * 0.98, h * 0.98)))
                movie.setScaledSize(QSize(side, side))
            self._refresh_ability_form_visibility()
        if hasattr(self, "mouse_layer"):
            self.mouse_layer.setGeometry(0, 0, w, h)
        if hasattr(self, "drag_layer"):
            self.drag_layer.setGeometry(0, 0, w, h)
        if hasattr(self, "ability_aura"):
            self.ability_aura.setGeometry(0, 0, w, h)
            self.ability_aura.raise_()
        if hasattr(self, "report_overlay"):
            # Overlay spans the whole pet canvas; each report asset owns a normalized
            # whiteboard rectangle in report_layouts.
            self.report_overlay.setGeometry(0, 0, w, h)
            self.report_overlay.raise_()
        if hasattr(self, "dialogue_overlay"):
            self.dialogue_overlay.setGeometry(0, 0, w, h)
            self.dialogue_overlay.raise_()
        if hasattr(self, "dialogue_indicator"):
            lamp = max(22, int(round(w * 0.105)))
            self.dialogue_indicator.setGeometry(max(0, w-lamp-5), 5, lamp, lamp)
            self.dialogue_indicator.raise_()

    def set_ability_states(self, states):
        if hasattr(self, "ability_aura"):
            self.ability_aura.set_states(states if isinstance(states, dict) else {})
            # Speech/report layers must remain above the decorative aura.
            try:
                self.report_overlay.raise_()
                self.dialogue_overlay.raise_()
                self.dialogue_indicator.raise_()
            except Exception:
                pass

    def set_ability_form_requested(self, active):
        self._ability_form_requested = bool(active)
        self._refresh_ability_form_visibility()

    def _restart_ability_form_movie(self):
        movie = getattr(self, "_ability_form_movie", None)
        if movie is None or not getattr(self, "_ability_form_requested", False):
            return
        if not getattr(self, "ability_form_label", None) or not self.ability_form_label.isVisible():
            return
        QTimer.singleShot(16, movie.start)

    def _refresh_ability_form_visibility(self):
        label = getattr(self, "ability_form_label", None)
        if label is None:
            return
        show_form = bool(
            getattr(self, "_ability_form_requested", False)
            and self.current_state == "idle"
            and not self.report_active
            and not self.dialogue_board_active
            and not self.drag_visual_active
        )
        movie = getattr(self, "_ability_form_movie", None)
        if show_form:
            for lab in self.labels:
                lab.hide()
            try:
                if self.mouse_interaction_active:
                    self._exit_mouse_interaction(resume_idle=False)
                self.mouse_layer.hide()
            except Exception:
                pass
            label.show(); label.raise_()
            if movie is not None and movie.isValid():
                movie.start()
            try:
                self.ability_aura.raise_()
                self.report_overlay.raise_(); self.dialogue_overlay.raise_(); self.dialogue_indicator.raise_()
            except Exception:
                pass
        else:
            if movie is not None:
                movie.stop()
                try: movie.jumpToFrame(0)
                except Exception: pass
            label.hide()
            for lab in self.labels:
                lab.show()
            if getattr(self, "mouse_interaction_active", False):
                try:
                    self.mouse_layer.show(); self.mouse_layer.raise_()
                except Exception:
                    pass

    def enterEvent(self, event):
        self.ability_hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.ability_hover_left.emit()
        super().leaveEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.ability_geometry_changed.emit()

    def ensure_on_screen(self):
        try:
            screen = QApplication.primaryScreen()
            if not screen:
                return
            area = screen.availableGeometry()
            if not area.intersects(self.frameGeometry()):
                margin = 40
                x = max(area.left() + margin, area.right() - self.width() - margin)
                y = max(area.top() + margin, area.bottom() - self.height() - margin)
                self.move(x, y)
                self.cfg["x"], self.cfg["y"] = x, y
                save_config(self.cfg)
        except Exception:
            LOGGER.exception("检查桌宠位置失败")

    def _state_pool(self, state):
        pool = _asset_list(self.cfg.get("assets", {}).get(state))
        pool = [p for p in pool if Path(p).exists()]
        if not pool:
            pool = _asset_list(bundled_assets().get(state))
        return pool[:MAX_ASSETS_PER_STATE]

    def _pick_asset(self, state):
        pool = self._state_pool(state)
        if not pool:
            return None
        # V0.4.8 retains independent random draw WITH replacement.  Do not exclude the
        # previously played clip. This intentionally allows sequences such as
        # 1→1→2, 2→2→1, 3→3→2, etc. Every clip gets the same probability on
        # every draw, including the clip that just finished.
        path = ASSET_RNG.choice(pool)
        self.last_asset_by_state[state] = path
        return path

    def set_asset(self, label_idx, path, state):
        movie = QMovie(path)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        movie.setScaledSize(self.size())
        if not movie.isValid():
            raise RuntimeError(f"动画素材无效: {path}")
        self.movie_generation += 1
        token = self.movie_generation
        # Imported WebP clips are finite. When one finishes, choose another clip
        # from the same state pool. Stale movies are ignored via generation token.
        movie.finished.connect(lambda tok=token, st=state: self._movie_finished(tok, st))
        self.movies[label_idx] = movie
        self.labels[label_idx].setMovie(movie)
        self.current_asset_path = path
        if state == "report" and hasattr(self, "report_overlay"):
            self.report_overlay.set_asset(path)
        movie.start()

    def _movie_finished(self, token, state):
        if token != self.movie_generation or state != self.current_state:
            return
        if state == "dialogue":
            # The source clip is 15 seconds. Long answers restart the talking
            # loop. V0.8.8 never freezes the final frame; the clip stays animated
            # until TTS ends and the board is removed.
            if self.dialogue_board_active:
                movie = self.movies[self.current_slot]
                if movie is not None:
                    QTimer.singleShot(20, movie.start)
            return
        if state == "report":
            # The 10-second report lifetime is controlled by report_timer.
            return
        if len(self._state_pool(state)) <= 1:
            # Finite one-clip pool: replay the same clip without changing state.
            QTimer.singleShot(25, lambda st=state: self.play_state(st, force_new_clip=True, immediate=True))
        else:
            QTimer.singleShot(25, lambda st=state: self.play_state(st, force_new_clip=True))

    def _set_mouse_layer_visible(self, visible, fade_ms=180):
        if self._mouse_transition_group:
            try: self._mouse_transition_group.stop()
            except Exception: pass
        fade_ms = max(0, int(fade_ms))
        if visible:
            self.mouse_layer.show(); self.mouse_layer.raise_()
            self.report_overlay.raise_()
            self.mouse_effect.setOpacity(0.0 if fade_ms else 1.0)
            if fade_ms <= 0:
                self.effects[self.current_slot].setOpacity(0.0)
                return
            old = self.current_slot
            a1 = QPropertyAnimation(self.effects[old], b"opacity")
            a1.setDuration(fade_ms); a1.setStartValue(self.effects[old].opacity()); a1.setEndValue(0.0)
            a2 = QPropertyAnimation(self.mouse_effect, b"opacity")
            a2.setDuration(fade_ms); a2.setStartValue(self.mouse_effect.opacity()); a2.setEndValue(1.0)
            grp = QParallelAnimationGroup(self); grp.addAnimation(a1); grp.addAnimation(a2)
            def done():
                if self.movies[old]: self.movies[old].stop()
            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()
        else:
            self.mouse_effect.setOpacity(0.0)
            self.mouse_layer.hide()

    def _enter_mouse_interaction(self):
        if self.mouse_interaction_active or self.current_state != "idle" or self.report_active or self.dialogue_board_active:
            return
        if not bool(self.cfg.get("mouse_interaction", {}).get("enabled", True)):
            return
        self.mouse_interaction_active = True
        self.mouse_layer.reset_pose()
        self._set_mouse_layer_visible(True, 180)
        LOGGER.info("鼠标互动进入：注意力区域触发")

    def _exit_mouse_interaction(self, resume_idle=True):
        if not self.mouse_interaction_active:
            return
        self.mouse_interaction_active = False
        self._mouse_inside_since = None
        self._mouse_outside_since = None
        self.mouse_layer.set_target(0.0, 0.0)
        if not resume_idle:
            self._set_mouse_layer_visible(False, 0)
            return
        # Prepare a fresh random idle clip behind the interaction layer, then cross-fade.
        path = self._pick_asset("idle")
        if not path:
            self._set_mouse_layer_visible(False, 0); return
        try:
            new = 1 - self.current_slot
            self.set_asset(new, path, "idle")
            self.effects[new].setOpacity(0.0)
            self.labels[new].show()
            if self._mouse_transition_group:
                try: self._mouse_transition_group.stop()
                except Exception: pass
            a1 = QPropertyAnimation(self.mouse_effect, b"opacity")
            a1.setDuration(180); a1.setStartValue(self.mouse_effect.opacity()); a1.setEndValue(0.0)
            a2 = QPropertyAnimation(self.effects[new], b"opacity")
            a2.setDuration(180); a2.setStartValue(0.0); a2.setEndValue(1.0)
            grp = QParallelAnimationGroup(self); grp.addAnimation(a1); grp.addAnimation(a2)
            def done():
                self.mouse_layer.hide(); self.current_slot = new
                self.effects[1-new].setOpacity(0.0)
            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()
            self.current_state = "idle"
            self.cfg["last_state"] = "idle"
            save_config(self.cfg)
            LOGGER.info("鼠标互动退出：恢复随机待机素材")
        except Exception:
            LOGGER.exception("鼠标互动退出失败")
            self._set_mouse_layer_visible(False, 0)

    def refresh_mouse_interaction_config(self):
        interval = max(20, min(80, int(self.cfg.get("mouse_interaction", {}).get("poll_interval_ms", 33))))
        if hasattr(self, "mouse_interaction_timer"):
            self.mouse_interaction_timer.setInterval(interval)
        if not bool(self.cfg.get("mouse_interaction", {}).get("enabled", True)) and self.mouse_interaction_active:
            self._exit_mouse_interaction(resume_idle=True)

    def poll_mouse_interaction(self):
        try:
            micfg = self.cfg.get("mouse_interaction", {})
            if getattr(self, "_ability_form_requested", False):
                if self.mouse_interaction_active:
                    self._exit_mouse_interaction(resume_idle=False)
                return
            if not bool(micfg.get("enabled", True)) or not self.isVisible():
                if self.mouse_interaction_active: self._exit_mouse_interaction(resume_idle=True)
                return
            if self.drag_offset is not None or self.drag_visual_active:
                if self.mouse_interaction_active:
                    self._exit_mouse_interaction(resume_idle=False)
                return
            if self.report_active or self.current_state != "idle":
                if self.mouse_interaction_active: self._exit_mouse_interaction(resume_idle=False)
                return
            now = time.monotonic()
            pos = QCursor.pos()
            if self._mouse_last_pos is None:
                self._mouse_last_pos = pos
            moved = (pos - self._mouse_last_pos).manhattanLength() >= 2
            if moved:
                self._mouse_last_move_time = now
                self._mouse_last_pos = pos

            fg = self.frameGeometry(); c = fg.center()
            dx = float(pos.x() - c.x()); dy = float(pos.y() - c.y())
            # Elliptical normalized distance: 1.0 is roughly one pet-width/height from center.
            ux = dx / max(1.0, self.width() * 0.55)
            uy = dy / max(1.0, self.height() * 0.55)
            dist = (ux*ux + uy*uy) ** 0.5
            outer = max(1.15, min(2.8, float(micfg.get("attention_radius", 1.75))))
            inner = max(0.65, min(outer-0.05, float(micfg.get("interaction_radius", 1.10))))
            inside_outer = dist <= outer
            inside_inner = dist <= inner

            if not self.mouse_interaction_active:
                if inside_outer and moved:
                    if self._mouse_inside_since is None: self._mouse_inside_since = now
                    need = int(micfg.get("inner_enter_delay_ms" if inside_inner else "enter_delay_ms", 120 if inside_inner else 320)) / 1000.0
                    if now - self._mouse_inside_since >= need:
                        self._enter_mouse_interaction()
                elif not inside_outer:
                    self._mouse_inside_since = None
            else:
                # Track continuously. Eye/head motion is continuous, not discrete animation switching.
                tx = max(-1.0, min(1.0, ux / max(inner, 1e-6)))
                ty = max(-1.0, min(1.0, uy / max(inner, 1e-6)))
                self.mouse_layer.set_target(tx, ty)
                self.mouse_layer.step(now)

                if inside_outer:
                    self._mouse_outside_since = None
                else:
                    if self._mouse_outside_since is None: self._mouse_outside_since = now
                    if now - self._mouse_outside_since >= int(micfg.get("exit_delay_ms", 700))/1000.0:
                        self._exit_mouse_interaction(resume_idle=True); return

                idle_timeout = max(2000, int(micfg.get("idle_timeout_ms", 10000))) / 1000.0
                if now - self._mouse_last_move_time >= idle_timeout:
                    self._exit_mouse_interaction(resume_idle=True); return
        except Exception:
            LOGGER.exception("鼠标互动轮询失败")

    def play_state(self, state, immediate=False, force_new_clip=False, asset_override=None):
        if self.dialogue_board_active:
            if state in STATE_NAMES:
                self._dialogue_pending_state = state
            return
        if self.drag_visual_active:
            if state != "idle":
                self._cancel_drag_interaction()
                immediate = True
            elif not force_new_clip and not immediate:
                return
        if state not in STATE_NAMES:
            return
        if self.report_active and state != "report":
            return
        if self.mouse_interaction_active:
            if state == "idle" and not force_new_clip and not immediate:
                return
            if state != "idle":
                # Game reactions/report always outrank mouse interaction.
                self._exit_mouse_interaction(resume_idle=False)
                immediate = True
        if state == self.current_state and not immediate and not force_new_clip:
            return
        path = str(asset_override) if asset_override and Path(str(asset_override)).exists() else self._pick_asset(state)
        if not path:
            LOGGER.error("状态素材池为空: %s", state)
            return
        try:
            next_slot = self.current_slot if immediate and self.current_state is None else 1 - self.current_slot
            self.set_asset(next_slot, path, state)
            if immediate or self.current_state is None:
                self.effects[next_slot].setOpacity(1.0)
                self.effects[1 - next_slot].setOpacity(0.0)
                old = 1 - next_slot
                if self.movies[old]:
                    self.movies[old].stop()
                self.current_slot = next_slot
            else:
                if self.anim_group:
                    self.anim_group.stop()
                old, new = self.current_slot, next_slot
                a1 = QPropertyAnimation(self.effects[old], b"opacity")
                a1.setDuration(int(self.cfg.get("transition_ms", 220)))
                a1.setStartValue(self.effects[old].opacity())
                a1.setEndValue(0.0)
                a1.setEasingCurve(QEasingCurve.Type.InOutQuad)
                a2 = QPropertyAnimation(self.effects[new], b"opacity")
                a2.setDuration(int(self.cfg.get("transition_ms", 220)))
                a2.setStartValue(self.effects[new].opacity())
                a2.setEndValue(1.0)
                a2.setEasingCurve(QEasingCurve.Type.InOutQuad)
                grp = QParallelAnimationGroup(self)
                grp.addAnimation(a1); grp.addAnimation(a2)
                def done():
                    if self.movies[old]:
                        self.movies[old].stop()
                    self.current_slot = new
                grp.finished.connect(done)
                self.anim_group = grp
                grp.start()
            self.current_state = state
            self.cfg["last_state"] = state
            save_config(self.cfg)
            self._refresh_ability_form_visibility()
            LOGGER.info("切换状态 -> %s | 素材=%s", STATE_NAMES[state], Path(path).name)
        except Exception:
            LOGGER.exception("播放状态失败: %s", state)

    def show_report(self, data):
        try:
            if self.dialogue_board_active:
                self._dialogue_pending_report = dict(data or {})
                return
            kills = int(data.get("kills", 0))
            evaluation = str(data.get("evaluation") or report_evaluation(kills))
            if self.mouse_interaction_active:
                self._exit_mouse_interaction(resume_idle=False)
            self.report_active = True
            self.play_state("report", force_new_clip=True)
            self.report_overlay.set_asset(self.current_asset_path)
            self.report_overlay.set_report(kills, evaluation)
            self.report_overlay.raise_()
            duration = max(3000, int(self.cfg.get("report_duration_ms", 10000)))
            self.report_timer.start(duration)
            LOGGER.info("显示整局战报 | nickname=%s agent=%s kills=%s eval=%s", data.get("nickname"), data.get("agent"), kills, evaluation)
        except Exception:
            LOGGER.exception("显示整局战报失败")

    def _end_report(self):
        self.report_active = False
        self.report_overlay.clear_report()
        if not self.dialogue_board_active:
            self.play_state("idle", force_new_clip=True, immediate=True)

    def _prepare_dialogue_asset_async(self):
        target = CACHE_DIR / "whiteboard_template_v080_1.webp"
        if target.exists() and target.stat().st_size > 10_000:
            self.dialogue_asset_ready.emit(str(target)); return
        source = Path(resource("assets/whiteboard_template_v080.mp4"))
        if not source.exists():
            LOGGER.error("V0.8.8 通用白板素材缺失: %s", source); return
        def job():
            try:
                convert_greenscreen_video(str(source), target, max_width=420, target_fps=12)
                self.dialogue_asset_ready.emit(str(target))
                LOGGER.info("通用对白白板已准备: %s", target)
            except Exception:
                LOGGER.exception("准备通用对白白板失败")
        threading.Thread(target=job, name="XiaoMeiliWhiteboardPrepare", daemon=True).start()

    def _on_dialogue_asset_ready(self, path):
        self.dialogue_asset_path = str(path or "")

    def set_dialogue_indicator(self, active):
        enabled = bool(self.cfg.get("speech", {}).get("indicator_enabled", True))
        self.dialogue_indicator.set_active(bool(active) and enabled)
        if active and enabled:
            self.dialogue_indicator.raise_()

    def _show_dialogue_asset(self):
        path = str(self.dialogue_asset_path or "")
        if not path or not Path(path).exists():
            self._prepare_dialogue_asset_async()
            return False
        if self.mouse_interaction_active:
            self._exit_mouse_interaction(resume_idle=False)
        if self.drag_visual_active:
            self._cancel_drag_interaction()
        if self.report_active:
            self.report_active = False
            self.report_timer.stop()
            self.report_overlay.clear_report()
        previous = self.current_state if self.current_state in STATE_NAMES and self.current_state != "report" else "idle"
        self._dialogue_return_state = previous
        new = 1 - self.current_slot
        self.set_asset(new, path, "dialogue")
        self.effects[new].setOpacity(1.0); self.effects[self.current_slot].setOpacity(0.0)
        old = self.current_slot
        if self.movies[old]: self.movies[old].stop()
        self.current_slot = new; self.current_state = "dialogue"
        self._refresh_ability_form_visibility()
        return True

    def start_dialogue_board(self, text, duration_ms):
        self.dialogue_visual_generation += 1
        self.dialogue_board_active = True
        if not self._show_dialogue_asset():
            # Keep the session alive even if first-run chroma conversion is still
            # finishing. The next utterance will pick up the prepared asset.
            self.dialogue_board_active = False
            return False
        self.dialogue_overlay.set_dialogue(str(text or ""), max(180, int(duration_ms or 1)))
        self.dialogue_overlay.raise_(); self.dialogue_indicator.raise_()
        return True

    def finish_dialogue_board(self, hold_ms=None):
        if not self.dialogue_board_active:
            return
        # V0.8.8: the supplied board clip is a talking animation. Never pause it
        # on the last frame. Keep motion alive until the board is removed.
        self.dialogue_overlay.complete()
        self.dialogue_visual_generation += 1
        generation = self.dialogue_visual_generation
        if hold_ms is None:
            hold_ms = int(self.cfg.get("whiteboard", {}).get("hold_ms", 3000))
        QTimer.singleShot(max(300, int(hold_ms)), lambda g=generation: self._end_dialogue_board(g))

    def _end_dialogue_board(self, generation=None):
        if generation is not None and int(generation) != int(self.dialogue_visual_generation):
            return
        if not self.dialogue_board_active:
            return
        self.dialogue_board_active = False
        self.dialogue_overlay.clear_dialogue()
        pending_report = self._dialogue_pending_report; self._dialogue_pending_report = None
        pending = self._dialogue_pending_state; self._dialogue_pending_state = None
        self.current_state = None
        if pending_report:
            self.show_report(pending_report)
        else:
            state = pending if pending in STATE_NAMES else self._dialogue_return_state
            if state not in STATE_NAMES or state == "report": state = "idle"
            self.play_state(state, force_new_clip=True, immediate=True)
        self.dialogue_indicator.raise_()

    def preview_dialogue(self, text, duration_ms=2600):
        self.set_dialogue_indicator(True)
        if self.start_dialogue_board(text, duration_ms):
            QTimer.singleShot(max(200, int(duration_ms)), lambda: self.finish_dialogue_board())
            total = max(200, int(duration_ms)) + int(self.cfg.get("whiteboard", {}).get("hold_ms", 3000)) + 80
            QTimer.singleShot(total, lambda: self.set_dialogue_indicator(False))

    def _cursor_hits_pet_shape(self, global_pos):
        if not self.isVisible() or not self.frameGeometry().contains(global_pos):
            return False
        if self._hit_image.isNull():
            return True
        local = global_pos - self.frameGeometry().topLeft()
        ix = int(local.x() * self._hit_image.width() / max(1, self.width()))
        iy = int(local.y() * self._hit_image.height() / max(1, self.height()))
        ix = max(0, min(self._hit_image.width() - 1, ix))
        iy = max(0, min(self._hit_image.height() - 1, iy))
        return self._hit_image.pixelColor(ix, iy).alpha() > 18

    def _position_lock_bubble(self):
        try:
            self.lock_bubble.hide()
        except Exception:
            pass

    def poll_hover_lock_button(self):
        # While locked, the pet is a true WS_EX_TRANSPARENT + NOACTIVATE window,
        # so Qt cannot receive a right click. Poll the physical right button at
        # low frequency and unlock only when its DOWN edge happens over the
        # visible pet silhouette.
        try:
            if self.lock_bubble.isVisible():
                self.lock_bubble.hide()
        except Exception:
            pass

        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            self._v0778_unlock_pending = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down

            if down and not was_down:
                pos = QCursor.pos()
                self._v0778_unlock_pending = bool(self._cursor_hits_pet_shape(pos))
                if self._v0778_unlock_pending:
                    LOGGER.info("锁定状态检测到小美丽区域右键：等待释放后显示解锁菜单")

            if (not down) and was_down and bool(getattr(self, "_v0778_unlock_pending", False)):
                self._v0778_unlock_pending = False
                menu_pos = QCursor.pos()
                LOGGER.info("锁定状态右键已释放：显示解锁菜单")
                QTimer.singleShot(0, lambda p=menu_pos: self._show_locked_context_menu(p))
        except Exception:
            self._v0778_unlock_pending = False
            LOGGER.warning("锁定状态右键菜单检测失败", exc_info=True)

    def _show_locked_context_menu(self, global_pos=None):
        if not bool(self.cfg.get("lock_position", False)):
            return
        pos = global_pos if global_pos is not None else QCursor.pos()
        menu = QMenu()
        unlock_action = menu.addAction("解锁小美丽（游戏防误触）")
        chosen = menu.exec(pos)
        if chosen == unlock_action:
            self.set_interaction_lock(False)

    def set_interaction_lock(self, locked):
        locked = bool(locked)
        self.cfg["lock_position"] = locked
        self.cfg["click_through"] = locked
        self.cfg["opacity"] = 100
        if locked:
            self.drag_offset = None
            self.drag_press_global = None
            self.drag_last_global = None
            try:
                self.releaseMouse()
            except Exception:
                pass
            try:
                if self.drag_visual_active:
                    self._cancel_drag_interaction()
            except Exception:
                pass
        save_config(self.cfg)
        self.apply_clickthrough_native()
        try:
            self.lock_bubble.hide()
        except Exception:
            pass
        self.config_changed.emit()

    def toggle_interaction_lock(self):
        self.set_interaction_lock(not bool(self.cfg.get("lock_position", False)))

    def toggle_show_hide(self):
        if self.isVisible():
            self.lock_bubble.hide(); self.hide()
        else:
            self.show(); self.raise_(); self.activateWindow()

    def _begin_drag_interaction(self):
        # While the ability sidebar is open, dragging moves the whole pet/sidebar
        # group but never replaces the unique ability-form animation.
        if getattr(self, "_ability_form_requested", False):
            return
        if self.drag_visual_active:
            self.drag_layer.start_drag()
            return
        if self.report_active or self.current_state != "idle":
            return
        if self.mouse_interaction_active:
            self._exit_mouse_interaction(resume_idle=False)
        self.drag_visual_active = True
        self._refresh_ability_form_visibility()
        for lab in self.labels:
            lab.hide()
        self.mouse_layer.hide()
        self.drag_layer.setGeometry(0, 0, self.width(), self.height())
        self.drag_layer.start_drag()
        self.drag_layer.raise_()
        self.report_overlay.raise_()
        LOGGER.info("拖拽互动进入：分层悬挂姿态")

    def _feed_drag_interaction(self, dx, dy):
        if self.drag_visual_active:
            self.drag_layer.feed_motion(dx, dy)
            if self.drag_offset is not None:
                self.drag_layer.set_cursor_focus(
                    self.drag_offset.x(), self.drag_offset.y(),
                    self.width(), self.height(),
                )

    def _end_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_layer.begin_recover()
        LOGGER.info("拖拽互动松手：开始回弹")

    def _finish_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_visual_active = False
        self.drag_layer.hide()
        if not self.report_active and self.current_state == "idle":
            for lab in self.labels:
                lab.show()
            self.play_state("idle", force_new_clip=True, immediate=True)
        self._refresh_ability_form_visibility()
        LOGGER.info("拖拽互动结束：恢复待机")

    def _cancel_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_visual_active = False
        self.drag_layer.cancel()
        for lab in self.labels:
            lab.show()
        self._refresh_ability_form_visibility()
        LOGGER.info("拖拽互动被更高优先级状态打断")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.cfg.get("lock_position", False) and not self.cfg.get("click_through", False):
            gp = event.globalPosition().toPoint()
            self.drag_offset = gp - self.frameGeometry().topLeft()
            self.drag_press_global = gp
            self.drag_last_global = gp

            # Kill the normal V2 cross-fade immediately. In V0.7.7 that timer could race the
            # first drag and make the first press feel "dead".
            if self.mouse_interaction_active:
                self._exit_mouse_interaction(resume_idle=False)
            try:
                self.grabMouse()
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            gp = event.globalPosition().toPoint()

            # Always move on the FIRST physical drag. Visual switching no longer gates movement.
            self.move(gp - self.drag_offset)

            delta = gp - self.drag_last_global if self.drag_last_global is not None else QPoint(0, 0)
            if (not self.drag_visual_active and self.drag_press_global is not None
                    and bool(self.cfg.get("drag_interaction", {}).get("enabled", True))):
                threshold = max(2, min(6, int(self.cfg.get("drag_interaction", {}).get("threshold_px", 4))))
                if (gp - self.drag_press_global).manhattanLength() >= threshold:
                    self._begin_drag_interaction()

            if self.drag_visual_active:
                self._feed_drag_interaction(delta.x(), delta.y())

            self.drag_last_global = gp
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            was_dragging = self.drag_visual_active
            self.drag_offset = None
            self.drag_press_global = None
            self.drag_last_global = None
            try:
                self.releaseMouse()
            except Exception:
                pass

            self.cfg["x"], self.cfg["y"] = self.x(), self.y()
            save_config(self.cfg)

            if was_dragging:
                self._end_drag_interaction()
            elif not self.report_active and self.current_state == "idle":
                # A click without enough movement must not leave V2 hidden.
                for lab in self.labels:
                    lab.show()
                self._refresh_ability_form_visibility()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        if locked:
            # Normally unreachable because the pet itself is transparent.
            # Keep this fallback state-correct if Windows delivers it anyway.
            self._show_locked_context_menu(event.globalPos())
            event.accept()
            return

        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        ability_action = menu.addAction("美丽能力")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == ability_action:
            self.request_abilities.emit()
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

    def mouseDoubleClickEvent(self, event):
        if bool(self.cfg.get("lock_position", False) or self.cfg.get("click_through", False)):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.request_settings.emit()



# ------------------------------
# VALORANT screen-only recognition
# ------------------------------

def _find_valorant_client_rect():
    """Return screen-space client rect (x, y, w, h) for the largest visible VALORANT window."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    candidates = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    @WNDENUMPROC
    def enum_proc(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if "VALORANT" not in title.upper():
                return True
            rc = RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
                return True
            p = POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(p)):
                return True
            w, h = rc.right - rc.left, rc.bottom - rc.top
            if w >= 800 and h >= 450:
                candidates.append((w * h, p.x, p.y, w, h, title))
        except Exception:
            pass
        return True

    user32.EnumWindows(enum_proc, 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, x, y, w, h, title = candidates[0]
    return (x, y, w, h, title)


def _trim_and_normalize_game(frame):
    """Trim obvious black bars and center-crop to a 16:9 gameplay viewport."""
    if frame is None or frame.size == 0:
        return frame
    img = frame
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Trim only very obvious near-black pillar/letterbox bars. Limit to 12% per side.
    def left_cut():
        lim = int(w * 0.12)
        for x in range(lim):
            col = gray[:, x]
            if np.percentile(col, 90) > 20:
                return max(0, x - 1)
        return 0
    def right_cut():
        lim = int(w * 0.12)
        for d in range(lim):
            col = gray[:, w - 1 - d]
            if np.percentile(col, 90) > 20:
                return max(0, d - 1)
        return 0
    lc, rc = left_cut(), right_cut()
    if lc > 4 or rc > 4:
        img = img[:, lc:w - rc if rc else w]

    h, w = img.shape[:2]
    target = 16 / 9
    ar = w / max(1, h)
    if ar > target + 0.02:
        nw = int(h * target)
        x = max(0, (w - nw) // 2)
        img = img[:, x:x + nw]
    elif ar < target - 0.02:
        nh = int(w / target)
        y = max(0, (h - nh) // 2)
        img = img[y:y + nh, :]
    return img


def _match_multiscale(gray, templ, scales):
    best_score, best_loc, best_size = -1.0, (0, 0), (0, 0)
    for s in scales:
        tw = max(8, int(round(templ.shape[1] * s)))
        th = max(8, int(round(templ.shape[0] * s)))
        if gray.shape[1] < tw or gray.shape[0] < th:
            continue
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
        t = cv2.resize(templ, (tw, th), interpolation=interp)
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best_score:
            best_score, best_loc, best_size = float(score), loc, (tw, th)
    return best_score, best_loc, best_size


def _roi(frame, box):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    return frame[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


def _scan_gray_template(frame, templ, box, scales):
    r = _roi(frame, box)
    if r.size == 0:
        return 0.0
    gray = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    return _match_multiscale(gray, templ, scales)[0]


def _scan_binary_template(frame, templ, box, scales, white_threshold=220):
    r = _roi(frame, box)
    if r.size == 0:
        return 0.0
    gray = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    bw = (gray > white_threshold).astype(np.uint8) * 255
    return _match_multiscale(bw, templ, scales)[0]


def _template_detection_count(frame, templ, box, threshold):
    """Count distinct own-kill rows in the killfeed using NMS over multiple scales."""
    r = _roi(frame, box)
    if r.size == 0:
        return 0, 0.0
    gray = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    detections = []
    best_score = 0.0
    for s in np.linspace(0.70, 1.40, 15):
        tw = max(12, int(round(templ.shape[1] * s)))
        th = max(8, int(round(templ.shape[0] * s)))
        if gray.shape[1] < tw or gray.shape[0] < th:
            continue
        t = cv2.resize(templ, (tw, th), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        best_score = max(best_score, float(res.max()))
        ys, xs = np.where(res >= threshold)
        # cap candidates per scale
        if len(xs) > 50:
            vals = res[ys, xs]
            idx = np.argsort(vals)[-50:]
            xs, ys = xs[idx], ys[idx]
        for x, y in zip(xs, ys):
            detections.append((int(x), int(y), tw, th, float(res[y, x])))
    detections.sort(key=lambda d: d[4], reverse=True)
    kept = []
    for d in detections:
        x, y, w, h, score = d
        cx, cy = x + w / 2, y + h / 2
        duplicate = False
        for k in kept:
            kx, ky, kw, kh, _ = k
            kcx, kcy = kx + kw / 2, ky + kh / 2
            if abs(cx - kcx) < min(w, kw) * 0.55 and abs(cy - kcy) < min(h, kh) * 0.65:
                duplicate = True
                break
        if not duplicate:
            kept.append(d)
    return min(5, len(kept)), best_score


class DigitReader:
    def __init__(self, npz_path):
        data = np.load(npz_path)
        self.bank = {str(i): data[f"d{i}"] for i in range(10)}

    @staticmethod
    def _normalize(mask, target=(32, 48)):
        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            return np.zeros((target[1], target[0]), np.uint8)
        crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        tw, th = target
        scale = min((tw - 4) / max(1, crop.shape[1]), (th - 4) / max(1, crop.shape[0]))
        nw = max(1, int(round(crop.shape[1] * scale)))
        nh = max(1, int(round(crop.shape[0] * scale)))
        rs = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_NEAREST)
        out = np.zeros((th, tw), np.uint8)
        x, y = (tw - nw) // 2, (th - nh) // 2
        out[y:y + nh, x:x + nw] = rs
        return out

    @staticmethod
    def _score(glyph, templates):
        g = (glyph > 0).astype(np.float32)
        gf = g.ravel()
        scores = []
        for t in templates:
            b = (t > 0).astype(np.float32)
            inter = float((g * b).sum())
            union = float(((g + b) > 0).sum())
            iou = inter / union if union else 0.0
            bf = b.ravel()
            gs, bs = gf.std(), bf.std()
            corr = 0.0 if gs < 1e-6 or bs < 1e-6 else float(np.corrcoef(gf, bf)[0, 1])
            scores.append(0.55 * iou + 0.45 * corr)
        return max(scores) if scores else 0.0

    def read_hp_roi(self, r):
        if r is None or r.size == 0:
            return None, 0.0
        gray = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        comps = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            density = area / max(1, w * h)
            if h >= r.shape[0] * 0.28 and area >= 50 and w >= 3 and density >= 0.16:
                comps.append((x, y, w, h, area))
        comps.sort(key=lambda c: c[0])
        # Keep plausible digit groups only and discard low-density HUD lines.
        if len(comps) > 3:
            comps = sorted(comps, key=lambda c: c[4], reverse=True)[:3]
            comps.sort(key=lambda c: c[0])
        if not (1 <= len(comps) <= 3):
            return None, 0.0

        digits, confidences = [], []
        for x, y, w, h, area in comps:
            glyph = self._normalize(bw[y:y + h, x:x + w])
            ranked = []
            for d, templates in self.bank.items():
                ranked.append((self._score(glyph, templates), d))
            ranked.sort(reverse=True)
            best, second = ranked[0], ranked[1]
            # Confidence combines shape fit and separation from runner-up.
            conf = max(0.0, min(1.0, best[0] * 0.85 + max(0.0, best[0] - second[0]) * 0.6))
            digits.append(best[1]); confidences.append(conf)
        try:
            value = int("".join(digits))
        except Exception:
            return None, 0.0
        conf = min(confidences) if confidences else 0.0
        if value < 0 or value > 100 or conf < 0.44:
            return None, conf
        return value, conf


    def read_hp(self, frame):
        # Compatibility path for offline validation/debug frames.
        r = _roi(frame, ROI_HP)
        return self.read_hp_roi(r)


ROI_CONTEXT_LEFT = (0.190, 0.018, 0.230, 0.082)
ROI_CONTEXT_CENTER = (0.450, 0.005, 0.550, 0.120)
ROI_CONTEXT_RIGHT = (0.770, 0.018, 0.810, 0.082)
ROI_ALIVE = (0.145, 0.00, 0.505, 0.145)
ROI_HP = (0.303, 0.915, 0.347, 0.970)
# V0.9.0 round-highlight tracker ROIs (normalized viewport coordinates)
ROI_ENEMY_TEAM = (0.588, 0.006, 0.785, 0.082)
V090_ENEMY_CENTERS = (0.615, 0.648, 0.681, 0.714, 0.747)

ROI_KILL_PROBE = (0.70, 0.02, 1.00, 0.20)
ROI_KILL_OCR = (0.60, 0.02, 1.00, 0.23)
ROI_RESULT = (0.35, 0.08, 0.65, 0.35)
ROI_DEATH_REPORT = (0.775, 0.300, 0.995, 0.735)
# Whole-match result screen: five player cards + red Continue button.
# Low-resolution radar crop. Keep it small and cheap; it is never OCR'd.
ROI_REPORT_CARDS_RADAR = (0.020, 0.500, 0.960, 0.770)
# High-resolution parse crop calibrated to the 2026-09-27 five-card layout.
# X now keeps the complete first/fifth cards; Y still includes nickname, ACS and K/D/A.
ROI_REPORT_CARDS = (0.020, 0.500, 0.960, 0.820)
ROI_REPORT_CONTINUE = (0.405, 0.900, 0.595, 0.990)


def _find_valorant_window():
    """Return (hwnd, x, y, w, h, title) for the largest visible VALORANT client window."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    candidates = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    @WNDENUMPROC
    def enum_proc(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if "VALORANT" not in title.upper():
                return True
            rc = RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
                return True
            pt = POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                return True
            w, h = rc.right - rc.left, rc.bottom - rc.top
            if w >= 800 and h >= 450:
                candidates.append((w * h, int(hwnd), pt.x, pt.y, w, h, title))
        except Exception:
            pass
        return True

    user32.EnumWindows(enum_proc, 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, hwnd, x, y, w, h, title = candidates[0]
    return hwnd, x, y, w, h, title


def _client_rect_for_hwnd(hwnd):
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rc = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
            return None
        pt = POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w < 800 or h < 450:
            return None
        return pt.x, pt.y, w, h
    except Exception:
        return None


def _viewport_from_client(client_rect):
    """Map a possibly letterboxed/pillarboxed client area to its centered 16:9 game viewport."""
    x, y, w, h = client_rect
    target = 16.0 / 9.0
    ar = w / max(1.0, h)
    if ar > target + 0.005:
        vw = int(round(h * target))
        return x + (w - vw) // 2, y, vw, h
    if ar < target - 0.005:
        vh = int(round(w / target))
        return x, y + (h - vh) // 2, w, vh
    return x, y, w, h


class ScreenGrabber:
    """Small-region screen grabber. Prefer DXGI Desktop Duplication (dxcam) on Windows,
    and fall back to MSS. We never start a continuous capture thread; each request is a
    single tiny ROI grab, which keeps idle cost near zero.
    """
    def __init__(self, prefer_dxcam=True):
        self.backend = "mss"
        self.camera = None
        self.sct = None
        if sys.platform == "win32" and prefer_dxcam:
            try:
                import dxcam
                self.camera = dxcam.create(output_color="BGR")
                self.backend = "dxcam"
                LOGGER.info("截图后端：DXGI Desktop Duplication (dxcam)")
            except Exception:
                LOGGER.warning("dxcam 不可用，回退 MSS ROI 截图", exc_info=True)
                self.camera = None
        if self.camera is None:
            from mss import mss
            self.sct = mss()
            self.backend = "mss"
            LOGGER.info("截图后端：MSS ROI")

    def grab(self, left, top, width, height):
        width=max(2,int(width)); height=max(2,int(height))
        left=int(left); top=int(top)
        if self.camera is not None:
            frame=self.camera.grab(region=(left, top, left+width, top+height))
            if frame is not None:
                return np.asarray(frame, dtype=np.uint8)
        if self.sct is None:
            from mss import mss
            self.sct=mss(); self.backend="mss"
        shot=np.asarray(self.sct.grab({"left":left,"top":top,"width":width,"height":height}), dtype=np.uint8)
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def close(self):
        try:
            if self.camera is not None:
                self.camera.stop()
        except Exception:
            pass
        try:
            if self.sct is not None:
                self.sct.close()
        except Exception:
            pass


def _grab_relative_roi(grabber, viewport, box, target_size=None):
    vx, vy, vw, vh = viewport
    x1, y1, x2, y2 = box
    left = int(round(vx + vw * x1))
    top = int(round(vy + vh * y1))
    width = max(2, int(round(vw * (x2 - x1))))
    height = max(2, int(round(vh * (y2 - y1))))
    img = grabber.grab(left, top, width, height)
    if img is None or img.size == 0:
        return np.zeros((2,2,3), np.uint8)
    if target_size and (img.shape[1], img.shape[0]) != tuple(target_size):
        img = cv2.resize(img, tuple(target_size), interpolation=cv2.INTER_AREA)
    return img


def _killfeed_green_signature(img):
    """Cheap event probe: count green/cyan killfeed row bands without OCR."""
    if img is None or img.size == 0:
        return (0, ()), 0.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    mask = ((h >= 35) & (h <= 100) & (s >= 70) & (v >= 80)).astype(np.uint8)
    row_density = mask.mean(axis=1)
    active = row_density > 0.03
    centers = []
    start = None
    for i, val in enumerate(active):
        if val and start is None:
            start = i
        if (not val or i == len(active) - 1) and start is not None:
            end = i if not val else i + 1
            if end - start >= 2:
                centers.append(int(round((start + end) / 2 / max(1, len(active)) * 20)))
            start = None
    sig = (len(centers), tuple(centers))
    return sig, float(row_density.max()) if len(row_density) else 0.0


class VisionWorker(QThread):
    state_requested = Signal(str)
    report_ready = Signal(object)
    snapshot = Signal(object)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._stop_event = threading.Event()
        self._debug_event = threading.Event()

        # Preload only tiny templates. All matching is confined to HUD ROIs.
        alive = cv2.imread(resource("assets/vision/sage_alive.png"), cv2.IMREAD_GRAYSCALE)
        alive_alt = cv2.imread(resource("assets/vision/sage_alive_alt.png"), cv2.IMREAD_GRAYSCALE)
        kill = cv2.imread(resource("assets/vision/own_kill_segment.png"), cv2.IMREAD_GRAYSCALE)
        win = cv2.imread(resource("assets/vision/victory_mask.png"), cv2.IMREAD_GRAYSCALE)
        loss = cv2.imread(resource("assets/vision/defeat_mask.png"), cv2.IMREAD_GRAYSCALE)
        ctx = cv2.imread(resource("assets/vision/match_center_mask.png"), cv2.IMREAD_GRAYSCALE)
        base_alive = cv2.resize(alive, None, fx=0.80, fy=0.80, interpolation=cv2.INTER_AREA)
        self.alive_templates = [
            cv2.resize(base_alive, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            for s in (0.90, 1.00, 1.10)
        ]
        if alive_alt is not None:
            alt_base = cv2.resize(alive_alt, None, fx=0.79, fy=0.79, interpolation=cv2.INTER_AREA)
            self.alive_templates.extend([
                cv2.resize(alt_base, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                for s in (0.92, 1.00, 1.08)
            ])
        self.kill_portrait_t = cv2.resize(kill[:, :48], None, fx=0.80, fy=0.80, interpolation=cv2.INTER_AREA)
        self.win_t = cv2.resize(win, None, fx=0.80, fy=0.80, interpolation=cv2.INTER_NEAREST)
        self.loss_t = cv2.resize(loss, None, fx=0.825, fy=0.825, interpolation=cv2.INTER_NEAREST)
        self.context_center_t = (ctx > 0).astype(np.uint8)
        self.digit_reader = DigitReader(resource("assets/vision/hp_digit_templates.npz"))

        # High-level phase gate. No death/HP/kill decision is legal outside MATCH_CONTEXT.
        self.match_context = False
        self.context_hits = 0
        self.context_misses = 0
        self.context_left_score = 0.0
        self.context_center_score = 0.0
        self.context_right_score = 0.0
        self.context_votes = 0
        self.match_recent_until = 0.0
        self.phase = "OUT_OF_MATCH"
        # V0.9.0: single-round event memory for highlight CTA.
        self.round_self_kills = 0
        self.enemy_alive = 5
        self.enemy_alive_scores = [0.0] * 5
        self.enemy_alive_confident = False
        self.self_final_kill_candidate = False
        self.self_final_kill_confirmed = False
        self.highlight_triggered = False
        self.highlight_event_id = 0
        self.highlight_last_reason = "等待回合"
        self.highlight_candidate = False
        self.hl_round_finalized = False
        self.visible_own_kill_rows = 0
        self.next_enemy_alive = 0.0
        self.last_enemy_alive_scan = 0.0

        self.last_snapshot = {}
        self.alive_state = None
        self.ever_alive = False
        self.alive_hits = 0
        self.alive_misses = 0
        self.low_hits = 0
        self.low_state = False
        self.last_valid_hp = None
        self.last_hp_time = 0.0
        # V0.4.8: HP is decided by a rolling vote, not a single read.
        self.hp_history = []
        self.hp_enter_votes = 0
        self.hp_exit_votes = 0
        self.hp_occluded = False
        self.hp_guard_reason = "-"
        self.hp_last_confirmed = None
        self.win_latched = False
        self.loss_latched = False
        self.round_end = False
        self.current_display_state = "idle"
        self.transient_until = 0.0
        self.pending_result = None

        # Death is a two-stage decision: portrait disappears -> suspected -> evidence/fallback.
        self.death_suspect_since = None
        self.death_latched = False
        self.death_ocr_checked = False
        self.last_death_report_score = 0.0
        self.last_death_evidence = "-"

        self.hwnd = None
        self.window_title = ""
        self.last_window_lookup = 0.0
        self.background_since = None
        self.last_snapshot_emit = 0.0

        self.last_alive_score = 0.0
        self.last_hp = None
        self.last_hp_conf = 0.0
        self.last_kill_score = 0.0
        self.last_kill_count = 0
        self.last_nickname_match = "-"
        self.last_ocr_texts = []
        self.last_win_score = 0.0
        self.last_loss_score = 0.0
        self.last_kill_signature = (0, ())
        self.last_kill_probe_strength = 0.0
        self.last_kill_event_time = 0.0
        self.last_hp_probe = None
        self.last_hp_full_read = 0.0

        self.ocr_trigger_count = 0
        self.hp_read_count = 0
        self.next_context = self.next_alive = self.next_hp = self.next_kill = self.next_result = self.next_death = 0.0

        self.perf_wall = time.monotonic()
        self.perf_cpu = time.process_time()
        self.perf_scans = 0
        self.scan_fps = 0.0
        self.cpu_estimate = 0.0
        self.backend_name = "pending"
        self.timings = {k:0.0 for k in ("capture","context","alive","hp","kill","death","result","ocr")}
        self.worker_busy = False
        self.skipped_cycles = 0

        # Whole-match report scanner. It sleeps during live rounds and runs only
        # after a real match has been registered and the live HUD has disappeared.
        self.report_armed = False
        self.report_armed_since = 0.0
        self.report_last_live_seen = 0.0
        self.report_done = False
        self.report_candidate_hits = 0
        self.report_attempts = 0
        self.report_retry_after = 0.0
        self.next_report = 0.0
        self.session_sage_seen = False
        self.last_report_layout_score = 0.0
        self.last_report_nickname = "-"
        self.last_report_agent = "-"
        self.last_report_kills = None
        self.report_pending_kills = None
        self.report_kill_confirm_hits = 0
        # V0.4.9.9: post-match report uses two stages.  During the live match
        # report OCR is fully asleep.  Once the live HUD disappears we keep only
        # a low-frequency, layout-only sentinel alive.  A convincing result frame
        # is frozen immediately; a short burst scanner is used only if the first
        # frozen frame cannot be parsed cleanly.
        self.report_waiting_result = False
        self.report_wait_started = 0.0
        self.report_wait_samples = 0
        self.report_capture_active = False
        self.report_capture_started = 0.0
        self.report_capture_deadline = 0.0
        self.report_snapshot_locked = False
        self.report_snapshot_score = 0.0
        self.report_capture_samples = 0
        self.report_capture_best_score = 0.0
        self.report_capture_best_cards = None
        # V0.4.9.9: snapshot ownership is independent from OCR success. Once a
        # result page has been frozen, parsing can fail without throwing away the
        # user's only copy of that short-lived screen.
        self.report_snapshot_cards = None
        self.report_snapshot_full = None
        self.report_snapshot_locked_at = 0.0
        # V0.4.10.2: as soon as a genuine five-card result page appears, keep
        # the best native-resolution frame in memory immediately. Stability is
        # now only a confirmation step, not a prerequisite for owning the frame.
        self.report_best_candidate_cards = None
        self.report_best_candidate_full = None
        self.report_best_candidate_quality = 0.0
        self.report_best_candidate_at = 0.0
        self.report_best_candidate_counts = []
        self.report_candidate_signature = None
        self.report_candidate_stable_hits = 0
        self.report_last_signature_diff = 0.0
        self.report_parse_status = "等待结算页"
        self.report_parse_attempts = 0
        self.report_ocr_engine = None
        self.report_ocr_init_failed = False
        self.last_report_debug_dir = ""

    def stop(self):
        self._stop_event.set()

    def request_debug_frame(self):
        self._debug_event.set()

    def _ema_timing(self, key, ms):
        old=float(self.timings.get(key,0.0))
        self.timings[key] = ms if old <= 0 else old*0.82 + ms*0.18

    @staticmethod
    def _fixed_match(gray, templ):
        if gray is None or templ is None or gray.shape[0] < templ.shape[0] or gray.shape[1] < templ.shape[1]:
            return 0.0
        return float(cv2.minMaxLoc(cv2.matchTemplate(gray, templ, cv2.TM_CCOEFF_NORMED))[1])

    def _multi_match(self, gray, templates):
        best = 0.0
        for templ in templates:
            best = max(best, self._fixed_match(gray, templ))
        return best

    def _request_state(self, state, reason=""):
        if state not in STATE_NAMES:
            return
        if state != self.current_display_state:
            self.current_display_state = state
            LOGGER.info("视觉识别触发 -> %s | %s", STATE_NAMES[state], reason)
            self.state_requested.emit(state)

    def _persistent_state(self):
        if not self.match_context:
            return "idle"
        if self.round_end:
            return "idle"
        if self.death_latched:
            return "dead"
        if self.alive_state is True and self.low_state:
            return "low_hp"
        return "idle"

    def _reset_match_state(self, reason=""):
        self.alive_state = None
        self.ever_alive = False
        self.alive_hits = 0
        self.alive_misses = 0
        self.low_hits = 0
        self.low_state = False
        self.last_hp = None
        self.last_hp_conf = 0.0
        self.last_hp_probe = None
        self.hp_history = []
        self.hp_enter_votes = 0
        self.hp_exit_votes = 0
        self.hp_occluded = False
        self.hp_guard_reason = "-"
        self.hp_last_confirmed = None
        self.death_suspect_since = None
        self.death_latched = False
        self.death_ocr_checked = False
        self.last_death_report_score = 0.0
        self.last_death_evidence = "-"
        self.round_end = False
        self.phase = "OUT_OF_MATCH"
        self.pending_result = None
        if self.current_display_state not in ("victory", "defeat") or time.monotonic() >= self.transient_until:
            self.transient_until = 0.0
            self._request_state("idle", reason or "outside match")

    @staticmethod
    def _norm_name(text):
        text = str(text or "").strip().lower()
        return re.sub(r"[\s\-_.·•#丨|:：\[\]()（）{}<>《》]+", "", text)

    @staticmethod
    def _name_similarity(a, b):
        a = VisionWorker._norm_name(a); b = VisionWorker._norm_name(b)
        if not a or not b:
            return 0.0
        if a in b or b in a:
            return min(1.0, min(len(a), len(b)) / max(1, max(len(a), len(b))) + 0.35)
        return SequenceMatcher(None, a, b).ratio()

    def _get_report_ocr_engine(self):
        """Create RapidOCR once and reuse it inside the vision worker thread."""
        if self.report_ocr_engine is not None:
            return self.report_ocr_engine
        if self.report_ocr_init_failed:
            return None
        try:
            from rapidocr import RapidOCR
            self.report_ocr_engine = RapidOCR()
            LOGGER.info("RapidOCR 战报引擎初始化完成（复用模式）")
            return self.report_ocr_engine
        except Exception:
            self.report_ocr_init_failed = True
            LOGGER.exception("RapidOCR 战报引擎初始化失败")
            return None

    def _ocr_names_once(self, kill_roi, want="killer"):
        nickname = str(self.cfg.get("vision", {}).get("player_nickname", "")).strip()
        if not nickname or not bool(self.cfg.get("vision",{}).get("nickname_ocr_fallback", True)):
            return False, "未启用昵称二次校验"
        t0=time.perf_counter(); engine=self._get_report_ocr_engine()
        try:
            if engine is None:
                return False, "OCR引擎不可用"
            self.ocr_trigger_count += 1
            roi2 = cv2.resize(kill_roi, None, fx=1.15, fy=1.15, interpolation=cv2.INTER_LINEAR)
            result = engine(roi2)
            boxes = getattr(result, "boxes", None); txts = getattr(result, "txts", None); scores = getattr(result, "scores", None)
            if txts is None or boxes is None:
                self.last_ocr_texts=[]; return False, "未识别到文字"
            target=self._norm_name(nickname); debug=[]; rw=roi2.shape[1]
            hit=False
            for i, txt in enumerate(list(txts)):
                score=float(scores[i]) if scores is not None and i < len(scores) else 1.0
                if score < 0.42: continue
                box=np.array(boxes[i],dtype=np.float32); cx=float(box[:,0].mean())/max(1.0,rw)
                sim=self._name_similarity(target,txt); debug.append(f"{txt}@{cx:.2f}/{sim:.2f}")
                if sim < 0.66: continue
                if want == "killer" and cx < 0.66:
                    hit=True
                if want == "victim" and cx > 0.62:
                    hit=True
            self.last_ocr_texts=debug[:10]
            return hit, ("命中" if hit else "未命中")
        except Exception as e:
            LOGGER.exception("昵称 OCR 二次校验失败")
            return False, f"OCR错误:{type(e).__name__}"
        finally:
            self._ema_timing("ocr", (time.perf_counter()-t0)*1000)

    def _ocr_own_kill_once(self, kill_roi):
        hit, desc = self._ocr_names_once(kill_roi, "killer")
        return (1 if hit else 0), desc

    def _mode_intervals(self):
        mode=str(self.cfg.get("vision",{}).get("mode","ultra_low"))
        if mode == "debug":
            return 0.35, 0.45, 0.25, 0.18, 0.35, 0.22, 0.35
        # context, identity, HP hash, killfeed probe, result, death-confirm, UI emit
        return 0.65, 0.85, 0.34, 0.32, 0.80, 0.30, 0.75

    def _update_perf(self, now):
        dt=now-self.perf_wall
        if dt < 2.0: return
        cpu_now=time.process_time(); cpu_dt=max(0.0,cpu_now-self.perf_cpu); cores=max(1,os.cpu_count() or 1)
        self.cpu_estimate=max(0.0,min(100.0,cpu_dt/max(0.001,dt)/cores*100.0))
        self.scan_fps=self.perf_scans/max(0.001,dt); self.perf_scans=0
        self.perf_wall=now; self.perf_cpu=cpu_now

    @staticmethod
    def _context_icon_score(img, side):
        if img is None or img.size == 0:
            return 0.0
        hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV); h,s,v=cv2.split(hsv)
        if side == "left":
            mask=((h>=75)&(h<=105)&(s>=55)&(v>=90))
        else:
            mask=(((h<=10)|(h>=170))&(s>=70)&(v>=95))
        return float(mask.mean())

    def _context_center_similarity(self, img):
        if img is None or img.size == 0:
            return 0.0
        img=cv2.resize(img,(205,132),interpolation=cv2.INTER_AREA)
        hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV); _,s,v=cv2.split(hsv)
        white=((s<85)&(v>135)).astype(np.uint8)
        cand=np.zeros_like(white)
        cand[58:132,:]=white[58:132,:]
        cand[18:70,:48]=white[18:70,:48]
        cand[18:70,157:]=white[18:70,157:]
        cand=cv2.morphologyEx(cand,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
        templ=self.context_center_t
        inter=float(np.logical_and(templ>0,cand>0).sum())
        ps=float((cand>0).sum()); ts=float((templ>0).sum())
        if ps <= 0 or ts <= 0: return 0.0
        precision=inter/ps; recall=inter/ts
        return float(2*precision*recall/max(1e-9,precision+recall))

    def _scan_context(self, grabber, viewport, now):
        t0=time.perf_counter()
        left=_grab_relative_roi(grabber,viewport,ROI_CONTEXT_LEFT,(82,74))
        center=_grab_relative_roi(grabber,viewport,ROI_CONTEXT_CENTER,(205,132))
        right=_grab_relative_roi(grabber,viewport,ROI_CONTEXT_RIGHT,(82,74))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter()
        ls=self._context_icon_score(left,"left")
        cs=self._context_center_similarity(center)
        rs=self._context_icon_score(right,"right")
        self._ema_timing("context",(time.perf_counter()-q)*1000); self.perf_scans+=1
        self.context_left_score=ls; self.context_center_score=cs; self.context_right_score=rs
        votes=int(ls>=0.028)+int(cs>=0.24)+int(rs>=0.065)
        self.context_votes=votes
        raw=votes>=int(self.cfg.get("vision",{}).get("context_threshold",2))
        if raw:
            self.context_hits+=1; self.context_misses=0; self.match_recent_until=now+4.0
            if self.report_armed:
                self.report_last_live_seen = now
            # A real live HUD coming back means this was only an inter-round gap.
            # Stop the temporary result-screen radar immediately.
            if self.report_waiting_result or self.report_capture_active:
                self._cancel_report_capture_window("live HUD returned")
        else:
            self.context_misses+=1; self.context_hits=0
            # Start the cheap waiter on the FIRST missing live-HUD sample instead
            # of waiting for the full MATCH_CONTEXT state to decay.  This buys
            # roughly one extra context interval when the user clicks through a
            # very short-lived result page.  A returning live HUD cancels it.
            if self.match_context and self.report_armed and not self.report_done and not self.report_waiting_result:
                self._start_report_wait(now, "first live HUD miss")
        if not self.match_context and self.context_hits>=2:
            if self.hl_round_finalized:
                self._reset_round_highlight("新一回合 live HUD")
            self.match_context=True; self.phase="IN_MATCH_UNKNOWN"; LOGGER.info("MATCH_CONTEXT TRUE votes=%s L=%.3f C=%.3f R=%.3f",votes,ls,cs,rs)
            # A new live HUD means a real match session. The whole-match report is
            # registered here and is deliberately NOT tied to Sage detection.
            # This costs essentially nothing during the match: it is only a boolean
            # memory flag plus the last-live timestamp. Report OCR remains asleep.
            if self.report_done:
                self.report_done = False
                self.report_attempts = 0
                self.report_pending_kills = None
                self.report_kill_confirm_hits = 0
                self.session_sage_seen = False
                self.report_last_live_seen = 0.0
                self.last_report_nickname = "-"
                self.last_report_agent = "-"
                self.last_report_kills = None
                self._clear_report_snapshot("new match HUD")
            elif self.report_snapshot_locked:
                # A live HUD returning while an unfinished snapshot exists means
                # the prior candidate was not the final whole-match page.
                self._clear_report_snapshot("live HUD returned before report completion")
            if not self.report_armed:
                self.report_armed_since = now
            self.report_armed = True
            self.report_last_live_seen = now
            if not self.report_snapshot_locked:
                self.report_parse_status = "本局已登记"
            # Make identity scan immediate when entering a real match.
            self.next_alive=0.0
        elif self.match_context and self.context_misses>=2:
            self.match_context=False; LOGGER.info("MATCH_CONTEXT FALSE votes=%s L=%.3f C=%.3f R=%.3f",votes,ls,cs,rs)
            # Enter low-power post-match waiting.  This is intentionally NOT a
            # short countdown anymore: ordinary inter-round gaps are cancelled
            # as soon as the live HUD returns, while a real end-of-match screen
            # can arrive many seconds later without being missed.
            if self.report_armed and not self.report_done:
                self._start_report_wait(now, "live HUD disappeared")
            self._reset_match_state("not in live match HUD")

    def _clear_report_snapshot(self, reason=""):
        if self.report_snapshot_locked or self.report_snapshot_cards is not None:
            LOGGER.info("清除战报快照 | %s", reason or "reset")
        self.report_snapshot_locked = False
        self.report_snapshot_score = 0.0
        self.report_snapshot_cards = None
        self.report_snapshot_full = None
        self.report_snapshot_locked_at = 0.0
        self.report_best_candidate_cards = None
        self.report_best_candidate_full = None
        self.report_best_candidate_quality = 0.0
        self.report_best_candidate_at = 0.0
        self.report_best_candidate_counts = []
        self.report_candidate_signature = None
        self.report_candidate_stable_hits = 0
        self.report_last_signature_diff = 0.0
        self.report_parse_status = "等待结算页"
        self.report_parse_attempts = 0

    def _start_report_wait(self, now, reason=""):
        """Enter lightweight waiting without touching an already-owned snapshot."""
        if not bool(self.cfg.get("vision", {}).get("report_enabled", True)):
            return
        if not self.report_armed or self.report_done or self.report_snapshot_locked:
            return
        if not self.report_waiting_result:
            self.report_wait_started = now
            self.report_wait_samples = 0
            self.report_parse_status = "等待整局结算页"
            LOGGER.info("战报低功耗等待启动 | %s", reason or "live HUD disappeared")
        self.report_waiting_result = True
        self.report_capture_active = False
        self.report_capture_started = 0.0
        self.report_capture_deadline = 0.0
        self.report_capture_samples = 0
        self.report_capture_best_score = 0.0
        self.report_capture_best_cards = None
        self.report_best_candidate_cards = None
        self.report_best_candidate_full = None
        self.report_best_candidate_quality = 0.0
        self.report_best_candidate_at = 0.0
        self.report_best_candidate_counts = []
        self.report_candidate_hits = 0
        self.report_candidate_signature = None
        self.report_candidate_stable_hits = 0
        self.report_last_signature_diff = 0.0
        self.report_retry_after = 0.0
        self.last_report_layout_score = 0.0
        self.next_report = 0.0

    def _start_report_capture_window(self, now, reason=""):
        """Legacy burst mode retained only for diagnostics; never unlocks a snapshot."""
        if not bool(self.cfg.get("vision", {}).get("report_enabled", True)):
            return
        if not self.report_armed or self.report_done or self.report_snapshot_locked:
            return
        window_ms = max(1200, min(6000, int(self.cfg.get("vision", {}).get("report_capture_window_ms", 3000))))
        self.report_waiting_result = True
        self.report_capture_active = True
        self.report_capture_started = now
        self.report_capture_deadline = now + window_ms / 1000.0
        self.report_capture_samples = 0
        self.report_candidate_hits = 0
        self.report_retry_after = 0.0
        self.next_report = 0.0
        LOGGER.info("战报高速捕获窗口启动 %.1fs | %s", window_ms/1000.0, reason or "candidate")

    def _cancel_report_capture_window(self, reason=""):
        # A real live HUD returning proves an inter-round gap. If a snapshot was
        # somehow captured before that, it was a false positive and is safe to clear.
        if self.report_waiting_result or self.report_capture_active or self.report_snapshot_locked:
            LOGGER.info("战报等待/捕获结束 | %s", reason or "cancel")
        self.report_waiting_result = False
        self.report_wait_started = 0.0
        self.report_wait_samples = 0
        self.report_capture_active = False
        self.report_capture_started = 0.0
        self.report_capture_deadline = 0.0
        self.report_capture_samples = 0
        self.report_capture_best_score = 0.0
        self.report_capture_best_cards = None
        self.report_candidate_hits = 0
        self.last_report_layout_score = 0.0
        self._clear_report_snapshot(reason or "capture cancelled")

    def _verify_k_same_snapshot(self, cards_img, data):
        """Second K check from the same frozen result frame.

        This replaces the old requirement that the user keep the result screen
        visible for a *second screen scan*.  A slightly wider crop is fed through
        the lightweight digit templates.  High-confidence primary reads are also
        accepted when the alternate crop is inconclusive.
        """
        try:
            card_idx = int(data.get("card_index", 1)) - 1
            ch, cw = cards_img.shape[:2]
            x1 = int(card_idx * cw / 5); x2 = int((card_idx + 1) * cw / 5)
            card = cards_img[:, x1:x2]
            h, w = card.shape[:2]
            roi = card[int(h*0.70):int(h*0.95), int(w*0.21):int(w*0.46)]
            if roi.size:
                value, conf = self.digit_reader.read_hp_roi(roi)
                if value is not None and 0 <= int(value) <= 60 and float(conf) >= 0.50:
                    return int(value) == int(data.get("kills")), int(value), float(conf)
        except Exception:
            LOGGER.exception("战报同帧K二次校验失败")
        primary_conf = float(data.get("kill_confidence", 0.0) or 0.0)
        # The normal tight-crop digit path is already very conservative.
        if data.get("kill_method") == "digit-template" and primary_conf >= 0.66:
            return True, int(data.get("kills")), primary_conf
        return False, None, 0.0

    def _scan_alive(self, grabber, viewport, now):
        if not self.match_context:
            return
        t0=time.perf_counter()
        img=_grab_relative_roi(grabber,viewport,ROI_ALIVE,(580,132)); self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter(); gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY); score=self._multi_match(gray,self.alive_templates)
        self._ema_timing("alive",(time.perf_counter()-q)*1000); self.last_alive_score=score; self.perf_scans+=1
        thr=float(self.cfg.get("vision",{}).get("alive_threshold",0.74)); raw=score>=thr
        if raw:
            self.alive_hits+=1; self.alive_misses=0
        else:
            self.alive_misses+=1; self.alive_hits=0

        if raw and self.alive_hits>=2:
            was_dead=self.death_latched
            self.alive_state=True; self.ever_alive=True; self.death_latched=False
            # Sage detection still drives the six live reaction states, but whole-match
            # report registration is handled by MATCH_CONTEXT so reports also work when
            # the player uses Sova/Jett/etc.
            self.session_sage_seen=True
            self.death_suspect_since=None; self.death_ocr_checked=False; self.last_death_evidence="-"
            if self.round_end and now>=self.transient_until:
                self.round_end=False
            self.phase="IN_MATCH_ALIVE"
            if was_dead:
                LOGGER.info("检测到新回合/复活：绿色友方条重新出现贤者头像 score=%.3f",score)
            return

        if self.alive_state is True and self.alive_misses>=2 and not self.death_latched:
            # Missing portrait is only a suspicion. Do not play DEAD yet.
            self.alive_state=None; self.low_state=False; self.low_hits=0; self.hp_history=[]; self.hp_enter_votes=0; self.hp_exit_votes=0
            self.death_suspect_since=now; self.death_ocr_checked=False
            self.phase="SUSPECTED_DEAD"
            self.last_death_evidence="贤者头像消失，等待二次证据"
            LOGGER.info("疑似死亡：绿色友方条贤者头像消失 score=%.3f",score)
            if self.current_display_state=="low_hp":
                self._request_state("idle","death pending confirmation")

    @staticmethod
    def _death_report_score(img):
        if img is None or img.size == 0:
            return 0.0
        hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV); _,_,v=cv2.split(hsv)
        # Combat report is a large dark rectangular panel. This is only a secondary cue
        # after the player's top HUD portrait has already disappeared.
        return float((v<105).mean())

    def _confirm_death(self, reason):
        self.death_latched=True; self.alive_state=False; self.low_state=False; self.low_hits=0; self.hp_history=[]; self.hp_enter_votes=0; self.hp_exit_votes=0
        self.death_suspect_since=None; self.phase="IN_MATCH_DEAD"; self.last_death_evidence=reason
        self.transient_until=0.0; self.pending_result=None
        self._request_state("dead",reason)
        LOGGER.info("DEAD_CONFIRMED | %s",reason)

    def _scan_death_confirmation(self, grabber, viewport, now):
        if not self.match_context or self.death_latched or self.death_suspect_since is None:
            return
        # If the portrait comes back before confirmation, cancel suspicion.
        if self.alive_state is True:
            self.death_suspect_since=None; self.phase="IN_MATCH_ALIVE"; return
        t0=time.perf_counter(); report=_grab_relative_roi(grabber,viewport,ROI_DEATH_REPORT,(360,250)); self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter(); report_score=self._death_report_score(report); self._ema_timing("death",(time.perf_counter()-q)*1000); self.perf_scans+=1
        self.last_death_report_score=report_score
        if report_score>=0.56:
            self._confirm_death(f"战斗记录面板证据 {report_score:.2f}")
            return

        # With a configured nickname, inspect killfeed once to see if nickname is on victim side.
        if not self.death_ocr_checked and now-self.death_suspect_since>=0.25:
            self.death_ocr_checked=True
            nickname=str(self.cfg.get("vision",{}).get("player_nickname","")).strip()
            if nickname and bool(self.cfg.get("vision",{}).get("nickname_ocr_fallback",True)):
                t0=time.perf_counter(); kill_roi=_grab_relative_roi(grabber,viewport,ROI_KILL_OCR,(640,189)); self._ema_timing("capture",(time.perf_counter()-t0)*1000)
                hit,desc=self._ocr_names_once(kill_roi,"victim")
                if hit:
                    self._confirm_death(f"击杀栏昵称位于被击杀侧：{desc}")
                    return

        fallback=float(self.cfg.get("vision",{}).get("death_fallback_seconds",2.2))
        thr=float(self.cfg.get("vision",{}).get("alive_threshold",0.74))
        if now-self.death_suspect_since>=fallback and self.last_alive_score < max(0.30,thr-0.06):
            self._confirm_death(f"对局HUD仍存在 + 贤者头像持续消失 {fallback:.1f}s")

    @staticmethod
    def _rect_intersects(a, b):
        ax1, ay1, ax2, ay2 = a; bx1, by1, bx2, by2 = b
        return min(ax2, bx2) > max(ax1, bx1) and min(ay2, by2) > max(ay1, by1)

    def _hp_screen_rect(self, viewport):
        vx, vy, vw, vh = viewport
        x1, y1, x2, y2 = ROI_HP
        return (int(vx + x1 * vw), int(vy + y1 * vh), int(vx + x2 * vw), int(vy + y2 * vh))

    def _pet_screen_rect(self):
        # Pet position is persisted whenever dragging ends. Use a conservative
        # bounding box as a fallback guard because DXGI/MSS captures the final
        # desktop composite, including XiaoMeili itself.
        try:
            px = int(self.cfg.get("x", -100000)); py = int(self.cfg.get("y", -100000))
            pw = max(80, int(self.cfg.get("pet_width", 280)))
            ph = max(80, int(round(pw * 660 / 620)))
            return (px, py, px + pw, py + ph)
        except Exception:
            return (-100000, -100000, -99999, -99999)

    def _hp_is_occluded_by_pet(self, viewport):
        if not bool(self.cfg.get("vision", {}).get("hp_occlusion_guard", True)):
            return False
        return self._rect_intersects(self._hp_screen_rect(viewport), self._pet_screen_rect())

    def _append_hp_sample(self, hp, conf):
        vcfg = self.cfg.get("vision", {})
        min_conf = float(vcfg.get("hp_min_conf", 0.56))
        if hp is None or not (0 <= int(hp) <= 100) or float(conf) < min_conf:
            return False
        window = max(3, int(vcfg.get("hp_vote_window", 5)))
        self.hp_history.append(int(hp))
        if len(self.hp_history) > window:
            self.hp_history = self.hp_history[-window:]
        self.hp_last_confirmed = int(hp)
        return True

    def _update_low_hp_vote(self):
        vcfg = self.cfg.get("vision", {})
        threshold = int(vcfg.get("low_hp_threshold", 50))
        exit_threshold = min(100, threshold + int(vcfg.get("hp_exit_margin", 10)))
        enter_needed = max(2, int(vcfg.get("hp_enter_votes", 3)))
        exit_needed = max(2, int(vcfg.get("hp_exit_votes", 3)))
        hist = list(self.hp_history)
        self.hp_enter_votes = sum(1 for v in hist if v <= threshold)
        self.hp_exit_votes = sum(1 for v in hist if v >= exit_threshold)

        if not self.low_state:
            # Require multiple independent valid readings before entering LOW_HP.
            if len(hist) >= enter_needed and self.hp_enter_votes >= enter_needed:
                self.low_state = True
                LOGGER.info("HP低血量确认 history=%s votes=%s/%s threshold=%s", hist, self.hp_enter_votes, len(hist), threshold)
        else:
            # Hysteresis: do not leave LOW_HP around 49/51. Require >= threshold+margin.
            if len(hist) >= exit_needed and self.hp_exit_votes >= exit_needed:
                self.low_state = False
                LOGGER.info("HP恢复确认 history=%s votes=%s/%s exit>=%s", hist, self.hp_exit_votes, len(hist), exit_threshold)

    def _scan_hp(self, grabber, viewport, now):
        if not self.match_context or self.alive_state is not True or self.death_latched or self.round_end:
            self.last_hp=None; self.last_hp_conf=0.0; self.last_hp_probe=None
            self.hp_history=[]; self.hp_enter_votes=0; self.hp_exit_votes=0
            self.hp_occluded=False; self.hp_guard_reason="-"
            return

        # V0.4.8 self-occlusion guard. Desktop Duplication/MSS sees the desktop
        # pet too. If XiaoMeili overlaps the tiny HP sensor, skip this cycle
        # rather than letting her own hair/effects become fake digits.
        if self._hp_is_occluded_by_pet(viewport):
            self.hp_occluded=True
            self.hp_guard_reason="小美丽遮挡生命值区域，本轮HP识别已暂停"
            self.last_hp=None; self.last_hp_conf=0.0; self.last_hp_probe=None
            self.low_hits=0
            self.perf_scans+=1
            return
        self.hp_occluded=False; self.hp_guard_reason="-"

        # ROI_HP is deliberately very tight around the HP digits only.
        t0=time.perf_counter(); img=_grab_relative_roi(grabber,viewport,ROI_HP,(90,61)); self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY); tiny=cv2.resize(g,(24,12),interpolation=cv2.INTER_AREA)
        changed=True
        if self.last_hp_probe is not None:
            changed=float(np.mean(cv2.absdiff(tiny,self.last_hp_probe))) >= 2.4
        self.last_hp_probe=tiny
        # Periodic refresh catches changes whose hash delta happens to be small.
        # After the first low/recovery candidate we temporarily re-read every HP
        # cycle so a 3-vote decision finishes in well under a second instead of
        # waiting several seconds for periodic refreshes.
        vcfg=self.cfg.get("vision",{})
        threshold=int(vcfg.get("low_hp_threshold",50))
        exit_threshold=min(100,threshold+int(vcfg.get("hp_exit_margin",10)))
        enter_needed=max(2,int(vcfg.get("hp_enter_votes",3)))
        exit_needed=max(2,int(vcfg.get("hp_exit_votes",3)))
        pending_enter=(not self.low_state and any(v<=threshold for v in self.hp_history) and self.hp_enter_votes<enter_needed)
        pending_exit=(self.low_state and any(v>=exit_threshold for v in self.hp_history) and self.hp_exit_votes<exit_needed)
        force=(self.last_hp is None or now-self.last_hp_full_read>1.8 or pending_enter or pending_exit)
        if not (changed or force):
            self.perf_scans+=1; return

        q=time.perf_counter(); hp,conf=self.digit_reader.read_hp_roi(img); self._ema_timing("hp",(time.perf_counter()-q)*1000)
        self.last_hp_full_read=now; self.hp_read_count+=1; self.perf_scans+=1
        self.last_hp=hp; self.last_hp_conf=conf

        # No stale-value reuse here: an unreadable frame is unknown, not the
        # previous HP. This prevents one bad low reading from lingering for 0.9s.
        if self._append_hp_sample(hp, conf):
            self.last_valid_hp=int(hp); self.last_hp_time=now
            self._update_low_hp_vote()
            self.low_hits=self.hp_enter_votes
        else:
            # Invalid/low-confidence frames do not vote and cannot trigger LOW_HP.
            self.low_hits=0

    def _reset_round_highlight(self, reason=""):
        self.round_self_kills = 0
        self.enemy_alive = 5
        self.enemy_alive_scores = [0.0] * 5
        self.enemy_alive_confident = False
        self.self_final_kill_candidate = False
        self.self_final_kill_confirmed = False
        self.highlight_triggered = False
        self.highlight_candidate = False
        self.visible_own_kill_rows = 0
        self.hl_round_finalized = False
        self.highlight_last_reason = f"新回合：{reason or 'HUD returned'}"
        LOGGER.info("[ROUND] reset | %s", reason or "new live HUD")

    def _scan_enemy_alive_v090(self, grabber, viewport, now):
        """Cheap top-HUD portrait-slot counter.

        We do not identify enemy agents. Each of the five fixed portrait slots is
        reduced to a tiny grayscale patch and judged by Laplacian texture energy.
        Living portraits are highly textured; an empty red team bar is nearly
        flat. The supplied 5-alive and 3-alive samples separate cleanly.
        """
        try:
            vx, vy, vw, vh = viewport
            scores = []
            alive = 0
            for cx in V090_ENEMY_CENTERS:
                box = (cx - 0.0105, 0.010, cx + 0.0105, 0.067)
                patch = _grab_relative_roi(grabber, viewport, box, (40, 64))
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                score = float(cv2.Laplacian(gray, cv2.CV_32F).var())
                scores.append(score)
                if score >= 1850.0:
                    alive += 1
            self.enemy_alive_scores = scores
            # Require at least one clearly high/low slot to avoid treating a
            # transient full-screen effect as authoritative.
            separated = any(x >= 2400.0 for x in scores) or all(x < 1500.0 for x in scores)
            self.enemy_alive_confident = bool(separated)
            if separated:
                self.enemy_alive = int(max(0, min(5, alive)))
            self.last_enemy_alive_scan = now
            return self.enemy_alive
        except Exception:
            LOGGER.exception("[ROUND] enemy alive scan failed")
            return self.enemy_alive

    def _ocr_own_kill_rows_v090(self, kill_roi):
        nickname = str(self.cfg.get("vision", {}).get("player_nickname", "")).strip()
        if not nickname:
            return 0, "未绑定游戏昵称"
        t0 = time.perf_counter()
        engine = self._get_report_ocr_engine()
        try:
            if engine is None:
                return 0, "OCR引擎不可用"
            self.ocr_trigger_count += 1
            roi2 = cv2.resize(kill_roi, None, fx=1.25, fy=1.25, interpolation=cv2.INTER_LINEAR)
            result = engine(roi2)
            boxes = getattr(result, "boxes", None)
            txts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            if txts is None or boxes is None:
                return 0, "未识别到昵称"
            target = self._norm_name(nickname)
            rw = max(1.0, float(roi2.shape[1]))
            hits = 0
            debug = []
            for i, txt in enumerate(list(txts)):
                conf = float(scores[i]) if scores is not None and i < len(scores) else 1.0
                if conf < 0.40:
                    continue
                box = np.array(boxes[i], dtype=np.float32)
                cx = float(box[:, 0].mean()) / rw
                sim = self._name_similarity(target, txt)
                debug.append(f"{txt}@{cx:.2f}/{sim:.2f}")
                if cx < 0.67 and sim >= 0.66:
                    hits += 1
            self.last_ocr_texts = debug[:12]
            return int(hits), (f"{nickname} 可见击杀行={hits}" if hits else "未发现本人击杀行")
        except Exception as exc:
            LOGGER.exception("[ROUND] own-kill OCR failed")
            return 0, f"OCR错误:{type(exc).__name__}"
        finally:
            self._ema_timing("ocr", (time.perf_counter() - t0) * 1000)

    def _scan_kill_probe(self, grabber, viewport, now):
        if not self.match_context or self.death_latched or self.round_end:
            self.last_kill_signature=(0,())
            self.last_kill_count=0
            self.visible_own_kill_rows=0
            return

        t0=time.perf_counter()
        probe=_grab_relative_roi(grabber,viewport,ROI_KILL_PROBE,(320,108))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter()
        sig,strength=_killfeed_green_signature(probe)
        self._ema_timing("kill",(time.perf_counter()-q)*1000)
        self.perf_scans+=1

        changed=sig!=self.last_kill_signature
        self.last_kill_probe_strength=strength
        self.last_kill_signature=sig
        if not changed:
            return

        # Any kill-feed edge is a useful moment to refresh the enemy count.
        before = int(self.enemy_alive)
        self._scan_enemy_alive_v090(grabber, viewport, now)

        if sig[0] <= 0:
            self.visible_own_kill_rows=0
            return
        if now-self.last_kill_event_time < 0.16:
            return
        self.last_kill_event_time=now

        # Character-agnostic identity: nickname is the source of truth. This
        # works when the user changes from Sage to Harbor or any other agent.
        t0=time.perf_counter()
        kill_roi=_grab_relative_roi(grabber,viewport,ROI_KILL_OCR,(640,189))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        visible, match = self._ocr_own_kill_rows_v090(kill_roi)
        delta=max(0, int(visible)-int(self.visible_own_kill_rows))
        self.visible_own_kill_rows=int(visible)
        self.last_nickname_match=match
        self.last_kill_count=delta

        if delta <= 0:
            LOGGER.info("[KILL] teammate/other kill ignored | %s | enemy=%s", match, self.enemy_alive)
            return

        self.round_self_kills += int(delta)
        self.highlight_candidate = self.round_self_kills >= int(
            self.cfg.get("highlight_cta",{}).get("min_kills",2)
        )
        after=int(self.enemy_alive)
        if before == 1:
            self.self_final_kill_candidate = True
            if after == 0 or not self.enemy_alive_confident:
                # If the result overlay races the top bar, the later victory is
                # the second half of the confirmation chain.
                self.self_final_kill_confirmed = (after == 0)
            LOGGER.info("[KILL] final-enemy candidate by self | before=%s after=%s", before, after)

        LOGGER.info(
            "[KILL] self +%s | round=%s enemy=%s->%s candidate=%s final=%s",
            delta, self.round_self_kills, before, after,
            self.highlight_candidate, self.self_final_kill_confirmed,
        )
        if self.alive_state is True:
            self._request_state("kill",f"event-driven own kill nick={match} +{delta}")
            self.transient_until=now+int(self.cfg.get("vision",{}).get("kill_show_ms",1400))/1000.0

    def _scan_result(self, grabber, viewport, now):
        # Do not run result matching continuously for highlight purposes. The
        # existing result scanner remains low-frequency; highlight eligibility
        # is only evaluated when a stable win event is actually confirmed.
        if not self.match_context and now>self.match_recent_until:
            return
        t0=time.perf_counter()
        img=_grab_relative_roi(grabber,viewport,ROI_RESULT,(480,243))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter()
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        bw=(gray>220).astype(np.uint8)*255
        win_score=self._fixed_match(bw,self.win_t)
        loss_score=self._fixed_match(bw,self.loss_t)
        self._ema_timing("result",(time.perf_counter()-q)*1000)
        self.perf_scans+=1
        self.last_win_score=win_score
        self.last_loss_score=loss_score

        thr=float(self.cfg.get("vision",{}).get("result_threshold",0.75))
        win_raw=win_score>=thr
        loss_raw=loss_score>=thr
        win_event=win_raw and not self.win_latched
        loss_event=loss_raw and not self.loss_latched
        if win_raw:self.win_latched=True
        elif win_score<thr-0.12:self.win_latched=False
        if loss_raw:self.loss_latched=True
        elif loss_score<thr-0.12:self.loss_latched=False

        result_state="victory" if win_event else "defeat" if loss_event else None
        if not result_state:
            return

        self.round_end=True
        self.phase="ROUND_END"
        self.hl_round_finalized=True

        if result_state == "victory":
            # A win after "before=1 + own kill" also confirms the last enemy
            # when the top portrait strip disappeared too quickly to read 0.
            if self.self_final_kill_candidate:
                self.self_final_kill_confirmed = True

            hcfg=self.cfg.get("highlight_cta",{}) if isinstance(self.cfg.get("highlight_cta"),dict) else {}
            min_kills=max(1,int(hcfg.get("min_kills",2)))
            enabled=bool(hcfg.get("enabled",True))
            alive_ok=not bool(self.death_latched)
            qualifies=(
                enabled
                and self.round_self_kills>=min_kills
                and bool(self.self_final_kill_confirmed)
                and alive_ok
                and not self.highlight_triggered
            )
            if qualifies:
                self.highlight_triggered=True
                self.highlight_event_id+=1
                self.highlight_last_reason=(
                    f"{self.round_self_kills}杀 · 最后一杀本人 · 存活 · 获胜"
                )
                LOGGER.info(
                    "[HIGHLIGHT] TRIGGER id=%s kills=%s final=%s alive=%s win=%.3f",
                    self.highlight_event_id,self.round_self_kills,
                    self.self_final_kill_confirmed,alive_ok,win_score,
                )
            else:
                reasons=[]
                if not enabled: reasons.append("功能关闭")
                if self.round_self_kills<min_kills: reasons.append(f"击杀不足 {self.round_self_kills}/{min_kills}")
                if not self.self_final_kill_confirmed: reasons.append("最后一杀非本人/未确认")
                if not alive_ok: reasons.append("主人已死亡")
                if self.highlight_triggered: reasons.append("本回合已触发")
                self.highlight_last_reason="未触发："+"；".join(reasons or ["条件不满足"])
                LOGGER.info("[HIGHLIGHT] NO TRIGGER | %s",self.highlight_last_reason)
        else:
            self.highlight_last_reason="未触发：本回合失败"
            LOGGER.info("[HIGHLIGHT] defeat | no trigger")

        if self.current_display_state=="kill" and now<self.transient_until:
            self.pending_result=(result_state,self.transient_until+0.06)
        else:
            self._request_state(result_state,f"round result win={win_score:.3f} loss={loss_score:.3f}")
            self.transient_until=now+int(self.cfg.get("vision",{}).get("result_show_ms",2800))/1000.0
            self.pending_result=None

    def _settle_state(self, now):
        if self.pending_result and now>=self.pending_result[1]:
            rs=self.pending_result[0]; self.pending_result=None; self._request_state(rs,"delayed after kill")
            self.transient_until=now+int(self.cfg.get("vision",{}).get("result_show_ms",2800))/1000.0
        if now>=self.transient_until and self.current_display_state in ("kill","victory","defeat"):
            self._request_state(self._persistent_state(),"transient finished")
        if self.current_display_state not in ("kill","victory","defeat"):
            self._request_state(self._persistent_state(),"persistent context")

    @staticmethod
    def _report_layout_candidate(cards, cont):
        if cards is None or cards.size == 0 or cont is None or cont.size == 0:
            return False, 0.0
        try:
            hsv = cv2.cvtColor(cont, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            red_frac = float((((h < 10) | (h > 170)) & (s > 85) & (v > 95)).mean())
            gray_votes = 0
            for i in range(5):
                x1 = int(i * cards.shape[1] / 5)
                x2 = int((i + 1) * cards.shape[1] / 5)
                seg = cards[:, x1:x2]
                vv = cv2.cvtColor(seg, cv2.COLOR_BGR2HSV)[..., 2]
                if float((vv < 105).mean()) >= 0.55:
                    gray_votes += 1
            score = min(1.0, red_frac * 1.8 + gray_votes / 5.0 * 0.55)
            return (red_frac >= 0.10 and gray_votes >= 4), float(score)
        except Exception:
            return False, 0.0

    @staticmethod
    def _report_five_card_completeness(cards):
        """Cheap structural check for the *actual* five-player result page.

        The post-result reward/progression page also has dark panels and a red
        button, so the older detector could confuse it with the scorecard page.
        A real scorecard has dense small white text (nickname / ACS / KDA) in
        all five equally-spaced card columns.  We count those text-like bright
        components in the lower part of each fifth.

        This is deliberately OCR-free and runs on the 820x270 radar image.
        """
        if cards is None or cards.size == 0:
            return False, 0.0, [], []
        try:
            gray = cv2.cvtColor(cards, cv2.COLOR_BGR2GRAY)
            counts, densities = [], []
            for i in range(5):
                x1 = int(i * gray.shape[1] / 5)
                x2 = int((i + 1) * gray.shape[1] / 5)
                seg = gray[:, x1:x2]
                # Skip the character-art-heavy top portion; player-name/ACS/KDA
                # live in the lower 65% of the card panel.
                seg = seg[int(seg.shape[0] * 0.35):, :]
                if seg.size == 0:
                    counts.append(0); densities.append(0.0); continue
                mask = (seg > 180).astype(np.uint8) * 255
                n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
                c = 0
                for st in stats[1:]:
                    w = int(st[cv2.CC_STAT_WIDTH]); h = int(st[cv2.CC_STAT_HEIGHT])
                    area = int(st[cv2.CC_STAT_AREA])
                    if 2 <= w <= 70 and 2 <= h <= 30 and area >= 5:
                        c += 1
                counts.append(c)
                densities.append(float((seg > 180).mean()))
            enough = sum(1 for c in counts if c >= 5)
            complete = (min(counts) >= 4 and enough >= 4 and min(densities) >= 0.004)
            # Score favors all-five balance, not one very text-heavy panel.
            comp_score = sum(min(1.0, c / 8.0) for c in counts) / 5.0
            density_score = sum(min(1.0, d / 0.012) for d in densities) / 5.0
            quality = 0.72 * comp_score + 0.28 * density_score
            return bool(complete), float(quality), counts, densities
        except Exception:
            return False, 0.0, [], []

    def _cache_report_candidate(self, grabber, viewport, now, layout_score, card_quality, counts):
        """Own a real result frame immediately, before waiting for stability."""
        quality = float(layout_score) * 0.35 + float(card_quality) * 0.65
        # Avoid recapturing native/full frames unless quality actually improves.
        if self.report_best_candidate_cards is not None and quality <= self.report_best_candidate_quality + 0.012:
            return False
        try:
            vx, vy, vw, vh = viewport
            t0 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            cards = _roi(full_frame, ROI_REPORT_CARDS) if full_frame is not None and getattr(full_frame, "size", 0) else None
            if cards is None or cards.size == 0:
                # Defensive fallback for capture backends that cannot return a full viewport.
                cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t0) * 1000)
            if cards is None or cards.size == 0:
                return False
            self.report_best_candidate_cards = cards.copy()
            self.report_best_candidate_full = None if full_frame is None else full_frame.copy()
            self.report_best_candidate_quality = quality
            self.report_best_candidate_at = now
            self.report_best_candidate_counts = list(counts or [])
            self.report_parse_status = f"五卡候选已缓存，等待定格（质量 {quality:.2f}）"
            LOGGER.info("战报五卡候选已缓存 quality=%.3f layout=%.3f counts=%s", quality, layout_score, counts)
            return True
        except Exception:
            LOGGER.exception("缓存战报五卡候选失败")
            return False

    def _lock_best_report_candidate(self, now, reason=""):
        if self.report_best_candidate_cards is None:
            return False
        self.report_snapshot_cards = self.report_best_candidate_cards.copy()
        self.report_snapshot_full = None if self.report_best_candidate_full is None else self.report_best_candidate_full.copy()
        self.report_snapshot_locked = True
        self.report_snapshot_locked_at = now
        self.report_snapshot_score = float(self.report_best_candidate_quality)
        self.report_waiting_result = False
        self.report_capture_active = False
        self.report_parse_status = "战报快照已锁定，后台解析中"
        self.report_attempts += 1
        LOGGER.info("锁定最佳五卡快照 quality=%.3f counts=%s | %s",
                    self.report_best_candidate_quality, self.report_best_candidate_counts, reason or "confirmed")
        return True

    @staticmethod
    def _parse_kill_number(text):
        """Parse only a compact kill-count token, not a full K/D/A string."""
        t = str(text or "").upper().replace("Ｏ", "0").replace("O", "0")
        t = t.replace("I", "1").replace("L", "1")
        nums = re.findall(r"(?<!\d)(\d{1,2})(?!\d)", t)
        for token in nums:
            try:
                value = int(token)
            except Exception:
                continue
            if 0 <= value <= 60:
                return value
        return None

    def _run_report_ocr(self, engine, image):
        if engine is None or image is None or image.size == 0:
            return None
        self.ocr_trigger_count += 1
        return engine(image)

    def _read_kill_count_from_card(self, cards_img, card_idx, engine=None):
        """Read K from a high-resolution frozen result card.

        V0.4.9.9 no longer uses the HP digit template as the primary method. The
        result-page K/D/A typography and vertical location differ from the HUD. We
        OCR only the narrow K/D/A row and keep the *leftmost* valid number, so D
        and A can be wrong without invalidating K. Two preprocessing variants are
        enough in normal cases; a third is used only when they disagree.
        """
        if cards_img is None or cards_img.size == 0:
            return None, 0.0, "empty"
        ch, cw = cards_img.shape[:2]
        x1 = int(card_idx * cw / 5); x2 = int((card_idx + 1) * cw / 5)
        card = cards_img[:, x1:x2]
        if card.size == 0:
            return None, 0.0, "empty-card"
        h, w = card.shape[:2]
        # V0.7.3.3 coordinates for ROI_REPORT_CARDS (y=0.50..0.82).
        # This band contains the K/D/A label and value row, not the nickname/ACS rows.
        kda_roi = card[int(h * 0.62):int(h * 0.92), int(w * 0.16):int(w * 0.84)]
        tight_k = card[int(h * 0.68):int(h * 0.90), int(w * 0.18):int(w * 0.43)]
        if kda_roi.size == 0:
            return None, 0.0, "empty-kda-roi"

        votes = []
        if engine is not None:
            try:
                up = cv2.resize(kda_roi, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(6,6)).apply(gray)
                variants = [up, cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)]
                # Third variant is only evaluated if the first two do not agree.
                for vi, variant in enumerate(variants):
                    rr = self._run_report_ocr(engine, variant)
                    try:
                        LOGGER.info("战报K OCR pass=%s txts=%s", vi + 1, ([] if getattr(rr, "txts", None) is None else (getattr(rr, "txts").tolist() if hasattr(getattr(rr, "txts"), "tolist") else list(getattr(rr, "txts")))))
                    except Exception:
                        pass
                    # RapidOCR 3.x commonly returns numpy.ndarray for boxes/scores.
                    # Using ``array or []`` raises:
                    # ValueError: The truth value of an array is ambiguous.
                    # That exception previously aborted KDA parsing even when the
                    # crop clearly contained e.g. "12/19/2".
                    boxes_raw = getattr(rr, "boxes", None)
                    txts_raw = getattr(rr, "txts", None)
                    scores_raw = getattr(rr, "scores", None)
                    boxes = [] if boxes_raw is None else list(boxes_raw)
                    txts = [] if txts_raw is None else list(txts_raw)
                    scores = [] if scores_raw is None else list(scores_raw)
                    nums = []
                    for i, txt in enumerate(txts):
                        val = self._parse_kill_number(txt)
                        if val is None:
                            continue
                        sc = float(scores[i]) if i < len(scores) else 0.5
                        if sc < 0.28:
                            continue
                        if i < len(boxes):
                            bx = np.asarray(boxes[i], dtype=np.float32)
                            xpos = float(bx[:,0].mean())
                        else:
                            xpos = float(i)
                        nums.append((xpos, int(val), sc))
                    if nums:
                        nums.sort(key=lambda z:z[0])
                        votes.append((nums[0][1], nums[0][2], vi))
                    else:
                        # Extra fallback: RapidOCR may return one compact token such
                        # as "12/19/2" without a usable box list. Parse the first
                        # valid number directly from OCR text order.
                        for i, txt in enumerate(txts):
                            val = self._parse_kill_number(txt)
                            if val is None:
                                continue
                            sc = float(scores[i]) if i < len(scores) else 0.5
                            if sc >= 0.22:
                                votes.append((int(val), sc, vi))
                                break
                if len(votes) >= 2 and votes[0][0] == votes[1][0]:
                    return votes[0][0], min(1.0, max(votes[0][1], votes[1][1]) + 0.12), "kda-ocr-consensus"
                # Only pay for a thresholded third pass when needed.
                _, bw = cv2.threshold(clahe, 160, 255, cv2.THRESH_BINARY)
                rr = self._run_report_ocr(engine, cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR))
                boxes_raw = getattr(rr, "boxes", None)
                txts_raw = getattr(rr, "txts", None)
                scores_raw = getattr(rr, "scores", None)
                boxes = [] if boxes_raw is None else list(boxes_raw)
                txts = [] if txts_raw is None else list(txts_raw)
                scores = [] if scores_raw is None else list(scores_raw)
                nums=[]
                for i, txt in enumerate(txts):
                    val=self._parse_kill_number(txt)
                    if val is None: continue
                    sc=float(scores[i]) if i < len(scores) else 0.5
                    if sc < 0.25: continue
                    xpos=float(np.asarray(boxes[i],dtype=np.float32)[:,0].mean()) if i < len(boxes) else float(i)
                    nums.append((xpos,int(val),sc))
                if nums:
                    nums.sort(key=lambda z:z[0]); votes.append((nums[0][1],nums[0][2],2))
                if votes:
                    counts={}
                    for val,sc,vi in votes:
                        counts.setdefault(val,[]).append(sc)
                    best_val,best_scores=max(counts.items(), key=lambda kv:(len(kv[1]),max(kv[1])))
                    if len(best_scores)>=2 or max(best_scores)>=0.62:
                        return int(best_val), float(max(best_scores)), "kda-ocr-vote"
            except Exception:
                LOGGER.exception("战报K专用OCR失败")

        # Last-resort local digit template, now on the corrected *tight* K crop.
        try:
            value, conf = self.digit_reader.read_hp_roi(tight_k)
            if value is not None and 0 <= int(value) <= 60 and float(conf) >= 0.64:
                return int(value), float(conf), "digit-template-fallback"
        except Exception:
            LOGGER.exception("战报K模板兜底失败")

        try:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(str(DEBUG_DIR / f"report_k_miss_{stamp}_card{card_idx+1}.png"), kda_roi)
        except Exception:
            pass
        return None, 0.0, "unread"

    @staticmethod
    def _report_stability_signature(cards, cont):
        try:
            parts = []
            for arr, size in ((cards, (240, 90)), (cont, (120, 40))):
                if arr is None or arr.size == 0:
                    continue
                gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
                parts.append(small)
            if not parts:
                return None
            return np.concatenate([p.reshape(-1) for p in parts]).astype(np.uint8)
        except Exception:
            return None

    @staticmethod
    def _report_signature_diff(sig_a, sig_b):
        if sig_a is None or sig_b is None:
            return 999.0
        try:
            a = np.asarray(sig_a, dtype=np.float32).reshape(-1)
            b = np.asarray(sig_b, dtype=np.float32).reshape(-1)
            if a.size != b.size or a.size == 0:
                return 999.0
            return float(np.mean(np.abs(a - b)))
        except Exception:
            return 999.0

    def _capture_report_snapshot(self, grabber, viewport, now, score):
        try:
            vx, vy, vw, vh = viewport
            t1 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            frozen_cards = _roi(full_frame, ROI_REPORT_CARDS) if full_frame is not None and getattr(full_frame, "size", 0) else None
            if frozen_cards is None or frozen_cards.size == 0:
                frozen_cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t1) * 1000)
            self.report_snapshot_full = None if full_frame is None else full_frame.copy()
            self.report_snapshot_cards = None if frozen_cards is None else frozen_cards.copy()
            if self.report_snapshot_cards is None or self.report_snapshot_cards.size == 0:
                raise RuntimeError("战报卡片快照为空")
            self.report_snapshot_locked = True
            self.report_snapshot_locked_at = now
            self.report_snapshot_score = float(score)
            self.report_waiting_result = False
            self.report_capture_active = False
            self.report_parse_status = "战报快照已锁定，后台解析中"
            self.report_attempts += 1
            LOGGER.info("战报高清快照已锁定 score=%.3f native=%sx%s；已等待结算动画定格", score, self.report_snapshot_cards.shape[1], self.report_snapshot_cards.shape[0])
            return True
        except Exception:
            LOGGER.exception("高清战报快照抓取失败")
            return False

    def _save_report_parse_debug(self, desc, data=None):
        try:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            out_dir = REPORT_DEBUG_DIR / f"reportdiag_{stamp}"
            out_dir.mkdir(parents=True, exist_ok=True)
            if self.report_snapshot_full is not None and getattr(self.report_snapshot_full, 'size', 0):
                cv2.imwrite(str(out_dir / "00_full_game_snapshot.png"), self.report_snapshot_full)
            if self.report_snapshot_cards is not None and getattr(self.report_snapshot_cards, 'size', 0):
                cv2.imwrite(str(out_dir / "01_locked_cards_snapshot.png"), self.report_snapshot_cards)
                ch, cw = self.report_snapshot_cards.shape[:2]
                for i in range(5):
                    x1 = int(i * cw / 5); x2 = int((i + 1) * cw / 5)
                    card = self.report_snapshot_cards[:, x1:x2]
                    if card.size:
                        cv2.imwrite(str(out_dir / f"02_card_{i+1}.png"), card)
                if data and data.get('card_index'):
                    idx = max(0, min(4, int(data.get('card_index')) - 1))
                    x1 = int(idx * cw / 5); x2 = int((idx + 1) * cw / 5)
                    card = self.report_snapshot_cards[:, x1:x2]
                    if card.size:
                        cv2.imwrite(str(out_dir / "03_my_card_crop.png"), card)
                        h, w = card.shape[:2]
                        nick_roi = card[int(h * 0.16):int(h * 0.42), int(w * 0.08):int(w * 0.92)]
                        kda_roi = card[int(h * 0.62):int(h * 0.92), int(w * 0.16):int(w * 0.84)]
                        if nick_roi.size:
                            cv2.imwrite(str(out_dir / "04_nickname_crop.png"), nick_roi)
                        if kda_roi.size:
                            cv2.imwrite(str(out_dir / "05_kda_crop.png"), kda_roi)
            info = [
                f"time={stamp}",
                f"status={desc}",
                f"nickname_cfg={self.cfg.get('vision', {}).get('player_nickname', '')}",
                f"layout_score={self.report_snapshot_score:.3f}",
                f"parse_attempts={self.report_parse_attempts}",
                f"stable_hits={self.report_candidate_stable_hits}",
                f"candidate_hits={self.report_candidate_hits}",
                f"signature_diff={self.report_last_signature_diff:.3f}",
            ]
            if data:
                for key in ("nickname", "nickname_similarity", "card_index", "kills", "kill_confidence", "kill_method"):
                    if key in data:
                        info.append(f"{key}={data.get(key)}")
            (out_dir / "90_parse_result.txt").write_text("\n".join(info), encoding="utf-8")
            self.last_report_debug_dir = str(out_dir)
            LOGGER.info("已导出战报诊断包: %s", out_dir)
        except Exception:
            LOGGER.exception("导出战报诊断包失败")

    def _find_player_card(self, cards_img, nickname, engine=None):
        if cards_img is None or cards_img.size == 0:
            return None
        target = self._norm_name(nickname)
        best = None
        ch, cw = cards_img.shape[:2]
        for card_idx in range(5):
            x1 = int(card_idx * cw / 5); x2 = int((card_idx + 1) * cw / 5)
            card = cards_img[:, x1:x2]
            if card.size == 0:
                continue
            h, w = card.shape[:2]
            roi = card[int(h * 0.16):int(h * 0.42), int(w * 0.08):int(w * 0.92)]
            if roi.size == 0:
                continue
            variants = []
            up = cv2.resize(roi, None, fx=2.3, fy=2.3, interpolation=cv2.INTER_CUBIC)
            variants.append(up)
            gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(gray)
            variants.append(cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR))
            _, bw = cv2.threshold(clahe, 168, 255, cv2.THRESH_BINARY)
            variants.append(cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR))
            for variant in variants:
                result = self._run_report_ocr(engine, variant)
                txts_raw = getattr(result, 'txts', None)
                scores_raw = getattr(result, 'scores', None)
                txts = [] if txts_raw is None else list(txts_raw)
                scores = [] if scores_raw is None else list(scores_raw)
                for i, txt in enumerate(txts):
                    sc = float(scores[i]) if i < len(scores) else 0.5
                    if sc < 0.22:
                        continue
                    sim = self._name_similarity(target, txt)
                    cand = (sim, sc, str(txt), card_idx)
                    if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                        best = cand
                if best and best[0] >= 0.80 and best[3] == card_idx:
                    break
        return best

    def _read_whole_match_report(self, cards_img):
        nickname = str(self.cfg.get("vision", {}).get("player_nickname", "")).strip()
        if not nickname:
            return None, "未填写游戏昵称"
        t0 = time.perf_counter()
        engine = self._get_report_ocr_engine()
        if engine is None:
            return None, "OCR引擎不可用"
        try:
            base = cards_img
            if base.shape[1] < 1500:
                scale = 1500.0 / max(1, base.shape[1])
                base = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            best = self._find_player_card(base, nickname, engine)
            if not best or best[0] < 0.58:
                self._save_report_parse_debug(f"未在5张卡片中找到昵称：{nickname}")
                return None, f"未在5张卡片中找到昵称：{nickname}"
            sim, nick_sc, nick_txt, card_idx = best
            kills, kill_conf, kill_method = self._read_kill_count_from_card(base, card_idx, engine)
            if kills is None:
                debug_data = {
                    "nickname": nick_txt,
                    "nickname_similarity": float(sim),
                    "card_index": int(card_idx + 1),
                }
                self._save_report_parse_debug("已找到本人卡片，但未读到击杀数K", debug_data)
                return None, "已找到本人卡片，但未读到击杀数K（诊断图已导出）"
            return {
                "nickname": nick_txt,
                "nickname_similarity": float(sim),
                "agent": "不校验角色",
                "kills": int(kills),
                "kill_confidence": float(kill_conf),
                "kill_method": str(kill_method),
                "evaluation": report_evaluation(int(kills)),
                "card_index": int(card_idx + 1),
            }, "ok"
        except Exception as e:
            LOGGER.exception("整局结算页 OCR 失败")
            self._save_report_parse_debug(f"OCR错误:{type(e).__name__}")
            return None, f"OCR错误:{type(e).__name__}"
        finally:
            self._ema_timing("ocr", (time.perf_counter() - t0) * 1000)

    def _scan_whole_match_report(self, grabber, viewport, now):
        if not bool(self.cfg.get("vision", {}).get("report_enabled", True)):
            return
        if not self.report_armed or self.report_done:
            return
        if self.report_snapshot_locked:
            return
        if self.match_context and not self.report_waiting_result:
            return
        if not self.report_waiting_result:
            self._start_report_wait(now, "armed outside live HUD")
        if not self.report_waiting_result or now < self.report_retry_after:
            return

        # Lightweight radar only. No OCR happens here.
        t0 = time.perf_counter()
        cards_radar = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS_RADAR, (820,270))
        cont = _grab_relative_roi(grabber, viewport, ROI_REPORT_CONTINUE, (260,100))
        self._ema_timing("capture", (time.perf_counter() - t0) * 1000)
        coarse_ok, layout_score = self._report_layout_candidate(cards_radar, cont)
        five_ok, card_quality, card_counts, card_densities = self._report_five_card_completeness(cards_radar)

        self.last_report_layout_score = float(layout_score)
        self.report_wait_samples += 1
        self.perf_scans += 1
        self.report_capture_best_score = max(self.report_capture_best_score, float(layout_score))

        strict_ok = bool(coarse_ok and five_ok)
        cache_seconds = max(1.0, min(5.0, float(self.cfg.get("vision", {}).get("report_candidate_cache_seconds", 2.8))))

        if strict_ok:
            # Critical V0.4.10.2 change: the first genuine five-card frame is
            # owned immediately. The user may click Continue 0.5s later and the
            # frame is already safe in memory.
            self._cache_report_candidate(grabber, viewport, now, layout_score, card_quality, card_counts)

            sig = self._report_stability_signature(cards_radar, cont)
            stable_need = max(1, int(self.cfg.get("vision", {}).get("report_settle_min_hits", 2)))
            diff_thr = float(self.cfg.get("vision", {}).get("report_settle_diff_threshold", 2.6))
            self.report_candidate_hits += 1
            if self.report_candidate_signature is None:
                self.report_candidate_stable_hits = 0
                self.report_last_signature_diff = 999.0
            else:
                diff = self._report_signature_diff(sig, self.report_candidate_signature)
                self.report_last_signature_diff = float(diff)
                if diff <= diff_thr:
                    self.report_candidate_stable_hits += 1
                else:
                    self.report_candidate_stable_hits = 0
            self.report_candidate_signature = sig

            self.report_parse_status = (
                f"五卡候选已缓存，等待动画定格"
                f"（稳定 {self.report_candidate_stable_hits}/{stable_need}）"
            )

            # If the five-card page survives two near-identical samples, lock
            # the best cached native frame. With 100ms scanning this is usually
            # ~0.2-0.3s after the page is fully visible.
            if self.report_candidate_stable_hits >= stable_need:
                if self._lock_best_report_candidate(now, "five-card page settled"):
                    pass
                else:
                    return
            else:
                return
        else:
            # If a genuine five-card frame was cached and the screen suddenly
            # changes (typically the user clicked Continue), lock the cached
            # frame instead of photographing the new reward/progression page.
            if (self.report_best_candidate_cards is not None and
                    now - float(self.report_best_candidate_at or now) <= cache_seconds):
                if not self._lock_best_report_candidate(now, "five-card page disappeared / Continue clicked"):
                    return
            else:
                # No real scorecard has ever been seen. Do NOT let the post-game
                # reward page become a candidate just because it has dark panels
                # and a red button.
                self.report_candidate_hits = 0
                self.report_candidate_stable_hits = 0
                self.report_candidate_signature = None
                self.report_last_signature_diff = 0.0
                self.report_parse_status = "等待五人结算页"
                return

        # Everything below uses the frozen candidate. Current screen no longer matters.
        data, desc = self._read_whole_match_report(self.report_snapshot_cards)
        self.report_parse_attempts += 1
        if data is None:
            self.report_parse_status = f"解析失败（快照已保留）：{desc}"
            LOGGER.warning("战报快照解析失败，但保持锁定 | %s", desc)
            try:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                full_debug = self.report_snapshot_full
                if full_debug is not None and getattr(full_debug, "size", 0):
                    cv2.imwrite(str(DEBUG_DIR / f"report_locked_parse_fail_{stamp}.png"), full_debug)
                else:
                    cv2.imwrite(str(DEBUG_DIR / f"report_locked_parse_fail_{stamp}.png"), self.report_snapshot_cards)
                cv2.imwrite(str(DEBUG_DIR / f"report_locked_cards_parse_fail_{stamp}.png"), self.report_snapshot_cards)
            except Exception:
                pass
            return

        new_k = int(data.get("kills"))
        self.last_report_nickname = data.get("nickname", "-")
        self.last_report_agent = data.get("agent", "-")
        self.last_report_kills = new_k
        self.report_pending_kills = new_k
        self.report_kill_confirm_hits = 2 if str(data.get("kill_method", "")).startswith("kda-ocr") else 1
        self.report_done = True
        self.report_armed = False
        self.report_armed_since = 0.0
        self.report_last_live_seen = 0.0
        self.report_waiting_result = False
        self.report_capture_active = False
        self.report_retry_after = now + 30.0
        self.report_parse_status = "解析完成，战报已生成"
        LOGGER.info("整局战报完成 | card=%s nickname=%s sim=%.2f kills=%s method=%s conf=%.2f",
                    data.get("card_index"), data.get("nickname"), data.get("nickname_similarity", 0),
                    new_k, data.get("kill_method"), data.get("kill_confidence", 0))
        self.report_ready.emit(data)

    def _build_snapshot(self, game_found=True, foreground=True, paused=False, error=None):
        data={
            "game_found":game_found,"foreground":foreground,"paused":paused,"alive":self.alive_state,
            "alive_score":self.last_alive_score,"hp":self.last_hp,"hp_conf":self.last_hp_conf,"low_hp":self.low_state,
            "hp_history":list(self.hp_history),"hp_enter_votes":self.hp_enter_votes,"hp_exit_votes":self.hp_exit_votes,
            "hp_occluded":self.hp_occluded,"hp_guard_reason":self.hp_guard_reason,"hp_last_confirmed":self.hp_last_confirmed,
            "hp_vote_window":int(self.cfg.get("vision",{}).get("hp_vote_window",5)),
            "kill_count":self.last_kill_count,"kill_score":self.last_kill_score,"nickname_match":self.last_nickname_match,
            "ocr_texts":self.last_ocr_texts,"win_score":self.last_win_score,"loss_score":self.last_loss_score,
            "state":self.current_display_state,"window_title":self.window_title,
            "match_context":self.match_context,"phase":self.phase,"context_votes":self.context_votes,
            "context_left":self.context_left_score,"context_center":self.context_center_score,"context_right":self.context_right_score,
            "death_suspect":self.death_suspect_since is not None,"death_latched":self.death_latched,
            "death_report_score":self.last_death_report_score,"death_evidence":self.last_death_evidence,
            "mode":str(self.cfg.get("vision",{}).get("mode","ultra_low")),"scan_fps":self.scan_fps,
            "cpu_estimate":self.cpu_estimate,"ocr_triggers":self.ocr_trigger_count,"hp_reads":self.hp_read_count,
            "capture_backend":self.backend_name,"timings":dict(self.timings),"worker_busy":self.worker_busy,
            "queue_length":0,"skipped_cycles":self.skipped_cycles,
            "round_self_kills":self.round_self_kills,
            "enemy_alive":self.enemy_alive,
            "enemy_alive_scores":[round(float(x),1) for x in self.enemy_alive_scores],
            "enemy_alive_confident":self.enemy_alive_confident,
            "self_final_kill_candidate":self.self_final_kill_candidate,
            "self_final_kill_confirmed":self.self_final_kill_confirmed,
            "highlight_candidate":self.highlight_candidate,
            "highlight_triggered":self.highlight_triggered,
            "highlight_event_id":self.highlight_event_id,
            "highlight_reason":self.highlight_last_reason,
            "report_armed":self.report_armed,"report_done":self.report_done,"report_layout_score":self.last_report_layout_score,
            "report_nickname":self.last_report_nickname,"report_agent":self.last_report_agent,"report_kills":self.last_report_kills,
            "report_waiting_result":self.report_waiting_result,"report_wait_samples":self.report_wait_samples,
            "report_capture_active":self.report_capture_active,"report_snapshot_locked":self.report_snapshot_locked,
            "report_snapshot_score":self.report_snapshot_score,"report_capture_samples":self.report_capture_samples,
            "report_candidate_hits":self.report_candidate_hits,"report_stable_hits":self.report_candidate_stable_hits,
            "report_candidate_cached":self.report_best_candidate_cards is not None,
            "report_candidate_quality":self.report_best_candidate_quality,
            "report_candidate_counts":list(self.report_best_candidate_counts),
            "report_signature_diff":self.report_last_signature_diff,
            "report_parse_status":self.report_parse_status,"report_parse_attempts":self.report_parse_attempts,
        }
        if error: data["error"]=str(error)
        return data

    def _save_debug_current(self, grabber, viewport, data):
        try:
            vx,vy,vw,vh=viewport; frame=grabber.grab(vx,vy,vw,vh); frame=cv2.resize(frame,(1600,900),interpolation=cv2.INTER_AREA)
            img=frame.copy(); h,w=img.shape[:2]
            boxes={"ctxL":ROI_CONTEXT_LEFT,"ctxC":ROI_CONTEXT_CENTER,"ctxR":ROI_CONTEXT_RIGHT,"alive":ROI_ALIVE,"hp":ROI_HP,"kill":ROI_KILL_OCR,"death":ROI_DEATH_REPORT,"result":ROI_RESULT,"report":ROI_REPORT_CARDS_RADAR}
            colors={"ctxL":(0,255,160),"ctxC":(0,255,160),"ctxR":(0,255,160),"alive":(0,255,0),"hp":(0,180,255),"kill":(255,200,0),"death":(0,80,255),"result":(255,0,255),"report":(160,255,255)}
            for name,b in boxes.items():
                x1,y1,x2,y2=b; cv2.rectangle(img,(int(w*x1),int(h*y1)),(int(w*x2),int(h*y2)),colors[name],2)
            t=data.get("timings",{})
            lines=[
                f"phase={data.get('phase')} match={data.get('match_context')} votes={data.get('context_votes')} L/C/R={data.get('context_left',0):.2f}/{data.get('context_center',0):.2f}/{data.get('context_right',0):.2f}",
                f"backend={data.get('capture_backend')} mode={data.get('mode')} cpu~={data.get('cpu_estimate',0):.1f}% scan={data.get('scan_fps',0):.2f}",
                f"alive={data.get('alive')} score={data.get('alive_score',0):.3f} hp={data.get('hp')} hist={data.get('hp_history')} low={data.get('low_hp')} dead={data.get('death_latched')}",
                f"deathPanel={data.get('death_report_score',0):.3f} evidence={data.get('death_evidence')}",
                f"kill={data.get('kill_count')} nick={data.get('nickname_match')} win={data.get('win_score',0):.3f} loss={data.get('loss_score',0):.3f}",
                f"ms cap={t.get('capture',0):.2f} ctx={t.get('context',0):.2f} alive={t.get('alive',0):.2f} hp={t.get('hp',0):.2f} kill={t.get('kill',0):.2f} death={t.get('death',0):.2f} result={t.get('result',0):.2f} ocr={t.get('ocr',0):.2f}",
            ]
            y=30
            for line in lines:
                cv2.putText(img,line,(16,y),cv2.FONT_HERSHEY_SIMPLEX,0.52,(0,0,0),4,cv2.LINE_AA); cv2.putText(img,line,(16,y),cv2.FONT_HERSHEY_SIMPLEX,0.52,(255,255,255),1,cv2.LINE_AA); y+=24
            path=DEBUG_DIR/f"vision_v041_{time.strftime('%Y%m%d_%H%M%S')}.png"; cv2.imwrite(str(path),img); LOGGER.info("已保存 V0.4 调试帧: %s",path)
        except Exception:
            LOGGER.exception("保存识别调试帧失败")

    def _refresh_window(self, now):
        if self.hwnd and _client_rect_for_hwnd(self.hwnd) and now-self.last_window_lookup<2.0: return True
        found=_find_valorant_window(); self.last_window_lookup=now
        if not found: self.hwnd=None; self.window_title=""; return False
        self.hwnd,_,_,_,_,self.window_title=found; return True

    def run(self):
        try:
            cv2.setNumThreads(1); cv2.ocl.setUseOpenCL(False)
        except Exception: pass
        grabber=None
        try:
            grabber=ScreenGrabber(bool(self.cfg.get("vision",{}).get("prefer_dxcam",True)))
            self.backend_name=grabber.backend
        except Exception as e:
            LOGGER.exception("截图后端初始化失败")
            self.snapshot.emit({"game_found":False,"error":f"capture init: {e}"}); return

        LOGGER.info("VALORANT V0.6 Voice Mouth + Continuous Puppet V2 识别线程启动 backend=%s",self.backend_name)
        try:
            while not self._stop_event.is_set():
                now=time.monotonic(); self._update_perf(now); vcfg=self.cfg.get("vision",{})
                if not bool(vcfg.get("enabled",True)):
                    if now-self.last_snapshot_emit>0.9:
                        data=self._build_snapshot(game_found=False,paused=True); data["disabled"]=True; self.last_snapshot=data; self.snapshot.emit(data); self.last_snapshot_emit=now
                    self._stop_event.wait(0.45); continue
                if not self._refresh_window(now):
                    self.match_context=False; self.context_hits=self.context_misses=0; self._reset_match_state("VALORANT not found")
                    if now-self.last_snapshot_emit>0.9:
                        data=self._build_snapshot(game_found=False); self.snapshot.emit(data); self.last_snapshot_emit=now
                    self._stop_event.wait(0.50); continue
                foreground=True
                if sys.platform=="win32":
                    try: foreground=int(ctypes.windll.user32.GetForegroundWindow())==int(self.hwnd)
                    except Exception: pass
                if bool(vcfg.get("pause_when_background",True)) and not foreground:
                    if self.background_since is None: self.background_since=now
                    if now-self.background_since>1.0: self._request_state("idle","background sleep")
                    if now-self.last_snapshot_emit>0.8:
                        self.snapshot.emit(self._build_snapshot(game_found=True,foreground=False,paused=True)); self.last_snapshot_emit=now
                    self._stop_event.wait(0.45); continue
                self.background_since=None
                client=_client_rect_for_hwnd(self.hwnd)
                if not client: self.hwnd=None; self._stop_event.wait(0.35); continue
                viewport=_viewport_from_client(client)
                context_i,alive_i,hp_i,kill_i,result_i,death_i,emit_i=self._mode_intervals()

                if self.worker_busy:
                    self.skipped_cycles+=1; self._stop_event.wait(0.08); continue
                self.worker_busy=True
                try:
                    if now>=self.next_context:
                        self._scan_context(grabber,viewport,now); self.next_context=now+context_i
                    if self.match_context:
                        if now>=self.next_alive: self._scan_alive(grabber,viewport,now); self.next_alive=now+alive_i
                        if now>=self.next_hp: self._scan_hp(grabber,viewport,now); self.next_hp=now+hp_i
                        if now>=self.next_kill: self._scan_kill_probe(grabber,viewport,now); self.next_kill=now+kill_i
                        if now>=self.next_death: self._scan_death_confirmation(grabber,viewport,now); self.next_death=now+death_i
                        if now>=self.next_enemy_alive:
                            self._scan_enemy_alive_v090(grabber,viewport,now)
                            self.next_enemy_alive=now+0.70
                    if now>=self.next_result:
                        self._scan_result(grabber,viewport,now); self.next_result=now+result_i
                    if now>=self.next_report:
                        self._scan_whole_match_report(grabber, viewport, now)
                        if self.report_capture_active:
                            # Short high-frequency retry only after a result-like
                            # frame has already appeared.  Still layout-only.
                            cap_ms=max(120,min(400,int(vcfg.get("report_capture_interval_ms",160))))
                            self.next_report=now + cap_ms/1000.0
                        elif self.report_waiting_result:
                            # First 20s after HUD loss: ~5 Hz cheap radar so even a
                            # one-second result page is very likely to be captured.
                            # Afterwards automatically fall back below 2 Hz.
                            fast_s=max(5,min(60,int(vcfg.get("report_wait_fast_seconds",20))))
                            elapsed=max(0.0, now-float(self.report_wait_started or now))
                            if elapsed <= fast_s:
                                wait_ms=max(150,min(500,int(vcfg.get("report_wait_fast_interval_ms",200))))
                            else:
                                wait_ms=max(500,min(1600,int(vcfg.get("report_wait_slow_interval_ms",850))))
                            self.next_report=now + wait_ms/1000.0
                        else:
                            self.next_report=now + max(1.0, int(vcfg.get("report_scan_interval_ms",1400))/1000.0)
                    self._settle_state(now); data=self._build_snapshot(game_found=True,foreground=True,paused=False); self.last_snapshot=data
                    if self._debug_event.is_set(): self._debug_event.clear(); self._save_debug_current(grabber,viewport,data)
                    if now-self.last_snapshot_emit>=emit_i: self.snapshot.emit(data); self.last_snapshot_emit=now
                except Exception as e:
                    LOGGER.exception("V0.6 识别处理失败")
                    if now-self.last_snapshot_emit>0.9: self.snapshot.emit(self._build_snapshot(game_found=True,foreground=foreground,error=e)); self.last_snapshot_emit=now
                finally:
                    self.worker_busy=False

                due=[self.next_context,self.next_result,self.next_report]
                if self.match_context:
                    due.extend([self.next_alive,self.next_hp,self.next_kill,self.next_death,self.next_enemy_alive])
                next_due=min(due)
                wait_for=max(0.06,min(0.28,next_due-time.monotonic())); self._stop_event.wait(wait_for)
        finally:
            if grabber: grabber.close()
            LOGGER.info("VALORANT V0.6 Voice Mouth + Continuous Puppet V2 识别线程结束")


def _sample_green_key_rgb(rgb):
    """Estimate the greenscreen color from frame corners. Falls back to pure
    green when corners are not green-dominant. This keeps Sage's teal outfit
    because the key model requires strong green dominance, not merely hue.
    """
    h, w = rgb.shape[:2]
    sy = max(2, int(h * 0.07)); sx = max(2, int(w * 0.07))
    samples = np.concatenate([
        rgb[:sy, :sx].reshape(-1, 3), rgb[:sy, -sx:].reshape(-1, 3),
        rgb[-sy:, :sx].reshape(-1, 3), rgb[-sy:, -sx:].reshape(-1, 3)
    ], axis=0)
    key = np.median(samples, axis=0).astype(np.float32)
    r, g, b = key.tolist()
    if g - max(r, b) < 45 or g < 120:
        key = np.array([0.0, 255.0, 0.0], dtype=np.float32)
    return key


def _green_key_rgba(rgb, key_rgb):
    arr = rgb.astype(np.float32)
    key = np.asarray(key_rgb, dtype=np.float32).reshape(1, 1, 3)
    dist = np.linalg.norm(arr - key, axis=2)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    dominance = g - np.maximum(r, b)

    # A pixel is keyed only when it is both close to the sampled screen color
    # and strongly green-dominant. Turquoise/teal clothing has much smaller
    # green-vs-blue dominance and therefore remains opaque.
    close = np.clip((118.0 - dist) / 92.0, 0.0, 1.0)
    dom = np.clip((dominance - 22.0) / 125.0, 0.0, 1.0)
    keyness = close * dom
    alpha = np.clip(255.0 * (1.0 - keyness), 0, 255)
    hard_bg = (dist < 30.0) & (dominance > 90.0)
    alpha[hard_bg] = 0.0

    # Despill only where the matte says the pixel is near the screen edge.
    edge = keyness > 0.06
    max_rb = np.maximum(r, b)
    allowed_g = max_rb + 10.0 + 34.0 * (alpha / 255.0)
    g2 = np.where(edge, np.minimum(g, allowed_g), g)
    out = np.dstack([r, g2, b, alpha])
    return np.clip(out, 0, 255).astype(np.uint8)


def _add_soft_white_glow(rgba, outline_px=1, glow_px=6, outline_strength=0.42, glow_strength=0.24):
    """Add a subtle white rim + soft outer glow *behind* an already keyed RGBA frame.

    The source subject RGB/alpha is preserved.  The effect is generated only
    outside the existing alpha matte, so facial features, clothing and teal
    energy details are not washed out.  This is intentionally subtle: a thin
    white edge improves separation, while a broader low-opacity halo helps the
    desktop pet remain readable on dark or busy game backgrounds.
    """
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        return rgba
    src = rgba.astype(np.float32)
    alpha = src[..., 3] / 255.0
    if float(alpha.max()) <= 0.001:
        return rgba

    a8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    opx = max(1, int(outline_px))
    gpx = max(opx + 1, int(glow_px))

    # Thin rim from a small dilation.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (opx * 2 + 1, opx * 2 + 1))
    dilated = cv2.dilate(a8, k, iterations=1).astype(np.float32) / 255.0
    outline = np.clip(dilated - alpha, 0.0, 1.0) * float(outline_strength)

    # Wider, feathered halo.  Blur a slightly larger dilation to avoid a harsh
    # neon-looking edge. Keep it strictly outside the original subject matte.
    kg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gpx * 2 + 1, gpx * 2 + 1))
    expanded = cv2.dilate(a8, kg, iterations=1)
    sigma = max(1.2, gpx * 0.62)
    blurred = cv2.GaussianBlur(expanded, (0, 0), sigmaX=sigma, sigmaY=sigma).astype(np.float32) / 255.0
    halo = np.clip(blurred - alpha, 0.0, 1.0) * float(glow_strength)
    white_a = np.maximum(outline, halo) * (1.0 - alpha)

    # Straight-alpha source-over composition: original subject over a white
    # halo layer.  Subject pixels remain unchanged; only outside pixels become
    # softly white/transparent.
    out_a = alpha + white_a * (1.0 - alpha)
    numer = src[..., :3] * alpha[..., None] + 255.0 * white_a[..., None] * (1.0 - alpha[..., None])
    denom = np.maximum(out_a[..., None], 1e-6)
    out_rgb = np.where(out_a[..., None] > 1e-6, numer / denom, 0.0)
    out = np.dstack([out_rgb, out_a * 255.0])
    return np.clip(out, 0, 255).astype(np.uint8)


def convert_greenscreen_video(src, dst, max_width=420, target_fps=12):
    """One-time import pipeline: video -> transparent animated WebP.

    Source is first copied to an ASCII temp path because OpenCV/FFmpeg builds on
    some Windows machines still dislike non-ASCII source paths. Animated WebP
    preserves full alpha and avoids GIF's 1-bit transparency/256-color halo.
    """
    src = Path(src); dst = Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = CACHE_DIR / "_import_tmp"; tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_src = tmp_dir / ("source" + (src.suffix.lower() or ".mp4"))
    shutil.copy2(src, tmp_src)
    cap = cv2.VideoCapture(str(tmp_src))
    try:
        if not cap.isOpened():
            raise RuntimeError("无法读取视频，请确认文件没有损坏")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not np.isfinite(fps) or fps <= 0.5:
            fps = 30.0
        out_fps = max(1.0, min(float(target_fps), fps))
        next_t = 0.0; idx = 0; frames = []; key_rgb = None
        max_frames = int(out_fps * 45)  # safety cap: 45s per desktop-pet clip
        while len(frames) < max_frames:
            ok, bgr = cap.read()
            if not ok:
                break
            t = idx / fps; idx += 1
            if t + 1e-6 < next_t:
                continue
            next_t += 1.0 / out_fps
            h, w = bgr.shape[:2]
            if w > max_width:
                nh = max(2, int(round(h * max_width / w)))
                bgr = cv2.resize(bgr, (max_width, nh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if key_rgb is None:
                key_rgb = _sample_green_key_rgb(rgb)
                LOGGER.info("绿幕自动取色 %s -> RGB(%.0f,%.0f,%.0f)", src.name, *key_rgb.tolist())
            rgba = _green_key_rgba(rgb, key_rgb)
            rgba = _add_soft_white_glow(rgba)
            frames.append(Image.fromarray(rgba, "RGBA"))
        if not frames:
            raise RuntimeError("视频没有可读取帧")
        duration = max(20, int(round(1000.0 / out_fps)))
        kwargs = dict(save_all=True, append_images=frames[1:], duration=duration,
                      loop=1, lossless=True, quality=100, method=4)
        try:
            frames[0].save(dst, "WEBP", exact=True, **kwargs)
        except TypeError:
            frames[0].save(dst, "WEBP", **kwargs)
        LOGGER.info("绿幕视频导入完成: %s -> %s | %d帧 @ %.1ffps", src, dst, len(frames), out_fps)
        return len(frames), out_fps
    finally:
        cap.release()
        try: tmp_src.unlink(missing_ok=True)
        except Exception: pass


def add_glow_to_transparent_animation(src, dst):
    """Upgrade an already-transparent animated WebP with the V0.4.8 white rim/glow.

    This is used for assets imported by V0.4.4 so users do not need the original
    greenscreen source just to gain the new outline effect.
    """
    src = Path(src); dst = Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    frames = []
    durations = []
    try:
        total = int(getattr(im, "n_frames", 1) or 1)
        for i in range(total):
            im.seek(i)
            frame = im.convert("RGBA")
            arr = np.array(frame, dtype=np.uint8)
            arr = _add_soft_white_glow(arr)
            frames.append(Image.fromarray(arr, "RGBA"))
            durations.append(int(im.info.get("duration", 83) or 83))
    finally:
        try: im.close()
        except Exception: pass
    if not frames:
        raise RuntimeError("透明动画没有可读取帧")
    kwargs = dict(save_all=True, append_images=frames[1:], duration=durations,
                  loop=1, lossless=True, quality=100, method=4)
    try:
        frames[0].save(dst, "WEBP", exact=True, **kwargs)
    except TypeError:
        frames[0].save(dst, "WEBP", **kwargs)
    return len(frames)



class AssetDropLabel(QLabel):
    """Per-state drop target for batch importing green-screen videos."""
    files_dropped = Signal(str, object)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setAcceptDrops(True)
        self.setMinimumHeight(46)
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._apply_drop_style(False)
        self.setToolTip("可一次拖入多支视频到本行；支持 MP4 / MOV / MKV / WebM / AVI / M4V，最多补到 20 支。")

    def _apply_drop_style(self, active):
        if active:
            self.setStyleSheet(
                "QLabel{border:2px dashed #5fbfb1;border-radius:8px;"
                "background:rgba(95,191,177,32);padding:6px;}"
            )
        else:
            self.setStyleSheet(
                "QLabel{border:1px dashed rgba(110,110,110,110);border-radius:8px;"
                "background:rgba(255,255,255,10);padding:6px;}"
            )

    def _accepted_paths(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            return []
        out = []
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                out.append(str(p))
        return out

    def dragEnterEvent(self, event):
        if self._accepted_paths(event):
            self._apply_drop_style(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepted_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._apply_drop_style(False)
        event.accept()

    def dropEvent(self, event):
        paths = self._accepted_paths(event)
        self._apply_drop_style(False)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(self.state, paths)
        else:
            event.ignore()


class ReportLayoutPreview(QWidget):
    layout_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(430, 430)
        self.setMouseTracking(True)
        self.image = QPixmap()
        self.layout_cfg = dict(DEFAULT_REPORT_LAYOUT)
        self.kills = 20
        self.evaluation = report_evaluation(20)
        self.font_family = "Microsoft YaHei"
        self._mode = None
        self._last = None
        self.setStyleSheet("background:#24282d;border:1px solid #555;border-radius:6px;")

    def set_image_path(self, path):
        pix=QPixmap()
        try:
            src=Path(str(path or ""))
            if src.exists():
                im=Image.open(src)
                try:
                    n=int(getattr(im,"n_frames",1) or 1)
                    if n>1: im.seek(n//2)
                    frame=im.convert("RGBA")
                    data=frame.tobytes("raw","RGBA")
                    qi=QImage(data,frame.width,frame.height,QImage.Format.Format_RGBA8888).copy()
                    pix=QPixmap.fromImage(qi)
                finally:
                    try: im.close()
                    except Exception: pass
        except Exception:
            LOGGER.exception("读取战报模板预览失败: %s",path)
        self.image=pix; self.update()

    def set_layout(self, layout):
        self.layout_cfg=normalized_report_layout(layout); self.update()

    def set_sample(self, kills, evaluation):
        self.kills=int(kills); self.evaluation=str(evaluation or ""); self.update()

    def set_font_family(self, family):
        self.font_family=str(family or "Microsoft YaHei"); self.update()

    def _image_rect(self):
        if self.image.isNull(): return QRect(12,12,max(1,self.width()-24),max(1,self.height()-24))
        iw,ih=self.image.width(),self.image.height(); aw=max(1,self.width()-24); ah=max(1,self.height()-24)
        scale=min(aw/iw,ah/ih); w=int(iw*scale); h=int(ih*scale)
        return QRect((self.width()-w)//2,(self.height()-h)//2,w,h)

    def _board_rect(self):
        ir=self._image_rect(); l=self.layout_cfg
        return QRect(int(ir.x()+(l['x']+l['offset_x'])*ir.width()),int(ir.y()+(l['y']+l['offset_y'])*ir.height()),max(12,int(l['w']*ir.width())),max(12,int(l['h']*ir.height())))

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        ir=self._image_rect()
        if not self.image.isNull(): p.drawPixmap(ir,self.image,self.image.rect())
        overlay=render_report_text_pixmap(ir.width(),ir.height(),self.layout_cfg,self.kills,self.evaluation,self.font_family)
        p.drawPixmap(ir.x(),ir.y(),overlay)
        br=self._board_rect(); pen=QPen(QColor(52,205,163),2,Qt.PenStyle.DashLine); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(br)
        p.setBrush(QColor(52,205,163)); p.setPen(Qt.PenStyle.NoPen); p.drawRect(br.right()-6,br.bottom()-6,12,12)
        p.end()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton: return
        br=self._board_rect(); pos=event.position().toPoint()
        handle=QRect(br.right()-14,br.bottom()-14,28,28)
        if handle.contains(pos): self._mode='resize'
        elif br.contains(pos): self._mode='move'
        else: self._mode=None
        self._last=pos

    def mouseMoveEvent(self,event):
        if not self._mode or self._last is None: return
        pos=event.position().toPoint(); dx=pos.x()-self._last.x(); dy=pos.y()-self._last.y(); self._last=pos
        ir=self._image_rect(); l=dict(self.layout_cfg)
        if ir.width()<=0 or ir.height()<=0: return
        if self._mode=='move':
            l['x']=l['x']+dx/ir.width(); l['y']=l['y']+dy/ir.height()
        else:
            l['w']=l['w']+dx/ir.width(); l['h']=l['h']+dy/ir.height()
        self.layout_cfg=normalized_report_layout(l); self.layout_changed.emit(dict(self.layout_cfg)); self.update()

    def mouseReleaseEvent(self,event):
        self._mode=None; self._last=None


class ReportTemplateDialog(QDialog):
    def __init__(self, cfg, pet, asset_path=None, parent=None):
        super().__init__(parent)
        self.cfg=cfg; self.pet=pet; self.assets=[p for p in _asset_list(cfg.get('assets',{}).get('report')) if Path(p).exists()]
        if not self.assets: self.assets=_asset_list(bundled_assets().get('report'))
        self.current_asset=str(asset_path or (self.assets[0] if self.assets else ''))
        self.current_layout=get_report_layout(cfg,self.current_asset)
        self._dirty=False; self._syncing=False
        self.setWindowTitle('小美丽｜战报白板模板')
        self.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png'))); self.resize(960,690)
        root=QVBoxLayout(self)
        top=QHBoxLayout(); top.addWidget(QLabel('战报素材：'))
        self.asset_combo=QComboBox()
        for p in self.assets: self.asset_combo.addItem(Path(p).name,p)
        idx=self.asset_combo.findData(self.current_asset); self.asset_combo.setCurrentIndex(max(0,idx))
        self.asset_combo.currentIndexChanged.connect(self._asset_changed); top.addWidget(self.asset_combo,1)
        top.addWidget(HelpBadge('每支战报视频拥有独立白板模板。白板静止时只需设置一次文字区域，之后所有战报都会自动套用。'))
        root.addLayout(top)
        body=QHBoxLayout(); root.addLayout(body,1)
        self.preview=ReportLayoutPreview(); self.preview.layout_changed.connect(self._preview_layout_changed); body.addWidget(self.preview,3)
        controls=QWidget(); form=QFormLayout(controls); body.addWidget(controls,2)
        self.spins={}
        specs=[('x','区域 X (%)',0,95,0.1),('y','区域 Y (%)',0,95,0.1),('w','区域宽度 (%)',5,100,0.1),('h','区域高度 (%)',5,100,0.1),('offset_x','水平偏移 (%)',-30,30,0.1),('offset_y','垂直偏移 (%)',-30,30,0.1),('line1_scale','第一行字号倍率',45,220,1),('line2_scale','第二行字号倍率',45,220,1),('line_spacing','行距 (%)',-10,25,0.1)]
        for key,label,mn,mx,step in specs:
            sp=QDoubleSpinBox(); sp.setRange(mn,mx); sp.setSingleStep(step); sp.setDecimals(1)
            sp.valueChanged.connect(lambda v,k=key:self._spin_changed(k,v)); self.spins[key]=sp; form.addRow(label,sp)
        self.auto_fill=QCheckBox('自动铺满（推荐）'); self.auto_fill.setChecked(True); self.auto_fill.toggled.connect(self._check_changed); form.addRow(self.auto_fill)
        self.outline=QDoubleSpinBox(); self.outline.setRange(0,5); self.outline.setSingleStep(0.5); self.outline.setDecimals(1); self.outline.valueChanged.connect(lambda v:self._spin_changed('outline_width',v)); form.addRow('淡描边 (px)',self.outline)
        sample_box=QGroupBox('四档预览'); sg=QGridLayout(sample_box)
        for i,k in enumerate((5,10,20,30)):
            b=QPushButton(f'{k}杀'); b.clicked.connect(lambda checked=False,n=k:self._set_sample_kills(n)); sg.addWidget(b,0,i)
        form.addRow(sample_box)
        auto_btn=QPushButton('一键自动铺满白板'); auto_btn.clicked.connect(self._auto_fill_default); form.addRow(auto_btn)
        reset_btn=QPushButton('恢复默认模板'); reset_btn.clicked.connect(self._reset_default); form.addRow(reset_btn)
        play_btn=QPushButton('播放动画预览'); play_btn.clicked.connect(self._play_preview); form.addRow(play_btn)
        help_label=QLabel('提示：可直接拖动绿色虚线框移动文字区；拖右下角绿色方块可缩放区域。\n“评价：”前缀已删除，白板只显示评价正文。')
        help_label.setWordWrap(True); help_label.setStyleSheet('color:#666;'); form.addRow(help_label)
        bottom=QHBoxLayout(); self.status=QLabel(''); self.status.setStyleSheet('color:#278a74;'); bottom.addWidget(self.status); bottom.addStretch(1)
        close=QPushButton('关闭'); close.clicked.connect(self.reject); self.save_btn=QPushButton('保存并应用'); self.save_btn.setEnabled(False); self.save_btn.clicked.connect(self._save)
        bottom.addWidget(close); bottom.addWidget(self.save_btn); root.addLayout(bottom)
        self._load_current()

    def _font_family(self):
        try:
            self.pet.report_overlay.reload_font(); return self.pet.report_overlay.font_family
        except Exception: return 'Microsoft YaHei'

    def _load_current(self):
        self.current_layout=get_report_layout(self.cfg,self.current_asset); self._syncing=True
        for k,sp in self.spins.items():
            v=float(self.current_layout.get(k,0.0)); sp.setValue(v*100 if k in ('x','y','w','h','offset_x','offset_y','line_spacing') else v*100)
        self.outline.setValue(float(self.current_layout.get('outline_width',0.0))); self.auto_fill.setChecked(bool(self.current_layout.get('auto_fill',True))); self._syncing=False
        self.preview.set_image_path(self.current_asset); self.preview.set_layout(self.current_layout); self.preview.set_font_family(self._font_family()); self._set_sample_kills(20,mark=False)
        self._dirty=False; self.save_btn.setEnabled(False); self.status.setText('')

    def _asset_changed(self):
        self.current_asset=str(self.asset_combo.currentData() or ''); self._load_current()

    def _mark_dirty(self):
        if self._syncing:return
        self._dirty=True; self.save_btn.setEnabled(True); self.status.setText('未保存')

    def _spin_changed(self,key,value):
        if self._syncing:return
        l=dict(self.current_layout)
        if key in ('x','y','w','h','offset_x','offset_y','line_spacing','line1_scale','line2_scale'): l[key]=float(value)/100.0
        else: l[key]=float(value)
        self.current_layout=normalized_report_layout(l); self.preview.set_layout(self.current_layout); self._mark_dirty()

    def _check_changed(self,v):
        if self._syncing:return
        self.current_layout['auto_fill']=bool(v); self.preview.set_layout(self.current_layout); self._mark_dirty()

    def _preview_layout_changed(self,l):
        self.current_layout=normalized_report_layout(l); self._syncing=True
        for k in ('x','y','w','h','offset_x','offset_y'):
            self.spins[k].setValue(float(self.current_layout[k])*100)
        self._syncing=False; self._mark_dirty()

    def _set_sample_kills(self,kills,mark=False):
        self.preview.set_sample(kills,report_evaluation(kills))
        if mark:self._mark_dirty()

    def _auto_fill_default(self):
        # Keep the proven whiteboard ROI, but let the new font-fitting engine maximize both lines.
        l=dict(self.current_layout); l.update({'x':0.105,'y':0.675,'w':0.790,'h':0.235,'offset_x':0.0,'offset_y':0.0,'line1_scale':1.0,'line2_scale':1.0,'line_spacing':0.02,'auto_fill':True})
        self.current_layout=normalized_report_layout(l); self.preview.set_layout(self.current_layout); self._syncing=True
        for k,sp in self.spins.items():
            if k in self.current_layout: sp.setValue(float(self.current_layout[k])*100)
        self.auto_fill.setChecked(True); self._syncing=False; self._mark_dirty()

    def _reset_default(self):
        self.current_layout=dict(DEFAULT_REPORT_LAYOUT); self.preview.set_layout(self.current_layout); self._syncing=True
        for k,sp in self.spins.items():
            if k in self.current_layout: sp.setValue(float(self.current_layout[k])*100)
        self.outline.setValue(float(self.current_layout['outline_width'])); self.auto_fill.setChecked(True); self._syncing=False; self._mark_dirty()

    def _save(self):
        set_report_layout(self.cfg,self.current_asset,self.current_layout); save_config(self.cfg)
        if getattr(self.pet,'current_asset_path',None)==self.current_asset: self.pet.report_overlay.set_asset(self.current_asset)
        self._dirty=False; self.save_btn.setEnabled(False); self.status.setText('已应用 ✓'); QTimer.singleShot(1600,lambda:self.status.setText(''))
        LOGGER.info('保存战报模板 | asset=%s layout=%s',Path(self.current_asset).name,self.current_layout)

    def _play_preview(self):
        set_report_layout(self.cfg,self.current_asset,self.current_layout); save_config(self.cfg)
        kills=int(self.preview.kills); evaluation=report_evaluation(kills)
        self.pet.report_active=True
        self.pet.play_state('report',force_new_clip=True,asset_override=self.current_asset)
        self.pet.report_overlay.set_asset(self.current_asset)
        self.pet.report_overlay.set_report(kills,evaluation)
        self.pet.report_overlay.raise_()
        self.pet.report_timer.start(max(3000,int(self.cfg.get('report_duration_ms',10000))))


class WhiteboardLayoutPreview(QWidget):
    layout_changed = Signal(object)
    SAMPLE_TEXTS = {
        5: "你认真的？",
        10: "还没打呢你就怂了？",
        20: "你买这把枪是准备送给对面的吗？",
        30: "你先别急着冲，看看对面的站位再决定，我可不想看你白给。",
        50: "你要是真想赢就先把脑子带上，别每次一看到人就往前冲，我救得了你一次可救不了你每一次。",
    }
    def __init__(self,parent=None):
        super().__init__(parent); self.setMinimumSize(430,430); self.setMouseTracking(True)
        self.image=QPixmap(); self.layout_cfg=dict(DEFAULT_WHITEBOARD_LAYOUT); self.sample_text=self.SAMPLE_TEXTS[20]
        self.font_family="Microsoft YaHei"; self._mode=None; self._last=None
        self.setStyleSheet("background:#EAF2EF;border:1px solid #C8D8D2;border-radius:8px;")

    def set_video_path(self,path):
        pix=QPixmap()
        try:
            cap=cv2.VideoCapture(str(path)); count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if count>2: cap.set(cv2.CAP_PROP_POS_FRAMES,count//2)
            ok,frame=cap.read(); cap.release()
            if ok and frame is not None:
                rgba=cv2.cvtColor(frame,cv2.COLOR_BGR2RGBA)
                r=rgba[:,:,0].astype(np.float32); g=rgba[:,:,1].astype(np.float32); b=rgba[:,:,2].astype(np.float32)
                green=(g>75)&(g>r*1.16)&(g>b*1.16)
                rgba[:,:,3]=np.where(green,0,255).astype(np.uint8)
                rgba=np.ascontiguousarray(rgba)
                qi=QImage(rgba.data,rgba.shape[1],rgba.shape[0],rgba.strides[0],QImage.Format.Format_RGBA8888).copy()
                pix=QPixmap.fromImage(qi)
        except Exception:
            LOGGER.exception("读取对白白板预览失败: %s",path)
        self.image=pix; self.update()

    def set_layout(self,layout): self.layout_cfg=normalized_whiteboard_layout(layout); self.update()
    def set_sample(self,text): self.sample_text=str(text or ""); self.update()
    def set_font_family(self,family): self.font_family=str(family or "Microsoft YaHei"); self.update()
    def _image_rect(self):
        if self.image.isNull(): return QRect(12,12,max(1,self.width()-24),max(1,self.height()-24))
        iw,ih=self.image.width(),self.image.height(); aw=max(1,self.width()-24); ah=max(1,self.height()-24)
        scale=min(aw/iw,ah/ih); w=int(iw*scale); h=int(ih*scale); return QRect((self.width()-w)//2,(self.height()-h)//2,w,h)
    def _board_rect(self):
        ir=self._image_rect(); l=self.layout_cfg
        return QRect(int(ir.x()+(l['x']+l['offset_x'])*ir.width()),int(ir.y()+(l['y']+l['offset_y'])*ir.height()),max(12,int(l['w']*ir.width())),max(12,int(l['h']*ir.height())))
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,True); ir=self._image_rect()
        if not self.image.isNull(): p.drawPixmap(ir,self.image,self.image.rect())
        overlay=render_dialogue_text_pixmap(ir.width(),ir.height(),self.layout_cfg,self.sample_text,self.font_family,None)
        p.drawPixmap(ir.x(),ir.y(),overlay); br=self._board_rect(); p.setPen(QPen(QColor(52,205,163),2,Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(br)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(52,205,163)); p.drawRect(br.right()-6,br.bottom()-6,12,12); p.end()
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        br=self._board_rect(); pos=event.position().toPoint(); handle=QRect(br.right()-14,br.bottom()-14,28,28)
        self._mode='resize' if handle.contains(pos) else ('move' if br.contains(pos) else None); self._last=pos
    def mouseMoveEvent(self,event):
        if not self._mode or self._last is None:return
        pos=event.position().toPoint(); dx=pos.x()-self._last.x(); dy=pos.y()-self._last.y(); self._last=pos; ir=self._image_rect(); l=dict(self.layout_cfg)
        if ir.width()<=0 or ir.height()<=0:return
        if self._mode=='move': l['x']+=dx/ir.width(); l['y']+=dy/ir.height()
        else: l['w']+=dx/ir.width(); l['h']+=dy/ir.height()
        self.layout_cfg=normalized_whiteboard_layout(l); self.layout_changed.emit(dict(self.layout_cfg)); self.update()
    def mouseReleaseEvent(self,event): self._mode=None; self._last=None


class WhiteboardTemplateDialog(QDialog):
    def __init__(self,cfg,pet,parent=None):
        super().__init__(parent); self.cfg=cfg; self.pet=pet; self.layout_cfg=normalized_whiteboard_layout(cfg.get('whiteboard',{})); self._syncing=False; self._dirty=False
        self.setWindowTitle('小美丽｜对白白板模板'); self.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png'))); self.resize(980,720); self.setMinimumSize(900,650)
        root=QVBoxLayout(self); top=QHBoxLayout(); top.addWidget(QLabel('通用白板：'))
        source=Path(resource('assets/whiteboard_template_v080.mp4')); self.source_path=str(source); self.source_label=QLabel(source.name if source.exists() else '素材缺失')
        self.source_label.setStyleSheet('font-weight:600;'); top.addWidget(self.source_label,1); top.addWidget(HelpBadge('这一支 15 秒白板视频会同时用于唤醒回应和所有语音回答。程序只使用画面，不播放素材自带音轨。')); root.addLayout(top)
        body=QHBoxLayout(); root.addLayout(body,1); self.preview=WhiteboardLayoutPreview(); self.preview.layout_changed.connect(self._preview_changed); body.addWidget(self.preview,3)
        controls=QWidget(); form=QFormLayout(controls); body.addWidget(controls,2); self.spins={}
        specs=[('x','区域 X (%)',0,95,0.1),('y','区域 Y (%)',0,95,0.1),('w','区域宽度 (%)',5,100,0.1),('h','区域高度 (%)',5,100,0.1),('offset_x','水平偏移 (%)',-30,30,0.1),('offset_y','垂直偏移 (%)',-30,30,0.1)]
        for key,label,mn,mx,step in specs:
            sp=QDoubleSpinBox(); sp.setRange(mn,mx); sp.setSingleStep(step); sp.setDecimals(1); sp.valueChanged.connect(lambda v,k=key:self._spin_percent(k,v)); self.spins[key]=sp; form.addRow(label,sp)
        self.min_font=QSpinBox(); self.min_font.setRange(8,48); self.min_font.valueChanged.connect(lambda v:self._spin_plain('min_font_px',v)); form.addRow('最小字号 (px)',self.min_font)
        self.max_font=QSpinBox(); self.max_font.setRange(12,88); self.max_font.valueChanged.connect(lambda v:self._spin_plain('max_font_px',v)); form.addRow('最大字号 (px)',self.max_font)
        self.font_scale=QDoubleSpinBox(); self.font_scale.setRange(50,180); self.font_scale.setSuffix('%'); self.font_scale.valueChanged.connect(lambda v:self._spin_ratio('font_scale',v)); form.addRow('整体字号倍率',self.font_scale)
        self.line_spacing=QDoubleSpinBox(); self.line_spacing.setRange(85,150); self.line_spacing.setSuffix('%'); self.line_spacing.valueChanged.connect(lambda v:self._spin_ratio('line_spacing',v)); form.addRow('行距',self.line_spacing)
        self.max_lines=QSpinBox(); self.max_lines.setRange(1,7); self.max_lines.valueChanged.connect(lambda v:self._spin_plain('max_lines',v)); form.addRow('最大行数',self.max_lines)
        self.outline=QDoubleSpinBox(); self.outline.setRange(0,4); self.outline.setSingleStep(0.5); self.outline.valueChanged.connect(lambda v:self._spin_plain('outline_width',v)); form.addRow('淡描边 (px)',self.outline)
        self.auto_fill=QCheckBox('自动换行 + 自动字号 + 居中（推荐）'); self.auto_fill.toggled.connect(self._auto_changed); form.addRow(self.auto_fill)
        self.hold=QDoubleSpinBox(); self.hold.setRange(0.5,8.0); self.hold.setSingleStep(0.5); self.hold.setSuffix(' 秒'); self.hold.valueChanged.connect(lambda v:self._spin_hold(v)); form.addRow('说完后动态停留',self.hold)
        sample_box=QGroupBox('字数预览'); sg=QGridLayout(sample_box)
        for i,n in enumerate((5,10,20,30,50)):
            b=QPushButton(f'{n}字'); b.clicked.connect(lambda checked=False,k=n:self._sample(k)); sg.addWidget(b,0,i)
        form.addRow(sample_box)
        auto=QPushButton('一键铺满对白区'); auto.clicked.connect(self._one_click); form.addRow(auto)
        reset=QPushButton('恢复默认模板'); reset.clicked.connect(self._reset); form.addRow(reset)
        play=QPushButton('▶ 播放对白预览'); play.clicked.connect(self._play); form.addRow(play)
        hint=QLabel('绿色虚线框就是文字安全区，可直接拖动；右下角绿色方块可缩放。顶部凸起属于聊天气泡指向角，正文仍保持在白色气泡主体内。\n文字会跟随 TTS 播报逐步出现；说完后白板继续保持动态并停留设定时间，默认 3 秒。15 秒素材不足时会自动循环，整个过程不冻结画面。')
        hint.setWordWrap(True); hint.setStyleSheet('color:#657185;'); form.addRow(hint)
        bottom=QHBoxLayout(); self.status=QLabel(''); self.status.setStyleSheet('color:#278a74;'); bottom.addWidget(self.status); bottom.addStretch(1); close=QPushButton('关闭'); close.clicked.connect(self.reject); self.save_btn=QPushButton('保存并应用'); self.save_btn.clicked.connect(self._save); bottom.addWidget(close); bottom.addWidget(self.save_btn); root.addLayout(bottom)
        self._load()

    def _font_family(self):
        try: self.pet.dialogue_overlay.reload_font(); return self.pet.dialogue_overlay.font_family
        except Exception:return 'Microsoft YaHei'
    def _load(self):
        self.layout_cfg=normalized_whiteboard_layout(self.cfg.get('whiteboard',{})); self._syncing=True
        for k,sp in self.spins.items(): sp.setValue(float(self.layout_cfg[k])*100)
        self.min_font.setValue(int(self.layout_cfg['min_font_px'])); self.max_font.setValue(int(self.layout_cfg['max_font_px'])); self.font_scale.setValue(float(self.layout_cfg['font_scale'])*100); self.line_spacing.setValue(float(self.layout_cfg['line_spacing'])*100); self.max_lines.setValue(int(self.layout_cfg['max_lines'])); self.outline.setValue(float(self.layout_cfg['outline_width'])); self.auto_fill.setChecked(bool(self.layout_cfg['auto_fill'])); self.hold.setValue(float(self.layout_cfg['hold_ms'])/1000.0); self._syncing=False
        self.preview.set_video_path(self.source_path); self.preview.set_layout(self.layout_cfg); self.preview.set_font_family(self._font_family()); self._sample(20,False); self._dirty=False; self.save_btn.setEnabled(False)
    def _mark(self):
        if self._syncing:return
        self._dirty=True; self.save_btn.setEnabled(True); self.status.setText('未保存')
    def _spin_percent(self,k,v):
        if self._syncing:return
        l=dict(self.layout_cfg); l[k]=float(v)/100.0; self.layout_cfg=normalized_whiteboard_layout(l); self.preview.set_layout(self.layout_cfg); self._mark()
    def _spin_plain(self,k,v):
        if self._syncing:return
        l=dict(self.layout_cfg); l[k]=float(v) if k=='outline_width' else int(v); self.layout_cfg=normalized_whiteboard_layout(l); self.preview.set_layout(self.layout_cfg); self._mark()
    def _spin_ratio(self,k,v):
        if self._syncing:return
        l=dict(self.layout_cfg); l[k]=float(v)/100.0; self.layout_cfg=normalized_whiteboard_layout(l); self.preview.set_layout(self.layout_cfg); self._mark()
    def _spin_hold(self,v):
        if self._syncing:return
        l=dict(self.layout_cfg); l['hold_ms']=int(float(v)*1000); self.layout_cfg=normalized_whiteboard_layout(l); self._mark()
    def _auto_changed(self,v):
        if self._syncing:return
        self.layout_cfg['auto_fill']=bool(v); self.preview.set_layout(self.layout_cfg); self._mark()
    def _preview_changed(self,l):
        self.layout_cfg=normalized_whiteboard_layout(l); self._syncing=True
        for k in ('x','y','w','h','offset_x','offset_y'): self.spins[k].setValue(float(self.layout_cfg[k])*100)
        self._syncing=False; self._mark()
    def _sample(self,n,mark=False):
        self.preview.set_sample(WhiteboardLayoutPreview.SAMPLE_TEXTS.get(int(n),WhiteboardLayoutPreview.SAMPLE_TEXTS[20])); self._sample_n=int(n)
        if mark:self._mark()
    def _one_click(self):
        l=dict(self.layout_cfg); l.update({'x':0.075,'y':0.655,'w':0.850,'h':0.300,'offset_x':0.0,'offset_y':0.0,'min_font_px':13,'max_font_px':42,'font_scale':1.0,'line_spacing':1.02,'max_lines':4,'auto_fill':True})
        self.layout_cfg=normalized_whiteboard_layout(l); self._syncing=True
        for k,sp in self.spins.items(): sp.setValue(float(self.layout_cfg[k])*100)
        self.min_font.setValue(self.layout_cfg['min_font_px']); self.max_font.setValue(self.layout_cfg['max_font_px']); self.font_scale.setValue(self.layout_cfg['font_scale']*100); self.line_spacing.setValue(self.layout_cfg['line_spacing']*100); self.max_lines.setValue(self.layout_cfg['max_lines']); self.auto_fill.setChecked(True); self._syncing=False; self.preview.set_layout(self.layout_cfg); self._mark()
    def _reset(self): self.cfg['whiteboard']=dict(DEFAULT_WHITEBOARD_LAYOUT); self._load(); self._mark()
    def _save(self):
        self.cfg['whiteboard']=normalized_whiteboard_layout(self.layout_cfg); save_config(self.cfg); self.pet.dialogue_overlay.update(); self._dirty=False; self.save_btn.setEnabled(False); self.status.setText('已应用 ✓'); QTimer.singleShot(1500,lambda:self.status.setText(''))
    def _play(self):
        self._save(); text=self.preview.sample_text; self.pet.preview_dialogue(text,max(1800,min(6500,len(text)*150)))




# ----------------------------
# V0.6.2 local voice subsystem
# ----------------------------
# Heavy Qwen3-TTS dependencies live in a separate first-use runtime so the
# desktop pet EXE stays small and future app updates do not redownload models.

# V0.6.2: native-Chinese Qwen3-TTS backend. The old Kokoro backend is intentionally not used.
from voice_qwen import VoiceService
from brain_qwen import BrainService, DEFAULT_PERSONA
from speech_input import SpeechInputService
from native_updater import install_update_package
from ndm_bridge import test_connection as ndm_test_connection, download_and_import as ndm_download_and_import

# ----------------------------
# V0.6.2 self-update subsystem
# ----------------------------
def _version_tuple(value):
    nums = re.findall(r"\d+", str(value or ""))[:4]
    return tuple(int(x) for x in nums) if nums else (0,)


class UpdateService(QObject):
    status_changed = Signal(str)
    check_finished = Signal(bool, object, str)
    progress_changed = Signal(int, str)
    restart_requested = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._busy = False
        self._latest_manifest = None

    def manifest_url(self):
        return str(self.cfg.get("updates", {}).get("manifest_url", "") or "").strip()

    def set_manifest_url(self, url):
        if not isinstance(self.cfg.get("updates"), dict):
            self.cfg["updates"] = {}
        self.cfg["updates"]["manifest_url"] = str(url or "").strip()
        save_config(self.cfg)

    def check_async(self):
        if self._busy:
            return
        url = self.manifest_url()
        if not url:
            self.check_finished.emit(False, None, "尚未绑定永久更新源。V0.6.1.1 已具备更新器，请在“更新”页绑定固定 latest.json 地址。")
            return
        self._busy = True
        self.status_changed.emit("正在检查更新…")

        def job():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": f"XiaoMeili/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read(1024 * 1024)
                manifest = json.loads(raw.decode("utf-8-sig"))
                version = str(manifest.get("version", "")).strip()
                package_url = str(manifest.get("package_url", "")).strip()
                if not version or not package_url:
                    raise ValueError("更新清单缺少 version 或 package_url")
                protocol = int(manifest.get("protocol", 1) or 1)
                if protocol > UPDATE_PROTOCOL_VERSION:
                    raise RuntimeError("更新协议版本过新，当前更新器无法安全处理。")
                self._latest_manifest = manifest
                if _version_tuple(version) > _version_tuple(APP_UPDATE_VERSION):
                    notes = manifest.get("notes", "")
                    if isinstance(notes, list):
                        notes = "\n".join("• " + str(x) for x in notes)
                    msg = f"发现新版本 V{version}" + (f"\n{notes}" if notes else "")
                    self.check_finished.emit(True, manifest, msg)
                else:
                    self.check_finished.emit(False, manifest, f"当前已是最新版本 V{APP_VERSION}。")
            except Exception as e:
                LOGGER.exception("检查更新失败")
                self.check_finished.emit(False, None, f"检查更新失败：{type(e).__name__}: {e}")
            finally:
                self._busy = False
        threading.Thread(target=job, name="XiaoMeiliUpdateCheck", daemon=True).start()

    @staticmethod
    def _sha256(path: Path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower()

    def install_latest_async(self):
        manifest = self._latest_manifest
        if not isinstance(manifest, dict):
            self.check_finished.emit(False, None, "请先检查更新。")
            return
        if self._busy:
            return
        self._busy = True

        def job():
            try:
                version = str(manifest.get("version", "")).strip()
                url = str(manifest.get("package_url", "")).strip()
                expected = str(manifest.get("sha256", "") or "").strip().lower()
                try:
                    expected_bytes = max(0, int(manifest.get("package_size", 0) or 0))
                except Exception:
                    expected_bytes = 0

                session_id = f"{version}_{int(time.time()*1000)}"
                package = UPDATE_DIR / f"XiaoMeili_{session_id}_update.zip"
                part = UPDATE_DIR / f"XiaoMeili_{session_id}_update.zip.part"
                UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                UPDATE_LOG_DIR.mkdir(parents=True, exist_ok=True)
                UPDATE_DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)

                # V0.9.2 safety: update staging is append-only; no file deletion.

                def verify_download(path_obj: Path):
                    if not path_obj.exists() or path_obj.stat().st_size < 5 * 1024 * 1024:
                        raise RuntimeError("更新包不存在或文件尺寸明显异常")
                    actual = self._sha256(path_obj)
                    if expected and actual != expected:
                        raise RuntimeError(
                            f"SHA-256 不一致：期望 {expected}，实际 {actual}，"
                            f"本次文件 {path_obj.stat().st_size} 字节"
                        )
                    with zipfile.ZipFile(path_obj, "r") as zf:
                        bad = zf.testzip()
                        if bad:
                            raise RuntimeError(f"ZIP 内部文件损坏：{bad}")
                        names = {Path(x).name.lower() for x in zf.namelist()}
                        if "xiaomeili.exe" not in names:
                            raise RuntimeError("ZIP 中没有 XiaoMeili.exe")
                    return actual

                download_ok = False
                source_name = ""
                last_detail = ""
                last_actual = ""

                brain_cfg = self.cfg.get("brain", {}) if isinstance(self.cfg.get("brain"), dict) else {}
                mode = str(brain_cfg.get("download_mode", "ndm") or "ndm").strip().lower()
                ndm_dir_raw = str(brain_cfg.get("ndm_download_dir") or (Path.home() / "Downloads")).strip()
                ndm_dir = Path(ndm_dir_raw) if ndm_dir_raw else Path.home() / "Downloads"

                if mode == "ndm" and ndm_dir.exists():
                    try:
                        ok, ndm_msg = ndm_test_connection(timeout=2.5)
                    except Exception as exc:
                        ok, ndm_msg = False, f"NDM 检测异常：{type(exc).__name__}: {exc}"
                    if ok:
                        try:
                            self.progress_changed.emit(2, f"已连接 NDM，正在发送 V{version} 更新任务…")

                            def ndm_note(message, done=0, total=0, speed_bps=0):
                                try:
                                    done = max(0, int(done or 0))
                                    total = max(0, int(total or 0))
                                    speed_bps = max(0, float(speed_bps or 0))
                                except Exception:
                                    done, total, speed_bps = 0, 0, 0.0
                                effective_total = total or expected_bytes
                                if effective_total > 0 and done > 0:
                                    pct = 3 + int(min(1.0, done / effective_total) * 91)
                                else:
                                    pct = 5
                                speed = f" · {speed_bps/1024/1024:.1f} MB/s" if speed_bps > 0 else ""
                                self.progress_changed.emit(
                                    max(2, min(94, pct)),
                                    f"NDM 下载 V{version}｜{message}{speed}",
                                )

                            ndm_download_and_import(
                                url=url,
                                filename=package.name,
                                download_root=ndm_dir,
                                destination=part,
                                min_bytes=5 * 1024 * 1024,
                                expected_bytes=expected_bytes,
                                progress_cb=ndm_note,
                                timeout_seconds=6 * 3600,
                            )
                            self.progress_changed.emit(95, "NDM 下载完成，正在校验 SHA-256 与 ZIP…")
                            last_actual = verify_download(part)
                            part.replace(package)
                            download_ok = True
                            source_name = "NDM"
                            LOGGER.info("更新包通过 NDM 下载并完成校验 | version=%s | sha256=%s", version, last_actual)
                        except Exception as exc:
                            last_detail = f"NDM 下载/校验失败：{type(exc).__name__}: {exc}"
                            LOGGER.warning("%s；自动回退内置下载器", last_detail, exc_info=True)
                            # Keep failed partial download for diagnostics; never delete it.
                            self.progress_changed.emit(0, "NDM 未能完成本次更新，自动切换小美丽内置下载器…")
                    else:
                        LOGGER.info("NDM 当前不可用，自动使用内置下载器：%s", ndm_msg)
                        self.progress_changed.emit(0, "NDM 未连接，自动使用小美丽内置下载器…")
                elif mode == "ndm":
                    LOGGER.info("NDM 下载目录无效，自动使用内置下载器：%s", ndm_dir)
                    self.progress_changed.emit(0, "NDM 下载目录无效，自动使用小美丽内置下载器…")

                if not download_ok:
                    for attempt in range(1, 4):
                        # Reuse this private staging file; never delete it automatically.
                        sep = "&" if "?" in url else "?"
                        attempt_url = (
                            url if attempt == 1
                            else f"{url}{sep}xm_retry={version}-{attempt}-{expected[:12]}-{int(time.time())}"
                        )
                        headers = {
                            "User-Agent": f"XiaoMeili/{APP_VERSION}",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache",
                            "Accept-Encoding": "identity",
                        }
                        try:
                            req = urllib.request.Request(attempt_url, headers=headers)
                            self.progress_changed.emit(0, f"内置下载器正在下载 V{version}（第 {attempt}/3 次）…")
                            with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as f:
                                status = int(getattr(resp, "status", 200) or 200)
                                if status not in (200, 206):
                                    raise RuntimeError(f"HTTP {status}")
                                total = int(resp.headers.get("Content-Length") or 0)
                                done = 0
                                while True:
                                    chunk = resp.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    done += len(chunk)
                                    pct = int(done * 94 / total) if total else 0
                                    self.progress_changed.emit(
                                        max(0, min(94, pct)),
                                        f"内置下载器 V{version}（第 {attempt}/3 次）… {done/1024/1024:.1f} MB",
                                    )
                                f.flush()
                                try:
                                    os.fsync(f.fileno())
                                except Exception:
                                    pass
                            if total and done != total:
                                raise RuntimeError(f"下载不完整：收到 {done} 字节，服务器声明 {total} 字节")
                            self.progress_changed.emit(95, "下载完成，正在校验 SHA-256 与 ZIP…")
                            last_actual = verify_download(part)
                            part.replace(package)
                            download_ok = True
                            source_name = "内置下载器"
                            break
                        except Exception as exc:
                            last_detail = f"第 {attempt}/3 次失败：{type(exc).__name__}: {exc}"
                            LOGGER.warning("更新内置下载失败 | %s", last_detail, exc_info=True)
                            # Keep failed partial download for diagnostics; never delete it.
                            if attempt < 3:
                                time.sleep(1.2)

                if not download_ok:
                    raise RuntimeError(
                        "更新包下载/校验失败。"
                        + (f" 最后一次实际 SHA-256：{last_actual}。" if last_actual else "")
                        + (f" {last_detail}" if last_detail else "")
                        + f" 详细日志保存在 {UPDATE_LOG_DIR}。"
                    )

                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行正式更新，请在打包后的 XiaoMeili.exe 中测试。")

                local_appdata = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
                if not local_appdata:
                    raise RuntimeError("无法读取 LOCALAPPDATA，安全更新已停止。")
                install_root = Path(local_appdata).absolute() / "XiaoMeiliApp"
                current_exe = Path(sys.executable).resolve()
                native_log = UPDATE_LOG_DIR / "native_updater.log"

                self.progress_changed.emit(96, "校验完成，正在创建全新的版本目录…")
                result = install_update_package(
                    package=package,
                    install_root=install_root,
                    expected_version=version,
                    expected_sha256=expected,
                    current_exe=current_exe,
                    log_path=native_log,
                )
                launcher = Path(result["launcher"])
                self.progress_changed.emit(
                    100,
                    f"{source_name}下载并校验完成，V{version} 已安全安装到独立版本目录，正在重启…",
                )
                subprocess.Popen(
                    [str(launcher)],
                    cwd=str(install_root),
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                time.sleep(0.35)
                self.restart_requested.emit()
            except Exception as e:
                LOGGER.exception("安装更新失败")
                self.check_finished.emit(False, None, f"安装更新失败：{type(e).__name__}: {e}")
            finally:
                self._busy = False

        threading.Thread(target=job, name="XiaoMeiliUpdateInstall", daemon=True).start()


def _path_size_bytes(path: Path):
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except Exception:
        return 0


def cleanup_obsolete_storage():
    # V0.9.2.3 safety baseline: never delete files automatically.
    LOGGER.info("自动存储清理已禁用：V0.10.0 不会自动删除任何文件。")


def xiaomeili_logical_data_root():
    if sys.platform == "win32":
        return Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    return USER


def xiaomeili_physical_data_root():
    root = xiaomeili_logical_data_root()
    try:
        return Path(os.path.realpath(str(root)))
    except Exception:
        return root


def format_storage_size(value):
    try:
        value = int(value or 0)
    except Exception:
        value = 0
    if value >= 1024 ** 3:
        return f"{value / (1024 ** 3):.2f} GB"
    if value >= 1024 ** 2:
        return f"{value / (1024 ** 2):.1f} MB"
    return f"{value / 1024:.1f} KB"


def storage_is_on_d():
    if sys.platform != "win32":
        return False
    try:
        physical = xiaomeili_physical_data_root()
        return str(physical.drive or "").upper() == "D:"
    except Exception:
        return False


class EditableAvatar(QLabel):
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._editable_hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("点击更换头像")

    def enterEvent(self, event):
        self._editable_hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._editable_hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._editable_hover:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(9, 49, 40, 145))
        p.drawEllipse(rect)
        p.setPen(QColor("#FFFFFF"))
        font = p.font()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "更换")
        p.end()


from PySide6.QtGui import QPainterPath


class FavoriteStarButton(QPushButton):
    """Font-independent five-point favorite button used by every settings card."""

    def __init__(self, checked=False, parent=None):
        super().__init__("", parent)
        self.setObjectName("favoriteButton")
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("收藏到常用")
        self.setStyleSheet(
            "QPushButton#favoriteButton{background:transparent;border:none;padding:0px;"
            "min-width:34px;max-width:34px;min-height:34px;max-height:34px;}"
        )

    @staticmethod
    def _star_path(rect):
        # Normalized ten-point polygon: five outer tips + five inner corners.
        pts = (
            (0.500, 0.030),
            (0.615, 0.355),
            (0.965, 0.365),
            (0.690, 0.575),
            (0.790, 0.925),
            (0.500, 0.725),
            (0.210, 0.925),
            (0.310, 0.575),
            (0.035, 0.365),
            (0.385, 0.355),
        )
        left = rect.left() + 6.0
        top = rect.top() + 5.5
        width = max(1.0, rect.width() - 12.0)
        height = max(1.0, rect.height() - 11.0)
        path = QPainterPath()
        for i, (x, y) in enumerate(pts):
            px = left + x * width
            py = top + y * height
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 200, 61, 34 if not self.isChecked() else 48))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)

        star = self._star_path(self.rect())
        if self.isChecked():
            painter.setPen(QColor("#D99A00"))
            painter.setBrush(QColor("#FFC83D"))
        else:
            painter.setPen(QColor("#9DAEA7") if not self.underMouse() else QColor("#D5A000"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(star)

        # Small highlight keeps the selected icon close to the soft yellow
        # reference image without depending on an external PNG asset.
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 92))
            painter.drawEllipse(12, 9, 5, 3)
        painter.end()



class HighlightVideoOverlay(QWidget):
    """Dedicated high-glow whiteboard player with isolated base-pet rendering.

    V0.9.2.2 uses exactly the same typography/layout engine as the dialogue
    whiteboard.  While this overlay is visible the normal pet window is hidden,
    so the idle animation can never ghost through the green-screen background.
    """

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.view = QLabel(self)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setStyleSheet("background:transparent;")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.cap = None
        self.path = ""
        self.text = ""
        self.duration_ms = 1
        self.started_at = 0.0
        self.layout_cfg = dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)
        self.font_family = "Microsoft YaHei"
        self._generation = 0
        self._pet_was_visible = False
        self._pet_hidden_by_overlay = False
        self._cached_geometry = QRect()

    def _sync_geometry(self):
        try:
            if self.pet.isVisible() or self._cached_geometry.isNull():
                self._cached_geometry = QRect(self.pet.frameGeometry())
            g = self._cached_geometry
            if g.isNull():
                g = self.pet.frameGeometry()
            self.setGeometry(g)
            self.view.setGeometry(0,0,max(1,g.width()),max(1,g.height()))
        except Exception:
            pass

    def _hide_base_pet(self):
        try:
            self._pet_was_visible = bool(self.pet.isVisible())
            self._sync_geometry()
            if self._pet_was_visible:
                self.pet.hide()
                self._pet_hidden_by_overlay = True
        except Exception:
            LOGGER.warning("[HIGHLIGHT] hide base pet failed", exc_info=True)

    def _restore_base_pet(self):
        if not self._pet_hidden_by_overlay:
            return
        self._pet_hidden_by_overlay = False
        try:
            if self._pet_was_visible:
                self.pet.show()
                self.pet.raise_()
                QTimer.singleShot(30, self.pet.apply_clickthrough_native)
        except Exception:
            LOGGER.warning("[HIGHLIGHT] restore base pet failed", exc_info=True)

    @staticmethod
    def _green_alpha(frame):
        b,g,r = cv2.split(frame)
        mx = np.maximum(r,b).astype(np.int16)
        gi = g.astype(np.int16)
        excess = gi - mx
        greenish = (g >= 80) & (excess >= 18)
        alpha = np.full(g.shape,255,dtype=np.uint8)
        feather = np.clip((36 - excess) * (255.0/18.0),0,255).astype(np.uint8)
        alpha[greenish] = feather[greenish]
        alpha[(g >= 110) & (excess >= 42)] = 0
        rgba = cv2.cvtColor(frame,cv2.COLOR_BGR2RGBA)
        rgba[:,:,3] = alpha
        return rgba

    def _paint_text(self, image):
        try:
            elapsed = max(0.0,(time.monotonic()-self.started_at)*1000.0)
            ratio = min(1.0, elapsed / max(250.0,float(self.duration_ms)))
            reveal = max(1,int(round(len(self.text)*ratio))) if self.text else 0
            if reveal <= 0:
                return image
            pm = render_dialogue_text_pixmap(
                image.width(), image.height(), self.layout_cfg,
                self.text, self.font_family, reveal,
            )
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
            painter.drawPixmap(0,0,pm)
            painter.end()
        except Exception:
            LOGGER.exception("[HIGHLIGHT] draw text failed")
        return image

    def play(self, path, text, duration_ms, box=None, font_family=None):
        self.stop()
        self._generation += 1
        self.path = str(path or "")
        self.text = str(text or "")
        self.duration_ms = max(300,int(duration_ms or 3000))
        self.started_at = time.monotonic()
        self.layout_cfg = normalized_highlight_text_layout(
            box if isinstance(box,dict) else {},
            self.pet.cfg.get("whiteboard",{}) if isinstance(getattr(self.pet,"cfg",None),dict) else {},
        )
        self.font_family = str(font_family or getattr(getattr(self.pet,"dialogue_overlay",None),"font_family","") or "Microsoft YaHei")

        try:
            self.cap = cv2.VideoCapture(self.path)
            if not self.cap or not self.cap.isOpened():
                raise RuntimeError("无法打开高光白板视频")
            fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 30.0)
            interval = int(max(20,min(66,1000.0/max(12.0,min(50.0,fps)))))
            self._hide_base_pet()
            self._sync_geometry()
            self.show()
            self.raise_()
            self.timer.start(interval)
            self._tick()
            return True
        except Exception:
            LOGGER.exception("[HIGHLIGHT] dedicated video play failed: %s",self.path)
            self.stop()
            return False

    def finish(self, hold_ms=800):
        generation = self._generation
        QTimer.singleShot(
            max(0,int(hold_ms)),
            lambda g=generation: self.stop() if g==self._generation else None,
        )

    def stop(self):
        try:self.timer.stop()
        except Exception:pass
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:pass
        self.cap = None
        try:self.hide()
        except Exception:pass
        self._restore_base_pet()

    def _tick(self):
        if self.cap is None:
            return
        try:
            ok,frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES,0)
                ok,frame = self.cap.read()
            if not ok:
                return
            self._sync_geometry()
            tw=max(2,self.width()); th=max(2,self.height())
            frame=cv2.resize(frame,(tw,th),interpolation=cv2.INTER_AREA)
            rgba=self._green_alpha(frame)
            q=QImage(rgba.data,tw,th,rgba.strides[0],QImage.Format.Format_RGBA8888).copy()
            q=self._paint_text(q)
            self.view.setPixmap(QPixmap.fromImage(q))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] frame render failed")


class SettingsDialog(QDialog):
    hotkeys_changed = Signal()
    config_changed = Signal()
    storage_migration_requested = Signal(str)

    def __init__(self, cfg, pet: PetWindow, vision: VisionWorker, voice_service, brain_service, update_service, speech_service=None, parent=None):
        super().__init__(parent)
        # Give the settings dialog normal Windows title-bar controls: minimize + close,
        # while intentionally keeping maximize disabled.
        self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.cfg = cfg
        self.pet = pet
        self.vision = vision
        self.voice_service = voice_service
        self.brain_service = brain_service
        self.update_service = update_service
        self.speech_service = speech_service or SpeechInputService()
        self._v080_speech_state_code, self._v080_speech_state_label = self.speech_service.current_state()
        self.asset_labels = {}
        self._dirty = False
        self.setWindowTitle(f"小美丽 V{APP_VERSION} 设置")
        self.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        self.resize(780, 720)
        self.setMinimumSize(720, 620)
        self.setStyleSheet("""
            QDialog { background: #F7F9FC; }
            QTabWidget::pane { border: 1px solid #DDE3EC; border-radius: 8px; background: #FFFFFF; }
            QTabBar::tab { background: transparent; border: none; padding: 8px 12px; margin: 0 1px; color: #3C4657; }
            QTabBar::tab:selected { color: #1769E0; border-bottom: 2px solid #2D7CF6; font-weight: 600; }
            QGroupBox { border: 1px solid #DDE3EC; border-radius: 9px; margin-top: 9px; padding-top: 9px; background: #FFFFFF; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { min-height: 28px; border: 1px solid #D4DAE4; border-radius: 7px; padding: 3px 12px; background: #FFFFFF; color: #283243; }
            QPushButton:hover { border-color: #8FB8F7; background: #F3F8FF; }
            QPushButton:pressed { background: #E8F1FF; }
            QPushButton:disabled { color: #9AA4B2; background: #F3F5F8; }
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox { border: 1px solid #D8DEE8; border-radius: 7px; background: #FFFFFF; padding: 4px 7px; }
            QProgressBar { border: 1px solid #D8DEE8; border-radius: 6px; text-align: center; background: #F1F4F8; min-height: 14px; }
            QProgressBar::chunk { border-radius: 5px; background: #2E7AF0; }
            QCheckBox { spacing: 7px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.tabs = QTabWidget(); root.addWidget(self.tabs)

        # General
        page = QWidget(); form = QFormLayout(page)
        self.top_cb = QCheckBox("永远置顶"); self.top_cb.setChecked(cfg.get("always_on_top", True))
        self.lock_cb = QCheckBox("锁定（固定位置 + 点击穿透）"); self.lock_cb.setChecked(bool(cfg.get("click_through", False)))
        form.addRow(self.top_cb); form.addRow(self.lock_cb)
        hint = QLabel("锁定后小美丽不会拦截鼠标；把鼠标移到小美丽身上，右上角仍会出现解锁按钮。")
        hint.setWordWrap(True); form.addRow(hint)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(30,100); self.opacity.setValue(cfg.get("opacity",100))
        form.addRow("透明度", self.opacity)
        self.size_spin = QSpinBox(); self.size_spin.setRange(120,600); self.size_spin.setValue(cfg.get("pet_width",280)); self.size_spin.setSuffix(" px")
        form.addRow("桌宠宽度", self.size_spin)
        self.trans_spin = QSpinBox(); self.trans_spin.setRange(0,1000); self.trans_spin.setValue(cfg.get("transition_ms",220)); self.trans_spin.setSuffix(" ms")
        form.addRow("动画切换过渡", self.trans_spin)
        self.mouse_interaction_cb = QCheckBox("启用鼠标互动基础版")
        self.mouse_interaction_cb.setChecked(bool(cfg.get("mouse_interaction", {}).get("enabled", True)))
        form.addRow(self.mouse_interaction_cb)
        mouse_hint = QLabel("仅在普通待机时生效：鼠标进入小美丽周围的隐形注意区并移动后，切入连续互动版。眼睛、头部、身体、头发、耳环都会顺滑跟随鼠标；游戏击杀/低血量/胜负/战报等状态会立即抢占。鼠标离开或长时间不动后自动回到随机待机视频。")
        mouse_hint.setWordWrap(True); form.addRow(mouse_hint)
        reset_btn = QPushButton("重置到屏幕左上"); reset_btn.clicked.connect(lambda:self.pet.move(100,100)); form.addRow(reset_btn)
        self.tabs.addTab(page,"常规")

        # Hotkeys. A dedicated clear button makes "no shortcut" explicit.
        hp = QWidget(); hv = QVBoxLayout(hp)
        self.hk_table = QTableWidget(9,3)
        self.hk_table.setHorizontalHeaderLabels(["功能","快捷键","操作"])
        self.hk_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.hk_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.hk_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        hk_rows = [
            ("idle","待机"),("low_hp","低血量"),("kill","击杀"),("dead","被击杀"),("victory","获胜"),("defeat","失败"),
            ("toggle_lock","锁定/解锁（含点击穿透）"),("settings","打开设置"),("show_hide","显示/隐藏桌宠")
        ]
        self.hk_editors={}
        for r,(key,name) in enumerate(hk_rows):
            self.hk_table.setItem(r,0,QTableWidgetItem(name))
            e=QKeySequenceEdit(QKeySequence(cfg.get("hotkeys",{}).get(key,"")))
            self.hk_table.setCellWidget(r,1,e); self.hk_editors[key]=e
            clear_btn=QPushButton("清除")
            clear_btn.setToolTip("清空后，该功能不注册任何全局快捷键")
            clear_btn.clicked.connect(lambda checked=False, ed=e: ed.clear())
            self.hk_table.setCellWidget(r,2,clear_btn)
        hk_hint=QLabel("快捷键可以完全留空。点击右侧“清除”后保存并应用，即不会为该功能注册快捷键。")
        hk_hint.setWordWrap(True); hv.addWidget(hk_hint)
        hv.addWidget(self.hk_table); self.tabs.addTab(hp,"快捷键")

        # Animation asset pools: each state supports up to 20 clips and random rotation.
        ap = QWidget(); av = QVBoxLayout(ap)
        title_row = QHBoxLayout()
        title = QLabel("6 个识别状态 + 1 个战报状态 → 每个状态最多 20 支视频")
        title.setStyleSheet("font-weight:600; font-size:15px;")
        title_row.addWidget(title); title_row.addWidget(HelpBadge(
            "绿幕视频导入后会自动抠绿、去绿边、添加淡白边/柔光并缓存为透明 WebP。\n"
            "支持按钮导入或批量拖拽。随机播放采用有放回抽取，允许连续抽到同一支。\n"
            "‘战报’状态默认使用你提供的10秒静止白板模板。"))
        title_row.addStretch(1); av.addLayout(title_row)
        grid = QGridLayout(); grid.setColumnStretch(1,1)
        grid.addWidget(QLabel("状态"),0,0); grid.addWidget(QLabel("素材池"),0,1)
        for c in range(2,6): grid.addWidget(QLabel(""),0,c)
        for row,(key,name) in enumerate(STATE_NAMES.items(), start=1):
            grid.addWidget(QLabel(name),row,0)
            lab=AssetDropLabel(key)
            lab.files_dropped.connect(self._on_asset_files_dropped)
            self.asset_labels[key]=lab; self._refresh_asset_label(key)
            grid.addWidget(lab,row,1)
            btn=QPushButton("导入视频")
            btn.clicked.connect(lambda checked=False,s=key:self.import_video_for(s))
            grid.addWidget(btn,row,2)
            manage=QPushButton("管理")
            manage.clicked.connect(lambda checked=False,s=key:self.manage_assets(s))
            grid.addWidget(manage,row,3)
            if key=="report":
                templ=QPushButton("模板")
                templ.setToolTip("调整战报白板文字区域、字号、行距和位置，并实时预览。")
                templ.clicked.connect(self.open_report_template_editor)
                grid.addWidget(templ,row,4)
                test=QPushButton("测试")
                test.clicked.connect(lambda checked=False,s=key:self._v0926_choose_and_test_asset(s))
                grid.addWidget(test,row,5)
            else:
                grid.addWidget(QWidget(),row,4)
                test=QPushButton("测试")
                test.clicked.connect(lambda checked=False,s=key:self._v0926_choose_and_test_asset(s))
                grid.addWidget(test,row,5)
        av.addLayout(grid)
        helper_row=QHBoxLayout()
        helper_row.addWidget(QLabel("批量拖拽 / 随机规则"))
        helper_row.addWidget(HelpBadge("从资源管理器一次选中多支视频，直接拖到对应状态素材框即可批量导入；每个状态最多20支。每次播放完重新独立抽签，允许 1→1→2、3→3→3 等连续重复。"))
        helper_row.addStretch(1); av.addLayout(helper_row)

        font_row=QHBoxLayout()
        font_row.addWidget(QLabel("战报字体："))
        self.report_font_label=QLabel(self._report_font_status())
        font_row.addWidget(self.report_font_label,1)
        import_font_btn=QPushButton("导入战报字体")
        import_font_btn.clicked.connect(self.import_report_font)
        font_row.addWidget(import_font_btn)
        font_row.addWidget(HelpBadge("战报动态文字固定使用 MaokenAssortedSans-Lite.otf（猫啃什锦黑-轻量版）。选择一次后会复制到 XiaoMeiliData/fonts，后续升级继续使用。"))
        av.addLayout(font_row)

        migrate_glow=QPushButton("为旧版已导入素材补上白边 / 柔光")
        migrate_glow.setToolTip("将 V0.4.4 及更早版本已经抠好透明底的 WebP 重新加上淡白边/柔光，不需要原绿幕视频。")
        migrate_glow.clicked.connect(self.upgrade_existing_assets_glow)
        av.addWidget(migrate_glow)
        restore=QPushButton("恢复 7 种内置占位动画")
        restore.clicked.connect(self.restore_assets); av.addWidget(restore); av.addStretch(1)
        self.tabs.addTab(ap,"动画素材")

        # Voice V0.6: choose one built-in Chinese female voice and keep it forever.
        sp = QWidget(); sv = QVBoxLayout(sp)
        intro = QLabel(
            f"V{APP_VERSION} 使用 Qwen3-TTS 1.7B 中文语音。固定声线会同时用于试听、语音对话和唤醒回应。"
            "\n麦克风、唤醒词和本地 ASR 已进入 V0.8.8 语音交互阶段。"
        )
        intro.setWordWrap(True); sv.addWidget(intro)

        voice_box = QGroupBox("小美丽固定声音"); vf2 = QFormLayout(voice_box)
        self.voice_status = QLabel(self.voice_service.component_status())
        self.voice_status.setWordWrap(True)
        vf2.addRow("组件状态", self.voice_status)
        self.voice_progress = QProgressBar(); self.voice_progress.setRange(0,100); self.voice_progress.setValue(100 if self.voice_service.ready() else 0)
        vf2.addRow("首次准备", self.voice_progress)
        self.voice_prepare_btn = QPushButton("准备 Qwen3-TTS（首次约 7–9 GB）")
        self.voice_prepare_btn.setEnabled(not self.voice_service.ready())
        self.voice_prepare_btn.clicked.connect(self._prepare_voice_components)
        vf2.addRow(self.voice_prepare_btn)

        self.voice_design_btn = QPushButton(
            "✓ 小女孩声线扩展已安装"
            if self.voice_service.design_ready()
            else "安装小女孩声线扩展（可选，约 4.5 GB）"
        )
        self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
        self.voice_design_btn.clicked.connect(self._prepare_voice_design)
        vf2.addRow(self.voice_design_btn)

        self.voice_combo = QComboBox(); self.voice_combo.setMinimumContentsLength(22)
        self.voice_combo.setEnabled(False)
        vf2.addRow("中文女声", self.voice_combo)

        nav = QWidget(); nav_l = QHBoxLayout(nav); nav_l.setContentsMargins(0,0,0,0)
        prev_btn = QPushButton("上一位"); next_btn = QPushButton("下一位")
        prev_btn.clicked.connect(lambda: self._step_voice(-1)); next_btn.clicked.connect(lambda: self._step_voice(1))
        self.voice_preview_btn = QPushButton("▶ 试听当前声音"); self.voice_preview_btn.setEnabled(False)
        self.voice_preview_btn.clicked.connect(self._preview_voice)
        nav_l.addWidget(prev_btn); nav_l.addWidget(self.voice_preview_btn); nav_l.addWidget(next_btn)
        vf2.addRow("海选", nav)

        self.voice_test_text = QLineEdit(str(
            cfg.get("voice",{}).get("test_text")
            or "你又要保枪？不过……随你。别说是我教的。"
        ))
        self.voice_test_text.setMaxLength(120)
        vf2.addRow("试听台词", self.voice_test_text)
        self.voice_speed = QDoubleSpinBox(); self.voice_speed.setRange(0.70,1.30); self.voice_speed.setSingleStep(0.05); self.voice_speed.setDecimals(2)
        self.voice_speed.setValue(float(cfg.get("voice",{}).get("speed",1.0) or 1.0)); self.voice_speed.setSuffix(" ×")
        vf2.addRow("语速", self.voice_speed)

        output_row = QWidget(); output_l = QHBoxLayout(output_row); output_l.setContentsMargins(0,0,0,0)
        self.voice_output_combo = QComboBox(); self.voice_output_combo.setMinimumContentsLength(28)
        self.voice_output_refresh_btn = QPushButton("刷新")
        self.voice_output_refresh_btn.setToolTip("刷新 Windows 当前可用的播放设备")
        self.voice_output_refresh_btn.clicked.connect(self._populate_voice_outputs)
        output_l.addWidget(self.voice_output_combo, 1); output_l.addWidget(self.voice_output_refresh_btn)
        vf2.addRow("播放设备", output_row)
        self._populate_voice_outputs()

        _fixed_vid = str(cfg.get("voice",{}).get("voice_id") or "")
        _fixed_name = self.voice_service.display_name(_fixed_vid) if _fixed_vid else "尚未选择"
        self.voice_fixed_label = QLabel("当前固定：" + _fixed_name)
        self.voice_fixed_label.setStyleSheet("font-weight:600;")
        vf2.addRow(self.voice_fixed_label)
        self.voice_fix_btn = QPushButton("设为小美丽固定声音")
        self.voice_fix_btn.setEnabled(False); self.voice_fix_btn.clicked.connect(self._fix_current_voice)
        vf2.addRow(self.voice_fix_btn)
        sv.addWidget(voice_box)

        voice_note = QLabel(
            "说明：Qwen3-TTS 运行环境和模型只会保存在本机 XiaoMeiliData 中。选定后，后续语音对话版本直接复用这个固定声线，"
            "你不需要再打开任何 TTS 软件。"
        )
        voice_note.setWordWrap(True); sv.addWidget(voice_note); sv.addStretch(1)
        self.tabs.addTab(sp, "声音")

        self.voice_service.download_progress.connect(self._voice_download_progress)
        self.voice_service.download_finished.connect(self._voice_download_finished)
        self.voice_service.voices_ready.connect(self._voice_list_ready)
        self.voice_service.synthesis_started.connect(self._voice_synth_started)
        self.voice_service.synthesis_finished.connect(self._voice_synth_finished)
        if self.voice_service.ready():
            self.voice_service.load_voices_async()

        # V0.8.8 speech-input technical widgets. They are shown only under
        # System → Components & Downloads; normal speech controls stay simple.
        self.speech_status = QLabel(self.speech_service.component_status())
        self.speech_status.setWordWrap(True)
        self.speech_progress = QProgressBar(); self.speech_progress.setRange(0,100); self.speech_progress.setValue(100 if self.speech_service.ready() else 0)
        self.speech_prepare_btn = QPushButton("准备语音输入（FSMN-VAD + Fun-ASR-Nano-2512）")
        self.speech_prepare_btn.setEnabled(not self.speech_service.ready())
        self.speech_prepare_btn.clicked.connect(self._v080_prepare_speech)
        self.speech_service.setup_progress.connect(self._v080_speech_setup_progress)
        self.speech_service.setup_finished.connect(self._v080_speech_setup_finished)
        self.speech_service.state_changed.connect(self._v080_speech_state_changed)
        self.speech_service.error.connect(self._v080_speech_error)

        # Brain V0.7.7.3: compact main page + second-level editors.
        bp = QWidget(); bv = QVBoxLayout(bp)
        bv.setContentsMargins(10, 10, 10, 10); bv.setSpacing(9)

        self.brain_advanced_toggle = QPushButton("模型与下载配置  ▸")
        self.brain_advanced_toggle.setCheckable(True)
        self.brain_advanced_toggle.setChecked(False)
        self.brain_advanced_toggle.setStyleSheet("text-align:left; font-weight:600; padding-left:12px;")
        self.brain_advanced_toggle.toggled.connect(self._toggle_brain_advanced)
        bv.addWidget(self.brain_advanced_toggle)

        self.brain_advanced_body = QGroupBox("")
        adv = QFormLayout(self.brain_advanced_body)
        adv.setContentsMargins(12, 8, 12, 10); adv.setSpacing(7)
        self.brain_status = QLabel(self.brain_service.component_status())
        self.brain_status.setWordWrap(True)
        adv.addRow("组件状态", self.brain_status)
        self.brain_progress = QProgressBar(); self.brain_progress.setRange(0,100)
        self.brain_progress.setValue(100 if self.brain_service.ready() else 0)
        adv.addRow("首次准备", self.brain_progress)
        self.brain_prepare_btn = QPushButton("准备小美丽大脑（Qwen3-8B Q4_K_M，模型约 5.03 GB）")
        self.brain_prepare_btn.setEnabled(not self.brain_service.ready())
        self.brain_prepare_btn.clicked.connect(self._prepare_brain)
        adv.addRow(self.brain_prepare_btn)

        dl_row = QWidget(); dl_l = QHBoxLayout(dl_row); dl_l.setContentsMargins(0,0,0,0); dl_l.setSpacing(7)
        self.brain_download_mode = QComboBox()
        self.brain_download_mode.addItem("NDM 加速下载（推荐）", "ndm")
        self.brain_download_mode.addItem("小美丽内置下载器", "builtin")
        wanted_mode = str(cfg.get("brain",{}).get("download_mode","ndm") or "ndm")
        idx = self.brain_download_mode.findData(wanted_mode)
        if idx >= 0: self.brain_download_mode.setCurrentIndex(idx)
        self.brain_ndm_test_btn = QPushButton("测试 NDM")
        self.brain_ndm_test_btn.clicked.connect(self._brain_test_ndm)
        dl_l.addWidget(self.brain_download_mode, 1); dl_l.addWidget(self.brain_ndm_test_btn)
        adv.addRow("下载方式", dl_row)

        dir_row = QWidget(); dir_l = QHBoxLayout(dir_row); dir_l.setContentsMargins(0,0,0,0); dir_l.setSpacing(7)
        self.brain_ndm_dir = QLineEdit(str(cfg.get("brain",{}).get("ndm_download_dir") or (Path.home() / "Downloads")))
        self.brain_ndm_dir.setPlaceholderText("请选择 NDM 的 Download Directory")
        self.brain_ndm_browse_btn = QPushButton("选择目录")
        self.brain_ndm_browse_btn.clicked.connect(self._brain_choose_ndm_dir)
        dir_l.addWidget(self.brain_ndm_dir, 1); dir_l.addWidget(self.brain_ndm_browse_btn)
        adv.addRow("NDM 下载目录", dir_row)
        ndm_note = QLabel(
            "NDM 模式会把小美丽需要的组件直接发送给本机 Neat Download Manager。"
            "下载完成后会自动监控目录并导入 XiaoMeiliData；若 NDM 没有开启或连接失败，可切换到内置下载器。"
        )
        ndm_note.setWordWrap(True); ndm_note.setStyleSheet("color:#657185;")
        adv.addRow(ndm_note)
        self.brain_advanced_body.setVisible(False)
        bv.addWidget(self.brain_advanced_body)

        chat_box = QGroupBox("对话")
        chat_v = QVBoxLayout(chat_box); chat_v.setContentsMargins(10, 12, 10, 10); chat_v.setSpacing(8)
        self.brain_chat = QListWidget(); self.brain_chat.setWordWrap(True); self.brain_chat.setMinimumHeight(235)
        chat_v.addWidget(self.brain_chat, 1)

        ask_row = QWidget(); ask_l = QHBoxLayout(ask_row); ask_l.setContentsMargins(0,0,0,0); ask_l.setSpacing(8)
        ask_l.addWidget(QLabel("和美丽说话"))
        self.brain_input = QLineEdit(); self.brain_input.setPlaceholderText("例如：美丽，你觉得我今天枪法怎么样？")
        self.brain_input.returnPressed.connect(self._brain_ask)
        self.brain_send_btn = QPushButton("发送")
        self.brain_send_btn.setEnabled(self.brain_service.ready())
        self.brain_send_btn.clicked.connect(self._brain_ask)
        ask_l.addWidget(self.brain_input, 1); ask_l.addWidget(self.brain_send_btn)
        chat_v.addWidget(ask_row)

        chat_controls = QHBoxLayout()
        self.brain_auto_speak = QCheckBox("回答后自动说出来")
        self.brain_auto_speak.setChecked(bool(cfg.get("brain",{}).get("auto_speak", True)))
        clear_chat = QPushButton("清空上下文"); clear_chat.clicked.connect(self._brain_clear_history)
        chat_controls.addWidget(self.brain_auto_speak); chat_controls.addStretch(1); chat_controls.addWidget(clear_chat)
        chat_v.addLayout(chat_controls)
        bv.addWidget(chat_box, 1)

        train_box = QGroupBox("养成工具")
        train_l = QHBoxLayout(train_box); train_l.setContentsMargins(10, 12, 10, 10); train_l.setSpacing(8)
        train_l.addWidget(QLabel("随机度"))
        self.brain_temp = QDoubleSpinBox(); self.brain_temp.setRange(0.20,1.20); self.brain_temp.setSingleStep(0.05); self.brain_temp.setDecimals(2)
        self.brain_temp.setValue(float(cfg.get("brain",{}).get("temperature",0.78)))
        train_l.addWidget(self.brain_temp)
        train_l.addSpacing(6); train_l.addWidget(QLabel("记住最近"))
        self.brain_context = QSpinBox(); self.brain_context.setRange(2,12); self.brain_context.setValue(int(cfg.get("brain",{}).get("context_turns",6)))
        train_l.addWidget(self.brain_context); train_l.addWidget(QLabel("轮"))
        train_l.addStretch(1)
        self.brain_feedback_label = QLabel(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        train_l.addWidget(self.brain_feedback_label)
        self.brain_like_btn = QPushButton("👍 这句像小美丽")
        self.brain_dislike_btn = QPushButton("👎 纠正 / 养成")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_like_btn.clicked.connect(self._brain_like); self.brain_dislike_btn.clicked.connect(self._brain_dislike)
        train_l.addWidget(self.brain_like_btn); train_l.addWidget(self.brain_dislike_btn)
        bv.addWidget(train_box)

        self.brain_rules_dialog = QDialog(self)
        self.brain_rules_dialog.setWindowTitle("养成库 / 语义规则编辑")
        self.brain_rules_dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        rules_dv = QVBoxLayout(self.brain_rules_dialog)
        rules_dv.setContentsMargins(12, 12, 12, 12)
        rules_dv.setSpacing(8)

        rules_hint = QLabel(
            "按分组管理固定台词和语义规则。分组只用于整理与查找，不会改变小美丽的匹配逻辑。"
        )
        rules_hint.setWordWrap(True)
        rules_hint.setStyleSheet("color:#657185;")
        rules_dv.addWidget(rules_hint)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索"))
        self.brain_rules_search = QLineEdit()
        self.brain_rules_search.setPlaceholderText("搜索规则、场景、核心意思、参考回答…")
        self.brain_rules_search.setClearButtonEnabled(True)
        self.brain_rules_search.textChanged.connect(self._refresh_brain_rules)
        search_row.addWidget(self.brain_rules_search, 1)
        rules_dv.addLayout(search_row)

        organizer = QHBoxLayout()
        organizer.setSpacing(10)

        groups_box = QGroupBox("分组")
        groups_v = QVBoxLayout(groups_box)
        groups_v.setContentsMargins(9, 12, 9, 9)
        groups_v.setSpacing(7)
        self.brain_rule_groups_list = QListWidget()
        self.brain_rule_groups_list.setMinimumWidth(180)
        self.brain_rule_groups_list.setMaximumWidth(220)
        self.brain_rule_groups_list.setToolTip("选择分组后，右侧只显示该分组里的规则")
        self.brain_rule_groups_list.itemSelectionChanged.connect(self._refresh_brain_rules)
        groups_v.addWidget(self.brain_rule_groups_list, 1)

        group_buttons = QHBoxLayout()
        self.brain_group_new_btn = QPushButton("新建")
        self.brain_group_rename_btn = QPushButton("重命名")
        self.brain_group_delete_btn = QPushButton("删除")
        self.brain_group_new_btn.clicked.connect(self._brain_create_rule_group)
        self.brain_group_rename_btn.clicked.connect(self._brain_rename_rule_group)
        self.brain_group_delete_btn.clicked.connect(self._brain_delete_rule_group)
        group_buttons.addWidget(self.brain_group_new_btn)
        group_buttons.addWidget(self.brain_group_rename_btn)
        group_buttons.addWidget(self.brain_group_delete_btn)
        groups_v.addLayout(group_buttons)
        organizer.addWidget(groups_box, 0)

        rules_panel = QWidget()
        rules_v = QVBoxLayout(rules_panel)
        rules_v.setContentsMargins(0, 0, 0, 0)
        rules_v.setSpacing(7)
        self.brain_rules_list = QListWidget()
        self.brain_rules_list.setMinimumHeight(360)
        self.brain_rules_list.setToolTip("双击任意规则即可编辑")
        self.brain_rules_list.itemDoubleClicked.connect(lambda item: self._brain_edit_rule())
        rules_v.addWidget(self.brain_rules_list, 1)

        move_row = QHBoxLayout()
        move_row.addWidget(QLabel("移动选中规则到"))
        self.brain_rule_move_combo = QComboBox()
        self.brain_rule_move_combo.setMinimumWidth(170)
        move_row.addWidget(self.brain_rule_move_combo)
        self.brain_rule_move_btn = QPushButton("移动")
        self.brain_rule_move_btn.clicked.connect(self._brain_move_rule_to_group)
        move_row.addWidget(self.brain_rule_move_btn)
        move_row.addStretch(1)
        rules_v.addLayout(move_row)

        organizer.addWidget(rules_panel, 1)
        rules_dv.addLayout(organizer, 1)

        rules_btns = QHBoxLayout()
        self.brain_rules_refresh_btn = QPushButton("刷新")
        self.brain_rules_edit_btn = QPushButton("编辑")
        self.brain_rules_toggle_btn = QPushButton("启用 / 暂停")
        self.brain_rules_delete_btn = QPushButton("删除")
        self.brain_rules_refresh_btn.clicked.connect(self._refresh_brain_rules)
        self.brain_rules_edit_btn.clicked.connect(self._brain_edit_rule)
        self.brain_rules_toggle_btn.clicked.connect(self._brain_toggle_rule)
        self.brain_rules_delete_btn.clicked.connect(self._brain_delete_rule)
        rules_btns.addWidget(self.brain_rules_refresh_btn)
        rules_btns.addWidget(self.brain_rules_edit_btn)
        rules_btns.addWidget(self.brain_rules_toggle_btn)
        rules_btns.addWidget(self.brain_rules_delete_btn)
        rules_btns.addStretch(1)
        rules_close = QPushButton("关闭")
        rules_close.clicked.connect(self.brain_rules_dialog.accept)
        rules_btns.addWidget(rules_close)
        rules_dv.addLayout(rules_btns)

        self.brain_persona_dialog = QDialog(self)
        self.brain_persona_dialog.setWindowTitle("小美丽性格编辑")
        self.brain_persona_dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        persona_v = QVBoxLayout(self.brain_persona_dialog); persona_v.setContentsMargins(12,12,12,12); persona_v.setSpacing(8)
        persona_hint = QLabel("这里决定小美丽的人设、性格和说话方式。JSON 输出协议由程序内部锁定，不需要写进性格卡。")
        persona_hint.setWordWrap(True); persona_hint.setStyleSheet("color:#657185;")
        persona_v.addWidget(persona_hint)
        self.brain_persona = QTextEdit(); self.brain_persona.setMinimumHeight(300)
        self.brain_persona.setPlainText(str(cfg.get("brain",{}).get("persona") or DEFAULT_PERSONA))
        persona_v.addWidget(self.brain_persona, 1)
        persona_btns = QHBoxLayout()
        reset_persona = QPushButton("恢复默认人格"); reset_persona.clicked.connect(self._brain_reset_persona)
        persona_btns.addWidget(reset_persona); persona_btns.addStretch(1)
        persona_cancel = QPushButton("取消"); persona_cancel.clicked.connect(self.brain_persona_dialog.reject)
        persona_save = QPushButton("保存并应用"); persona_save.clicked.connect(self._save_persona_dialog)
        persona_btns.addWidget(persona_cancel); persona_btns.addWidget(persona_save); persona_v.addLayout(persona_btns)

        cards = QHBoxLayout(); cards.setSpacing(9)
        rules_card = QGroupBox("养成库 / 语义规则")
        rcv = QVBoxLayout(rules_card); rcv.setContentsMargins(10,12,10,10)
        rdesc = QLabel("管理固定台词、语义规则、触发逻辑与启用状态")
        rdesc.setWordWrap(True); rdesc.setStyleSheet("color:#657185;")
        open_rules = QPushButton("打开编辑"); open_rules.clicked.connect(self._open_brain_rules_editor)
        rcv.addWidget(rdesc); rcv.addWidget(open_rules)
        persona_card = QGroupBox("小美丽性格")
        pcv = QVBoxLayout(persona_card); pcv.setContentsMargins(10,12,10,10)
        pdesc = QLabel("编辑小美丽的人设、性格和说话风格")
        pdesc.setWordWrap(True); pdesc.setStyleSheet("color:#657185;")
        open_persona = QPushButton("打开性格编辑"); open_persona.clicked.connect(self._open_brain_persona_editor)
        pcv.addWidget(pdesc); pcv.addWidget(open_persona)
        cards.addWidget(rules_card, 1); cards.addWidget(persona_card, 1)
        bv.addLayout(cards)

        bnote = QLabel("提示：日常聊天只需要停留在这一页；模型下载、NDM 等低频设置已经收进上方的「模型与下载配置」。")
        bnote.setWordWrap(True); bnote.setStyleSheet("color:#55749E; background:#EEF6FF; border:1px solid #D5E8FF; border-radius:7px; padding:6px 8px;")
        bv.addWidget(bnote)
        self.tabs.addTab(bp, "大脑")

        self.brain_service.setup_progress.connect(self._brain_setup_progress)
        self.brain_service.setup_finished.connect(self._brain_setup_finished)
        self.brain_service.status_changed.connect(self.brain_status.setText)
        self.brain_service.generation_started.connect(self._brain_generation_started)
        self.brain_service.generation_finished.connect(self._brain_generation_finished)
        self.brain_service.rule_proposed.connect(self._brain_rule_proposed)
        self._pending_semantic_lesson = None
        self._refresh_brain_rules()

        # Updates V0.7.7.3: fixed-height release notes prevent window overflow.
        up = QWidget(); uv = QVBoxLayout(up)
        uv.setContentsMargins(10, 10, 10, 10); uv.setSpacing(9)

        ubox = QGroupBox("检查更新"); uf = QFormLayout(ubox)
        uf.setContentsMargins(12, 12, 12, 10); uf.setSpacing(7)
        self.update_version_label = QLabel(f"V{APP_VERSION}")
        uf.addRow("当前版本", self.update_version_label)

        source_row = QWidget(); source_l = QHBoxLayout(source_row); source_l.setContentsMargins(0,0,0,0); source_l.setSpacing(7)
        self.update_url = QLineEdit(self.update_service.manifest_url())
        self.update_url.setPlaceholderText("永久更新清单地址（latest.json）")
        save_source = QPushButton("保存更新源"); save_source.clicked.connect(self._save_update_source)
        source_l.addWidget(self.update_url, 1); source_l.addWidget(save_source)
        uf.addRow("更新源", source_row)

        self.update_status = QLabel("尚未检查更新")
        self.update_status.setWordWrap(True)
        self.update_status.setMaximumHeight(48)
        uf.addRow("状态", self.update_status)
        self.update_progress = QProgressBar(); self.update_progress.setRange(0,100); self.update_progress.setValue(0)
        uf.addRow("更新进度", self.update_progress)

        update_buttons = QWidget(); update_l = QHBoxLayout(update_buttons); update_l.setContentsMargins(0,0,0,0); update_l.setSpacing(8)
        self.update_check_btn = QPushButton("检查更新")
        self.update_install_btn = QPushButton("立即更新"); self.update_install_btn.setEnabled(False)
        self.update_check_btn.clicked.connect(self._check_update); self.update_install_btn.clicked.connect(self._install_update)
        update_l.addWidget(self.update_check_btn); update_l.addWidget(self.update_install_btn)
        uf.addRow(update_buttons)
        uv.addWidget(ubox)

        notes_box = QGroupBox("更新内容")
        notes_v = QVBoxLayout(notes_box); notes_v.setContentsMargins(10,12,10,10)
        self.update_notes = QTextEdit(); self.update_notes.setReadOnly(True)
        self.update_notes.setMinimumHeight(205); self.update_notes.setMaximumHeight(270)
        self.update_notes.setPlainText("点击「检查更新」后，本次版本说明会显示在这里。\n内容再多也只在这个区域内滚动，不会把设置窗口撑出屏幕。")
        notes_v.addWidget(self.update_notes)
        uv.addWidget(notes_box, 1)

        unote = QLabel("更新包会先下载到 XiaoMeiliData/updates，完成完整性与 SHA-256 校验后再替换程序。个人配置、模型、动作素材和养成数据不会被覆盖。")
        unote.setWordWrap(True); unote.setStyleSheet("color:#657185;")
        uv.addWidget(unote)
        self.tabs.addTab(up, "更新")
        self.update_service.status_changed.connect(self.update_status.setText)
        self.update_service.check_finished.connect(self._update_check_finished)
        self.update_service.progress_changed.connect(self._update_progress_changed)

        # Storage V0.7.6
        sp = QWidget(); sv = QVBoxLayout(sp)
        sbox = QGroupBox("小美丽存储位置"); sf = QFormLayout(sbox)
        self.storage_current = QLabel("")
        self.storage_current.setWordWrap(True)
        sf.addRow("当前位置", self.storage_current)

        target_row = QWidget(); target_l = QHBoxLayout(target_row); target_l.setContentsMargins(0,0,0,0)
        self.storage_target = QLineEdit(r"D:\XiaoMeiliData")
        self.storage_target.setReadOnly(True)
        self.storage_browse = QPushButton("固定安全目录")
        self.storage_browse.setEnabled(False)
        target_l.addWidget(self.storage_target, 1); target_l.addWidget(self.storage_browse)
        sf.addRow("迁移目标", target_row)

        self.storage_migrate_btn = QPushButton("一键迁移到 D 盘并自动重启")
        self.storage_migrate_btn.clicked.connect(self._storage_migrate)
        sf.addRow(self.storage_migrate_btn)

        self.storage_refresh_btn = QPushButton("刷新存储状态")
        self.storage_refresh_btn.clicked.connect(self._refresh_storage_status)
        sf.addRow(self.storage_refresh_btn)

        sv.addWidget(sbox)
        snote = QLabel(
            "V0.7.6 会把 XiaoMeiliData 整体搬到 D 盘，包括 Qwen3-8B、llama.cpp、Qwen3-TTS、"
            "语音运行环境、动作素材、养成库、日志、调试文件和更新缓存。\n"
            "为保证以前所有绝对路径和桌宠效果完全不变，C:\\Users\\Public\\XiaoMeiliData "
            "会变成一个几乎不占空间的 Windows 兼容入口（Junction），实际文件全部在 D 盘。\n"
            "小美丽程序核心 EXE 仍保留在原安装位置，因为它体积远小于模型，并可避免破坏现有快捷方式与自更新器。"
        )
        snote.setWordWrap(True); sv.addWidget(snote); sv.addStretch(1)
        self.tabs.addTab(sp, "存储")
        self._refresh_storage_status()

        # Vision
        vp=QWidget(); vv=QVBoxLayout(vp)
        box=QGroupBox("VALORANT 自动识别（仅分析屏幕像素）"); vf=QFormLayout(box)
        self.vision_enabled=QCheckBox("启用自动识别")
        self.vision_enabled.setChecked(bool(cfg.get("vision",{}).get("enabled",True)))
        vf.addRow(self.vision_enabled)
        self.nickname_edit = QLineEdit(str(cfg.get("vision",{}).get("player_nickname", "")))
        self.nickname_edit.setPlaceholderText("例如：我是朱棣（填写游戏击杀信息中显示的昵称）")
        nick_label=QWidget(); nick_lay=QHBoxLayout(nick_label); nick_lay.setContentsMargins(0,0,0,0)
        nick_lay.addWidget(QLabel("我的游戏昵称")); nick_lay.addWidget(HelpBadge("用于击杀栏二次校验，也用于整局结算页在5张玩家卡片中找到你。换账号或改名后只需要修改这里。")); nick_lay.addStretch(1)
        vf.addRow(nick_label, self.nickname_edit)
        self.hp_threshold=QSpinBox(); self.hp_threshold.setRange(1,99); self.hp_threshold.setValue(int(cfg.get("vision",{}).get("low_hp_threshold",50)))
        self.hp_threshold.setSuffix(" HP")
        vf.addRow("低血量触发阈值 ≤",self.hp_threshold)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("极低功耗模式（推荐）", "ultra_low")
        self.mode_combo.addItem("调试模式（更高刷新率）", "debug")
        current_mode = str(cfg.get("vision", {}).get("mode", "ultra_low"))
        idx = self.mode_combo.findData(current_mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        vf.addRow("识别模式", self.mode_combo)
        self.pause_bg = QCheckBox("VALORANT 不在前台时自动休眠")
        self.pause_bg.setChecked(bool(cfg.get("vision", {}).get("pause_when_background", True)))
        vf.addRow(self.pause_bg)
        self.nickname_ocr_cb = QCheckBox("昵称 OCR 二次校验（仅在贤者头像判断模糊时启用）")
        self.nickname_ocr_cb.setChecked(bool(cfg.get("vision", {}).get("nickname_ocr_fallback", True)))
        vf.addRow(self.nickname_ocr_cb)
        logic_row=QHBoxLayout(); logic_row.addWidget(QLabel("识别说明")); logic_row.addWidget(HelpBadge(
            "先确认顶部真实比赛HUD，再允许存活/HP/击杀/死亡/胜负识别；大厅、选人和加载界面保持待机。\n"
            "整局战报与英雄选择解耦：真实对局期间战报OCR完全休眠，只登记本局。直播HUD消失后的前20秒使用约5FPS轻量雷达，之后自动降频。检测到真正的五人结算卡后会立刻把最佳高清候选帧缓存到内存；随后再等待短暂稳定确认。即使你在0.5秒左右马上点“继续”，也会使用刚缓存的五卡画面，而不会误截后面的奖励/再玩一局页面。之后只解析昵称和K，D和A不参与结果判断。")); logic_row.addStretch(1)
        vf.addRow(logic_row)
        vv.addWidget(box)

        hcfg=cfg.setdefault("highlight_cta",{})
        hbox=QGroupBox("高光回合 · P100 最高优先级")
        hf=QFormLayout(hbox)
        self.highlight_enabled=QCheckBox("启用高光关注事件")
        self.highlight_enabled.setChecked(bool(hcfg.get("enabled",True)))
        hf.addRow(self.highlight_enabled)

        identity=QLabel(str(cfg.get("vision",{}).get("player_nickname","")).strip() or "未绑定")
        identity.setStyleSheet("font-weight:700;")
        hf.addRow("绑定玩家（来自上方昵称）",identity)

        self.highlight_min_kills=QSpinBox()
        self.highlight_min_kills.setRange(1,5)
        self.highlight_min_kills.setValue(int(hcfg.get("min_kills",2)))
        hf.addRow("最低本人击杀",self.highlight_min_kills)

        self.highlight_phrases=QTextEdit()
        self.highlight_phrases.setMinimumHeight(108)
        _phrases=hcfg.get("phrases") or [
            "愣着干嘛，点点关注呀！",
            "这波还不值得一个关注？",
            "看完还想白嫖呀？",
        ]
        self.highlight_phrases.setPlainText("\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        # Dedicated high-glow video pool. Imported MP4s are re-encoded without
        # audio into XiaoMeiliData so source-track audio can never leak into TTS.
        video_panel=QWidget()
        video_l=QVBoxLayout(video_panel); video_l.setContentsMargins(0,0,0,0); video_l.setSpacing(6)
        self.highlight_video_list=QListWidget()
        self.highlight_video_list.setMinimumHeight(82)
        for _p in hcfg.get("videos",[]) if isinstance(hcfg.get("videos"),list) else []:
            if str(_p or "").strip():
                _boxes=hcfg.get("video_text_boxes") if isinstance(hcfg.get("video_text_boxes"),dict) else {}
                _name=Path(str(_p)).name
                _item=QListWidgetItem(("✓ " if _name in _boxes else "")+_name)
                _item.setData(Qt.ItemDataRole.UserRole,str(_p))
                self.highlight_video_list.addItem(_item)
        video_l.addWidget(self.highlight_video_list)
        _vr=QHBoxLayout()
        self.highlight_import_video_btn=QPushButton("导入白板视频")
        self.highlight_remove_video_btn=QPushButton("移出列表")
        self.highlight_remove_video_btn.setToolTip("只从高光素材池移除，不删除磁盘上的视频文件。")
        self.highlight_text_box_btn=QPushButton("文字与限制框")
        self.highlight_preview_btn=QPushButton("预览")
        self.highlight_preview_btn.setToolTip("随机抽取一条播报台词，并按实战逻辑轮换高光白板视频。")
        self.highlight_import_video_btn.clicked.connect(self._v0911_import_highlight_videos)
        self.highlight_remove_video_btn.clicked.connect(self._v0911_remove_highlight_video)
        self.highlight_text_box_btn.clicked.connect(self._v0911_edit_highlight_text_box)
        self.highlight_preview_btn.clicked.connect(self._v0924_preview_highlight)
        if not getattr(self,"_v0925_preview_signals_bound",False):
            self.voice_service.playback_started.connect(self._v0925_highlight_preview_started)
            self.voice_service.playback_finished.connect(self._v0925_highlight_preview_finished)
            self._v0925_preview_signals_bound=True
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_text_box_btn,self.highlight_preview_btn):
            _vr.addWidget(_b)
        _vr.addStretch(1)
        video_l.addLayout(_vr)
        _vh=QLabel("每支白板都可保存自己的文字限制框；先选中视频，再点“文字与限制框”。实战与“预览”会分别随机抽取视频和台词并合并播放，语音结束后动画继续循环 3 秒。")
        _vh.setWordWrap(True); _vh.setObjectName("pageSubtitle"); video_l.addWidget(_vh)
        hf.addRow("高光白板视频",video_panel)

        self.highlight_status=QLabel(
            "本人击杀：0  |  敌方存活：?/5  |  存活：未确认\n"
            "最后一杀：非本人\n最近判定：等待"
        )
        self.highlight_status.setWordWrap(True)
        hf.addRow("实时状态",self.highlight_status)

        self.highlight_qualification=QLabel("高光资格：未满足")
        self.highlight_qualification.setObjectName("highlightQualification")
        self.highlight_qualification.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.highlight_qualification.setMinimumHeight(54)
        self.highlight_qualification.setStyleSheet(
            "QLabel#highlightQualification{background:#FDE8E8;color:#B42318;"
            "border:1px solid #F4B4B4;border-radius:10px;padding:10px 14px;"
            "font-size:20px;font-weight:900;}"
        )
        hf.addRow(self.highlight_qualification)

        hnote=QLabel("已支持导入专属高光白板视频；导入时自动去除原生音轨。随机台词会同时用于白板文字和小美丽TTS，并使用文字限制框排版。")
        hnote.setWordWrap(True)
        hf.addRow(hnote)
        vv.addWidget(hbox)

        live=QGroupBox("战报识别状态"); lv=QVBoxLayout(live)
        self.report_snapshot_status=QLabel("战报快照：未锁定")
        self.report_snapshot_status.setStyleSheet("font-size:16px;font-weight:700;color:#D62828;padding:4px 0;")
        self.report_parse_label=QLabel("战报解析：等待结算动画结束")
        self.report_parse_label.setWordWrap(True)
        lv.addWidget(self.report_snapshot_status)
        lv.addWidget(self.report_parse_label)
        QTimer.singleShot(0,self._v0911_style_report_snapshot_bar)
        self.vision_status=QLabel("等待识别数据...")
        self.vision_status.setWordWrap(True); self.vision_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.vision_status.setVisible(False)
        self.diag_btn=QPushButton("显示高级诊断")
        self.diag_btn.setCheckable(True)
        def _toggle_diag(checked):
            self.vision_status.setVisible(bool(checked))
            self.diag_btn.setText("隐藏高级诊断" if checked else "显示高级诊断")
        self.diag_btn.toggled.connect(_toggle_diag)
        lv.addWidget(self.diag_btn)
        lv.addWidget(self.vision_status)
        brow=QHBoxLayout()
        debug_btn=QPushButton("保存下一帧识别调试图")
        debug_btn.clicked.connect(self.request_debug)
        open_debug=QPushButton("打开调试目录")
        open_debug.clicked.connect(lambda: os.startfile(str(DEBUG_DIR)) if sys.platform=='win32' else None)
        report_test_btn=QPushButton("从截图测试战报")
        report_test_btn.setToolTip("跳过真实对局流程，直接用一张整局结算页截图测试：结算布局 → 昵称定位本人卡片 → 只读K数字 → 白板展示。")
        report_test_btn.clicked.connect(self.test_report_from_screenshot)
        brow.addWidget(debug_btn); brow.addWidget(report_test_btn); brow.addWidget(open_debug); lv.addLayout(brow)
        vv.addWidget(live); vv.addStretch(1)
        self.tabs.addTab(vp,"游戏识别")

        # Logs
        lp=QWidget(); ll=QVBoxLayout(lp)
        ll.addWidget(QLabel(f"日志目录：\n{LOG_DIR}\n\n当前日志：\n{CURRENT_LOG}"))
        openlog=QPushButton("打开日志文件夹")
        openlog.clicked.connect(lambda: os.startfile(str(LOG_DIR)) if sys.platform=='win32' else None)
        ll.addWidget(openlog); ll.addStretch(1); self.tabs.addTab(lp,"日志")

        buttons=QHBoxLayout()
        self.apply_status = QLabel("")
        self.apply_status.setStyleSheet("color:#2a8f78;")
        buttons.addWidget(self.apply_status)
        buttons.addStretch(1)
        close_btn=QPushButton("关闭")
        self.save_btn=QPushButton("保存并应用")
        self.save_btn.setEnabled(False)
        close_btn.clicked.connect(self.reject); self.save_btn.clicked.connect(self.apply)
        buttons.addWidget(close_btn); buttons.addWidget(self.save_btn); root.addLayout(buttons)
        self._bind_dirty_tracking()
        self._install_v0774_shell(root)

    def _populate_voice_outputs(self):
        current = str(self.cfg.get("voice", {}).get("output_device", "default") or "default")
        if hasattr(self, "voice_output_combo"):
            selected = self.voice_output_combo.currentData()
            if selected:
                current = str(selected)
            self.voice_output_combo.blockSignals(True)
            self.voice_output_combo.clear()
            try:
                items = self.voice_service.output_devices()
            except Exception as e:
                LOGGER.exception("枚举播放设备失败")
                items = [("default", "系统默认播放设备")]
            for key, label in items:
                self.voice_output_combo.addItem(str(label), str(key))
            idx = self.voice_output_combo.findData(current)
            if idx < 0:
                idx = self.voice_output_combo.findData("default")
            if idx >= 0:
                self.voice_output_combo.setCurrentIndex(idx)
            self.voice_output_combo.blockSignals(False)

    def _brain_choose_ndm_dir(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.brain_ndm_dir.text().strip() or str(Path.home() / "Downloads")
        chosen = QFileDialog.getExistingDirectory(self, "选择 NDM 的 Download Directory", start)
        if chosen:
            self.brain_ndm_dir.setText(chosen)
            self._brain_save_settings()

    def _brain_test_ndm(self):
        ok, msg = self.brain_service.test_ndm()
        self.brain_status.setText(msg)
        if not ok:
            QMessageBox.warning(self, "NDM 未连接", "没有连接到 Neat Download Manager。\n\n请先打开 NDM，再点击“测试 NDM”。")

    def _v774_page(self, title, subtitle):
        self._v0883_current_page = str(title or "")
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)

        heading = QWidget()
        hv = QVBoxLayout(heading)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(5)
        title_label = QLabel(str(title))
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(str(subtitle))
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        hv.addWidget(title_label)
        hv.addWidget(subtitle_label)

        hl.addWidget(heading, 1)
        theme_btn = QPushButton("☾")
        theme_btn.setObjectName("themeButton")
        theme_btn.setFixedSize(34, 34)
        theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        theme_btn.setToolTip("切换到夜间模式")
        theme_btn.clicked.connect(self._v0775_toggle_theme)
        hl.addWidget(theme_btn, 0, Qt.AlignmentFlag.AlignTop)
        if not hasattr(self, "v0777_theme_buttons"):
            self.v0777_theme_buttons = []
        self.v0777_theme_buttons.append(theme_btn)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(12)
        outer.addWidget(body, 1)
        return page, body_layout

    def _v0882_feature_meta(self, title):
        # Stable IDs for known tiles keep V0.8.8.2 favorites compatible.
        # Any future _v774_card tile still receives a favorite button via the
        # page/title fallback instead of silently losing the control.
        mapping = {
            "昵称": ("general.name", "常规"),
            "开机启动": ("general.autostart", "常规"),
            "始终置顶": ("general.top", "常规"),
            "点击穿透": ("general.clickthrough", "常规"),
            "锁定位置": ("general.lock", "常规"),
            "透明度": ("general.opacity", "常规"),
            "桌宠大小": ("general.size", "常规"),
            "快捷键": ("general.hotkeys", "常规"),
            "桌宠位置": ("general.position", "常规"),
            "AI 大脑": ("brain.ai", "大脑"),
            "小美丽性格": ("brain.persona", "大脑"),
            "记忆": ("brain.memory", "大脑"),
            "学习与养成": ("brain.learning", "大脑"),
            "表达自由度": ("brain.expression", "大脑"),
            "对话测试": ("brain.chat_test", "大脑"),
            "唤醒词": ("voice.wake", "声音"),
            "语音识别": ("voice.asr", "声音"),
            "语音对话": ("voice.dialogue", "声音"),
            "唤醒回应": ("voice.wake_replies", "声音"),
            "小美丽声音": ("voice.tts", "声音"),
            "单句语气微调": ("voice.phrase_style", "声音"),
            "回答后自动说出来": ("voice.auto_speak", "声音"),
            "声音输出": ("voice.output", "声音"),
            "输入设备": ("voice.input", "声音"),
            "鼠标跟随": ("interaction.mouse", "互动"),
            "跟随强度": ("interaction.strength", "互动"),
            "拖拽互动": ("interaction.drag", "互动"),
            "游戏防误触锁定": ("interaction.game_lock", "互动"),
            "主动互动": ("interaction.proactive", "互动"),
            "点击反馈": ("interaction.click", "互动"),
            "动画过渡": ("interaction.transition", "互动"),
            "美丽能力": ("interaction.abilities", "互动"),
            "动作库": ("actions.library", "动作"),
            "白板播报": ("actions.whiteboard", "动作"),
            "事件触发": ("actions.event_trigger", "动作"),
        }
        title = str(title or "").strip()
        known = mapping.get(title)
        if known:
            return known
        page = str(getattr(self, "_v0883_current_page", "") or "设置").strip()
        return (f"card:{page}:{title}", page)

    def _v0891_favorites_file(self):
        root = Path(xiaomeili_logical_data_root()) / "ui_state"
        root.mkdir(parents=True, exist_ok=True)
        return root / "favorites_v2.json"

    @staticmethod
    def _v0891_clean_favorite_ids(values):
        clean = []
        if not isinstance(values, list):
            return clean
        for value in values:
            value = str(value or "").strip()
            if value and value not in clean:
                clean.append(value)
        return clean

    def _v0891_read_favorites_file(self):
        path = self._v0891_favorites_file()
        backup = path.with_suffix(".bak")
        for candidate in (path, backup):
            try:
                if not candidate.exists():
                    continue
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                values = payload.get("favorites") if isinstance(payload, dict) else payload
                if isinstance(values, list):
                    return self._v0891_clean_favorite_ids(values)
            except Exception:
                LOGGER.warning("读取常用独立状态失败: %s", candidate, exc_info=True)
        return None

    def _v0891_write_favorites_file(self, values):
        clean = self._v0891_clean_favorite_ids(values)
        path = self._v0891_favorites_file()
        temp = path.with_suffix(".tmp")
        backup = path.with_suffix(".bak")
        payload = {"schema": 2, "favorites": clean}
        try:
            if path.exists():
                try:
                    backup.write_bytes(path.read_bytes())
                except Exception:
                    LOGGER.warning("备份常用状态失败", exc_info=True)
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(path)
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass
        return clean

    def _v0882_favorites(self):
        # Dedicated UI-state file is authoritative from V0.8.9.1 onward.
        file_values = self._v0891_read_favorites_file()
        ui = self.cfg.setdefault("settings_ui", {})
        if file_values is not None:
            ui["favorites_v0882"] = list(file_values)
            return list(file_values)

        # One-time migration from the old config field. An empty/missing old
        # value on the buggy builds is treated as lost state and repaired to the
        # original three defaults. After the new file exists, an intentionally
        # empty Favorites page remains empty across restarts.
        defaults = ["brain.learning", "brain.chat_test", "actions.event_trigger"]
        legacy = ui.get("favorites_v0882")
        values = self._v0891_clean_favorite_ids(legacy)
        if not values:
            values = list(defaults)

        self._v0891_write_favorites_file(values)
        ui["favorites_v0882"] = list(values)
        try:
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("迁移常用状态到主配置镜像失败，但独立状态文件已保存", exc_info=True)
        return list(values)

    def _v0882_save_favorites(self, values):
        clean = self._v0891_write_favorites_file(values)

        # Mirror into the main config for backward compatibility, but Favorites
        # no longer depends on that monolithic file surviving every legacy save.
        self.cfg.setdefault("settings_ui", {})["favorites_v0882"] = list(clean)
        try:
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("保存常用到主配置镜像失败，独立状态文件仍然有效", exc_info=True)

        self._v0882_refresh_favorite_buttons()
        self._v0882_refresh_favorites()

    def _v0882_go_page(self, page_name):
        try:
            self._v774_switch_page(self.v774_nav_names.index(str(page_name)))
        except Exception:
            LOGGER.warning("常用入口定位失败: %s", page_name, exc_info=True)

    def _v0882_register_feature(self, feature_id, title, description, page_name, action=None):
        if not hasattr(self, "v0882_feature_catalog"):
            self.v0882_feature_catalog = {}
        self.v0882_feature_catalog[str(feature_id)] = {
            "id": str(feature_id),
            "title": str(title),
            "description": str(description or ""),
            "page": str(page_name),
            "action": action,
        }

    def _v0882_register_card(self, card, title, description, button_slot=None):
        feature_id, page_name = self._v0882_feature_meta(title)
        action = button_slot if callable(button_slot) else None
        self._v0882_register_feature(feature_id, title, description, page_name, action)

        active = feature_id in self._v0882_favorites()
        btn = FavoriteStarButton(active, card)
        btn.setToolTip("从常用移除" if active else "添加到常用")
        btn.setAccessibleName(("取消收藏：" if active else "收藏：") + str(title))
        btn.clicked.connect(lambda checked=False, fid=feature_id: self._v0882_toggle_favorite(fid))
        try:
            card.layout().addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        except Exception:
            return
        if not hasattr(self, "v0882_favorite_buttons"):
            self.v0882_favorite_buttons = {}
        self.v0882_favorite_buttons.setdefault(feature_id, []).append(btn)

    def _v0882_toggle_favorite(self, feature_id):
        values = self._v0882_favorites()
        if feature_id in values:
            values = [x for x in values if x != feature_id]
        else:
            values.append(feature_id)
        self._v0882_save_favorites(values)

    def _v0882_refresh_favorite_buttons(self):
        selected = set(self._v0882_favorites())
        for feature_id, buttons in getattr(self, "v0882_favorite_buttons", {}).items():
            for btn in list(buttons):
                try:
                    active = feature_id in selected
                    btn.setChecked(active)
                    btn.setToolTip("从常用移除" if active else "添加到常用")
                    btn.setAccessibleName(("取消收藏：" if active else "收藏：") + str(feature_id))
                    btn.update()
                except Exception:
                    pass

    def _v0882_open_feature(self, feature_id):
        item = getattr(self, "v0882_feature_catalog", {}).get(str(feature_id))
        if not item:
            return
        action = item.get("action")
        if callable(action):
            try:
                action()
                return
            except Exception:
                LOGGER.warning("常用快捷功能执行失败: %s", feature_id, exc_info=True)
        self._v0882_go_page(item.get("page") or "常规")

    def _v0882_make_favorite_card(self, item):
        card = QFrame()
        card.setObjectName("settingCard")
        card.setMinimumHeight(112)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 12, 14)
        lay.setSpacing(12)

        text_box = QWidget()
        tv = QVBoxLayout(text_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        title = QLabel(str(item.get("title") or "快捷功能"))
        title.setObjectName("cardTitle")
        value = QLabel(str(item.get("description") or ""))
        value.setObjectName("cardValue")
        value.setWordWrap(True)
        source = QLabel(f"来自：{item.get('page') or '设置'}")
        source.setObjectName("cardDesc")
        tv.addWidget(title)
        tv.addWidget(value)
        tv.addWidget(source)
        lay.addWidget(text_box, 1)

        action_box = QWidget()
        av = QVBoxLayout(action_box)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(6)
        star = FavoriteStarButton(True, action_box)
        star.setToolTip("从常用移除")
        star.setAccessibleName("取消收藏：" + str(item.get("title") or ""))
        star.clicked.connect(lambda checked=False, fid=item.get("id"): self._v0882_toggle_favorite(fid))
        av.addWidget(star, 0, Qt.AlignmentFlag.AlignRight)
        av.addStretch(1)

        open_btn = QPushButton("打开" if callable(item.get("action")) else "定位")
        open_btn.setObjectName("cardButton")
        open_btn.clicked.connect(lambda checked=False, fid=item.get("id"): self._v0882_open_feature(fid))
        av.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignRight)
        av.addStretch(1)
        lay.addWidget(action_box, 0)
        return card

    def _v0882_refresh_favorites(self):
        grid = getattr(self, "v0882_favorites_grid", None)
        if grid is None:
            return
        while grid.count():
            child = grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        selected = self._v0882_favorites()
        catalog = getattr(self, "v0882_feature_catalog", {})
        visible = [catalog[x] for x in selected if x in catalog]
        if not visible:
            empty = QLabel("还没有常用功能。点击右上角「管理常用」，或在其他页面点 ☆ 收藏。")
            empty.setWordWrap(True)
            empty.setObjectName("pageSubtitle")
            grid.addWidget(empty, 0, 0, 1, 2)
            return
        for i, item in enumerate(visible):
            grid.addWidget(self._v0882_make_favorite_card(item), i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

    def _v0882_manage_favorites(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("管理常用")
        try: dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        except Exception: pass
        dlg.resize(620, 650)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("选择常用功能")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        desc = QLabel("勾选要固定到「常用」的功能。选中项目可用上移 / 下移调整顺序。")
        desc.setWordWrap(True)
        desc.setObjectName("pageSubtitle")
        root.addWidget(desc)

        listing = QListWidget()
        catalog = getattr(self, "v0882_feature_catalog", {})
        selected = self._v0882_favorites()
        ordered_ids = [x for x in selected if x in catalog]
        ordered_ids += [x for x in catalog.keys() if x not in ordered_ids]
        for fid in ordered_ids:
            meta = catalog[fid]
            item = QListWidgetItem(f"{meta.get('title')}    ·    {meta.get('page')}")
            item.setData(Qt.ItemDataRole.UserRole, fid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if fid in selected else Qt.CheckState.Unchecked)
            listing.addItem(item)
        root.addWidget(listing, 1)

        move_row = QHBoxLayout()
        up = QPushButton("↑ 上移")
        down = QPushButton("↓ 下移")
        reset = QPushButton("恢复默认")
        move_row.addWidget(up); move_row.addWidget(down); move_row.addStretch(1); move_row.addWidget(reset)
        root.addLayout(move_row)

        def move(delta):
            row = listing.currentRow()
            target = row + int(delta)
            if row < 0 or target < 0 or target >= listing.count():
                return
            item = listing.takeItem(row)
            listing.insertItem(target, item)
            listing.setCurrentRow(target)

        up.clicked.connect(lambda: move(-1))
        down.clicked.connect(lambda: move(1))

        def reset_defaults():
            defaults = {"brain.learning", "brain.chat_test", "actions.event_trigger"}
            for i in range(listing.count()):
                item = listing.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in defaults else Qt.CheckState.Unchecked)

        reset.clicked.connect(reset_defaults)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        save = QPushButton("保存并应用")
        buttons.addWidget(cancel); buttons.addWidget(save)
        root.addLayout(buttons)
        cancel.clicked.connect(dlg.reject)

        def commit():
            values = []
            for i in range(listing.count()):
                item = listing.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    values.append(str(item.data(Qt.ItemDataRole.UserRole)))
            self._v0882_save_favorites(values)
            dlg.accept()

        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _v774_card(self, title, value="", description="", button_text="", button_slot=None, control=None):
        card = QFrame()
        card.setObjectName("settingCard")
        card.setMinimumHeight(106)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 16, 14)
        lay.setSpacing(14)
        text_box = QWidget()
        tv = QVBoxLayout(text_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        ttl = QLabel(str(title))
        ttl.setObjectName("cardTitle")
        val = QLabel(str(value))
        val.setObjectName("cardValue")
        val.setWordWrap(True)
        tv.addWidget(ttl)
        tv.addWidget(val)
        if description:
            desc = QLabel(str(description))
            desc.setObjectName("cardDesc")
            desc.setWordWrap(True)
            tv.addWidget(desc)
        lay.addWidget(text_box, 1)
        if control is not None:
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        elif button_text:
            btn = QPushButton(str(button_text))
            btn.setObjectName("cardButton")
            if button_slot is not None:
                btn.clicked.connect(button_slot)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        try:
            self._v0882_register_card(card, title, description, button_slot)
        except Exception:
            LOGGER.warning("注册常用卡片失败: %s", title, exc_info=True)
        return card, val

    def _v774_scroll_grid(self, cards, columns=2):
        host = QWidget()
        host.setObjectName("settingsScrollHost")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 4, 4)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for i, card in enumerate(cards):
            grid.addWidget(card, i // columns, i % columns)
        for c in range(columns):
            grid.setColumnStretch(c, 1)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScrollArea")
        scroll.viewport().setObjectName("settingsScrollViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll

    def _v774_legacy_index(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                return i
        return -1

    def _v774_take_legacy_page(self, title):
        idx = self._v774_legacy_index(title)
        if idx < 0:
            return None
        page = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        page.setParent(None)
        return page

    def _v0775_build_legacy_dialog(self, title, window_title=None, size=(940, 650)):
        idx = self._v774_legacy_index(title)
        if idx < 0:
            return None, None, -1

        self.tabs.setCurrentIndex(idx)
        page = self.tabs.widget(idx)
        if page is None:
            return None, None, -1

        # Removing a page from a hidden QTabWidget can leave WA_WState_Hidden
        # set. Clear that state explicitly after the new parent is assigned.
        self.tabs.removeTab(idx)

        dialog = QDialog(self)
        dialog.setWindowTitle(window_title or title)
        dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dialog.resize(int(size[0]), int(size[1]))
        dialog.setMinimumSize(720, 520)

        dv = QVBoxLayout(dialog)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(10)

        page.setParent(dialog)
        dv.addWidget(page, 1)
        page.setVisible(True)
        page.show()
        page.raise_()

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryCloseButton")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dv.addLayout(close_row)

        try:
            self._v0775_apply_native_titlebar(dialog, self._v0775_theme_mode == "dark")
        except Exception:
            pass

        dialog._v0775_page = page
        dialog._v0775_tab_title = str(title)
        dialog._v0775_original_index = int(idx)
        return dialog, page, idx

    def _v0775_restore_legacy_dialog(self, dialog, page, idx, title):
        if page is None:
            return
        try:
            page.hide()
            layout = dialog.layout() if dialog is not None else None
            if layout is not None:
                layout.removeWidget(page)
            page.setParent(None)
            insert_at = max(0, min(int(idx), self.tabs.count()))
            self.tabs.insertTab(insert_at, page, str(title))
        except Exception:
            LOGGER.exception("恢复二级设置页失败: %s", title)

    def _v774_open_legacy_dialog(self, title, window_title=None, size=(940, 650)):
        dialog, page, idx = self._v0775_build_legacy_dialog(title, window_title, size)
        if dialog is None or page is None:
            QMessageBox.warning(self, "小美丽", f"没有找到「{title}」设置页。")
            return
        try:
            # A queued show is important on Windows after a widget has just left
            # a hidden QTabWidget.
            QTimer.singleShot(0, page.show)
            dialog.exec()
        finally:
            self._v0775_restore_legacy_dialog(dialog, page, idx, title)

    def _v774_hide_form_row(self, widget):
        try:
            parent = widget.parentWidget()
            layout = parent.layout() if parent else None
            if isinstance(layout, QFormLayout):
                label = layout.labelForField(widget)
                if label is not None:
                    label.hide()
            widget.hide()
        except Exception:
            pass

    def _v774_switch_page(self, index):
        index = max(0, min(int(index), self.v774_stack.count() - 1))
        self.v774_stack.setCurrentIndex(index)
        try:
            if self.v774_nav_names[index] == "常用":
                self._v0882_refresh_favorites()
                self._v0882_refresh_favorite_buttons()
        except Exception:
            LOGGER.warning("进入常用页时刷新失败", exc_info=True)
        for i, btn in enumerate(self.v774_nav_buttons):
            btn.setChecked(i == index)
        try:
            ui = self.cfg.setdefault("settings_ui", {})
            ui["last_page"] = self.v774_nav_names[index]
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("保存设置页位置失败", exc_info=True)

    def _v774_schedule_apply(self, *args):
        if hasattr(self, "_v774_apply_timer"):
            self._v774_apply_timer.start(180)

    def _v774_apply_now(self):
        try:
            if hasattr(self, "v774_top_cb"):
                self.top_cb.blockSignals(True)
                self.top_cb.setChecked(bool(self.v774_top_cb.isChecked()))
                self.top_cb.blockSignals(False)
            if hasattr(self, "v774_size"):
                self.size_spin.blockSignals(True)
                self.size_spin.setValue(int(self.v774_size.value()))
                self.size_spin.blockSignals(False)
            if hasattr(self, "v774_mouse_cb"):
                self.mouse_interaction_cb.blockSignals(True)
                self.mouse_interaction_cb.setChecked(bool(self.v774_mouse_cb.isChecked()))
                self.mouse_interaction_cb.blockSignals(False)
            if hasattr(self, "v774_transition_combo"):
                self.trans_spin.blockSignals(True)
                self.trans_spin.setValue(int(self.v774_transition_combo.currentData() or 200))
                self.trans_spin.blockSignals(False)
            self.apply()
            try:
                self.pet.apply_window_flags()
                self.pet.apply_clickthrough_native()
                self.pet.refresh_mouse_interaction_config()
            except Exception:
                LOGGER.warning("即时应用桌宠设置失败", exc_info=True)
        except Exception as exc:
            LOGGER.exception("V0.7.7.4 即时保存失败")
            QMessageBox.warning(self, "保存设置失败", f"{type(exc).__name__}: {exc}")

    def _v774_autostart_enabled(self):
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "XiaoMeili")
                return bool(str(value or "").strip())
        except Exception:
            return False

    def _v774_set_autostart(self, checked):
        checked = bool(checked)
        if sys.platform != "win32":
            QMessageBox.information(self, "开机启动", "开机启动只在 Windows 正式版中可用。")
            return
        try:
            import winreg
            if getattr(sys, "frozen", False):
                command = f'"{Path(sys.executable)}"'
            else:
                command = f'"{sys.executable}" "{Path(__file__).resolve()}"'
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if checked:
                    winreg.SetValueEx(key, "XiaoMeili", 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "XiaoMeili")
                    except FileNotFoundError:
                        pass
            self.cfg["start_with_windows"] = checked
            save_config(self.cfg)
        except Exception as exc:
            LOGGER.exception("修改开机启动失败")
            self.v774_startup_cb.blockSignals(True)
            self.v774_startup_cb.setChecked(not checked)
            self.v774_startup_cb.blockSignals(False)
            QMessageBox.warning(self, "开机启动设置失败", f"{type(exc).__name__}: {exc}")

    def _v0776_avatar_file(self):
        raw = str(self.cfg.get("settings_ui", {}).get("profile_avatar") or "").strip()
        p = Path(raw) if raw else (USER / "profile" / "avatar.png")
        return p

    def _v0776_refresh_avatar(self):
        label = getattr(self, "v0776_avatar", None)
        if label is None:
            return
        p = self._v0776_avatar_file()
        if p.exists() and p.is_file():
            pix = QPixmap(str(p))
            if not pix.isNull():
                label.setText("")
                label.setPixmap(
                    pix.scaled(
                        56, 56,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        label.setPixmap(QPixmap())
        label.setText("美")

    def _v0776_choose_avatar(self):
        start = str(Path.home() / "Pictures")
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择小美丽头像",
            start,
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not chosen:
            return
        try:
            target = USER / "profile" / "avatar.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(chosen) as src:
                img = ImageOps.exif_transpose(src).convert("RGBA")
                side = max(1, min(img.width, img.height))
                left = max(0, (img.width - side) // 2)
                top = max(0, (img.height - side) // 2)
                img = img.crop((left, top, left + side, top + side))
                resampling = getattr(Image, "Resampling", Image)
                img = img.resize((256, 256), resampling.LANCZOS)
                mask = Image.new("L", (256, 256), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((2, 2, 253, 253), fill=255)
                out = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                out.paste(img, (0, 0), mask)
                out.save(target, format="PNG", optimize=True)

            self.cfg.setdefault("settings_ui", {})["profile_avatar"] = str(target)
            save_config(self.cfg)
            self._v0776_refresh_avatar()
        except Exception as exc:
            LOGGER.exception("保存自定义头像失败")
            QMessageBox.warning(self, "头像设置失败", f"{type(exc).__name__}: {exc}")

    def _v774_edit_pet_name(self):
        current = str(getattr(self, "_v774_pet_name", "") or self.cfg.get("pet_name") or "小美丽")
        value, ok = QInputDialog.getText(self, "修改昵称", "你想怎么称呼小美丽？", text=current)
        if not ok:
            return
        value = str(value or "").strip()
        if not value:
            return
        self._v774_pet_name = value[:20]
        self.cfg["pet_name"] = self._v774_pet_name
        save_config(self.cfg)
        self.v774_profile_name.setText(self._v774_pet_name)
        self.v774_name_value.setText(self._v774_pet_name)

    def _v774_open_hotkeys(self):
        self._v774_open_legacy_dialog("快捷键", "快捷键", (860, 620))

    def _v774_open_actions(self):
        self._v774_open_legacy_dialog("动画素材", "动作库与视频素材", (1080, 720))
        self._v774_refresh_action_summary()
        self._v0882_refresh_favorites()
        self._v0882_refresh_favorite_buttons()

    def _v774_open_brain_chat(self):
        self._v774_open_legacy_dialog("大脑", "和小美丽聊两句", (900, 690))
        self._v774_refresh_brain_summary()

    def _v774_open_voice_editor(self):
        if not self.voice_service.ready():
            self.open_system_section("组件与下载")
            QMessageBox.information(self, "小美丽声音", "声音组件还没有准备好，已经带你来到「系统 → 组件与下载」。")
            return
        self._v774_open_legacy_dialog("声音", "小美丽声音", (900, 650))
        self._v774_refresh_voice_summary()

    def _v080_speech_label(self):
        speech = self.cfg.get("speech", {}) if isinstance(self.cfg.get("speech"), dict) else {}
        if not bool(speech.get("enabled", True)):
            return "已关闭"
        if not self.speech_service.ready():
            return "已开启 · 语音输入尚未准备"
        return "已开启 · " + str(self._v080_speech_state_label or "等待“美丽美丽”")

    def _v080_refresh_speech_summary(self):
        if hasattr(self, "v080_speech_value"):
            self.v080_speech_value.setText(self._v080_speech_label())
        if hasattr(self, "v080_wake_value"):
            replies=self.cfg.get("speech",{}).get("wake_replies",[]) if isinstance(self.cfg.get("speech"),dict) else []
            self.v080_wake_value.setText(f"{len(replies)} 条 · 随机不连续重复")
        if hasattr(self, "v087_phrase_value"):
            rules=self.cfg.get("speech",{}).get("phrase_voice_overrides",{}) if isinstance(self.cfg.get("speech"),dict) else {}
            count=len(rules) if isinstance(rules,dict) else 0
            self.v087_phrase_value.setText(f"{count} 条 · 完全匹配台词")
        if hasattr(self, "v080_input_value"):
            key=str(self.cfg.get("speech",{}).get("input_device","default") or "default")
            label="系统默认麦克风"
            try:
                for k,n in self.speech_service.input_devices():
                    if str(k)==key: label=str(n); break
            except Exception: pass
            self.v080_input_value.setText(label)
        if hasattr(self, "v080_whiteboard_value"):
            hold=float(self.cfg.get("whiteboard",{}).get("hold_ms",3000))/1000.0
            ready=bool(getattr(self.pet,"dialogue_asset_path","") and Path(str(self.pet.dialogue_asset_path)).exists())
            self.v080_whiteboard_value.setText(f"{'通用白板已就绪' if ready else '通用白板正在准备'} · 停留 {hold:.1f} 秒")
        if hasattr(self, "v080_indicator_cb"):
            self.v080_indicator_cb.blockSignals(True); self.v080_indicator_cb.setChecked(bool(self.cfg.get("speech",{}).get("indicator_enabled",True))); self.v080_indicator_cb.blockSignals(False)

    def _v080_speech_state_changed(self, code, label):
        self._v080_speech_state_code=str(code or ""); self._v080_speech_state_label=str(label or "")
        if hasattr(self,"speech_status") and self.speech_service.ready(): self.speech_status.setText(self.speech_service.component_status()+f"\n当前：{self._v080_speech_state_label}")
        if hasattr(self,"v07712_resource_activity"):
            mapping={"listening":"🎙️ 语音监听","hearing":"👂 正在听你说话","recognizing":"👂 ASR 识别","thinking":"🧠 大脑思考","speaking":"🔊 小美丽回答","holding":"💬 白板停留","paused":"⏸ 语音监听暂停","loading":"⏳ 加载语音模型"}
            self.v07712_resource_activity.setText("当前主要模块："+mapping.get(self._v080_speech_state_code,self._v080_speech_state_label or "待机"))
        self._v080_refresh_speech_summary()

    def _v080_speech_error(self, message):
        LOGGER.warning("语音输入: %s",message)
        if hasattr(self,"speech_status"): self.speech_status.setText(str(message))

    def _v080_prepare_speech(self):
        if not self.voice_service.ready():
            QMessageBox.information(self,"准备语音输入","语音识别会共用 Qwen3-TTS 的独立 Python 环境。请先准备上方「声音组件」。")
            return
        self.speech_prepare_btn.setEnabled(False); self.speech_progress.setValue(1); self.speech_status.setText("正在准备 FSMN-VAD 与 Fun-ASR-Nano-2512，请保持网络连接。")
        self.speech_service.prepare_async()

    def _v080_speech_setup_progress(self, value, text):
        self.speech_progress.setValue(max(0,min(100,int(value)))); self.speech_status.setText(str(text))

    def _v080_speech_setup_finished(self, ok, message):
        self.speech_status.setText(str(message)); self.speech_progress.setValue(100 if ok else 0); self.speech_prepare_btn.setEnabled(not self.speech_service.ready())
        if ok:
            self.config_changed.emit()
        self._v080_refresh_speech_summary()

    def _v080_open_speech_settings(self):
        dlg=QDialog(self); dlg.setWindowTitle("小美丽｜语音对话"); dlg.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png'))); dlg.resize(720,470)
        root=QVBoxLayout(dlg); head=QLabel("语音对话"); head.setObjectName("pageTitle"); root.addWidget(head)
        hint=QLabel("说“美丽美丽”唤醒小美丽。既支持先唤醒再提问，也支持“美丽美丽，我该不该买大狙？”一句话完成。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)
        box=QGroupBox("对话设置"); form=QFormLayout(box)
        enabled=QCheckBox("启用语音对话"); enabled.setChecked(bool(self.cfg.get('speech',{}).get('enabled',True))); form.addRow(enabled)
        wake=QLineEdit(str(self.cfg.get('speech',{}).get('wake_word','美丽美丽'))); wake.setReadOnly(True); form.addRow("唤醒词",wake)
        mic=QComboBox(); items=self.speech_service.input_devices(); current=str(self.cfg.get('speech',{}).get('input_device','default'))
        for key,label in items: mic.addItem(label,key)
        idx=mic.findData(current); mic.setCurrentIndex(max(0,idx)); form.addRow("麦克风",mic)
        state=QLabel(self._v080_speech_label()); state.setWordWrap(True); form.addRow("当前状态",state)
        board=QCheckBox("回答时使用通用白板 + 打字机文字"); board.setChecked(bool(self.cfg.get('speech',{}).get('whiteboard_enabled',True))); form.addRow(board)
        lamp=QCheckBox("语音会话期间显示右上角淡绿色状态灯"); lamp.setChecked(bool(self.cfg.get('speech',{}).get('indicator_enabled',True))); form.addRow(lamp)
        timeout=QSpinBox(); timeout.setRange(5,30); timeout.setValue(max(5,int(self.cfg.get('speech',{}).get('listen_timeout_ms',15000))//1000)); timeout.setSuffix(" 秒"); form.addRow("连续对话静默退出",timeout)
        root.addWidget(box)
        note=QLabel("小美丽自己播放语音时会暂停麦克风识别，避免把自己的声音再次听进去。语音结束后恢复监听。")
        note.setWordWrap(True); note.setObjectName("cardDesc"); root.addWidget(note); root.addStretch(1)
        row=QHBoxLayout(); setup=QPushButton("组件与下载"); setup.clicked.connect(lambda:(dlg.accept(),self.open_system_section('组件与下载'))); row.addWidget(setup); row.addStretch(1); cancel=QPushButton("取消"); save=QPushButton("保存并应用"); row.addWidget(cancel); row.addWidget(save); root.addLayout(row); cancel.clicked.connect(dlg.reject)
        def commit():
            sp=self.cfg.setdefault('speech',{}); sp['enabled']=bool(enabled.isChecked()); sp['wake_word']='美丽美丽'; sp['input_device']=str(mic.currentData() or 'default'); sp['whiteboard_enabled']=bool(board.isChecked()); sp['indicator_enabled']=bool(lamp.isChecked()); sp['listen_timeout_ms']=int(timeout.value())*1000; save_config(self.cfg); self.config_changed.emit(); self._v080_refresh_speech_summary(); dlg.accept()
        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _v080_open_wake_replies(self):
        dlg=QDialog(self); dlg.setWindowTitle("小美丽｜唤醒回应"); dlg.resize(650,480); root=QVBoxLayout(dlg)
        root.addWidget(QLabel("唤醒后随机回应（不会连续重复同一句）")); lst=QListWidget(); root.addWidget(lst,1)
        replies=list(self.cfg.get('speech',{}).get('wake_replies') or ["干嘛？","咋滴了？","有事你就说！"])
        for x in replies: lst.addItem(str(x))
        buttons=QHBoxLayout(); add=QPushButton("添加"); edit=QPushButton("编辑"); delete=QPushButton("删除"); buttons.addWidget(add); buttons.addWidget(edit); buttons.addWidget(delete); buttons.addStretch(1); root.addLayout(buttons)
        def add_one():
            text,ok=QInputDialog.getText(dlg,"添加唤醒回应","小美丽要说：")
            if ok and str(text).strip(): lst.addItem(str(text).strip()[:30])
        def edit_one():
            item=lst.currentItem()
            if not item:return
            text,ok=QInputDialog.getText(dlg,"编辑唤醒回应","小美丽要说：",text=item.text())
            if ok and str(text).strip(): item.setText(str(text).strip()[:30])
        def del_one():
            if lst.count()<=1: QMessageBox.information(dlg,"至少保留一句","唤醒回应至少需要保留一句。"); return
            row=lst.currentRow()
            if row>=0: lst.takeItem(row)
        add.clicked.connect(add_one); edit.clicked.connect(edit_one); delete.clicked.connect(del_one); lst.itemDoubleClicked.connect(lambda _i:edit_one())
        bottom=QHBoxLayout(); bottom.addStretch(1); cancel=QPushButton("取消"); save=QPushButton("保存并应用"); bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom); cancel.clicked.connect(dlg.reject)
        def commit():
            values=[lst.item(i).text().strip() for i in range(lst.count()) if lst.item(i).text().strip()]
            if not values:return
            self.cfg.setdefault('speech',{})['wake_replies']=values[:12]; save_config(self.cfg); self.config_changed.emit(); self._v080_refresh_speech_summary(); dlg.accept()
        save.clicked.connect(commit); dlg.exec()

    def _v087_open_phrase_voice_overrides(self):
        dlg=QDialog(self); dlg.setWindowTitle("小美丽｜单句语气微调"); dlg.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png'))); dlg.resize(860,560)
        root=QVBoxLayout(dlg)
        title=QLabel("单句语气微调"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("只对完全匹配的台词追加一条声音要求。匹配时会忽略空格和常见标点，不会改变小美丽的全局固定声线。适合修正“干嘛”这类特别短、偶尔年龄感漂移的句子。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)

        table=QTableWidget(0,2); table.setHorizontalHeaderLabels(["台词","附加声音要求"])
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(table,1)

        rules=self.cfg.get('speech',{}).get('phrase_voice_overrides',{})
        if not isinstance(rules,dict): rules={}
        def add_row(phrase="", instruct=""):
            row=table.rowCount(); table.insertRow(row)
            table.setItem(row,0,QTableWidgetItem(str(phrase or "")))
            table.setItem(row,1,QTableWidgetItem(str(instruct or "")))
            table.setRowHeight(row,54)
        for phrase,instruct in rules.items():
            add_row(phrase,instruct)

        buttons=QHBoxLayout()
        add=QPushButton("添加台词"); delete=QPushButton("删除选中"); preview=QPushButton("试听选中")
        buttons.addWidget(add); buttons.addWidget(delete); buttons.addWidget(preview); buttons.addStretch(1); root.addLayout(buttons)
        def add_one():
            add_row("","")
            table.setCurrentCell(table.rowCount()-1,0); table.editItem(table.item(table.rowCount()-1,0))
        def del_one():
            rows=sorted({idx.row() for idx in table.selectionModel().selectedRows()},reverse=True)
            for row in rows: table.removeRow(row)
        def preview_one():
            row=table.currentRow()
            if row<0: return
            p=table.item(row,0).text().strip() if table.item(row,0) else ""
            ins=table.item(row,1).text().strip() if table.item(row,1) else ""
            if not p:
                QMessageBox.information(dlg,"单句语气微调","请先填写要试听的台词。"); return
            voice=self.cfg.get('voice',{}) if isinstance(self.cfg.get('voice'),dict) else {}
            vid=str(voice.get('voice_id') or "")
            if not vid or not self.voice_service.ready():
                QMessageBox.information(dlg,"单句语气微调","请先在“小美丽声音”中固定一个可用声线。"); return
            self.voice_service.preview(
                p, vid, float(voice.get('speed',1.0) or 1.0),
                str(voice.get('output_device','default') or 'default'),
                extra_instruct=ins,
            )
        add.clicked.connect(add_one); delete.clicked.connect(del_one); preview.clicked.connect(preview_one)

        bottom=QHBoxLayout(); bottom.addStretch(1)
        cancel=QPushButton("取消"); save=QPushButton("保存并应用")
        bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom); cancel.clicked.connect(dlg.reject)
        def commit():
            out={}
            for row in range(table.rowCount()):
                phrase=table.item(row,0).text().strip() if table.item(row,0) else ""
                instruct=table.item(row,1).text().strip() if table.item(row,1) else ""
                if not phrase and not instruct: continue
                if not phrase or not instruct:
                    QMessageBox.warning(dlg,"无法保存",f"第 {row+1} 行需要同时填写台词和声音要求。"); return
                out[phrase[:40]]=instruct[:400]
                if len(out)>=20: break
            self.cfg.setdefault('speech',{})['phrase_voice_overrides']=out
            save_config(self.cfg); self.config_changed.emit(); self._v080_refresh_speech_summary()
            dlg.accept()
        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _v080_open_whiteboard_template(self):
        dlg=WhiteboardTemplateDialog(self.cfg,self.pet,self); dlg.exec(); self._v080_refresh_speech_summary()

    def _v080_toggle_indicator(self, checked):
        self.cfg.setdefault('speech',{})['indicator_enabled']=bool(checked); save_config(self.cfg); self.config_changed.emit()
        if not checked:self.pet.set_dialogue_indicator(False)

    def _v774_set_ai_enabled(self, checked):
        self.cfg.setdefault("brain", {})["enabled"] = bool(checked)
        save_config(self.cfg)
        self._v774_refresh_brain_summary()

    def _v774_set_expression(self, value):
        try:
            self.brain_temp.setValue(max(0.20, min(1.20, int(value) / 100.0)))
            self._brain_save_settings()
            self.v774_expression_value.setText(f"{int(value)}% · " + ("更稳定" if value < 55 else "自然" if value < 85 else "更自由"))
        except Exception:
            LOGGER.warning("保存表达自由度失败", exc_info=True)

    def _v0777_memory_category_label(self, category):
        return {
            "preference": "偏好",
            "identity": "身份",
            "habit": "习惯",
            "plan": "计划",
            "important": "重要",
            "manual": "手动",
            "fact": "信息",
        }.get(str(category or ""), "记忆")

    def _v774_edit_memory(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("小美丽记忆管理")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(780, 610)
        dlg.setMinimumSize(700, 540)
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(18, 18, 18, 16)
        dv.setSpacing(12)

        heading = QLabel("记忆")
        heading.setObjectName("pageTitle")
        heading.setStyleSheet("font-size:20px;font-weight:750;")
        dv.addWidget(heading)
        hint = QLabel(
            "最近对话负责“刚刚聊了什么”；长期记忆负责跨很多轮、跨重启保留稳定的偏好、身份、习惯和明确计划。"
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        dv.addWidget(hint)

        short_box = QGroupBox("最近对话")
        sh = QHBoxLayout(short_box)
        sh.setContentsMargins(14, 14, 14, 12)
        sh.addWidget(QLabel("每次回答带上最近"))
        short_spin = QSpinBox()
        short_spin.setRange(2, 12)
        short_spin.setValue(int(self.brain_context.value()))
        short_spin.setSuffix(" 轮")
        sh.addWidget(short_spin)
        sh.addStretch(1)
        clear_short = QPushButton("清空最近对话")
        sh.addWidget(clear_short)
        dv.addWidget(short_box)

        long_box = QGroupBox("长期记忆")
        lv = QVBoxLayout(long_box)
        lv.setContentsMargins(14, 14, 14, 12)
        lv.setSpacing(9)
        long_top = QHBoxLayout()
        long_enabled = QCheckBox("启用长期记忆")
        long_enabled.setChecked(bool(self.cfg.get("brain", {}).get("long_term_memory", True)))
        self.v0777_memory_stats = QLabel("")
        self.v0777_memory_stats.setObjectName("pageSubtitle")
        long_top.addWidget(long_enabled)
        long_top.addStretch(1)
        long_top.addWidget(self.v0777_memory_stats)
        lv.addLayout(long_top)

        explain = QLabel(
            "小美丽会自动保存像“我喜欢…… / 我主玩…… / 我叫…… / 我习惯……”这类稳定信息；"
            "普通闲聊不会整段保存。临时计划默认约 60 天后自动过期。所有记忆都只保存在本机。"
        )
        explain.setWordWrap(True)
        explain.setObjectName("cardDesc")
        lv.addWidget(explain)

        self.v0777_memory_list = QListWidget()
        self.v0777_memory_list.setMinimumHeight(245)
        lv.addWidget(self.v0777_memory_list, 1)

        add_row = QHBoxLayout()
        add_edit = QLineEdit()
        add_edit.setPlaceholderText("手动告诉小美丽一条长期记忆，例如：我最喜欢用大狙")
        add_btn = QPushButton("添加")
        add_btn.setObjectName("cardButton")
        add_row.addWidget(add_edit, 1)
        add_row.addWidget(add_btn)
        lv.addLayout(add_row)

        manage_row = QHBoxLayout()
        edit_btn = QPushButton("编辑选中")
        delete_btn = QPushButton("删除选中")
        clear_all_btn = QPushButton("清空长期记忆")
        manage_row.addWidget(edit_btn)
        manage_row.addWidget(delete_btn)
        manage_row.addWidget(clear_all_btn)
        manage_row.addStretch(1)
        lv.addLayout(manage_row)
        dv.addWidget(long_box, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryCloseButton")
        bottom.addWidget(close_btn)
        dv.addLayout(bottom)

        def refresh():
            self.v0777_memory_list.clear()
            rows = self.brain_service.list_memories()
            for row in rows:
                label = self._v0777_memory_category_label(row.get("category"))
                text = str(row.get("text") or "").strip()
                self.v0777_memory_list.addItem(f"[{label}]  {text}")
                item = self.v0777_memory_list.item(self.v0777_memory_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, str(row.get("id") or ""))
                item.setToolTip(text)
            size = int(self.brain_service.memory_storage_bytes())
            if size < 1024:
                size_text = f"{size} B"
            else:
                size_text = f"{size / 1024:.1f} KB"
            self.v0777_memory_stats.setText(f"{len(rows)} 条 · {size_text}")

        def selected_id():
            item = self.v0777_memory_list.currentItem()
            return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

        def save_short(value):
            self.brain_context.setValue(int(value))
            self._brain_save_settings()
            self._v774_refresh_brain_summary()

        def toggle_long(checked):
            self.cfg.setdefault("brain", {})["long_term_memory"] = bool(checked)
            save_config(self.cfg)
            self._v774_refresh_brain_summary()

        def add_manual():
            text = str(add_edit.text() or "").strip()
            if not text:
                return
            self.brain_service.add_memory(text, "manual", "manual")
            add_edit.clear()
            refresh()
            self._v774_refresh_brain_summary()

        def edit_selected():
            mid = selected_id()
            item = self.v0777_memory_list.currentItem()
            if not mid or item is None:
                return
            shown = str(item.text() or "")
            old = shown.split("]  ", 1)[-1] if "]  " in shown else shown
            value, ok = QInputDialog.getMultiLineText(dlg, "编辑长期记忆", "修改这条记忆：", old)
            if ok and str(value or "").strip():
                self.brain_service.update_memory(mid, str(value).strip())
                refresh()
                self._v774_refresh_brain_summary()

        def delete_selected():
            mid = selected_id()
            if not mid:
                return
            self.brain_service.delete_memory(mid)
            refresh()
            self._v774_refresh_brain_summary()

        def clear_all():
            answer = QMessageBox.question(
                dlg,
                "清空长期记忆",
                "确定删除所有长期记忆吗？\n养成库和性格卡不会受影响。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.brain_service.clear_memories()
                refresh()
                self._v774_refresh_brain_summary()

        short_spin.valueChanged.connect(save_short)
        clear_short.clicked.connect(self._v774_clear_context)
        long_enabled.toggled.connect(toggle_long)
        add_btn.clicked.connect(add_manual)
        add_edit.returnPressed.connect(add_manual)
        edit_btn.clicked.connect(edit_selected)
        delete_btn.clicked.connect(delete_selected)
        clear_all_btn.clicked.connect(clear_all)
        close_btn.clicked.connect(dlg.accept)
        refresh()

        try:
            self._v0775_apply_native_titlebar(dlg, getattr(self, "_v0775_theme_mode", "light") == "dark")
        except Exception:
            pass
        dlg.exec()

    def _v774_clear_context(self):
        answer = QMessageBox.question(
            self,
            "清空当前对话",
            "只清空最近聊天上下文，不会删除性格卡和养成库。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._brain_clear_history()
            self._v774_refresh_brain_summary()

    def _v774_refresh_brain_summary(self):
        if not hasattr(self, "v774_ai_value"):
            return
        enabled = bool(self.cfg.get("brain", {}).get("enabled", True))
        ready = bool(self.brain_service.ready())
        if not enabled:
            state = "已关闭"
        elif ready:
            state = "已开启 · 大脑就绪"
        else:
            state = "已开启 · 尚未准备"
        self.v774_ai_value.setText(state)
        turns = int(self.brain_context.value()) if hasattr(self, "brain_context") else int(self.cfg.get("brain", {}).get("context_turns", 6))
        count = int(self.brain_service.feedback_count())
        memory_on = bool(self.cfg.get("brain", {}).get("long_term_memory", True))
        memory_count = int(self.brain_service.memory_count())
        self.v774_memory_value.setText(f"最近 {turns} 轮 · 长期记忆{'已开启' if memory_on else '已关闭'} · {memory_count} 条")
        self.v774_learning_value.setText(f"已积累 {count} 条养成样本")
        try:
            persona = str(self.brain_persona.toPlainText() or "").strip()
            self.v774_persona_value.setText("已使用自定义性格卡" if persona and persona != str(DEFAULT_PERSONA).strip() else "默认小美丽性格")
        except Exception:
            self.v774_persona_value.setText("小美丽性格")

    def _v774_set_auto_speak(self, checked):
        self.brain_auto_speak.setChecked(bool(checked))
        self._brain_save_settings()

    def _v774_refresh_voice_summary(self):
        if not hasattr(self, "v774_voice_value"):
            return
        voice = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        vid = str(voice.get("voice_id") or "").strip()
        if not self.voice_service.ready():
            label = "声音组件尚未准备"
        elif not vid:
            label = "尚未选择固定声音"
        else:
            try:
                label = str(self.voice_service.display_name(vid))
            except Exception:
                label = vid
        self.v774_voice_value.setText(label)
        try:
            self.v774_output_value.setText(str(self.voice_output_combo.currentText() or "系统默认播放设备"))
        except Exception:
            self.v774_output_value.setText("系统默认播放设备")

    def _v774_set_strength_index(self, index):
        self._v774_schedule_apply()

    def _v0100_refresh_ability_summary(self):
        if not hasattr(self, "v0100_ability_value"):
            return
        acfg = self.cfg.get("ability_sidebar", {}) if isinstance(self.cfg.get("ability_sidebar"), dict) else {}
        parts = ["已启用" if bool(acfg.get("enabled", True)) else "已关闭"]
        parts.append("语音反馈开" if bool(acfg.get("voice_enabled", True)) else "语音反馈关")
        parts.append("语音控制开" if bool(acfg.get("voice_command_enabled", True)) else "语音控制关")
        self.v0100_ability_value.setText(" · ".join(parts))

    def _v0100_open_ability_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("美丽能力")
        dlg.setModal(True)
        dlg.resize(470, 290)
        root = QVBoxLayout(dlg)
        title = QLabel("美丽能力")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        note = QLabel("侧栏使用 V0.10.0.2 原生透明玻璃矢量方案；外框双光点只在侧栏展开时运行。这里只保留必要开关。")
        note.setWordWrap(True); note.setObjectName("pageSubtitle"); root.addWidget(note)
        acfg = self.cfg.setdefault("ability_sidebar", {})
        enabled = QCheckBox("启用美丽能力侧栏")
        enabled.setChecked(bool(acfg.get("enabled", True)))
        voice = QCheckBox("启用能力语音反馈")
        voice.setChecked(bool(acfg.get("voice_enabled", True)))
        command = QCheckBox("允许语音打开 / 收起侧栏")
        command.setChecked(bool(acfg.get("voice_command_enabled", True)))
        root.addWidget(enabled); root.addWidget(voice); root.addWidget(command); root.addStretch(1)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        cancel = QPushButton("取消"); ok = QPushButton("保存并应用")
        buttons.addWidget(cancel); buttons.addWidget(ok); root.addLayout(buttons)
        cancel.clicked.connect(dlg.reject)
        def save_ability():
            acfg["enabled"] = bool(enabled.isChecked())
            acfg["voice_enabled"] = bool(voice.isChecked())
            acfg["voice_command_enabled"] = bool(command.isChecked())
            save_config(self.cfg)
            self._v0100_refresh_ability_summary()
            self.config_changed.emit()
            dlg.accept()
        ok.clicked.connect(save_ability)
        dlg.exec()

    def _v774_refresh_action_summary(self):
        if not hasattr(self, "v774_action_value"):
            return
        total = 0
        try:
            for key in STATE_NAMES:
                total += len([p for p in _asset_list(self.cfg.get("assets", {}).get(key)) if p])
        except Exception:
            total = 0
        self.v774_action_value.setText(f"{len(STATE_NAMES)} 个状态 · {total} 个素材")
        if hasattr(self, "v774_video_value"):
            self.v774_video_value.setText(f"当前共 {total} 个动作素材")

    def _v774_export_diagnostics(self):
        try:
            out = desktop_dir() / f"小美丽诊断包_{time.strftime('%Y%m%d_%H%M%S')}.zip"
            files = []
            if CONFIG_FILE.exists():
                files.append(CONFIG_FILE)
            logs = sorted(
                [
                    p for p in LOG_DIR.rglob("*")
                    if p.is_file() and p.suffix.lower() in {".log", ".txt", ".json"}
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]
            files.extend(logs)
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "README.txt",
                    f"小美丽诊断包\n版本: V{APP_VERSION}\n生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "请把这个 ZIP 直接上传给 ChatGPT，用于定位小美丽运行问题。\n",
                )
                for p in files:
                    try:
                        zf.write(p, arcname=f"data/{p.relative_to(USER) if p.is_relative_to(USER) else p.name}")
                    except Exception:
                        LOGGER.warning("诊断包跳过文件: %s", p, exc_info=True)
            QMessageBox.information(self, "诊断包已生成", f"已保存到桌面：\n{out}")
            if sys.platform == "win32":
                try:
                    os.startfile(str(out.parent))
                except Exception:
                    pass
        except Exception as exc:
            LOGGER.exception("导出诊断包失败")
            QMessageBox.warning(self, "导出失败", f"{type(exc).__name__}: {exc}")

    def _v774_clean_old_logs(self):
        try:
            removed = 0
            for p in sorted(LOG_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[8:]:
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
            QMessageBox.information(self, "日志清理", f"已清理 {removed} 个旧日志，最近 8 个日志会保留。")
        except Exception as exc:
            QMessageBox.warning(self, "日志清理失败", str(exc))

    def _v07712_format_bytes(self, value):
        value = max(0.0, float(value or 0))
        units = ["B", "KB", "MB", "GB"]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit in {"B", "KB", "MB"} else f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} GB"

    def _v07712_gpu_metrics(self):
        result = {"util": None, "used_mb": None, "total_mb": None, "temp": None}
        if sys.platform != "win32":
            return result
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=1.5,
                creationflags=flags,
                stderr=subprocess.DEVNULL,
            )
            first = str(out).strip().splitlines()[0]
            parts = [x.strip() for x in first.split(",")]
            if len(parts) >= 4:
                result["util"] = float(parts[0])
                result["used_mb"] = float(parts[1])
                result["total_mb"] = float(parts[2])
                result["temp"] = float(parts[3])
        except Exception:
            pass
        return result

    def _v07712_refresh_resources(self):
        if not hasattr(self, "v07712_resource_cpu"):
            return
        try:
            vm = psutil.virtual_memory()
            cpu_total = float(psutil.cpu_percent(interval=None))
            proc = psutil.Process(os.getpid())
            proc_cpu = float(proc.cpu_percent(interval=None))
            proc_mem = float(proc.memory_info().rss)
            child_mem = 0.0
            child_cpu = 0.0
            try:
                for child in proc.children(recursive=True):
                    try:
                        child_mem += float(child.memory_info().rss)
                        child_cpu += float(child.cpu_percent(interval=None))
                    except Exception:
                        pass
            except Exception:
                pass

            app_mem = proc_mem + child_mem
            app_cpu = proc_cpu + child_cpu
            gpu = self._v07712_gpu_metrics()

            self.v07712_resource_cpu.setText(
                f"整机 {cpu_total:.0f}%   ·   小美丽约 {app_cpu:.1f}%"
            )
            self.v07712_resource_cpu_bar.setValue(max(0, min(100, int(round(cpu_total)))))

            self.v07712_resource_ram.setText(
                f"整机 {vm.percent:.0f}%   ·   小美丽约 {self._v07712_format_bytes(app_mem)}"
            )
            self.v07712_resource_ram_bar.setValue(max(0, min(100, int(round(vm.percent)))))

            if gpu["util"] is None:
                self.v07712_resource_gpu.setText("暂未读取到 NVIDIA GPU 数据")
                self.v07712_resource_gpu_bar.setValue(0)
                self.v07712_resource_vram.setText("显存：不可用")
                self.v07712_resource_vram_bar.setValue(0)
            else:
                util = float(gpu["util"])
                used = float(gpu["used_mb"] or 0)
                total = max(1.0, float(gpu["total_mb"] or 1))
                temp = float(gpu["temp"] or 0)
                self.v07712_resource_gpu.setText(
                    f"整机 {util:.0f}%   ·   {temp:.0f}°C"
                )
                self.v07712_resource_gpu_bar.setValue(max(0, min(100, int(round(util)))))
                self.v07712_resource_vram.setText(
                    f"显存 {used / 1024:.1f} / {total / 1024:.1f} GB"
                )
                self.v07712_resource_vram_bar.setValue(
                    max(0, min(100, int(round(used * 100.0 / total))))
                )

            # Simple one-glance pressure summary. GPU figures are whole-system
            # because Windows WDDM does not reliably expose per-process VRAM.
            pressure = max(
                cpu_total,
                float(vm.percent),
                float(gpu["util"] or 0),
                (float(gpu["used_mb"] or 0) * 100.0 / max(1.0, float(gpu["total_mb"] or 1))),
            )
            if pressure >= 90:
                label = "压力很高"
            elif pressure >= 75:
                label = "压力偏高"
            elif pressure >= 55:
                label = "中等"
            else:
                label = "轻松"
            self.v07712_resource_summary.setText(
                f"当前资源压力：{label}  ·  2 秒刷新"
            )
        except Exception as exc:
            LOGGER.warning("刷新资源监控失败: %s", exc)

    def _v07712_make_metric(self, title):
        box = QGroupBox(str(title))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        value = QLabel("正在读取…")
        value.setObjectName("cardValue")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        lay.addWidget(value)
        lay.addWidget(bar)
        return box, value, bar

    def _v07712_build_resource_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("资源占用")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "用来观察小美丽未来增加画面识别、动画和 AI 功能后的性能压力。"
            "CPU/内存会显示小美丽进程及其子进程估算值；GPU/显存显示整机数据。"
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.v07712_resource_summary = QLabel("正在读取资源状态…")
        self.v07712_resource_summary.setObjectName("cardValue")
        outer.addWidget(self.v07712_resource_summary)
        self.v07712_resource_activity = QLabel("当前主要模块：待机")
        self.v07712_resource_activity.setObjectName("pageSubtitle")
        outer.addWidget(self.v07712_resource_activity)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        cpu_box, self.v07712_resource_cpu, self.v07712_resource_cpu_bar = self._v07712_make_metric("CPU")
        ram_box, self.v07712_resource_ram, self.v07712_resource_ram_bar = self._v07712_make_metric("内存")
        gpu_box, self.v07712_resource_gpu, self.v07712_resource_gpu_bar = self._v07712_make_metric("GPU")
        vram_box, self.v07712_resource_vram, self.v07712_resource_vram_bar = self._v07712_make_metric("显存")

        grid.addWidget(cpu_box, 0, 0)
        grid.addWidget(ram_box, 0, 1)
        grid.addWidget(gpu_box, 1, 0)
        grid.addWidget(vram_box, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        note = QLabel(
            "提示：GPU/显存显示整机占用，不等于全部由小美丽产生。"
            "以后增加游戏画面识别时，可以先看开启前后的变化来判断新增功能成本。"
        )
        note.setWordWrap(True)
        note.setObjectName("cardDesc")
        outer.addWidget(note)
        outer.addStretch(1)

        self.v07712_resource_timer = QTimer(self)
        self.v07712_resource_timer.setInterval(2000)
        self.v07712_resource_timer.timeout.connect(self._v07712_refresh_resources)
        self.v07712_resource_timer.start()
        QTimer.singleShot(100, self._v07712_refresh_resources)
        return page

    def open_system_section(self, name="更新"):
        try:
            self._v774_switch_page(self.v774_nav_names.index("系统"))
            idx = self._v774_system_index.get(str(name), 0)
            self.v774_system_tabs.setCurrentIndex(idx)
        except Exception:
            LOGGER.warning("切换系统二级页失败: %s", name, exc_info=True)

    def _v0922_export_source_project(self):
        """Export the exact release source snapshot without deleting or overwriting anything."""
        try:
            bundle=Path(resource(f"assets/XiaoMeili_V{APP_VERSION}_SourceProject.zip"))
            if not bundle.is_file():
                raise FileNotFoundError(f"源码快照缺失：{bundle.name}")
            folder=QFileDialog.getExistingDirectory(self,"选择源码工程保存位置",str(desktop_dir()))
            if not folder:
                return
            folder=Path(folder)
            base=folder/f"XiaoMeili_V{APP_VERSION}_完整原始源码工程.zip"
            target=base
            index=1
            # Never overwrite an existing user file.  Generate a unique name instead.
            while target.exists():
                target=folder/f"XiaoMeili_V{APP_VERSION}_完整原始源码工程 ({index}).zip"
                index+=1
            shutil.copyfile(bundle,target)
            src_hash=hashlib.sha256(bundle.read_bytes()).hexdigest()
            dst_hash=hashlib.sha256(target.read_bytes()).hexdigest()
            if src_hash != dst_hash:
                raise RuntimeError("导出后 SHA-256 校验失败")
            if hasattr(self,"v0922_source_status"):
                self.v0922_source_status.setText(f"已导出：{target.name}  |  SHA-256 校验通过")
            QMessageBox.information(self,"源码工程已导出",f"完整原始源码工程已保存：\n{target}\n\n没有覆盖或删除任何现有文件。")
        except Exception as exc:
            LOGGER.exception("导出完整原始源码工程失败")
            QMessageBox.warning(self,"源码工程导出失败",f"{type(exc).__name__}: {exc}")

    def _v774_first_run_notice(self):
        # V0.7.7.11: onboarding notice retired permanently.
        return

    def _v0911_highlight_video_dir(self):
        p=Path(xiaomeili_logical_data_root())/"highlight_cta"/"videos"
        p.mkdir(parents=True,exist_ok=True)
        return p

    def _v0911_mute_copy_video(self, source, target):
        cap=cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise RuntimeError("无法读取视频")
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if w<=0 or h<=0:
            cap.release(); raise RuntimeError("无法读取视频尺寸")
        writer=cv2.VideoWriter(
            str(target),cv2.VideoWriter_fourcc(*"mp4v"),
            max(1.0,fps),(w,h)
        )
        if not writer.isOpened():
            cap.release(); raise RuntimeError("无法创建无音轨视频")
        written=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok: break
                writer.write(frame); written+=1
        finally:
            cap.release(); writer.release()
        if written<2 or not Path(target).exists() or Path(target).stat().st_size<4096:
            raise RuntimeError("视频转码失败")
        return written,fps

    def _v0911_import_highlight_videos(self):
        paths,_=QFileDialog.getOpenFileNames(
            self,"导入高光白板视频","",
            "视频文件 (*.mp4 *.mov *.avi *.mkv);;所有文件 (*.*)"
        )
        if not paths:return
        outdir=self._v0911_highlight_video_dir()
        ok_count=0; errors=[]
        for source in paths[:20]:
            try:
                src=Path(source)
                stamp=time.strftime("%Y%m%d_%H%M%S")
                target=outdir/f"{src.stem}_{stamp}_{ok_count+1}_muted.mp4"
                self._v0911_mute_copy_video(src,target)
                item=QListWidgetItem(target.name)
                item.setData(Qt.ItemDataRole.UserRole,str(target))
                self.highlight_video_list.addItem(item)
                ok_count+=1
            except Exception as exc:
                errors.append(f"{Path(source).name}: {exc}")
        self._v0911_save_highlight_editor_state()
        msg=f"成功导入 {ok_count} 支高光白板视频。导入副本不包含原生音轨。"
        if errors: msg+="\\n\\n失败：\\n"+"\\n".join(errors[:6])
        QMessageBox.information(self,"高光白板视频",msg)

    def _v0911_remove_highlight_video(self):
        row=self.highlight_video_list.currentRow() if hasattr(self,"highlight_video_list") else -1
        if row<0:return
        # V0.9.2.2 safety rule: remove only from the configured pool.  The
        # imported muted file is intentionally retained on disk so this action
        # can never destroy user data or a recoverable asset.
        self.highlight_video_list.takeItem(row)
        self._v0911_save_highlight_editor_state()

    def _v0911_save_highlight_editor_state(self):
        hcfg=self.cfg.setdefault("highlight_cta",{})
        if hasattr(self,"highlight_video_list"):
            hcfg["videos"]=[
                str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
                for i in range(self.highlight_video_list.count())
                if str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
            ]
        save_config(self.cfg)
        try:self.config_changed.emit()
        except Exception:pass

    def _v0911_selected_highlight_video(self):
        if not hasattr(self,"highlight_video_list") or self.highlight_video_list.count()<=0:
            return ""
        item=self.highlight_video_list.currentItem() or self.highlight_video_list.item(0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _v0911_preview_overlay(self):
        if getattr(self,"_v0911_overlay",None) is None:
            self._v0911_overlay=HighlightVideoOverlay(self.pet)
        return self._v0911_overlay

    def _v0922_highlight_font_family(self):
        try:
            self.pet.dialogue_overlay.reload_font()
            return self.pet.dialogue_overlay.font_family
        except Exception:
            return "Microsoft YaHei"

    def _v0926_highlight_video_key(self,path):
        return Path(str(path or "")).name

    def _v0926_highlight_text_box_for(self,path):
        cfg=self.cfg.setdefault("highlight_cta",{})
        boxes=cfg.get("video_text_boxes") if isinstance(cfg.get("video_text_boxes"),dict) else {}
        key=self._v0926_highlight_video_key(path)
        raw=boxes.get(key) if key else None
        if not isinstance(raw,dict):
            raw=cfg.get("text_box") or {}
        return normalized_highlight_text_layout(raw,self.cfg.get("whiteboard",{}))

    def _v0911_edit_highlight_text_box(self):
        cfg=self.cfg.setdefault("highlight_cta",{})
        path=self._v0911_selected_highlight_video()
        if not path:
            QMessageBox.information(self,"高光白板视频","请先导入并选中一支高光白板视频，再调整文字限制框。")
            return

        video_key=self._v0926_highlight_video_key(path)
        layout=self._v0926_highlight_text_box_for(path)
        dlg=QDialog(self)
        dlg.setWindowTitle("高光白板｜文字与限制框")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(980,720); dlg.setMinimumSize(900,650)
        root=QVBoxLayout(dlg)
        title=QLabel(f"文字与限制框 · {Path(path).name}"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("当前设置只属于这支白板视频。绿色虚线框可直接拖动，右下角绿色方块可缩放；实战和“预览”随机抽到这支视频时，会自动使用它自己的文字区域。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)

        body=QHBoxLayout(); root.addLayout(body,1)
        preview=WhiteboardLayoutPreview(); preview.set_video_path(path); preview.set_font_family(self._v0922_highlight_font_family())
        sample=(self._v091_editor_highlight_phrases() or ["愣着干嘛，点点关注呀！"])[0]
        preview.set_sample(sample); preview.set_layout(layout); body.addWidget(preview,3)

        controls=QWidget(); form=QFormLayout(controls); body.addWidget(controls,2)
        spins={}; syncing={"on":False}; dirty={"on":False}
        specs=[('x','区域 X (%)',0,95,0.1),('y','区域 Y (%)',0,95,0.1),('w','区域宽度 (%)',5,100,0.1),('h','区域高度 (%)',5,100,0.1),('offset_x','水平偏移 (%)',-30,30,0.1),('offset_y','垂直偏移 (%)',-30,30,0.1)]
        for key,label,lo,hi,step in specs:
            sp=QDoubleSpinBox(); sp.setRange(lo,hi); sp.setSingleStep(step); sp.setDecimals(1); spins[key]=sp; form.addRow(label,sp)
        min_font=QSpinBox(); min_font.setRange(8,48); form.addRow('最小字号 (px)',min_font)
        max_font=QSpinBox(); max_font.setRange(12,88); form.addRow('最大字号 (px)',max_font)
        font_scale=QDoubleSpinBox(); font_scale.setRange(50,180); font_scale.setSuffix('%'); form.addRow('整体字号倍率',font_scale)
        line_spacing=QDoubleSpinBox(); line_spacing.setRange(85,150); line_spacing.setSuffix('%'); form.addRow('行距',line_spacing)
        max_lines=QSpinBox(); max_lines.setRange(1,7); form.addRow('最大行数',max_lines)
        outline=QDoubleSpinBox(); outline.setRange(0,4); outline.setSingleStep(0.5); form.addRow('淡描边 (px)',outline)
        auto_fill=QCheckBox('自动换行 + 自动字号 + 居中（推荐）'); form.addRow(auto_fill)
        sample_box=QGroupBox('台词预览'); sg=QGridLayout(sample_box)
        samples=[x for x in self._v091_editor_highlight_phrases()[:5]] or [sample]
        for i,text_value in enumerate(samples):
            b=QPushButton(f'{i+1}'); b.setToolTip(text_value); b.clicked.connect(lambda checked=False,t=text_value:preview.set_sample(t)); sg.addWidget(b,0,i)
        form.addRow(sample_box)
        full=QPushButton('一键铺满白板区'); form.addRow(full)
        reset=QPushButton('恢复默认模板'); form.addRow(reset)
        help_label=QLabel('绿色虚线框就是文字安全区。字体家族与“对白白板模板”完全一致；保存后，设置页预览与实战高光都使用同一套渲染逻辑。')
        help_label.setWordWrap(True); help_label.setStyleSheet('color:#657185;'); form.addRow(help_label)

        status=QLabel(''); status.setStyleSheet('color:#278a74;')
        bottom=QHBoxLayout(); bottom.addWidget(status); bottom.addStretch(1)
        cancel=QPushButton('取消'); save=QPushButton('保存并应用'); save.setEnabled(False)
        bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom)

        def mark():
            if syncing['on']: return
            dirty['on']=True; save.setEnabled(True); status.setText('未保存')

        def current_from_controls():
            l=dict(layout)
            for key,sp in spins.items(): l[key]=float(sp.value())/100.0
            l['min_font_px']=int(min_font.value()); l['max_font_px']=int(max_font.value())
            l['font_scale']=float(font_scale.value())/100.0; l['line_spacing']=float(line_spacing.value())/100.0
            l['max_lines']=int(max_lines.value()); l['outline_width']=float(outline.value()); l['auto_fill']=bool(auto_fill.isChecked())
            # Always follow the general dialogue-whiteboard typography colors in this mode.
            wb=normalized_whiteboard_layout(self.cfg.get('whiteboard',{}))
            l['text_color']=wb.get('text_color','#08423A'); l['outline_color']=wb.get('outline_color','#F6FFF9')
            return normalized_highlight_text_layout(l,self.cfg.get('whiteboard',{}))

        def sync_controls(l):
            nonlocal layout
            layout=normalized_highlight_text_layout(l,self.cfg.get('whiteboard',{})); syncing['on']=True
            for key,sp in spins.items(): sp.setValue(float(layout[key])*100.0)
            min_font.setValue(int(layout['min_font_px'])); max_font.setValue(int(layout['max_font_px']))
            font_scale.setValue(float(layout['font_scale'])*100.0); line_spacing.setValue(float(layout['line_spacing'])*100.0)
            max_lines.setValue(int(layout['max_lines'])); outline.setValue(float(layout['outline_width'])); auto_fill.setChecked(bool(layout['auto_fill']))
            syncing['on']=False; preview.set_layout(layout)

        def control_changed(*_):
            nonlocal layout
            if syncing['on']: return
            layout=current_from_controls(); preview.set_layout(layout); mark()

        def preview_changed(l):
            sync_controls(l); mark()

        for sp in spins.values(): sp.valueChanged.connect(control_changed)
        for w in (min_font,max_font,font_scale,line_spacing,max_lines,outline): w.valueChanged.connect(control_changed)
        auto_fill.toggled.connect(control_changed)
        preview.layout_changed.connect(preview_changed)

        def do_full():
            l=current_from_controls(); l.update({'x':0.075,'y':0.655,'w':0.850,'h':0.300,'offset_x':0.0,'offset_y':0.0}); sync_controls(l); mark()
        def do_reset():
            wb=normalized_whiteboard_layout(self.cfg.get('whiteboard',{})); l=dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)
            for key in ('min_font_px','max_font_px','font_scale','line_spacing','max_lines','text_color','outline_color','outline_width','auto_fill'):
                l[key]=wb.get(key,l[key])
            sync_controls(l); mark()
        full.clicked.connect(do_full); reset.clicked.connect(do_reset)

        def commit():
            final=normalized_highlight_text_layout(layout,self.cfg.get('whiteboard',{}))
            boxes=cfg.setdefault('video_text_boxes',{})
            boxes[video_key]={'schema':3,**final}
            if hasattr(self,"highlight_video_list"):
                item=self.highlight_video_list.currentItem()
                if item is not None:
                    item.setText("✓ "+Path(str(item.data(Qt.ItemDataRole.UserRole) or "")).name)
            save_config(self.cfg)
            try:self.config_changed.emit()
            except Exception:pass
            status.setText('已应用 ✓'); save.setEnabled(False); dlg.accept()
        save.clicked.connect(commit); cancel.clicked.connect(dlg.reject)
        sync_controls(layout); dirty['on']=False; save.setEnabled(False)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _v091_editor_highlight_phrases(self):
        if hasattr(self,"highlight_phrases"):
            values=[x.strip() for x in self.highlight_phrases.toPlainText().splitlines() if x.strip()]
        else:
            values=[]
        return values or ["愣着干嘛，点点关注呀！"]

    def _v0924_preview_pick_phrase(self):
        values=self._v091_editor_highlight_phrases()
        key=tuple(values)
        if getattr(self,"_v0924_preview_phrase_key",None)!=key:
            self._v0924_preview_phrase_key=key
            self._v0924_preview_phrase_bag=[]
        bag=list(getattr(self,"_v0924_preview_phrase_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_v0924_preview_phrase_last","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        phrase=bag.pop(0)
        self._v0924_preview_phrase_bag=bag
        self._v0924_preview_phrase_last=phrase
        return phrase

    def _v0924_preview_pick_video(self):
        values=[]
        if hasattr(self,"highlight_video_list"):
            for i in range(self.highlight_video_list.count()):
                p=str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
                if p and Path(p).exists() and p not in values:
                    values.append(p)
        if not values:
            return ""
        key=tuple(values)
        if getattr(self,"_v0924_preview_video_key",None)!=key:
            self._v0924_preview_video_key=key
            self._v0924_preview_video_bag=[]
        bag=list(getattr(self,"_v0924_preview_video_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_v0924_preview_video_last","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        path=bag.pop(0)
        self._v0924_preview_video_bag=bag
        self._v0924_preview_video_last=path
        return path

    def _v0925_highlight_phrase_instruct(self, text):
        rules=(self.cfg.get("speech",{}) or {}).get("phrase_voice_overrides") or {}
        if not isinstance(rules,dict):
            return ""
        normalized=re.sub(r"[\s，,。.!！？?、:：]+","",str(text or "").strip())
        for key,value in rules.items():
            k=re.sub(r"[\s，,。.!！？?、:：]+","",str(key or "").strip())
            if k and k==normalized:
                return str(value or "").strip()
        return ""

    def _v0925_finish_preview_visual(self, hold_ms=3000):
        try:
            overlay=self._v0911_preview_overlay()
            if overlay.isVisible():
                overlay.finish(int(hold_ms))
            elif getattr(self.pet,"dialogue_board_active",False):
                self.pet.finish_dialogue_board(int(hold_ms))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] preview visual finish failed")

    def _v0925_reset_preview_button(self):
        try:
            if hasattr(self,"highlight_preview_btn"):
                self.highlight_preview_btn.setText("预览")
                self.highlight_preview_btn.setEnabled(True)
        except Exception:
            pass
        self._v0925_preview_pending_video=""

    def _v0925_highlight_preview_started(self, text, duration_ms, tag):
        if str(tag or "")!="highlight_preview":
            return
        phrase=str(text or "").strip()
        path=str(getattr(self,"_v0925_preview_pending_video","") or "")
        box=self._v0926_highlight_text_box_for(path)
        try:
            if path and self._v0911_preview_overlay().play(
                path,phrase,int(duration_ms),box,self._v0922_highlight_font_family()
            ):
                return
            # Graceful fallback when no dedicated high-glow video exists.
            self.pet.start_dialogue_board(phrase,int(duration_ms))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] synced preview start failed")

    def _v0925_highlight_preview_finished(self, ok, message, tag):
        if str(tag or "")!="highlight_preview":
            return
        # The user's high-glow clip contains a continuously talking mouth.
        # Keep the VIDEO LOOPING during the 3-second reading tail; never freeze.
        hold_ms=3000 if bool(ok) else 400
        self._v0925_finish_preview_visual(hold_ms)
        QTimer.singleShot(hold_ms+80,self._v0925_reset_preview_button)
        if not ok:
            LOGGER.warning("[HIGHLIGHT] preview voice failed: %s",message)

    def _v0924_preview_highlight(self):
        phrase=self._v0924_preview_pick_phrase()
        path=self._v0924_preview_pick_video()

        # Stop any prior visual preview without deleting or modifying media.
        try:
            self._v0911_preview_overlay().stop()
        except Exception:
            pass
        try:
            if getattr(self.pet,"dialogue_board_active",False):
                self.pet._end_dialogue_board()
        except Exception:
            pass

        voice=self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
        vid=str(voice.get("voice_id") or "").strip()
        self._v0925_preview_pending_video=path
        if hasattr(self,"highlight_preview_btn"):
            self.highlight_preview_btn.setEnabled(False)
            self.highlight_preview_btn.setText("准备预览…")

        if not vid or not self.voice_service.ready():
            # Visual-only fallback. There is no audio to synchronize with.
            box=self._v0926_highlight_text_box_for(path)
            if path:
                if self._v0911_preview_overlay().play(
                    path,phrase,4200,box,self._v0922_highlight_font_family()
                ):
                    QTimer.singleShot(4200,lambda:self._v0925_finish_preview_visual(3000))
                    QTimer.singleShot(7280,self._v0925_reset_preview_button)
                    return
            try:
                self.pet.start_dialogue_board(phrase,4200)
                QTimer.singleShot(4200,lambda:self._v0925_finish_preview_visual(3000))
                QTimer.singleShot(7280,self._v0925_reset_preview_button)
            except Exception:
                LOGGER.exception("[HIGHLIGHT] visual-only preview failed")
                self._v0925_reset_preview_button()
            return

        # Use the normal speak path, not VoiceService.preview. speak() emits
        # playback_started with the real WAV duration immediately before audio
        # starts, giving the board/video a single timing origin.
        self.voice_service.speak(
            phrase,
            vid,
            float(voice.get("speed",1.0) or 1.0),
            str(voice.get("output_device","default") or "default"),
            tag="highlight_preview",
            extra_instruct=self._v0925_highlight_phrase_instruct(phrase),
        )

    def _v0911_style_report_snapshot_bar(self):
        """Keep report-snapshot state visually identical to the highlight qualification card."""
        try:
            label=getattr(self,"report_snapshot_status",None)
            if label is None:
                return
            raw=str(label.text() or "").strip()
            if "已锁定" in raw and "未锁定" not in raw:
                palette="background:#E1F7EA;color:#147A45;border:1px solid #8AD5AA;"
            elif "候选" in raw or "缓存" in raw or "等待" in raw:
                palette="background:#FFF4D6;color:#9A6700;border:1px solid #E6C66A;"
            else:
                palette="background:#FDE8E8;color:#B42318;border:1px solid #F4B4B4;"
            label.setObjectName("reportSnapshotBar")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(54)
            label.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            label.setStyleSheet(
                "QLabel#reportSnapshotBar{"+palette+
                "border-radius:10px;padding:10px 14px;font-size:20px;font-weight:900;}"
            )
        except Exception:
            LOGGER.warning("战报快照状态条样式更新失败",exc_info=True)

    def _v091_scale_css(self, css, scale):
        scale=max(0.72,min(1.15,float(scale or 1.0)))
        def repl(match):
            value=float(match.group(1))
            scaled=max(1.0,value*scale)
            if abs(scaled-round(scaled))<0.05:
                return f"{int(round(scaled))}px"
            return f"{scaled:.1f}px"
        return re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)px\b", repl, str(css or ""))

    def _v091_auto_scale(self):
        try:
            screen=self.screen() or QApplication.primaryScreen()
            if screen is None:
                return 1.0
            area=screen.availableGeometry()
            # Leave breathing room for the title bar, taskbar and window shadow.
            sx=max(0.1,(float(area.width())-36.0)/1080.0)
            sy=max(0.1,(float(area.height())-36.0)/720.0)
            return max(0.75,min(1.0,sx,sy))
        except Exception:
            return 0.90

    def _v091_capture_fixed_baselines(self):
        if getattr(self,"_v091_baselines_captured",False):
            return
        self._v091_baselines_captured=True
        for widget in self.findChildren(QWidget):
            try:
                widget.setProperty("_v091_min_w",int(widget.minimumWidth()))
                widget.setProperty("_v091_min_h",int(widget.minimumHeight()))
                widget.setProperty("_v091_max_w",int(widget.maximumWidth()))
                widget.setProperty("_v091_max_h",int(widget.maximumHeight()))
            except Exception:
                pass

    def _v091_apply_widget_scale(self, scale):
        self._v091_capture_fixed_baselines()
        huge=1000000
        for widget in self.findChildren(QWidget):
            try:
                min_w=int(widget.property("_v091_min_w") or 0)
                min_h=int(widget.property("_v091_min_h") or 0)
                max_w=int(widget.property("_v091_max_w") or 16777215)
                max_h=int(widget.property("_v091_max_h") or 16777215)
                widget.setMinimumWidth(max(0,int(round(min_w*scale))) if min_w>0 else 0)
                widget.setMinimumHeight(max(0,int(round(min_h*scale))) if min_h>0 else 0)
                if 0<max_w<huge:
                    widget.setMaximumWidth(max(1,int(round(max_w*scale))))
                if 0<max_h<huge:
                    widget.setMaximumHeight(max(1,int(round(max_h*scale))))
            except Exception:
                pass

    def _v091_resolve_scale(self):
        mode="auto"
        if hasattr(self,"v091_scale_combo"):
            mode=str(self.v091_scale_combo.currentData() or "auto")
        else:
            mode=str(self.cfg.get("settings_ui",{}).get("ui_scale_mode","auto") or "auto")
        if mode=="auto":
            return self._v091_auto_scale()
        try:
            return max(0.72,min(1.15,float(mode)))
        except Exception:
            return self._v091_auto_scale()

    def _v091_apply_settings_scale(self, persist=False):
        scale=self._v091_resolve_scale()
        self._v091_ui_scale=float(scale)
        self._v091_apply_widget_scale(scale)

        # Rebuild the current theme through the scale-aware stylesheet hook.
        try:
            self._v0775_apply_theme(getattr(self,"_v0775_theme_mode","light"),False)
        except Exception:
            pass

        try:
            screen=self.screen() or QApplication.primaryScreen()
            area=screen.availableGeometry() if screen is not None else None
            target_w=max(760,int(round(1080*scale)))
            target_h=max(520,int(round(720*scale)))
            if area is not None:
                target_w=min(target_w,max(680,int(area.width())-20))
                target_h=min(target_h,max(480,int(area.height())-20))
            self.setMinimumSize(min(760,target_w),min(500,target_h))
            self.resize(target_w,target_h)
        except Exception:
            pass

        try:
            self._v0775_place_theme_button()
        except Exception:
            pass

        if persist:
            ui=self.cfg.setdefault("settings_ui",{})
            ui["ui_scale_mode"]=str(self.v091_scale_combo.currentData() or "auto")
            save_config(self.cfg)

    def _v091_scale_changed(self, *args):
        self._v091_apply_settings_scale(True)

    def _install_v0774_shell(self, root):
        # Native Windows frame is retained for reliable DPI / multi-monitor behavior.
        self.setWindowTitle("小美丽 设置")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._v091_ui_scale=self._v091_resolve_scale()
        try:
            _screen=self.screen() or QApplication.primaryScreen()
            _area=_screen.availableGeometry() if _screen is not None else None
            _tw=max(760,int(round(1080*self._v091_ui_scale)))
            _th=max(520,int(round(720*self._v091_ui_scale)))
            if _area is not None:
                _tw=min(_tw,max(680,int(_area.width())-20))
                _th=min(_th,max(480,int(_area.height())-20))
            self.setMinimumSize(min(760,_tw),min(500,_th))
            self.resize(_tw,_th)
        except Exception:
            self.setMinimumSize(720,480)
            self.resize(900,620)

        self.setStyleSheet("""
            QDialog { background: #F3F8F6; color: #183A34; }
            QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 13px; }
            QFrame#sidebar { background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 22px; }
            QLabel#avatar {
                background: #3CC9A8; color: white; border-radius: 28px;
                font-size: 25px; font-weight: 800;
            }
            QLabel#profileName { color: #173B34; font-size: 18px; font-weight: 700; }
            QLabel#profileStatus { color: #2DAF8E; font-size: 12px; }
            QPushButton#navButton {
                background: transparent; color: #48635D; border: none; border-radius: 12px;
                text-align: left; padding: 11px 16px; font-size: 14px; font-weight: 600;
            }
            QPushButton#navButton:hover { background: #F1F8F5; color: #1B5B4E; }
            QPushButton#navButton:checked {
                background: #E3F7F0; color: #167B67; border: 1px solid #B9EBDD;
            }
            QLabel#pageTitle { color: #173B34; font-size: 25px; font-weight: 800; }
            QLabel#pageSubtitle { color: #74867F; font-size: 13px; }
            QFrame#settingCard {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 16px;
            }
            QLabel#cardTitle { color: #526B64; font-size: 13px; font-weight: 600; }
            QLabel#cardValue { color: #173B34; font-size: 16px; font-weight: 700; }
            QLabel#cardDesc { color: #85958F; font-size: 11px; }
            QPushButton {
                min-height: 30px; border: 1px solid #D5E5DF; border-radius: 9px;
                padding: 4px 13px; background: #FFFFFF; color: #28584D;
            }
            QPushButton:hover { background: #EFF9F5; border-color: #9EDCCB; }
            QPushButton:pressed { background: #DFF4EC; }
            QPushButton:disabled { background: #F3F6F5; color: #A4B0AC; border-color: #E5EBE9; }
            QPushButton#cardButton {
                min-width: 92px; background: #E4F7F1; border: 1px solid #C7EEE2;
                color: #168069; font-weight: 700;
            }
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox,
            QTableWidget {
                background: #FFFFFF; color: #24473F; border: 1px solid #D8E5E0;
                border-radius: 9px; padding: 5px 7px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox { min-height: 28px; }
            QCheckBox { color: #385A52; spacing: 7px; }
            QSlider::groove:horizontal {
                height: 5px; background: #DFEAE6; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 16px; margin: -6px 0; border-radius: 8px;
                background: #36C4A2; border: 1px solid #29AE8F;
            }
            QSlider::sub-page:horizontal { background: #36C4A2; border-radius: 2px; }
            QProgressBar {
                min-height: 16px; border: 1px solid #D8E5E0; border-radius: 7px;
                text-align: center; background: #EDF3F1; color: #31564D;
            }
            QProgressBar::chunk { background: #36C4A2; border-radius: 6px; }
            QGroupBox {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 13px;
                margin-top: 10px; padding-top: 10px; font-weight: 700; color: #294D44;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QTabWidget::pane {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 13px;
            }
            QTabBar::tab {
                background: transparent; border: none; padding: 9px 13px;
                color: #647C75; margin: 0 2px;
            }
            QTabBar::tab:selected {
                color: #167B67; font-weight: 700; border-bottom: 2px solid #36C4A2;
            }
            QScrollArea { background: transparent; border: none; }
        """)

        # Old top tabs are now a hidden functional backend and second-level editor pool.
        self.tabs.hide()

        # Hide the old bottom-level Save/Close strip. V0.7.7.4 saves ordinary
        # controls immediately; second-level editors retain explicit save actions where needed.
        try:
            self.save_btn.hide()
            self.apply_status.hide()
            for btn in self.findChildren(QPushButton):
                if btn.text() == "关闭" and btn.window() is self:
                    btn.hide()
        except Exception:
            pass

        # Technical rows must no longer leak into the user-facing Brain/Voice pages.
        try:
            self.brain_advanced_toggle.hide()
            self.brain_advanced_body.hide()
        except Exception:
            pass

        self.v0882_feature_catalog = {}
        self.v0882_favorite_buttons = {}
        # Build shell.
        shell = QWidget()
        shell_l = QHBoxLayout(shell)
        shell_l.setContentsMargins(12, 12, 12, 12)
        shell_l.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 20, 18, 18)
        side.setSpacing(8)

        profile = QWidget()
        ph = QHBoxLayout(profile)
        ph.setContentsMargins(0, 0, 0, 12)
        ph.setSpacing(12)
        self.v0776_avatar = EditableAvatar("美")
        self.v0776_avatar.setObjectName("avatar")
        self.v0776_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.v0776_avatar.setFixedSize(56, 56)
        self.v0776_avatar.clicked.connect(self._v0776_choose_avatar)
        self._v0776_refresh_avatar()
        ph.addWidget(self.v0776_avatar)
        ptext = QVBoxLayout()
        self._v774_pet_name = str(self.cfg.get("pet_name") or "小美丽").strip() or "小美丽"
        self.v774_profile_name = QLabel(self._v774_pet_name)
        self.v774_profile_name.setObjectName("profileName")
        status = QLabel("● 在线")
        status.setObjectName("profileStatus")
        ptext.addStretch(1)
        ptext.addWidget(self.v774_profile_name)
        ptext.addWidget(status)
        ptext.addStretch(1)
        ph.addLayout(ptext, 1)
        side.addWidget(profile)

        nav_caption = QLabel("我的设置")
        nav_caption.setStyleSheet("color:#879690;font-weight:600;padding:8px 4px 4px 4px;")
        side.addWidget(nav_caption)

        self.v774_nav_names = ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]
        self.v774_nav_buttons = []
        for i, name in enumerate(self.v774_nav_names):
            b = QPushButton(name)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, idx=i: self._v774_switch_page(idx))
            side.addWidget(b)
            self.v774_nav_buttons.append(b)

        side.addStretch(1)
        version = QLabel(f"小美丽 V{APP_VERSION}")
        version.setStyleSheet("color:#9AA8A3;font-size:11px;padding:4px;")
        side.addWidget(version)

        self.v774_stack = QStackedWidget()
        self.v091_stack_scroll = QScrollArea()
        self.v091_stack_scroll.setObjectName("settingsMainScroll")
        self.v091_stack_scroll.setWidgetResizable(True)
        self.v091_stack_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.v091_stack_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.v091_stack_scroll.setStyleSheet("QScrollArea#settingsMainScroll{background:transparent;border:none;} QScrollArea#settingsMainScroll>QWidget>QWidget{background:transparent;}")
        self.v091_stack_scroll.setWidget(self.v774_stack)
        shell_l.addWidget(sidebar)
        shell_l.addWidget(self.v091_stack_scroll, 1)

        # --------------------------------------------------------------
        # 1. General
        # --------------------------------------------------------------
        general, gv = self._v774_page("常规", "管理小美丽最常用的桌面设置。")
        cards = []

        name_card, self.v774_name_value = self._v774_card(
            "昵称", self._v774_pet_name, "只影响设置中心里的称呼。", "修改", self._v774_edit_pet_name
        )
        cards.append(name_card)

        self.v091_scale_combo = QComboBox()
        self.v091_scale_combo.addItem("自动（推荐）", "auto")
        self.v091_scale_combo.addItem("80%", "0.80")
        self.v091_scale_combo.addItem("90%", "0.90")
        self.v091_scale_combo.addItem("100%", "1.00")
        self.v091_scale_combo.addItem("110%", "1.10")
        _scale_mode=str(self.cfg.get("settings_ui",{}).get("ui_scale_mode","auto") or "auto")
        _scale_idx=self.v091_scale_combo.findData(_scale_mode)
        self.v091_scale_combo.setCurrentIndex(_scale_idx if _scale_idx>=0 else 0)
        self.v091_scale_combo.currentIndexChanged.connect(self._v091_scale_changed)
        card, _ = self._v774_card(
            "界面缩放",
            "只缩放设置中心，不影响桌面上的小美丽",
            "自动模式会根据当前显示器可用工作区等比例缩放；空间不足时仍可滚动。",
            control=self.v091_scale_combo,
        )
        cards.append(card)

        self.v774_startup_cb = QCheckBox("开机启动")
        self.v774_startup_cb.setChecked(self._v774_autostart_enabled())
        self.v774_startup_cb.toggled.connect(self._v774_set_autostart)
        card, _ = self._v774_card("开机启动", "登录 Windows 后自动启动小美丽", control=self.v774_startup_cb)
        cards.append(card)

        self.v774_top_cb = QCheckBox("开启")
        self.v774_top_cb.setChecked(bool(self.cfg.get("always_on_top", True)))
        self.v774_top_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("始终置顶", "保持在其他窗口上方", control=self.v774_top_cb)
        cards.append(card)

        self.v774_lockpos_cb = QCheckBox("锁定")
        self.v774_lockpos_cb.setChecked(bool(self.cfg.get("lock_position", False)))
        self.v774_lockpos_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("游戏防误触锁定", "锁定后左键、双击和拖拽完全穿透；右键小美丽可解除", control=self.v774_lockpos_cb)
        cards.append(card)

        self.v774_size = QSpinBox()
        self.v774_size.setRange(120, 600)
        self.v774_size.setSuffix(" px")
        self.v774_size.setValue(int(self.cfg.get("pet_width", 280)))
        self.v774_size.valueChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("桌宠大小", "调整小美丽在桌面上的尺寸", control=self.v774_size)
        cards.append(card)

        card, _ = self._v774_card("快捷键", "打开设置、显示隐藏、测试状态等", "全局快捷键可以全部留空", "管理", self._v774_open_hotkeys)
        cards.append(card)

        gv.addWidget(self._v774_scroll_grid(cards, 2), 1)
        self.v774_stack.addWidget(general)

        # --------------------------------------------------------------
        # Favorites / Common shortcuts
        # --------------------------------------------------------------
        favorite_page, favorite_body = self._v774_page(
            "常用", "把自己每天最常碰的功能固定在这里。这里只是快捷入口，不复制任何设置。"
        )
        fav_toolbar = QHBoxLayout()
        fav_toolbar.addStretch(1)
        manage_fav = QPushButton("管理常用")
        manage_fav.clicked.connect(self._v0882_manage_favorites)
        fav_toolbar.addWidget(manage_fav)
        favorite_body.addLayout(fav_toolbar)

        fav_scroll = QScrollArea()
        fav_scroll.setWidgetResizable(True)
        fav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fav_scroll.setAutoFillBackground(False)
        fav_scroll.viewport().setAutoFillBackground(False)
        fav_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea QWidget{background:transparent;}")
        fav_scroll.viewport().setStyleSheet("background:transparent;")
        fav_host = QWidget()
        fav_host.setObjectName("favoritesHost")
        fav_host.setAutoFillBackground(False)
        fav_host.setStyleSheet("QWidget#favoritesHost{background:transparent;}")
        self.v0882_favorites_grid = QGridLayout(fav_host)
        self.v0882_favorites_grid.setContentsMargins(0, 0, 4, 4)
        self.v0882_favorites_grid.setHorizontalSpacing(14)
        self.v0882_favorites_grid.setVerticalSpacing(14)
        fav_scroll.setWidget(fav_host)
        favorite_body.addWidget(fav_scroll, 1)
        self.v774_stack.addWidget(favorite_page)

        # --------------------------------------------------------------
        # 2. Brain
        # --------------------------------------------------------------
        brain, bv = self._v774_page("大脑", "决定小美丽怎么思考、怎么记住、怎么和你说话。")
        brain_cards = []

        self.v774_ai_cb = QCheckBox("启用 AI")
        self.v774_ai_cb.setChecked(bool(self.cfg.get("brain", {}).get("enabled", True)))
        self.v774_ai_cb.toggled.connect(self._v774_set_ai_enabled)
        card, self.v774_ai_value = self._v774_card("AI 大脑", "", "模型与组件问题统一到「系统」处理。", control=self.v774_ai_cb)
        brain_cards.append(card)

        card, self.v774_persona_value = self._v774_card(
            "小美丽性格", "", "人设、性格和说话方式。", "编辑性格", self._open_brain_persona_editor
        )
        brain_cards.append(card)

        card, self.v774_memory_value = self._v774_card(
            "记忆", "", "最近对话 + 本地长期记忆。", "管理", self._v774_edit_memory
        )
        brain_cards.append(card)

        card, self.v774_learning_value = self._v774_card(
            "学习与养成", "", "固定台词、语义规则和主人纠正。", "管理养成库", self._open_brain_rules_editor
        )
        brain_cards.append(card)

        expression_host = QWidget()
        eh = QHBoxLayout(expression_host)
        eh.setContentsMargins(0, 0, 0, 0)
        eh.setSpacing(8)
        self.v774_expression_slider = QSlider(Qt.Orientation.Horizontal)
        self.v774_expression_slider.setRange(20, 120)
        self.v774_expression_slider.setValue(int(round(float(self.cfg.get("brain", {}).get("temperature", 0.78)) * 100)))
        self.v774_expression_slider.setFixedWidth(125)
        self.v774_expression_slider.valueChanged.connect(self._v774_set_expression)
        self.v774_expression_value = QLabel("")
        self.v774_expression_value.setStyleSheet("color:#637A73;font-size:11px;")
        eh.addWidget(self.v774_expression_slider)
        eh.addWidget(self.v774_expression_value)
        card, _ = self._v774_card("表达自由度", "控制回答更稳定还是更自由", control=expression_host)
        brain_cards.append(card)

        card, _ = self._v774_card(
            "对话测试", "和小美丽聊两句", "支持 👍 / 👎 纠正与养成。", "打开", self._v774_open_brain_chat
        )
        brain_cards.append(card)

        bv.addWidget(self._v774_scroll_grid(brain_cards, 2), 1)
        self.v774_stack.addWidget(brain)

        # Hide duplicate Brain cards from the old second-level chat page.
        try:
            legacy_brain = self.tabs.widget(self._v774_legacy_index("大脑"))
            for gb in legacy_brain.findChildren(QGroupBox):
                if gb.title() in ("养成库 / 语义规则", "小美丽性格"):
                    gb.hide()
        except Exception:
            pass

        # --------------------------------------------------------------
        # 3. Voice
        # --------------------------------------------------------------
        voice_page, vv = self._v774_page("声音", "管理小美丽怎么听你说话，以及怎么开口。")
        voice_cards = []

        card, self.v080_speech_value = self._v774_card(
            "语音对话", "", "唤醒词：美丽美丽 · 唤醒 → 聆听 → 理解 → 回答。", "管理", self._v080_open_speech_settings
        )
        voice_cards.append(card)
        card, self.v080_wake_value = self._v774_card(
            "唤醒回应", "", "随机回应且不连续重复；默认：干嘛？ / 咋滴了？ / 有事你就说！", "管理", self._v080_open_wake_replies
        )
        voice_cards.append(card)

        card, self.v774_voice_value = self._v774_card(
            "小美丽声音", "", "选择固定中文声线、语速并试听。", "选择与试听", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        card, self.v087_phrase_value = self._v774_card(
            "单句语气微调", "", "只修正指定台词的年龄感、语气或说话方式，不改变全局声线。", "管理", self._v087_open_phrase_voice_overrides
        )
        voice_cards.append(card)

        self.v774_auto_speak_cb = QCheckBox("开启")
        self.v774_auto_speak_cb.setChecked(bool(self.cfg.get("brain", {}).get("auto_speak", True)))
        self.v774_auto_speak_cb.toggled.connect(self._v774_set_auto_speak)
        card, _ = self._v774_card("回答后自动说出来", "文字回答完成后自动朗读", control=self.v774_auto_speak_cb)
        voice_cards.append(card)

        card, self.v774_output_value = self._v774_card(
            "声音输出", "", "选择 Windows 播放设备。", "设置", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        card, self.v080_input_value = self._v774_card(
            "输入设备", "", "语音识别使用的麦克风。", "设置", self._v080_open_speech_settings
        )
        voice_cards.append(card)

        vv.addWidget(self._v774_scroll_grid(voice_cards, 2), 1)
        self.v774_stack.addWidget(voice_page)

        # --------------------------------------------------------------
        # 4. Interaction
        # --------------------------------------------------------------
        interact, iv = self._v774_page("互动", "决定小美丽在桌面上怎么回应你。")
        int_cards = []

        self.v774_mouse_cb = QCheckBox("开启")
        self.v774_mouse_cb.setChecked(bool(self.cfg.get("mouse_interaction", {}).get("enabled", True)))
        self.v774_mouse_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("鼠标跟随", "Continuous Puppet V2", "眼睛、头部、身体、头发和耳环连续跟随。", control=self.v774_mouse_cb)
        int_cards.append(card)

        self.v774_strength_combo = QComboBox()
        self.v774_strength_combo.addItem("轻柔", 0.80)
        self.v774_strength_combo.addItem("自然", 1.00)
        self.v774_strength_combo.addItem("明显", 1.25)
        current_strength = float(self.cfg.get("mouse_interaction", {}).get("strength", 1.0) or 1.0)
        best = min(range(self.v774_strength_combo.count()), key=lambda i: abs(float(self.v774_strength_combo.itemData(i)) - current_strength))
        self.v774_strength_combo.setCurrentIndex(best)
        self.v774_strength_combo.currentIndexChanged.connect(self._v774_set_strength_index)
        card, _ = self._v774_card("跟随强度", "调节鼠标互动的可见幅度", control=self.v774_strength_combo)
        int_cards.append(card)

        self.v774_drag_cb = QCheckBox("开启")
        self.v774_drag_cb.setChecked(bool(self.cfg.get("drag_interaction", {}).get("enabled", True)))
        self.v774_drag_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("拖拽互动", "悬挂姿态 + 惯性回弹", "动态眼球、身体、马尾和耳环继续沿用 V0.7.7.2 稳定逻辑。", control=self.v774_drag_cb)
        int_cards.append(card)

        card, _ = self._v774_card("主动互动", "尚未启用", "未来用于游戏事件主动吐槽、闲置主动动作等。")
        int_cards.append(card)

        self.v080_indicator_cb = QCheckBox("开启")
        self.v080_indicator_cb.setChecked(bool(self.cfg.get("speech", {}).get("indicator_enabled", True)))
        self.v080_indicator_cb.toggled.connect(self._v080_toggle_indicator)
        card, _ = self._v774_card("对话状态灯", "淡绿色呼吸灯", "唤醒后亮起；回答和白板停留结束后自动隐藏。", control=self.v080_indicator_cb)
        int_cards.append(card)

        card, _ = self._v774_card("点击反馈", "由鼠标互动 / 拖拽逻辑接管", "当前没有独立的单击动作触发器。")
        int_cards.append(card)

        self.v774_transition_combo = QComboBox()
        self.v774_transition_combo.addItem("快速", 120)
        self.v774_transition_combo.addItem("自然", 200)
        self.v774_transition_combo.addItem("柔和", 320)
        cur_ms = int(self.cfg.get("transition_ms", 200))
        best = min(range(self.v774_transition_combo.count()), key=lambda i: abs(int(self.v774_transition_combo.itemData(i)) - cur_ms))
        self.v774_transition_combo.setCurrentIndex(best)
        self.v774_transition_combo.currentIndexChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("动画过渡", "动作切换速度", control=self.v774_transition_combo)
        int_cards.append(card)

        _acfg = self.cfg.get("ability_sidebar", {}) if isinstance(self.cfg.get("ability_sidebar"), dict) else {}
        ability_summary = "已启用" if bool(_acfg.get("enabled", True)) else "已关闭"
        card, self.v0100_ability_value = self._v774_card(
            "美丽能力", ability_summary,
            "参考图同款青蓝玻璃侧栏 + 能力形态小美丽。五个能力每次启动默认全部 OFF。",
            "设置", self._v0100_open_ability_settings
        )
        int_cards.append(card)

        iv.addWidget(self._v774_scroll_grid(int_cards, 2), 1)
        self.v774_stack.addWidget(interact)

        # --------------------------------------------------------------
        # 5. Actions
        # --------------------------------------------------------------
        action_page, av = self._v774_page("动作", "管理小美丽的动作、素材和触发方式。")
        action_cards = []
        card, self.v774_action_value = self._v774_card(
            "动作库", "", "待机、低血量、击杀、死亡、胜负和战报素材池。", "打开动作库", self._v774_open_actions
        )
        action_cards.append(card)
        card, self.v080_whiteboard_value = self._v774_card(
            "白板播报", "", "通用 15 秒对白白板 · 动态打字 · TTS 结束后继续停留。", "管理白板", self._v080_open_whiteboard_template
        )
        action_cards.append(card)
        card, _ = self._v774_card(
            "事件触发", "由 VALORANT 识别自动触发", "识别到低血量、击杀、死亡、胜负等事件后播放对应动作。", "查看识别", lambda: self.open_system_section("游戏识别")
        )
        action_cards.append(card)
        av.addWidget(self._v774_scroll_grid(action_cards, 2), 1)
        self.v774_stack.addWidget(action_page)

        # --------------------------------------------------------------
        # 6. System
        # --------------------------------------------------------------
        system_page, syv = self._v774_page("系统", "更新、存储、组件和诊断工具。技术设置统一放在这里。")
        self.v774_system_tabs = QTabWidget()
        self._v774_system_index = {}

        resource_page = self._v07712_build_resource_page()
        self._v774_system_index["资源占用"] = self.v774_system_tabs.addTab(resource_page, "资源占用")

        update_page = self._v774_take_legacy_page("更新")
        storage_page = self._v774_take_legacy_page("存储")
        vision_page = self._v774_take_legacy_page("游戏识别")
        log_page = self._v774_take_legacy_page("日志")

        if update_page is not None:
            self._v774_system_index["更新"] = self.v774_system_tabs.addTab(update_page, "更新")
        if storage_page is not None:
            self._v774_system_index["存储"] = self.v774_system_tabs.addTab(storage_page, "存储")

        components = QWidget()
        cv = QVBoxLayout(components)
        cv.setContentsMargins(12, 12, 12, 12)
        cv.setSpacing(12)

        brain_group = QGroupBox("大脑组件")
        bg = QFormLayout(brain_group)
        bg.setContentsMargins(14, 14, 14, 12)
        bg.setSpacing(8)
        bg.addRow("状态", self.brain_status)
        bg.addRow("准备进度", self.brain_progress)
        bg.addRow(self.brain_prepare_btn)
        mode_row = QWidget(); ml = QHBoxLayout(mode_row); ml.setContentsMargins(0,0,0,0); ml.setSpacing(8)
        ml.addWidget(self.brain_download_mode, 1); ml.addWidget(self.brain_ndm_test_btn)
        bg.addRow("下载方式", mode_row)
        dir_row = QWidget(); dl = QHBoxLayout(dir_row); dl.setContentsMargins(0,0,0,0); dl.setSpacing(8)
        dl.addWidget(self.brain_ndm_dir, 1); dl.addWidget(self.brain_ndm_browse_btn)
        bg.addRow("NDM 下载目录", dir_row)
        cv.addWidget(brain_group)

        # Voice technical widgets are removed from the user-facing voice editor
        # and rehomed here.
        self._v774_hide_form_row(self.voice_status)
        self._v774_hide_form_row(self.voice_progress)
        self._v774_hide_form_row(self.voice_prepare_btn)
        self.voice_status.show(); self.voice_progress.show(); self.voice_prepare_btn.show()

        voice_group = QGroupBox("声音组件")
        vg = QFormLayout(voice_group)
        vg.setContentsMargins(14, 14, 14, 12)
        vg.setSpacing(8)
        vg.addRow("状态", self.voice_status)
        vg.addRow("准备进度", self.voice_progress)
        vg.addRow(self.voice_prepare_btn)
        cv.addWidget(voice_group)

        speech_group = QGroupBox("语音输入组件")
        sg = QFormLayout(speech_group)
        sg.setContentsMargins(14, 14, 14, 12); sg.setSpacing(8)
        sg.addRow("状态", self.speech_status); sg.addRow("准备进度", self.speech_progress); sg.addRow(self.speech_prepare_btn)
        speech_hint = QLabel("V0.8.8 使用 FSMN-VAD 判断说话起止，Fun-ASR-Nano-2512 负责中文识别。模型准备后可本地离线工作。")
        speech_hint.setWordWrap(True); speech_hint.setObjectName("cardDesc"); sg.addRow(speech_hint)
        cv.addWidget(speech_group)

        source_group = QGroupBox("源码工程")
        source_form = QFormLayout(source_group)
        source_form.setContentsMargins(14,14,14,12); source_form.setSpacing(8)
        self.v0922_source_status = QLabel(f"当前 V{APP_VERSION} 完整可编辑源码快照已随程序提供")
        self.v0922_source_status.setWordWrap(True)
        source_form.addRow("状态", self.v0922_source_status)
        self.v0922_export_source_btn = QPushButton("打包完整原始源码工程")
        self.v0922_export_source_btn.setToolTip("只导出当前版本随包携带的只读源码 ZIP；不会读取、移动、覆盖或删除你的个人文件。")
        self.v0922_export_source_btn.clicked.connect(self._v0922_export_source_project)
        source_form.addRow(self.v0922_export_source_btn)
        source_hint = QLabel("用于新建 ChatGPT 对话时直接上传继续开发。源码包不包含模型权重、个人配置、聊天记忆、日志或你后来导入的素材。")
        source_hint.setWordWrap(True); source_hint.setObjectName("cardDesc"); source_form.addRow(source_hint)
        cv.addWidget(source_group)

        tech_note = QLabel(
            "只有这里显示模型、下载方式、NDM 和组件准备状态。日常使用只需要去「大脑」和「声音」页面。"
        )
        tech_note.setWordWrap(True)
        tech_note.setStyleSheet("color:#73877F;background:#F2F8F5;border:1px solid #DCEAE4;border-radius:9px;padding:8px;")
        cv.addWidget(tech_note)
        cv.addStretch(1)

        self._v774_system_index["组件与下载"] = self.v774_system_tabs.addTab(components, "组件与下载")

        if vision_page is not None:
            self._v774_system_index["游戏识别"] = self.v774_system_tabs.addTab(vision_page, "游戏识别")

        if log_page is not None:
            try:
                log_layout = log_page.layout()
                diag = QGroupBox("诊断工具")
                dg = QVBoxLayout(diag)
                dtext = QLabel("普通更新记录与可恢复语音事件只保存在 XiaoMeiliData/logs，不再自动往桌面生成 TXT。真正异常可在这里一键导出诊断包。")
                dtext.setWordWrap(True)
                dg.addWidget(dtext)
                dr = QHBoxLayout()
                export_btn = QPushButton("导出给 ChatGPT")
                export_btn.clicked.connect(self._v774_export_diagnostics)
                clean_btn = QPushButton("清理旧日志")
                clean_btn.clicked.connect(self._v774_clean_old_logs)
                dr.addWidget(export_btn); dr.addWidget(clean_btn); dr.addStretch(1)
                dg.addLayout(dr)
                log_layout.insertWidget(1, diag)
            except Exception:
                LOGGER.warning("增强日志页失败", exc_info=True)
            self._v774_system_index["日志"] = self.v774_system_tabs.addTab(log_page, "日志")

        self._v0882_register_feature("system.resources", "资源占用", "查看 CPU、内存、GPU 与显存压力。", "系统", lambda: self.open_system_section("资源占用"))
        self._v0882_register_feature("system.updates", "检查更新", "检查并安装小美丽新版本。", "系统", lambda: self.open_system_section("更新"))
        self._v0882_register_feature("system.storage", "存储", "模型、数据与迁移设置。", "系统", lambda: self.open_system_section("存储"))
        self._v0882_register_feature("system.components", "组件与下载", "大脑、声音模型与下载配置。", "系统", lambda: self.open_system_section("组件与下载"))
        self._v0882_register_feature("system.vision", "游戏识别", "VALORANT 识别与事件触发设置。", "系统", lambda: self.open_system_section("游戏识别"))
        self._v0882_register_feature("system.logs", "日志", "诊断、导出与日志清理。", "系统", lambda: self.open_system_section("日志"))
        syv.addWidget(self.v774_system_tabs, 1)
        self.v774_stack.addWidget(system_page)

        # Put the new shell before the now-hidden legacy tab widget.
        root.insertWidget(0, shell, 1)

        # Automatic saving for controls that used to depend on the global Save button.
        self._v774_apply_timer = QTimer(self)
        self._v774_apply_timer.setSingleShot(True)
        self._v774_apply_timer.timeout.connect(self._v774_apply_now)

        # Dedicated high-glow persistence. These controls were introduced after
        # the original auto-save list, so they need their own debounce timer.
        self._v0927_highlight_save_timer = QTimer(self)
        self._v0927_highlight_save_timer.setSingleShot(True)
        self._v0927_highlight_save_timer.timeout.connect(self._v0927_save_highlight_ui_now)
        for _w,_sig in (
            (getattr(self,"highlight_enabled",None),"toggled"),
            (getattr(self,"highlight_min_kills",None),"valueChanged"),
            (getattr(self,"highlight_board_text",None),"textChanged"),
            (getattr(self,"highlight_phrases",None),"textChanged"),
        ):
            if _w is not None:
                try:
                    getattr(_w,_sig).connect(self._v0927_schedule_highlight_save)
                except Exception:
                    LOGGER.warning("连接高光自动保存信号失败: %s",_sig,exc_info=True)

        for editor in self.hk_editors.values():
            editor.keySequenceChanged.connect(self._v774_schedule_apply)
        for widget, signal_name in [
            (self.vision_enabled, "toggled"),
            (self.nickname_edit, "textChanged"),
            (self.hp_threshold, "valueChanged"),
            (self.mode_combo, "currentIndexChanged"),
            (self.pause_bg, "toggled"),
            (self.nickname_ocr_cb, "toggled"),
            (self.voice_test_text, "textChanged"),
            (self.voice_speed, "valueChanged"),
            (self.voice_output_combo, "currentIndexChanged"),
        ]:
            try:
                getattr(widget, signal_name).connect(self._v774_schedule_apply)
            except Exception:
                pass

        # Brain download settings are saved immediately even though they live in System.
        try:
            self.brain_download_mode.currentIndexChanged.connect(lambda *a: self._brain_save_settings())
            self.brain_ndm_dir.textChanged.connect(lambda *a: self._brain_save_settings())
        except Exception:
            pass

        # Keep summaries live.
        try:
            self.voice_fix_btn.clicked.connect(lambda *a: QTimer.singleShot(0, self._v774_refresh_voice_summary))
            self.brain_service.setup_finished.connect(lambda *a: self._v774_refresh_brain_summary())
            self.voice_service.download_finished.connect(lambda *a: self._v774_refresh_voice_summary())
        except Exception:
            pass

        # Initial summaries.
        self._v774_refresh_brain_summary()
        self._v774_refresh_voice_summary()
        self._v774_refresh_action_summary()
        self._v0100_refresh_ability_summary()
        self._v080_refresh_speech_summary()
        self._v774_set_expression(self.v774_expression_slider.value())

        # Restore last top-level page.
        wanted = str(self.cfg.get("settings_ui", {}).get("last_page", "常规") or "常规")
        try:
            initial = self.v774_nav_names.index(wanted)
        except ValueError:
            initial = 0
        self._v774_switch_page(initial)

        self._install_v0775_theme_layer()
        # V0.7.7.11: no startup/onboarding message box.

    def _v0775_apply_native_titlebar(self, window, dark):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            value = ctypes.c_int(1 if dark else 0)
            hwnd = int(window.winId())
            # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on modern Windows; 19 on older builds.
            for attr in (20, 19):
                try:
                    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                    )
                    if int(result) == 0:
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def _v0775_theme_urls(self, dark):
        suffix = "dark" if dark else "light"
        up = str(Path(resource(f"assets/v0775/chevron_up_{suffix}.svg"))).replace("\\", "/")
        down = str(Path(resource(f"assets/v0775/chevron_down_{suffix}.svg"))).replace("\\", "/")
        return up, down

    def _v0775_stylesheet(self, dark):
        up, down = self._v0775_theme_urls(dark)
        toggle_on = str(Path(resource("assets/v0925/toggle_on.svg"))).replace(chr(92), "/")
        toggle_off = str(Path(resource(f"assets/v0925/toggle_off_{'dark' if dark else 'light'}.svg"))).replace(chr(92), "/")
        if dark:
            bg = "#101815"
            sidebar = "#15211D"
            card = "#1C3028"
            card_hover = "#234037"
            border = "#315349"
            border_soft = "#2B493F"
            text = "#EAF4F0"
            text2 = "#B3C5BF"
            muted = "#80948D"
            accent = "#53D7B5"
            accent_text = "#8BEACF"
            accent_bg = "#173C32"
            accent_border = "#286858"
            input_bg = "#15251F"
            input_hover = "#1B3028"
            button_bg = "#192B24"
            button_hover = "#234037"
            disabled_bg = "#18201E"
            disabled_text = "#63726D"
            progress_bg = "#1B3028"
            title_sub = "#94A7A0"
        else:
            bg = "#F3F8F6"
            sidebar = "#FFFFFF"
            card = "#FFFFFF"
            card_hover = "#F9FCFB"
            border = "#DCE9E4"
            border_soft = "#D6E4DF"
            text = "#173B34"
            text2 = "#526B64"
            muted = "#85958F"
            accent = "#36C4A2"
            accent_text = "#167B67"
            accent_bg = "#E3F7F0"
            accent_border = "#B9EBDD"
            input_bg = "#FFFFFF"
            input_hover = "#F7FBF9"
            button_bg = "#FFFFFF"
            button_hover = "#EFF9F5"
            disabled_bg = "#F3F6F5"
            disabled_text = "#A4B0AC"
            progress_bg = "#EDF3F1"
            title_sub = "#74867F"

        return f"""
            QDialog {{ background: {bg}; color: {text}; }}
            QWidget {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 13px; color: {text}; }}

            QFrame#sidebar {{
                background: {sidebar}; border: 1px solid {border}; border-radius: 22px;
            }}
            QLabel#avatar {{
                background: {accent}; color: #FFFFFF; border-radius: 28px;
                font-size: 25px; font-weight: 800;
            }}
            QLabel#profileName {{ color: {text}; font-size: 18px; font-weight: 700; }}
            QLabel#profileStatus {{ color: {accent}; font-size: 12px; }}

            QPushButton#navButton {{
                background: transparent; color: {text2}; border: none; border-radius: 12px;
                text-align: left; padding: 11px 16px; font-size: 14px; font-weight: 600;
            }}
            QPushButton#navButton:hover {{ background: {card_hover}; color: {accent_text}; }}
            QPushButton#navButton:checked {{
                background: {accent_bg}; color: {accent_text};
                border: 1px solid {accent_border};
            }}

            QLabel#pageTitle {{ color: {text}; font-size: 25px; font-weight: 800; }}
            QLabel#pageSubtitle {{ color: {title_sub}; font-size: 13px; }}
            QFrame#settingCard {{
                background: {card}; border: 1px solid {border}; border-radius: 16px;
            }}
            QFrame#settingCard:hover {{ background: {card_hover}; }}
            QLabel#cardTitle {{ color: {text2}; font-size: 13px; font-weight: 600; }}
            QLabel#cardValue {{ color: {text}; font-size: 16px; font-weight: 700; }}
            QLabel#cardDesc {{ color: {muted}; font-size: 11px; }}

            QPushButton {{
                min-height: 30px; border: 1px solid {border_soft}; border-radius: 9px;
                padding: 4px 13px; background: {button_bg}; color: {text2};
            }}
            QPushButton:hover {{ background: {button_hover}; border-color: {accent_border}; color: {accent_text}; }}
            QPushButton:pressed {{ background: {accent_bg}; }}
            QPushButton:disabled {{
                background: {disabled_bg}; color: {disabled_text}; border-color: {border_soft};
            }}
            QPushButton#cardButton {{
                min-width: 92px; background: {accent_bg}; border: 1px solid {accent_border};
                color: {accent_text}; font-weight: 700;
            }}
            QPushButton#secondaryCloseButton {{
                min-width: 74px; background: {accent_bg}; border: 1px solid {accent_border};
                color: {accent_text}; font-weight: 700;
            }}
            QPushButton#themeButton {{
                min-width: 0px; min-height: 0px; padding: 0px;
                background: {card}; border: 1px solid {border}; border-radius: 17px;
                color: {accent_text}; font-size: 17px; font-weight: 700;
            }}
            QPushButton#themeButton:hover {{
                background: {accent_bg}; border-color: {accent_border};
            }}
            QPushButton#helpButton {{
                min-width: 0px; min-height: 0px; padding: 0px;
                background: {accent_bg}; border: 1px solid {accent_border};
                border-radius: 10px; color: {accent_text};
                font-size: 12px; font-weight: 800;
            }}
            QLabel#helpLabel {{
                background: {accent_bg}; border: 1px solid {accent_border};
                border-radius: 10px; color: {accent_text};
                font-size: 12px; font-weight: 800;
            }}

            QLineEdit, QTextEdit, QListWidget, QTableWidget {{
                background: {input_bg}; color: {text}; border: 1px solid {border_soft};
                border-radius: 9px; padding: 5px 7px; selection-background-color: {accent_bg};
                selection-color: {text};
            }}
            QLineEdit:focus, QTextEdit:focus, QListWidget:focus, QTableWidget:focus {{
                border: 1px solid {accent_border};
            }}

            QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {input_bg}; color: {text}; border: 1px solid {border_soft};
                border-radius: 9px; min-height: 30px; padding: 2px 36px 2px 9px;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                background: {input_hover}; border-color: {accent_border};
            }}

            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 30px; border: none; border-left: 1px solid {border_soft};
                border-top-right-radius: 8px; border-bottom-right-radius: 8px;
                background: transparent;
            }}
            QComboBox::drop-down:hover {{ background: {accent_bg}; }}
            QComboBox::down-arrow {{
                image: url("{down}"); width: 14px; height: 14px;
            }}

            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border; subcontrol-position: top right;
                width: 28px; height: 15px; border: none; border-left: 1px solid {border_soft};
                border-top-right-radius: 8px; background: transparent;
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border; subcontrol-position: bottom right;
                width: 28px; height: 15px; border: none; border-left: 1px solid {border_soft};
                border-bottom-right-radius: 8px; background: transparent;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {accent_bg};
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: url("{up}"); width: 12px; height: 12px;
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: url("{down}"); width: 12px; height: 12px;
            }}

            QCheckBox {{ color: {text2}; spacing: 8px; }}
            QCheckBox::indicator {{
                width: 38px; height: 22px;
                border: none; background: transparent;
            }}
            QCheckBox::indicator:unchecked {{ image: url("{toggle_off}"); }}
            QCheckBox::indicator:checked {{ image: url("{toggle_on}"); }}

            QSlider::groove:horizontal {{
                height: 5px; background: {border}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 16px; margin: -6px 0; border-radius: 8px;
                background: {accent}; border: 1px solid {accent};
            }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}

            QProgressBar {{
                min-height: 16px; border: 1px solid {border_soft}; border-radius: 7px;
                text-align: center; background: {progress_bg}; color: {text2};
            }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}

            QGroupBox {{
                background: {card}; border: 1px solid {border}; border-radius: 13px;
                margin-top: 10px; padding-top: 10px; font-weight: 700; color: {text2};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}

            QTabWidget::pane {{
                background: {card}; border: 1px solid {border}; border-radius: 13px;
            }}
            QTabBar::tab {{
                background: transparent; border: none; padding: 9px 13px;
                color: {muted}; margin: 0 2px;
            }}
            QTabBar::tab:hover {{ color: {accent_text}; }}
            QTabBar::tab:selected {{
                color: {accent_text}; font-weight: 700; border-bottom: 2px solid {accent};
            }}

            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea#settingsScrollArea,
            QWidget#settingsScrollHost,
            QWidget#settingsScrollViewport {{
                background: {bg}; border: none;
            }}
            QScrollBar:vertical {{
                width: 9px; background: transparent; margin: 3px 1px 3px 1px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_soft}; min-height: 28px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {accent_border}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    def _v0775_mark_help_widgets(self):
        # Replace legacy '?' affordances with a small, consistent information pill.
        for widget in self.findChildren(QWidget):
            try:
                getter = getattr(widget, "text", None)
                setter = getattr(widget, "setText", None)
                if not callable(getter) or not callable(setter):
                    continue
                raw = str(getter() or "").strip()
                if raw not in {"?", "？"}:
                    continue
                setter("?")
                if isinstance(widget, QLabel):
                    widget.setObjectName("helpLabel")
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    widget.setObjectName("helpButton")
                widget.setFixedSize(20, 20)
                widget.setStyleSheet("font-family:Arial;font-size:13px;font-weight:700;")
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            except Exception:
                continue

    def _v0775_place_theme_button(self):
        if not hasattr(self, "v0775_theme_btn"):
            return
        margin = 18
        x = max(0, self.width() - self.v0775_theme_btn.width() - margin)
        y = 16
        self.v0775_theme_btn.move(x, y)
        self.v0775_theme_btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._v0775_place_theme_button()
        except Exception:
            pass

    def _v0775_apply_theme(self, mode, persist=True):
        mode = "dark" if str(mode).lower() == "dark" else "light"
        self._v0775_theme_mode = mode
        dark = mode == "dark"
        _css=self._v0775_stylesheet(dark)
        self.setStyleSheet(self._v091_scale_css(_css, float(getattr(self,"_v091_ui_scale",1.0) or 1.0)))

        for btn in list(getattr(self, "v0777_theme_buttons", [])):
            try:
                btn.setText("☀" if dark else "☾")
                btn.setToolTip("切换到白天模式" if dark else "切换到夜间模式")
                btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                btn.setEnabled(True)
                btn.raise_()
            except Exception:
                pass

        self._v0775_mark_help_widgets()
        self._v0775_apply_native_titlebar(self, dark)
        for dlg_name in ("brain_persona_dialog", "brain_rules_dialog"):
            dlg = getattr(self, dlg_name, None)
            if dlg is not None:
                try:
                    self._v0775_apply_native_titlebar(dlg, dark)
                except Exception:
                    pass

        # Force immediate repaint so the mode switch is visually obvious.
        try:
            for widget in self.findChildren(QWidget):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
            self.update()
            QApplication.processEvents()
        except Exception:
            pass

        if persist:
            ui = self.cfg.setdefault("settings_ui", {})
            ui["theme"] = mode
            save_config(self.cfg)

    def _v0775_toggle_theme(self):
        self._v0775_apply_theme("light" if self._v0775_theme_mode == "dark" else "dark", True)

    def _install_v0775_theme_layer(self):
        ui = self.cfg.setdefault("settings_ui", {})
        self._v0775_theme_mode = "dark" if str(ui.get("theme", "light")).lower() == "dark" else "light"
        # V0.7.7.7 uses real in-layout buttons created by _v774_page. The old
        # absolute-position overlay button is intentionally retired.
        self._v0775_apply_theme(self._v0775_theme_mode, False)

    def _toggle_brain_advanced(self, checked):
        checked = bool(checked)
        if hasattr(self, "brain_advanced_body"):
            self.brain_advanced_body.setVisible(checked)
        if hasattr(self, "brain_advanced_toggle"):
            self.brain_advanced_toggle.setText("模型与下载配置  ▾" if checked else "模型与下载配置  ▸")

    def _open_brain_persona_editor(self):
        self.brain_persona_dialog.resize(680, 470)
        self.brain_persona_dialog.exec()

    def _save_persona_dialog(self):
        self._brain_save_persona()
        self.brain_persona_dialog.accept()

    def _open_brain_rules_editor(self):
        self._refresh_rule_groups()
        self._refresh_brain_rules()
        self.brain_rules_dialog.resize(940, 610)
        self.brain_rules_dialog.setMinimumSize(820, 540)
        try:
            self._v0775_apply_native_titlebar(
                self.brain_rules_dialog,
                getattr(self, "_v0775_theme_mode", "light") == "dark",
            )
        except Exception:
            pass
        self.brain_rules_dialog.exec()

    def _prepare_brain(self):
        self._brain_save_settings()
        mode = str(self.brain_download_mode.currentData() or "ndm")
        ndm_dir = self.brain_ndm_dir.text().strip()
        if mode == "ndm":
            if not ndm_dir or not Path(ndm_dir).exists():
                self._brain_choose_ndm_dir()
                ndm_dir = self.brain_ndm_dir.text().strip()
            if not ndm_dir or not Path(ndm_dir).exists():
                QMessageBox.warning(self, "请选择 NDM 下载目录", "请先选择 NDM 设置里的 Download Directory。")
                return
            ok, msg = self.brain_service.test_ndm()
            if not ok:
                QMessageBox.warning(self, "NDM 未连接", "请先打开 Neat Download Manager。\n\n小美丽会直接连接 NDM 本机接收服务，不需要浏览器扩展。")
                return
        self.brain_prepare_btn.setEnabled(False)
        self.brain_status.setText("正在准备本地大脑…")
        self.brain_service.start_setup(mode, ndm_dir)

    def _brain_setup_progress(self, value, text):
        self.brain_progress.setValue(max(0,min(100,int(value))))
        self.brain_status.setText(str(text))

    def _brain_setup_finished(self, ok, message):
        self.brain_status.setText(str(message))
        self.brain_prepare_btn.setEnabled(not ok)
        if ok:
            self.brain_progress.setValue(100)
            self.brain_send_btn.setEnabled(True)

    def _brain_save_settings(self):
        if not isinstance(self.cfg.get("brain"), dict):
            self.cfg["brain"] = {}
        self.cfg["brain"]["auto_speak"] = bool(self.brain_auto_speak.isChecked())
        self.cfg["brain"]["temperature"] = float(self.brain_temp.value())
        self.cfg["brain"]["context_turns"] = int(self.brain_context.value())
        self.cfg["brain"]["persona"] = self.brain_persona.toPlainText().strip() or DEFAULT_PERSONA
        self.cfg["brain"]["download_mode"] = str(self.brain_download_mode.currentData() or "ndm")
        self.cfg["brain"]["ndm_download_dir"] = self.brain_ndm_dir.text().strip()
        save_config(self.cfg)

    def _brain_save_persona(self):
        self._brain_save_settings()
        self.brain_status.setText("人格卡已保存。下一次回答立即生效。")

    def _brain_reset_persona(self):
        self.brain_persona.setPlainText(DEFAULT_PERSONA)
        self._brain_save_settings()
        self.brain_status.setText("已恢复默认小美丽人格。")

    def _brain_ask(self):
        if not bool(self.cfg.get("brain", {}).get("enabled", True)):
            QMessageBox.information(self, "小美丽大脑", "AI 大脑目前已关闭。请先在「大脑」页面重新开启。")
            return
        text = self.brain_input.text().strip()
        if not text:
            return
        self._brain_save_settings()
        self.brain_chat.addItem(f"你：{text}")
        self.brain_chat.scrollToBottom()
        self.brain_input.clear()
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_service.ask(
            text,
            self.cfg["brain"].get("persona") or DEFAULT_PERSONA,
            self.cfg["brain"].get("temperature",0.78),
            self.cfg["brain"].get("max_tokens",220),
            self.cfg["brain"].get("context_turns",6),
            self.cfg["brain"].get("long_term_memory", True),
        )

    def _brain_generation_started(self):
        self.brain_send_btn.setEnabled(False)
        self.brain_status.setText("小美丽正在想…")

    def _brain_generation_finished(self, ok, answer, message):
        self.brain_send_btn.setEnabled(True)
        self.brain_status.setText(str(message))
        if not ok:
            self.brain_chat.addItem(f"系统：{message}")
            self.brain_chat.scrollToBottom()
            return
        spoken = str(answer.get("spoken_text") or "").strip()
        board = str(answer.get("board_text") or "").strip()
        emotion = str(answer.get("emotion") or "neutral")
        ex = self.brain_service.last_exchange() or {}
        exchange = {
            "user_text": str(ex.get("user_text") or "").strip(),
            "assistant_text": spoken,
            "answer": dict(answer or {}),
        }
        reply_item = QListWidgetItem(f"小美丽：{spoken}")
        reply_item.setData(Qt.ItemDataRole.UserRole, exchange)
        self.brain_chat.addItem(reply_item)
        board_item = QListWidgetItem(f"〔白板草稿｜{emotion}〕{board.replace(chr(10),' / ')}")
        board_item.setData(Qt.ItemDataRole.UserRole, exchange)
        self.brain_chat.addItem(board_item)
        self.brain_chat.scrollToBottom()
        self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
        if self.brain_auto_speak.isChecked():
            voice = self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
            vid = str(voice.get("voice_id") or "")
            if vid:
                try:
                    self.voice_service.preview(
                        spoken, vid, float(voice.get("speed",1.0) or 1.0),
                        str(voice.get("output_device","default") or "default")
                    )
                except Exception:
                    LOGGER.exception("大脑回答自动朗读失败")

    def _v088_selected_exchange(self):
        item = self.brain_chat.currentItem() if hasattr(self, "brain_chat") else None
        if item is not None:
            try:
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and str(data.get("user_text") or "").strip() and str(data.get("assistant_text") or "").strip():
                    return dict(data)
            except Exception:
                pass
        return self.brain_service.last_exchange()

    def _brain_like(self):
        ex = self.brain_service.last_exchange()
        if not ex:
            return
        self.brain_service.save_feedback("up", ex.get("user_text",""), ex.get("assistant_text",""))
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        self.brain_status.setText("记住了：这句像小美丽。")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)

    def _refresh_storage_status(self):
        if not hasattr(self, "storage_current"):
            return
        logical = xiaomeili_logical_data_root()
        physical = xiaomeili_physical_data_root()
        try:
            size = _path_size_bytes(logical)
        except Exception:
            size = 0
        on_d = storage_is_on_d()
        if on_d:
            text = (
                f"逻辑兼容入口：{logical}\n"
                f"实际数据位置：{physical}\n"
                f"当前数据量：{format_storage_size(size)}\n"
                "状态：✅ 大模型/组件/缓存已经实际存放在 D 盘"
            )
        else:
            text = (
                f"当前数据目录：{logical}\n"
                f"实际数据位置：{physical}\n"
                f"当前数据量：{format_storage_size(size)}\n"
                "状态：⚠️ 目前仍实际占用 C 盘空间"
            )
        self.storage_current.setText(text)
        if hasattr(self, "storage_migrate_btn"):
            self.storage_migrate_btn.setEnabled(sys.platform == "win32" and not on_d)
            self.storage_migrate_btn.setText(
                "已经迁移到 D 盘" if on_d else "一键迁移到 D 盘并自动重启"
            )

    def _storage_browse(self):
        # V0.10.0: migration destination is fixed to XiaoMeili's own D-drive folder.
        # Arbitrary user folders are no longer accepted as a safety boundary.
        self.storage_target.setText(r"D:\XiaoMeiliData")


    def _storage_migrate(self):
        if sys.platform != "win32":
            QMessageBox.warning(self, "存储迁移", "D 盘迁移功能只用于 Windows。")
            return
        if storage_is_on_d():
            QMessageBox.information(self, "存储迁移", "小美丽的数据已经实际存放在 D 盘。")
            self._refresh_storage_status()
            return

        target_path = Path(r"D:\XiaoMeiliData")
        self.storage_target.setText(str(target_path))
        if str(target_path.drive or "").upper() != "D:":
            QMessageBox.warning(self, "存储迁移", "小美丽的固定安全迁移目录无效，迁移已停止。")
            return
        if not Path("D:/").exists():
            QMessageBox.warning(self, "存储迁移", "没有检测到 D: 盘。")
            return

        logical = xiaomeili_logical_data_root()
        size = _path_size_bytes(logical)
        answer = QMessageBox.question(
            self,
            "把小美丽搬到 D 盘",
            "准备迁移以下内容：\n\n"
            f"当前：{logical}\n"
            f"目标：{target_path}\n"
            f"预计数据量：{format_storage_size(size)}\n\n"
            "包含大脑模型、TTS 模型/运行环境、动作素材、养成数据、日志、调试文件和更新缓存。\n"
            "V0.7.6.1 会先等待迁移助手启动握手成功，只有确认 PowerShell 已正常解析后小美丽才会退出。迁移前会先完整复制并逐文件校验，"
            "校验通过后会切换到 D 盘，但会保留 C 盘原始副本作为安全备份；程序不会自动删除它。失败会自动回滚，不会拿现有效果冒险。\n\n"
            "现在开始吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.storage_migrate_btn.setEnabled(False)
        self.storage_current.setText("迁移助手即将启动，小美丽会安全退出。请不要在迁移过程中关闭迁移窗口或关机。")
        self.storage_migration_requested.emit(str(target_path))

    @staticmethod
    def _semantic_rule_text(rule):
        return (
            f"场景：{str(rule.get('scene') or '').strip()}\n"
            f"核心意思：{str(rule.get('intent') or '').strip()}\n"
            f"必须体现：{str(rule.get('must') or '').strip()}\n"
            f"禁止偏离：{str(rule.get('forbid') or '').strip()}\n"
            f"语气：{str(rule.get('tone') or '').strip()}"
        )

    @staticmethod
    def _parse_semantic_rule_text(text, fallback=None):
        fallback = dict(fallback or {})
        mapping = {
            "场景": "scene",
            "核心意思": "intent",
            "必须体现": "must",
            "禁止偏离": "forbid",
            "语气": "tone",
        }
        out = dict(fallback)
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            field = mapping.get(key.strip())
            if field:
                out[field] = value.strip()
        return out

    def _v0883_open_rule_editor(self, existing=None, user_text="", assistant_text="", from_chat=False):
        existing = dict(existing or {})
        rid = str(existing.get("id") or "").strip()
        original_user = str(existing.get("user_text") or user_text or "").strip()
        assistant_text = str(assistant_text or "").strip()
        original_reference = str(existing.get("reference_answer") or assistant_text).strip()
        original_intent = str(existing.get("intent") or original_reference or assistant_text).strip()
        original_mode = "fixed" if str(existing.get("mode") or "").strip().lower() == "fixed" else "semantic"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑养成规则 · {rid}" if rid else "纠正 / 养成")
        try: dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        except Exception: pass
        dlg.resize(740, 760)
        root = QVBoxLayout(dlg); root.setContentsMargins(18,16,18,16); root.setSpacing(10)

        title = QLabel("修改同类问题命中时，小美丽应该怎么想、怎么说")
        title.setObjectName("pageTitle"); root.addWidget(title)
        sub = QLabel("「模仿」让小美丽记住行为和立场后自己组织新回答；「固定」不调用大模型，直接从你的回复池中随机挑一句。")
        sub.setWordWrap(True); sub.setObjectName("pageSubtitle"); root.addWidget(sub)

        root.addWidget(QLabel("触发问题 / 示例"))
        question = QLineEdit(original_user)
        question.setPlaceholderText("例如：小美丽你在干嘛？")
        root.addWidget(question)

        # Prominent segmented switch.
        mode_row = QHBoxLayout()
        mode_row.addStretch(1)
        mimic_btn = QPushButton("模仿")
        fixed_btn = QPushButton("固定")
        for btn in (mimic_btn, fixed_btn):
            btn.setObjectName("learningModeSwitch")
            btn.setCheckable(True)
            btn.setFixedSize(176, 46)
            btn.setStyleSheet(
                "QPushButton#learningModeSwitch{"
                "border:1px solid #4FCFB0;border-radius:11px;padding:7px 22px;"
                "font-size:16px;font-weight:700;background:transparent;color:palette(text);"
                "}"
                "QPushButton#learningModeSwitch:hover{background:rgba(79,207,176,0.12);}"
                "QPushButton#learningModeSwitch:checked{background:#4FCFB0;color:#08352D;border-color:#4FCFB0;}"
            )
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        mode_hint = QLabel("")
        mode_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_hint.setObjectName("pageSubtitle")
        mode_hint.setWordWrap(True)
        root.addWidget(mode_hint)

        pages = QStackedWidget()
        root.addWidget(pages, 1)

        # ---------------- 模仿 ----------------
        mimic_page = QWidget()
        mv = QVBoxLayout(mimic_page)
        mv.setContentsMargins(0, 4, 0, 0)
        mv.setSpacing(9)

        mv.addWidget(QLabel("核心立场"))
        intent_edit = QTextEdit()
        intent_edit.setMinimumHeight(105)
        intent_edit.setPlaceholderText("写小美丽真正要坚持的态度/行为，不要只写一句台词。")
        intent_edit.setPlainText(original_intent)
        mv.addWidget(intent_edit)

        mv.addWidget(QLabel("参考说法（只学风格，不要求复读）"))
        reference_edit = QLineEdit(original_reference)
        reference_edit.setPlaceholderText("例如：要你管！  这里只是示例，不会作为必须复读的答案。")
        mv.addWidget(reference_edit)

        mimic_box = QGroupBox("语义规则｜命中后只执行这一条行为规则")
        mimic_form = QFormLayout(mimic_box)
        scene = QLineEdit(str(existing.get("scene") or original_user))
        scene.setPlaceholderText("描述哪类问题 / 哪种场景应触发，不要写回答内容")
        must = QLineEdit(str(existing.get("must") or ""))
        must.setPlaceholderText("回答中必须体现的立场或动作")
        forbid = QLineEdit(str(existing.get("forbid") or "不要反转核心立场；不要机械复读参考说法"))
        tone = QLineEdit(str(existing.get("tone") or "自然、傲娇、损友式、短促；允许每次换说法"))
        mimic_form.addRow("场景", scene)
        mimic_form.addRow("必须体现", must)
        mimic_form.addRow("禁止偏离", forbid)
        mimic_form.addRow("语气", tone)
        mv.addWidget(mimic_box)
        mv.addStretch(1)
        pages.addWidget(mimic_page)

        # ---------------- 固定 ----------------
        fixed_page = QWidget()
        fv = QVBoxLayout(fixed_page)
        fv.setContentsMargins(0, 4, 0, 0)
        fv.setSpacing(9)

        speed_badge = QLabel("⚡ 0 次模型思考 · 命中后直接随机回复")
        speed_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_badge.setStyleSheet(
            "padding:8px 12px;border:1px solid rgba(79,207,176,0.45);"
            "border-radius:9px;font-weight:700;background:rgba(79,207,176,0.08);"
        )
        fv.addWidget(speed_badge)

        fixed_desc = QLabel("把你认可的台词放进回复池。相同/相近触发问题命中后，小美丽直接随机挑一句；有两句以上时会尽量避免连续重复。")
        fixed_desc.setWordWrap(True)
        fixed_desc.setObjectName("pageSubtitle")
        fv.addWidget(fixed_desc)

        fixed_list = QListWidget()
        fixed_list.setMinimumHeight(260)
        fixed_list.setAlternatingRowColors(False)
        initial_pool = existing.get("fixed_replies") or []
        if not isinstance(initial_pool, list):
            initial_pool = []
        initial_pool = [str(x or "").strip() for x in initial_pool if str(x or "").strip()]
        if not initial_pool and original_reference:
            initial_pool = [original_reference]
        for line in initial_pool:
            fixed_list.addItem(line)
        fv.addWidget(fixed_list, 1)

        add_row = QHBoxLayout()
        fixed_input = QLineEdit()
        fixed_input.setPlaceholderText("输入一条固定回复，例如：查岗啊？不告诉你。")
        add_btn = QPushButton("＋ 添加")
        add_row.addWidget(fixed_input, 1)
        add_row.addWidget(add_btn)
        fv.addLayout(add_row)

        edit_row = QHBoxLayout()
        edit_fixed_btn = QPushButton("编辑选中")
        remove_fixed_btn = QPushButton("删除选中")
        clear_fixed_btn = QPushButton("清空")
        edit_row.addWidget(edit_fixed_btn)
        edit_row.addWidget(remove_fixed_btn)
        edit_row.addWidget(clear_fixed_btn)
        edit_row.addStretch(1)
        count_label = QLabel("0 句")
        count_label.setObjectName("pageSubtitle")
        edit_row.addWidget(count_label)
        fv.addLayout(edit_row)
        pages.addWidget(fixed_page)

        def refresh_count():
            count_label.setText(f"{fixed_list.count()} 句")

        def add_fixed():
            text_value = fixed_input.text().strip()
            if not text_value:
                return
            for i in range(fixed_list.count()):
                if fixed_list.item(i).text().strip() == text_value:
                    fixed_input.clear()
                    return
            fixed_list.addItem(text_value)
            fixed_input.clear()
            fixed_list.setCurrentRow(fixed_list.count() - 1)
            refresh_count()

        def edit_fixed():
            item = fixed_list.currentItem()
            if item is None:
                return
            value, ok = QInputDialog.getText(dlg, "编辑固定回复", "回复内容：", text=item.text())
            if ok and str(value or "").strip():
                item.setText(str(value).strip())
                refresh_count()

        def remove_fixed():
            row = fixed_list.currentRow()
            if row >= 0:
                fixed_list.takeItem(row)
                refresh_count()

        add_btn.clicked.connect(add_fixed)
        fixed_input.returnPressed.connect(add_fixed)
        edit_fixed_btn.clicked.connect(edit_fixed)
        remove_fixed_btn.clicked.connect(remove_fixed)
        clear_fixed_btn.clicked.connect(lambda: (fixed_list.clear(), refresh_count()))
        fixed_list.itemDoubleClicked.connect(lambda _item: edit_fixed())
        refresh_count()

        active_mode = {"value": original_mode}

        def apply_mode(mode):
            mode = "fixed" if mode == "fixed" else "semantic"
            active_mode["value"] = mode
            is_fixed = mode == "fixed"
            mimic_btn.blockSignals(True); fixed_btn.blockSignals(True)
            mimic_btn.setChecked(not is_fixed)
            fixed_btn.setChecked(is_fixed)
            mimic_btn.blockSignals(False); fixed_btn.blockSignals(False)
            pages.setCurrentIndex(1 if is_fixed else 0)
            mode_hint.setText(
                "固定：追求最快响应。命中后不启动 Qwen 推理，直接从回复池随机挑一句。"
                if is_fixed else
                "模仿：记住触发范围、核心立场和语气，由小美丽现场组织新句子；正常只进行 1 次主推理。"
            )

        mimic_btn.clicked.connect(lambda checked=False: apply_mode("semantic"))
        fixed_btn.clicked.connect(lambda checked=False: apply_mode("fixed"))
        apply_mode(original_mode)

        if rid:
            current_name = "固定" if original_mode == "fixed" else "模仿"
            status = QLabel(f"当前：#{rid} · {current_name}。保存会直接覆盖这一条，并保留规则编号、分组和命中次数。")
        else:
            status = QLabel("当前：新规则。")
        status.setWordWrap(True)
        root.addWidget(status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("保存并应用")
        save_btn.setMinimumWidth(132)
        cancel_btn = QPushButton("取消")
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        cancel_btn.clicked.connect(dlg.reject)

        def commit():
            q = question.text().strip()
            if not q:
                QMessageBox.warning(dlg, "无法保存", "触发问题 / 示例不能为空。")
                return

            mode = active_mode["value"]
            if mode == "semantic":
                intent = intent_edit.toPlainText().strip()
                if not intent:
                    QMessageBox.warning(dlg, "无法保存", "模仿模式下「核心立场」不能为空。")
                    return
                reference = reference_edit.text().strip() or intent
                scene_text = scene.text().strip() or q
                must_text = must.text().strip() or intent
                forbid_text = forbid.text().strip() or "不要反转核心立场；不要机械复读参考说法"
                tone_text = tone.text().strip() or "自然、符合小美丽人格；允许每次换说法"
                changes = {
                    "mode": "semantic",
                    "user_text": q,
                    "scene": scene_text,
                    "intent": intent,
                    "must": must_text,
                    "forbid": forbid_text,
                    "tone": tone_text,
                    "reference_answer": reference,
                    "fixed_replies": [],
                }
                if rid:
                    saved = self.brain_service.update_rule(rid, changes)
                    if not saved:
                        QMessageBox.warning(dlg, "保存失败", "没有找到原规则，已取消本次修改。")
                        return
                else:
                    self.brain_service.save_feedback(
                        "down", q, assistant_text, reference, "semantic",
                        {
                            "scene": scene_text,
                            "intent": intent,
                            "must": must_text,
                            "forbid": forbid_text,
                            "tone": tone_text,
                        },
                    )
                label = "模仿"
                self.brain_status.setText("模仿规则已保存：只记住行为与立场，参考说法不参与规则匹配，也不会被当成固定台词。")
            else:
                pool = []
                for i in range(fixed_list.count()):
                    value = fixed_list.item(i).text().strip()
                    if value and value not in pool:
                        pool.append(value)
                if not pool:
                    QMessageBox.warning(dlg, "无法保存", "固定模式至少需要添加 1 句回复。")
                    return
                reference = pool[0]
                changes = {
                    "mode": "fixed",
                    "user_text": q,
                    "scene": q,
                    "intent": "",
                    "must": "",
                    "forbid": "",
                    "tone": "",
                    "reference_answer": reference,
                    "fixed_replies": pool,
                }
                if rid:
                    saved = self.brain_service.update_rule(rid, changes)
                    if not saved:
                        QMessageBox.warning(dlg, "保存失败", "没有找到原规则，已取消本次修改。")
                        return
                else:
                    self.brain_service.save_feedback(
                        "down", q, assistant_text, reference, "fixed",
                        {"fixed_replies": pool},
                    )
                label = "固定"
                self.brain_status.setText(f"固定回复池已保存：{len(pool)} 句。命中后 0 次模型推理，直接随机回复。")

            if from_chat:
                try:
                    self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
                    self.brain_chat.addItem(f"你教她（{label}）：已保存")
                    self.brain_chat.scrollToBottom()
                    self.brain_like_btn.setEnabled(False)
                    self.brain_dislike_btn.setEnabled(False)
                except Exception:
                    pass

            self._refresh_brain_rules()
            self._v774_refresh_brain_summary()
            try: self._v0882_refresh_favorites()
            except Exception: pass
            dlg.accept()

        save_btn.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _brain_dislike(self):
        ex = self._v088_selected_exchange()
        if not ex:
            return
        user_text = str(ex.get("user_text") or "").strip()
        assistant_text = str(ex.get("assistant_text") or "").strip()
        if not user_text:
            return
        try:
            existing = dict(self.brain_service.find_rule_for_question(user_text) or {})
        except Exception:
            existing = {}
        self._v0883_open_rule_editor(existing, user_text, assistant_text, True)

    def _brain_rule_proposed(self, ok, rule, message):
        pending = self._pending_semantic_lesson
        if not pending:
            return
        if not ok:
            self.brain_status.setText(str(message))
            self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
            self._pending_semantic_lesson = None
            return

        initial = self._semantic_rule_text(rule)
        edited, accepted = QInputDialog.getMultiLineText(
            self,
            "确认小美丽学到的意思",
            "请检查下面这 5 项。理解不对可以直接修改；确认后才会真正写入养成库：",
            initial,
        )
        if not accepted:
            self.brain_status.setText("这次语义养成已取消，没有写入。")
            self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
            self._pending_semantic_lesson = None
            return

        final_rule = self._parse_semantic_rule_text(edited, rule)
        self.brain_service.save_feedback(
            "down",
            pending["user_text"],
            pending["assistant_text"],
            pending["desired"],
            "semantic",
            final_rule,
        )
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        self.brain_chat.addItem(f"你教她（学这个意思）：{pending['desired']}")
        self.brain_chat.scrollToBottom()
        self.brain_status.setText("语义规则已确认并写入养成库。以后命中时先生成，再经过守门检查。")
        self._pending_semantic_lesson = None
        self._refresh_brain_rules()

    def _selected_brain_group_id(self):
        if not hasattr(self, "brain_rule_groups_list"):
            return "__all__"
        item = self.brain_rule_groups_list.currentItem()
        if item is None:
            return "__all__"
        value = item.data(Qt.ItemDataRole.UserRole)
        return "__all__" if value is None else str(value)

    def _refresh_rule_groups(self):
        if not hasattr(self, "brain_rule_groups_list"):
            return

        wanted = self._selected_brain_group_id()
        if wanted == "__all__" and self.brain_rule_groups_list.count() == 0:
            wanted = "__all__"

        try:
            groups = self.brain_service.list_rule_groups()
            rules = self.brain_service.list_rules()
        except Exception:
            LOGGER.exception("刷新养成库分组失败")
            groups, rules = [], []

        counts = {"": 0}
        for rule in rules:
            gid = str(rule.get("group_id") or "")
            counts[gid] = counts.get(gid, 0) + 1

        self.brain_rule_groups_list.blockSignals(True)
        self.brain_rule_groups_list.clear()

        all_item = QListWidgetItem(f"全部规则  ({len(rules)})")
        all_item.setData(Qt.ItemDataRole.UserRole, "__all__")
        self.brain_rule_groups_list.addItem(all_item)

        ungrouped = QListWidgetItem(f"未分组  ({counts.get('', 0)})")
        ungrouped.setData(Qt.ItemDataRole.UserRole, "")
        self.brain_rule_groups_list.addItem(ungrouped)

        for group in groups:
            gid = str(group.get("id") or "")
            name = str(group.get("name") or "未命名")
            item = QListWidgetItem(f"{name}  ({counts.get(gid, 0)})")
            item.setData(Qt.ItemDataRole.UserRole, gid)
            item.setToolTip(name)
            self.brain_rule_groups_list.addItem(item)

        found = False
        for i in range(self.brain_rule_groups_list.count()):
            item = self.brain_rule_groups_list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == wanted:
                self.brain_rule_groups_list.setCurrentRow(i)
                found = True
                break
        if not found:
            self.brain_rule_groups_list.setCurrentRow(0)
        self.brain_rule_groups_list.blockSignals(False)

        if hasattr(self, "brain_rule_move_combo"):
            current_move = str(self.brain_rule_move_combo.currentData() or "")
            self.brain_rule_move_combo.blockSignals(True)
            self.brain_rule_move_combo.clear()
            self.brain_rule_move_combo.addItem("未分组", "")
            for group in groups:
                self.brain_rule_move_combo.addItem(
                    str(group.get("name") or "未命名"),
                    str(group.get("id") or ""),
                )
            for i in range(self.brain_rule_move_combo.count()):
                if str(self.brain_rule_move_combo.itemData(i) or "") == current_move:
                    self.brain_rule_move_combo.setCurrentIndex(i)
                    break
            self.brain_rule_move_combo.blockSignals(False)

        selected_gid = self._selected_brain_group_id()
        editable_group = selected_gid not in {"__all__", ""}
        if hasattr(self, "brain_group_rename_btn"):
            self.brain_group_rename_btn.setEnabled(editable_group)
        if hasattr(self, "brain_group_delete_btn"):
            self.brain_group_delete_btn.setEnabled(editable_group)

    def _refresh_brain_rules(self):
        if not hasattr(self, "brain_rules_list"):
            return

        self._refresh_rule_groups()
        selected_group = self._selected_brain_group_id()
        query = ""
        if hasattr(self, "brain_rules_search"):
            query = str(self.brain_rules_search.text() or "").strip().casefold()

        self.brain_rules_list.clear()
        try:
            rules = self.brain_service.list_rules()
            groups = self.brain_service.list_rule_groups()
        except Exception:
            LOGGER.exception("刷新养成库失败")
            rules, groups = [], []

        group_names = {str(x.get("id") or ""): str(x.get("name") or "") for x in groups}

        for rule in rules:
            gid = str(rule.get("group_id") or "")
            if selected_group != "__all__" and gid != selected_group:
                continue

            haystack = " ".join(
                str(rule.get(k) or "")
                for k in (
                    "id", "user_text", "scene", "intent", "must", "forbid",
                    "tone", "reference_answer",
                )
            ).casefold()
            if query and query not in haystack:
                continue

            mode = "语义" if rule.get("mode") == "semantic" else "固定"
            state = "启用" if rule.get("enabled", True) else "暂停"
            hits = int(rule.get("hit_count") or 0)
            title = str(
                rule.get("scene")
                or rule.get("user_text")
                or rule.get("reference_answer")
                or ""
            ).strip()
            if len(title) > 34:
                title = title[:34] + "…"

            group_name = group_names.get(gid, "未分组") if gid else "未分组"
            prefix = f"〔{group_name}〕 " if selected_group == "__all__" else ""
            item = QListWidgetItem(
                f"#{rule.get('id')}  {prefix}[{mode}｜{state}]  命中 {hits} 次｜{title}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(rule.get("id") or ""))
            item.setToolTip(
                f"分组：{group_name}\n"
                f"触发：{str(rule.get('user_text') or rule.get('scene') or '')}\n"
                f"回答/核心意思：{str(rule.get('reference_answer') or rule.get('intent') or '')}"
            )
            self.brain_rules_list.addItem(item)

    def _brain_create_rule_group(self):
        value, ok = QInputDialog.getText(
            self.brain_rules_dialog,
            "新建分组",
            "分组名称：",
        )
        if not ok:
            return
        row, error = self.brain_service.create_rule_group(value)
        if row is None:
            QMessageBox.information(self.brain_rules_dialog, "无法创建分组", str(error))
            return
        self._refresh_rule_groups()
        gid = str(row.get("id") or "")
        for i in range(self.brain_rule_groups_list.count()):
            item = self.brain_rule_groups_list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == gid:
                self.brain_rule_groups_list.setCurrentRow(i)
                break
        self._refresh_brain_rules()

    def _brain_rename_rule_group(self):
        gid = self._selected_brain_group_id()
        if gid in {"__all__", ""}:
            QMessageBox.information(self.brain_rules_dialog, "重命名分组", "请选择一个自定义分组。")
            return
        groups = self.brain_service.list_rule_groups()
        group = next((g for g in groups if str(g.get("id") or "") == gid), None)
        if not group:
            self._refresh_rule_groups()
            return
        value, ok = QInputDialog.getText(
            self.brain_rules_dialog,
            "重命名分组",
            "新的分组名称：",
            text=str(group.get("name") or ""),
        )
        if not ok:
            return
        changed, error = self.brain_service.rename_rule_group(gid, value)
        if not changed:
            QMessageBox.information(self.brain_rules_dialog, "无法重命名", str(error))
            return
        self._refresh_brain_rules()

    def _brain_delete_rule_group(self):
        gid = self._selected_brain_group_id()
        if gid in {"__all__", ""}:
            QMessageBox.information(self.brain_rules_dialog, "删除分组", "请选择一个自定义分组。")
            return
        groups = self.brain_service.list_rule_groups()
        group = next((g for g in groups if str(g.get("id") or "") == gid), None)
        name = str(group.get("name") or "这个分组") if group else "这个分组"
        answer = QMessageBox.question(
            self.brain_rules_dialog,
            "删除分组",
            f"确定删除分组「{name}」吗？\n\n分组里的规则不会被删除，会自动移动到「未分组」。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.brain_service.delete_rule_group(gid):
            QMessageBox.warning(self.brain_rules_dialog, "删除失败", "分组不存在或保存失败。")
            return
        self._refresh_brain_rules()

    def _brain_move_rule_to_group(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self.brain_rules_dialog, "移动规则", "请先选中一条规则。")
            return
        gid = str(self.brain_rule_move_combo.currentData() or "")
        if not self.brain_service.move_rule_to_group(rule_id, gid):
            QMessageBox.warning(self.brain_rules_dialog, "移动失败", "没有找到规则或目标分组。")
            return
        self.brain_status.setText(f"规则 #{rule_id} 已移动")
        self._refresh_brain_rules()

    def _selected_brain_rule_id(self):
        item = self.brain_rules_list.currentItem() if hasattr(self, "brain_rules_list") else None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _v0776_choose_rule_mode(self, current_mode="fixed"):
        box = QMessageBox(self)
        box.setWindowTitle("选择养成方式")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("这条修改后的规则，想让小美丽怎么记住？")
        box.setInformativeText(
            "学这个意思（推荐）：允许自然换句式，但核心意思不能偏离。\n"
            "固定这句话：同样的问题逐字回答你写的内容。"
        )
        semantic_btn = box.addButton("学这个意思（推荐）", QMessageBox.ButtonRole.AcceptRole)
        fixed_btn = box.addButton("固定这句话", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        if str(current_mode) == "semantic":
            box.setDefaultButton(semantic_btn)
        else:
            box.setDefaultButton(fixed_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is semantic_btn:
            return "semantic"
        if clicked is fixed_btn:
            return "fixed"
        return None

    def _brain_edit_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return
        self._v0883_open_rule_editor(
            rule,
            str(rule.get("user_text") or ""),
            str(rule.get("reference_answer") or rule.get("intent") or ""),
            False,
        )

    def _brain_toggle_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            return
        enabled = not bool(rule.get("enabled", True))
        self.brain_service.update_rule(rule_id, {"enabled": enabled})
        self.brain_status.setText(f"规则 #{rule_id} 已{'启用' if enabled else '暂停'}")
        self._refresh_brain_rules()

    def _brain_delete_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return

        title = str(rule.get("scene") or rule.get("user_text") or rule_id).strip()
        if len(title) > 42:
            title = title[:42] + "…"
        answer = QMessageBox.question(
            self.brain_rules_dialog,
            "删除养成规则",
            f"确定删除规则 #{rule_id} 吗？\n\n{title}\n\n"
            "删除后它不会再参与固定命中、语义匹配或回答风格示例。"
            "以后重新教同一问题时，会作为一条新规则重新建立。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not self.brain_service.delete_rule(rule_id):
            QMessageBox.warning(self.brain_rules_dialog, "删除失败", "规则没有成功写入删除状态，请重试。")
            return

        self.brain_status.setText(f"规则 #{rule_id} 已删除")
        self._refresh_brain_rules()

    def _brain_clear_history(self):
        self.brain_service.clear_history()
        self.brain_chat.clear()
        self.brain_status.setText("当前聊天上下文已清空；人格卡和养成样本仍然保留。")

    def _prepare_voice_design(self):
        if not self.voice_service.ready():
            QMessageBox.information(self, "小女孩声线扩展", "请先准备基础 Qwen3-TTS 语音组件。")
            return
        self.voice_design_btn.setEnabled(False)
        self.voice_status.setText("正在准备小女孩声线扩展。首次约 4.5 GB，完成后以后可离线使用。")
        self.voice_progress.setValue(0)
        self.voice_service.start_design_download()

    def _prepare_voice_components(self):
        self.voice_prepare_btn.setEnabled(False)
        self.voice_status.setText("正在准备语音组件，请保持网络连接。完成后以后可离线使用。")
        self.voice_service.start_download()

    def _voice_download_progress(self, value, text):
        if not self.isVisible():
            return
        self.voice_progress.setValue(max(0, min(100, int(value))))
        self.voice_status.setText(str(text))

    def _voice_download_finished(self, ok, message):
        if not self.isVisible():
            return
        self.voice_status.setText(str(message))
        self.voice_prepare_btn.setEnabled(not self.voice_service.ready())
        if hasattr(self, "voice_design_btn"):
            design_ready = self.voice_service.design_ready()
            self.voice_design_btn.setText(
                "✓ 小女孩声线扩展已安装"
                if design_ready
                else "安装小女孩声线扩展（可选，约 4.5 GB）"
            )
            self.voice_design_btn.setEnabled(self.voice_service.ready() and not design_ready)
        if ok:
            self.voice_progress.setValue(100)
            self.voice_service.load_voices_async()

    def _voice_list_ready(self, voices):
        voices = [str(v) for v in (voices or [])]
        current = str(self.cfg.get("voice",{}).get("voice_id","") or "")
        selected = self.voice_combo.currentData()
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for idx, vid in enumerate(voices, start=1):
            try:
                display = self.voice_service.display_name(vid)
            except Exception:
                display = str(vid)
            self.voice_combo.addItem(display, vid)
        target = current or selected
        if target:
            i = self.voice_combo.findData(target)
            if i >= 0:
                self.voice_combo.setCurrentIndex(i)
        self.voice_combo.blockSignals(False)
        ready = self.voice_combo.count() > 0
        self.voice_combo.setEnabled(ready)
        self.voice_preview_btn.setEnabled(ready)
        self.voice_fix_btn.setEnabled(ready)
        if ready:
            recommended = self.voice_combo.findData("design_xiaomeili_cool")
            suffix = " 推荐先试听「小美丽｜战斗贤者」。" if recommended >= 0 else ""
            self.voice_status.setText(
                f"Qwen3-TTS 已就绪：{self.voice_combo.count()} 个候选声线可试听。" + suffix
            )
        else:
            self.voice_status.setText("Qwen3-TTS 已准备，但没有读取到候选声线。请查看桌面错误日志。")

    def _step_voice(self, delta):
        if self.voice_combo.count() <= 0:
            return
        self.voice_combo.setCurrentIndex((self.voice_combo.currentIndex() + int(delta)) % self.voice_combo.count())
        self._preview_voice()

    def _preview_voice(self):
        vid = self.voice_combo.currentData()
        if not vid:
            QMessageBox.information(self,"声音试听","请先准备语音组件并选择声音。")
            return
        text = self.voice_test_text.text().strip()
        if not text:
            text = "美丽美丽，我在呢。今天又想让我陪你干嘛？"
            self.voice_test_text.setText(text)
        self.voice_service.preview(text, str(vid), self.voice_speed.value(), self.voice_output_combo.currentData() or "default")

    def _voice_synth_started(self):
        if self.isVisible():
            self.voice_preview_btn.setEnabled(False)
            self.voice_status.setText("正在生成试听语音…")

    def _voice_synth_finished(self, ok, message):
        if not self.isVisible():
            return
        self.voice_preview_btn.setEnabled(self.voice_combo.count() > 0)
        self.voice_status.setText(str(message))

    def _fix_current_voice(self):
        vid = str(self.voice_combo.currentData() or "").strip()
        if not vid:
            return
        if not isinstance(self.cfg.get("voice"), dict):
            self.cfg["voice"] = {}
        self.cfg["voice"]["voice_id"] = vid
        self.cfg["voice"]["speed"] = float(self.voice_speed.value())
        self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()
        self.cfg["voice"]["output_device"] = str(self.voice_output_combo.currentData() or "default")
        save_config(self.cfg)
        self.voice_fixed_label.setText(f"当前固定：{self.voice_service.display_name(vid) if hasattr(self.voice_service, 'display_name') else vid}")
        self.voice_status.setText(f"已固定为 {self.voice_service.display_name(vid) if hasattr(self.voice_service, 'display_name') else vid}。后续小美丽所有语音都默认使用这个声线。")

    def _refresh_asset_label(self,state):
        pool = _asset_list(self.cfg.get("assets",{}).get(state))
        user = [p for p in pool if _is_user_asset(p) and Path(p).exists()]
        lab=self.asset_labels.get(state)
        if lab:
            lab.setText(f"{len(user)}/{MAX_ASSETS_PER_STATE} 支")
            lab.setToolTip("可一次拖入多支视频到本行；自动抠绿、白边/柔光；最多20支。")

    def _on_asset_files_dropped(self, state, paths):
        """Handle batch drag-and-drop from an animation-state drop zone.

        This handler receives AssetDropLabel.files_dropped
        without carrying the handler across from V0.4.8, which made the
        Settings dialog fail during construction. Keep all drop imports on the
        same validated path as the Import Video button.
        """
        self.import_video_paths_for(state, list(paths or []), source="drop")

    def _report_font_status(self):
        pth=str(self.cfg.get("report_font_path","") or "")
        return "猫啃什锦黑-轻量版（已就绪）" if pth and Path(pth).exists() else "未导入（请选 MaokenAssortedSans-Lite.otf）"

    def import_report_font(self):
        path,_=QFileDialog.getOpenFileName(self,"选择小美丽战报字体",str(Path.home()),"OpenType/TrueType (*.otf *.ttf)")
        if not path: return
        try:
            REPORT_FONT_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, REPORT_FONT_LOCAL)
            self.cfg["report_font_path"] = str(REPORT_FONT_LOCAL)
            save_config(self.cfg)
            self.pet.report_overlay.reload_font()
            self.report_font_label.setText(self._report_font_status())
            QMessageBox.information(self,"字体已导入","战报动态文字将固定使用这款字体。")
        except Exception as e:
            LOGGER.exception("导入战报字体失败")
            QMessageBox.critical(self,"字体导入失败",str(e))

    def open_report_template_editor(self, asset_path=None):
        dlg=ReportTemplateDialog(self.cfg,self.pet,asset_path=asset_path,parent=self)
        dlg.exec()

    def test_report_preview(self):
        kills,ok=QInputDialog.getInt(self,"测试战报白板","模拟击杀数：",21,0,99,1)
        if not ok:return
        self.pet.show_report({"kills":int(kills),"evaluation":report_evaluation(int(kills)),"nickname":"手动预览","agent":"-"})

    def import_video_for(self,state):
        current = [p for p in _asset_list(self.cfg.get("assets",{}).get(state)) if _is_user_asset(p) and Path(p).exists()]
        remaining = max(0, MAX_ASSETS_PER_STATE-len(current))
        if remaining <= 0:
            QMessageBox.information(self,"素材池已满",f"「{STATE_NAMES[state]}」已经有 20 支视频。请先点“管理”移除不需要的素材。")
            return
        paths,_=QFileDialog.getOpenFileNames(self,f"为「{STATE_NAMES[state]}」选择绿幕视频（还可导入 {remaining} 支）",str(Path.home()),"Video (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)")
        if paths:
            self.import_video_paths_for(state, paths, source="dialog")

    def import_video_paths_for(self, state, paths, source="drop"):
        current = [p for p in _asset_list(self.cfg.get("assets",{}).get(state)) if _is_user_asset(p) and Path(p).exists()]
        remaining = max(0, MAX_ASSETS_PER_STATE-len(current))
        if remaining <= 0:
            QMessageBox.information(self,"素材池已满",f"「{STATE_NAMES[state]}」已经有 20 支视频。请先点“管理”移除不需要的素材。")
            return
        valid=[]
        ignored=[]
        seen=set()
        for raw in paths or []:
            p=Path(raw)
            key=str(p.resolve()) if p.exists() else str(p)
            if key in seen:
                continue
            seen.add(key)
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                valid.append(str(p))
            else:
                ignored.append(p.name or str(p))
        if not valid:
            QMessageBox.warning(self,"没有可导入的视频","拖入内容中没有支持的视频文件。\n支持：MP4 / MOV / MKV / WebM / AVI / M4V")
            return
        overflow=max(0, len(valid)-remaining)
        paths=valid[:remaining]
        progress=QProgressDialog("正在自动抠绿并生成透明动画…","取消",0,len(paths),self)
        progress.setWindowTitle("批量导入小美丽动画" if source=="drop" else "导入小美丽动画")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        success=[]; failed=[]
        state_dir=CACHE_DIR/"v048"/state; state_dir.mkdir(parents=True,exist_ok=True)
        for i,path in enumerate(paths, start=1):
            if progress.wasCanceled(): break
            progress.setLabelText(f"[{i}/{len(paths)}] {Path(path).name}\n自动取绿幕颜色 → 去绿边 → 淡白边/白色柔光 → 透明 WebP")
            QApplication.processEvents()
            try:
                stamp=int(time.time()*1000)
                safe=f"{state}_{stamp}_{i}.webp"
                dst=state_dir/safe
                convert_greenscreen_video(path,dst,max_width=420,target_fps=12)
                success.append(str(dst))
            except Exception as e:
                LOGGER.exception("视频导入失败: %s",path)
                failed.append((Path(path).name,str(e)))
            progress.setValue(i); QApplication.processEvents()
        progress.close()
        if success:
            self.cfg["assets"][state]=(current+success)[:MAX_ASSETS_PER_STATE]
            save_config(self.cfg)
            self.pet.play_state(state, force_new_clip=True)
            self._refresh_asset_label(state)
        msg=f"成功导入 {len(success)} 支。当前「{STATE_NAMES[state]}」素材池：{len(_asset_list(self.cfg['assets'].get(state)))}/{MAX_ASSETS_PER_STATE}。"
        if overflow:
            msg += f"\n\n素材池最多 20 支，本次有 {overflow} 支因容量限制未导入。"
        if ignored:
            msg += "\n\n已忽略非视频文件：" + "、".join(ignored[:5])
        if failed:
            msg += "\n\n失败：\n" + "\n".join(f"• {n}: {e}" for n,e in failed[:5])
        QMessageBox.information(self,"导入完成",msg)

    def upgrade_existing_assets_glow(self):
        jobs = []
        for state in STATE_NAMES:
            for pth in _asset_list(self.cfg.get("assets", {}).get(state)):
                p = Path(pth)
                if not (_is_user_asset(pth) and p.exists() and p.suffix.lower() == ".webp"):
                    continue
                # New V0.4.8 imports already have the effect.
                # V0.4.5+ imports already include the white rim/glow.
                glow_ready_dirs = {"v045", "v045_migrated", "v046", "v047", "v048"}
                if any(str(part).lower() in glow_ready_dirs for part in p.parts):
                    continue
                jobs.append((state, p))
        if not jobs:
            QMessageBox.information(self, "无需处理", "没有发现需要升级白边/柔光的旧版透明 WebP 素材。")
            return
        progress = QProgressDialog("正在为旧素材添加白边 / 柔光…", "取消", 0, len(jobs), self)
        progress.setWindowTitle("升级小美丽动画素材")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        replacements = {}
        failed = []
        for i, (state, src) in enumerate(jobs, start=1):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"[{i}/{len(jobs)}] {src.name}\n保留原透明人物 → 添加淡白边 → 柔和外发光")
            QApplication.processEvents()
            try:
                dst_dir = CACHE_DIR / "v045_migrated" / state
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst = dst_dir / f"{src.stem}_glow.webp"
                add_glow_to_transparent_animation(src, dst)
                replacements[str(src)] = str(dst)
            except Exception as e:
                LOGGER.exception("旧素材白边升级失败: %s", src)
                failed.append((src.name, str(e)))
            progress.setValue(i)
            QApplication.processEvents()
        progress.close()
        if replacements:
            for state in STATE_NAMES:
                pool = _asset_list(self.cfg.get("assets", {}).get(state))
                self.cfg["assets"][state] = [replacements.get(str(x), str(x)) for x in pool]
                self._refresh_asset_label(state)
            save_config(self.cfg)
            self.pet.play_state(self.pet.current_state or "idle", force_new_clip=True)
        msg = f"已为 {len(replacements)} 支旧素材补上白边 / 柔光。"
        if failed:
            msg += "\n\n失败：\n" + "\n".join(f"• {n}: {e}" for n,e in failed[:5])
        QMessageBox.information(self, "处理完成", msg)

    def _v0927_save_highlight_ui_now(self):
        try:
            hcfg=self.cfg.setdefault("highlight_cta",{})
            if hasattr(self,"highlight_enabled"):
                hcfg["enabled"]=bool(self.highlight_enabled.isChecked())
            if hasattr(self,"highlight_min_kills"):
                hcfg["min_kills"]=int(self.highlight_min_kills.value())
            if hasattr(self,"highlight_board_text"):
                hcfg["board_text"]=str(self.highlight_board_text.text() or "").strip()
            if hasattr(self,"highlight_phrases"):
                values=[
                    x.strip() for x in self.highlight_phrases.toPlainText().splitlines()
                    if x.strip()
                ]
                hcfg["phrases"]=values
            save_config(self.cfg)
            try:
                self.config_changed.emit()
            except Exception:
                pass
        except Exception:
            LOGGER.exception("V0.9.2.7 保存高光设置失败")

    def _v0927_schedule_highlight_save(self,*_):
        timer=getattr(self,"_v0927_highlight_save_timer",None)
        if timer is not None:
            timer.start(260)

    def _v0926_choose_and_test_asset(self,state):
        pool=[
            str(p) for p in _asset_list(self.cfg.get("assets",{}).get(state))
            if str(p or "").strip() and Path(str(p)).exists()
        ]
        if not pool:
            QMessageBox.information(self,"测试素材",f"「{STATE_NAMES.get(state,state)}」当前没有可播放素材。")
            return

        dlg=QDialog(self)
        dlg.setWindowTitle(f"选择要测试的「{STATE_NAMES.get(state,state)}」素材")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(720,560)
        lay=QVBoxLayout(dlg)
        hint=QLabel("选中一支素材后播放。这里仅做预览，不会修改、移动或删除素材文件。")
        hint.setWordWrap(True)
        hint.setObjectName("pageSubtitle")
        lay.addWidget(hint)

        lst=QListWidget()
        lst.setIconSize(QSize(96,96))
        lst.setSpacing(6)
        for pth in pool:
            thumb=asset_thumbnail(pth,96)
            item=QListWidgetItem(QIcon(thumb) if thumb else QIcon(),Path(pth).name)
            item.setData(Qt.ItemDataRole.UserRole,pth)
            item.setToolTip(pth)
            item.setSizeHint(QSize(0,104))
            lst.addItem(item)
        if lst.count():
            lst.setCurrentRow(0)
        lay.addWidget(lst,1)

        row=QHBoxLayout()
        row.addStretch(1)
        cancel=QPushButton("取消")
        play=QPushButton("播放选中")
        row.addWidget(cancel)
        row.addWidget(play)
        lay.addLayout(row)

        def do_play():
            item=lst.currentItem()
            if item is None:
                QMessageBox.information(dlg,"请选择素材","请先选中一支素材。")
                return
            selected=str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not selected or not Path(selected).exists():
                QMessageBox.warning(dlg,"素材不可用","选中的素材文件当前不可用。")
                return

            assets=self.cfg.setdefault("assets",{})
            had_key=state in assets
            original=assets.get(state)
            assets[state]=[selected]
            try:
                if state=="report":
                    self.test_report_preview()
                else:
                    self.pet.play_state(state,force_new_clip=True)
            finally:
                if had_key:
                    assets[state]=original
                else:
                    assets.pop(state,None)
            dlg.accept()

        play.clicked.connect(do_play)
        cancel.clicked.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda *_:do_play())
        try:
            self._v0775_apply_native_titlebar(dlg,getattr(self,"_v0775_theme_mode","light")=="dark")
        except Exception:
            pass
        dlg.exec()

    def manage_assets(self,state):
        pool=[p for p in _asset_list(self.cfg.get("assets",{}).get(state)) if _is_user_asset(p) and Path(p).exists()]
        dlg=QDialog(self); dlg.setWindowTitle(f"管理「{STATE_NAMES[state]}」素材池")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png"))); dlg.resize(650,500)
        lay=QVBoxLayout(dlg)
        top=QHBoxLayout(); info=QLabel(f"当前 {len(pool)}/{MAX_ASSETS_PER_STATE} 支")
        top.addWidget(info); top.addStretch(1); lay.addLayout(top)
        lst=QListWidget(); lst.setIconSize(QSize(96,96)); lst.setSpacing(6); lay.addWidget(lst)
        for pth in pool:
            thumb=asset_thumbnail(pth,96)
            item=QListWidgetItem(QIcon(thumb) if thumb else QIcon(), Path(pth).name)
            item.setData(Qt.ItemDataRole.UserRole,pth); item.setToolTip(pth); item.setSizeHint(QSize(0,104)); lst.addItem(item)
        row=QHBoxLayout(); remove=QPushButton("移除选中"); clear=QPushButton("全部清空"); close=QPushButton("关闭")
        row.addWidget(remove); row.addWidget(clear)
        if state=="report":
            edit_template=QPushButton("编辑选中模板")
            edit_template.setToolTip("为选中的战报视频单独设置白板文字区域和字号。也可以双击素材。")
            row.addWidget(edit_template)
        else:
            edit_template=None
        row.addStretch(1); row.addWidget(close); lay.addLayout(row)
        def sync_from_list():
            vals=[lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())]
            self.cfg["assets"][state]=vals if vals else bundled_assets()[state]
            save_config(self.cfg); self._refresh_asset_label(state)
            if self.pet.current_state==state: self.pet.play_state(state,force_new_clip=True)
            info.setText(f"当前 {len(vals)}/{MAX_ASSETS_PER_STATE} 支")
        def remove_selected():
            for item in list(lst.selectedItems()):
                lst.takeItem(lst.row(item))
            sync_from_list()
        def clear_all():
            if lst.count() and QMessageBox.question(dlg,"确认清空",f"清空「{STATE_NAMES[state]}」的自定义素材池？缓存文件会保留，可避免误删原始素材。") == QMessageBox.StandardButton.Yes:
                lst.clear(); sync_from_list()
        remove.clicked.connect(remove_selected); clear.clicked.connect(clear_all); close.clicked.connect(dlg.accept)
        if state=="report":
            def edit_selected():
                item=lst.currentItem()
                if not item:
                    QMessageBox.information(dlg,"请选择素材","请先选中一支战报视频。")
                    return
                self.open_report_template_editor(item.data(Qt.ItemDataRole.UserRole))
            edit_template.clicked.connect(edit_selected)
            lst.itemDoubleClicked.connect(lambda item:self.open_report_template_editor(item.data(Qt.ItemDataRole.UserRole)))
        dlg.exec()

    def restore_assets(self):
        self.cfg["assets"] = bundled_assets(); save_config(self.cfg)
        for k in STATE_NAMES:self._refresh_asset_label(k)
        self.pet.play_state("idle", force_new_clip=True)
        QMessageBox.information(self,"已恢复","7 个状态已恢复为内置占位动画。你导入过的透明缓存文件不会被删除。")

    def request_debug(self):
        self.vision.request_debug_frame()
        QMessageBox.information(self,"已请求",f"下一次成功识别到 VALORANT 画面时，会保存调试图到：\n{DEBUG_DIR}")

    def update_vision_snapshot(self,data):
        if not self.isVisible(): return
        locked=bool(data.get("report_snapshot_locked"))
        if locked:
            self.report_snapshot_status.setText("战报快照：已锁定")
            self.report_snapshot_status.setStyleSheet("font-size:16px;font-weight:700;color:#169447;padding:4px 0;")
        elif bool(data.get("report_candidate_cached")):
            self.report_snapshot_status.setText("战报快照：五卡候选已缓存")
            self.report_snapshot_status.setStyleSheet("font-size:16px;font-weight:700;color:#D98B00;padding:4px 0;")
        else:
            self.report_snapshot_status.setText("战报快照：未锁定")
            self.report_snapshot_status.setStyleSheet("font-size:16px;font-weight:700;color:#D62828;padding:4px 0;")
        parse_status=str(data.get("report_parse_status") or ("等待结算页" if not locked else "快照已锁定"))
        result=""
        if data.get("report_kills") is not None:
            result=f"  |  本局结果：{data.get('report_nickname','-')} / K={data.get('report_kills')}"
        self.report_parse_label.setText(f"战报解析：{parse_status}{result}")
        # V0.9.2.2: style immediately so disabled/background/non-game early
        # returns cannot leave the snapshot line in the old plain-text style.
        self._v0911_style_report_snapshot_bar()

        mode_name="极低功耗" if data.get("mode","ultra_low")=="ultra_low" else "调试"
        tm=data.get("timings",{}) or {}
        perf=(
            f"模式：{mode_name}  |  截图后端：{data.get('capture_backend','-')}  |  扫描：{data.get('scan_fps',0):.1f} 次/秒\n"
            f"CPU 估算：{data.get('cpu_estimate',0):.1f}%  |  OCR：{data.get('ocr_triggers',0)} 次  |  HP完整识别：{data.get('hp_reads',0)} 次  |  队列：{data.get('queue_length',0)}\n"
            f"耗时(ms)：截取 {tm.get('capture',0):.2f} / 对局 {tm.get('context',0):.2f} / 存活 {tm.get('alive',0):.2f} / HP {tm.get('hp',0):.2f} / 击杀 {tm.get('kill',0):.2f} / 死亡 {tm.get('death',0):.2f} / 结果 {tm.get('result',0):.2f} / OCR {tm.get('ocr',0):.2f}"
        )
        if data.get("disabled"):
            self.vision_status.setText("自动识别：已关闭\n"+perf); return
        if not data.get("game_found"):
            self.vision_status.setText("VALORANT窗口：未找到\n小美丽保持待机。\n"+perf); return
        if data.get("paused") and not data.get("foreground",True):
            self.vision_status.setText("VALORANT窗口：已找到，但当前不在前台\n视觉识别：休眠中\n"+perf); return
        if data.get("error"):
            self.vision_status.setText(f"VALORANT窗口：已找到\n识别错误：{data.get('error')}\n{perf}"); return
        alive={True:"存活",False:"已确认死亡",None:"未确认/疑似"}.get(data.get("alive"),"未确认")
        hp="?" if data.get("hp") is None else str(data.get("hp"))
        nick=str(self.cfg.get("vision",{}).get("player_nickname","")).strip() or "未设置"
        match_txt="对局中" if data.get("match_context") else "非对局（待机门控）"
        text=(
            f"VALORANT窗口：已找到  |  阶段：{data.get('phase','-')}\n"
            f"对局环境：{match_txt}（2/3票={data.get('context_votes',0)}）\n"
            f"对局线索 L/C/R：{data.get('context_left',0):.3f} / {data.get('context_center',0):.3f} / {data.get('context_right',0):.3f}\n"
            f"我的昵称：{nick}  |  击杀二次校验：{data.get('nickname_match','-')}\n"
            f"本人贤者：{alive}（绿色友方整条UI匹配 {data.get('alive_score',0):.3f}）\n"
            f"HP：{hp}（置信 {data.get('hp_conf',0):.3f}）  |  低血量：{'是' if data.get('low_hp') else '否'}\n"
            f"战报布局：{data.get('report_layout_score',0):.3f}  |  快照分数：{data.get('report_snapshot_score',0):.3f}\n"
            f"等待采样：{data.get('report_wait_samples',0)}  |  候选/稳定：{data.get('report_candidate_hits',0)}/{data.get('report_stable_hits',0)}  |  五卡：{data.get('report_candidate_counts',[])}  |  候选质量：{data.get('report_candidate_quality',0):.2f}  |  离线解析：{data.get('report_parse_attempts',0)} 次\n"
            f"当前自动状态：{STATE_NAMES.get(data.get('state'),'待机')}\n{perf}"
        )
        self.vision_status.setText(text)
        self._v0911_style_report_snapshot_bar()
        if hasattr(self,"highlight_status"):
            _dead=bool(data.get("death_latched"))
            _alive_state=data.get("alive_state")
            _alive_text="已死亡" if _dead else ("已确认" if _alive_state is True else "未确认")
            _final_text="是本人" if bool(data.get("self_final_kill_confirmed")) else "非本人"
            self.highlight_status.setText(
                f"本人击杀：{data.get('round_self_kills',0)}  |  敌方存活：{data.get('enemy_alive','?')}/5  |  "
                f"存活：{_alive_text}\n"
                f"最后一杀：{_final_text}\n"
                f"最近判定：{data.get('highlight_reason','等待')}"
            )
        if hasattr(self,"highlight_qualification"):
            _triggered=bool(data.get("highlight_triggered"))
            self.highlight_qualification.setText(
                "高光资格：已触发" if _triggered else "高光资格：未满足"
            )
            self.highlight_qualification.setStyleSheet(
                "QLabel#highlightQualification{"
                + (
                    "background:#E1F7EA;color:#147A45;border:1px solid #8AD5AA;"
                    if _triggered else
                    "background:#FDE8E8;color:#B42318;border:1px solid #F4B4B4;"
                )
                + "border-radius:10px;padding:10px 14px;font-size:20px;font-weight:900;}"
            )

    def test_report_from_screenshot(self):
        path,_ = QFileDialog.getOpenFileName(self, "选择整局结算页截图", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            img = cv2.imread(path)
            if img is None or img.size == 0:
                raise ValueError("无法读取图片")
            h,w = img.shape[:2]
            rx1,ry1,rx2,ry2 = ROI_REPORT_CARDS_RADAR
            radar = img[int(ry1*h):int(ry2*h), int(rx1*w):int(rx2*w)]
            x1,y1,x2,y2 = ROI_REPORT_CARDS
            cards = img[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]
            cx1,cy1,cx2,cy2 = ROI_REPORT_CONTINUE
            cont = img[int(cy1*h):int(cy2*h), int(cx1*w):int(cx2*w)]
            cand,score = self.vision._report_layout_candidate(radar, cont)
            five_ok, five_quality, five_counts, _ = self.vision._report_five_card_completeness(radar)
            if not cand or not five_ok:
                QMessageBox.warning(self, "战报截图测试",
                    f"未通过真正五人结算页检测。\n布局分数：{score:.3f}\n五卡计数：{five_counts}")
                return
            data,desc = self.vision._read_whole_match_report(cards)
            if data is None:
                QMessageBox.warning(self, "战报截图测试", f"结算页布局已命中（{score:.3f}），但OCR未完成：\n{desc}")
                return
            self.pet.show_report(data)
            QMessageBox.information(self, "战报截图测试",
                f"识别成功：\n昵称：{data.get('nickname')}\n卡片：第{data.get('card_index')}位\nK：{data.get('kills')}\n\n已在桌宠上模拟播放战报白板。")
        except Exception as e:
            LOGGER.exception("从截图测试战报失败")
            QMessageBox.critical(self, "战报截图测试失败", f"{type(e).__name__}: {e}")

    def _save_update_source(self):
        url = self.update_url.text().strip()
        self.update_service.set_manifest_url(url)
        self.update_status.setText("更新源已保存。" if url else "更新源已清空。")

    def _check_update(self):
        self._save_update_source()
        self.update_install_btn.setEnabled(False)
        self.update_progress.setValue(0)
        self.update_check_btn.setEnabled(False)
        self.update_service.check_async()

    def _update_check_finished(self, has_update, manifest, message):
        self.update_check_btn.setEnabled(True)
        self.update_install_btn.setEnabled(bool(has_update and manifest))

        if isinstance(manifest, dict):
            version = str(manifest.get("version") or "").strip()
            notes = manifest.get("notes", "")
            if isinstance(notes, list):
                body = "\n".join("• " + str(x) for x in notes)
            else:
                body = str(notes or "").strip()
            if has_update:
                self.update_status.setText(f"发现新版本 V{version}，可以立即更新。")
                title = f"V{version} 更新说明"
            else:
                self.update_status.setText(f"当前已是最新版本 V{APP_VERSION}。")
                title = f"V{version or APP_VERSION}（当前版本）"
            self.update_notes.setPlainText(title + ("\n\n" + body if body else "\n\n暂无额外版本说明。"))
        else:
            msg = str(message or "检查更新失败")
            self.update_status.setText(msg.splitlines()[0][:160])
            self.update_notes.setPlainText(msg)

        if not has_update:
            self.update_progress.setValue(0)

    def _update_progress_changed(self, value, message):
        self.update_progress.setValue(max(0, min(100, int(value))))
        self.update_status.setText(str(message))

    def _install_update(self):
        self.update_install_btn.setEnabled(False)
        self.update_check_btn.setEnabled(False)
        self.update_service.install_latest_async()

    def mark_dirty(self, *args):
        self._dirty = True
        self.save_btn.setEnabled(True)
        self.apply_status.setText("")

    def _bind_dirty_tracking(self):
        for widget, signal_name in [
            (self.top_cb, "toggled"), (self.lock_cb, "toggled"),
            (self.opacity, "valueChanged"), (self.size_spin, "valueChanged"),
            (self.trans_spin, "valueChanged"), (self.vision_enabled, "toggled"),
            (self.nickname_edit, "textChanged"), (self.hp_threshold, "valueChanged"),
            (self.mode_combo, "currentIndexChanged"), (self.pause_bg, "toggled"), (self.nickname_ocr_cb, "toggled"), (self.mouse_interaction_cb, "toggled"),
            (self.voice_test_text, "textChanged"), (self.voice_speed, "valueChanged"), (self.voice_output_combo, "currentIndexChanged"),
        ]:
            getattr(widget, signal_name).connect(self.mark_dirty)
        for editor in self.hk_editors.values():
            editor.keySequenceChanged.connect(self.mark_dirty)

    def _show_applied(self):
        self.apply_status.setText("已应用 ✓")
        QTimer.singleShot(1600, lambda: self.apply_status.setText("") if not self._dirty else None)

    def apply(self):
        self.cfg["always_on_top"]=self.top_cb.isChecked()
        locked=self.lock_cb.isChecked(); self.cfg["click_through"]=locked; self.cfg["lock_position"]=locked
        self.cfg["opacity"]=self.opacity.value(); self.cfg["pet_width"]=self.size_spin.value(); self.cfg["transition_ms"]=self.trans_spin.value()
        for k,e in self.hk_editors.items():
            self.cfg["hotkeys"][k]=e.keySequence().toString().lower().replace(" ","")
        self.cfg["mouse_interaction"]["enabled"] = self.mouse_interaction_cb.isChecked()
        if not isinstance(self.cfg.get("voice"), dict): self.cfg["voice"] = {}
        self.cfg["voice"]["speed"] = float(self.voice_speed.value())
        self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()
        self.cfg["voice"]["output_device"] = str(self.voice_output_combo.currentData() or "default")
        self.cfg["vision"]["enabled"]=self.vision_enabled.isChecked()
        self.cfg["vision"]["player_nickname"]=self.nickname_edit.text().strip()
        self.cfg["vision"]["low_hp_threshold"]=self.hp_threshold.value()
        self.cfg["vision"]["mode"]=self.mode_combo.currentData() or "ultra_low"
        self.cfg["vision"]["pause_when_background"]=self.pause_bg.isChecked()
        self.cfg["vision"]["nickname_ocr_fallback"]=self.nickname_ocr_cb.isChecked()
        hcfg=self.cfg.setdefault("highlight_cta",{})
        hcfg["enabled"]=bool(self.highlight_enabled.isChecked()) if hasattr(self,"highlight_enabled") else True
        hcfg["min_kills"]=int(self.highlight_min_kills.value()) if hasattr(self,"highlight_min_kills") else 2
        if hasattr(self,"highlight_phrases"):
            hcfg["phrases"]=[x.strip() for x in self.highlight_phrases.toPlainText().splitlines() if x.strip()]
        if hasattr(self,"highlight_video_list"):
            hcfg["videos"]=[
                str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
                for i in range(self.highlight_video_list.count())
                if str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
            ]
        self.cfg["x"],self.cfg["y"]=self.pet.x(),self.pet.y()
        # V0.7.7.7: one lock state controls position lock + real click-through.
        self.cfg["opacity"] = 100
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
        self.cfg["click_through"] = bool(self.cfg.get("lock_position", False))
        if hasattr(self, "v774_ai_cb"):
            self.cfg.setdefault("brain", {})["enabled"] = bool(self.v774_ai_cb.isChecked())
        if hasattr(self, "v774_drag_cb"):
            self.cfg.setdefault("drag_interaction", {})["enabled"] = bool(self.v774_drag_cb.isChecked())
        if hasattr(self, "v774_strength_combo"):
            try:
                self.cfg.setdefault("mouse_interaction", {})["strength"] = float(self.v774_strength_combo.currentData() or 1.0)
            except Exception:
                self.cfg.setdefault("mouse_interaction", {})["strength"] = 1.0
        if hasattr(self, "_v774_pet_name"):
            self.cfg["pet_name"] = str(self._v774_pet_name or "小美丽").strip() or "小美丽"
        save_config(self.cfg)
        self.pet.setWindowOpacity(self.cfg["opacity"]/100.0); self.pet.resize_pet(); self.pet.apply_window_flags(); self.pet.apply_clickthrough_native(); self.pet.refresh_mouse_interaction_config()
        self.hotkeys_changed.emit(); self.config_changed.emit(); LOGGER.info("设置已保存并应用（窗口保持打开）")
        self._dirty = False
        self.save_btn.setEnabled(False)
        self._show_applied()


class AppController(QObject):
    def __init__(self,app,cfg):
        super().__init__()
        self.app=app; self.cfg=cfg; self.bridge=Bridge(); self.pet=PetWindow(cfg); self.settings=None
        self.ability_sidebar=AbilitySidebar()
        self.ability_node=AbilityNode()
        self.ability_sidebar.set_states(self.cfg.get("ability_sidebar", {}).get("states", {}))
        self._ability_hover_token=0
        self.hotkeys=HotkeyManager(self.bridge)
        self.vision=VisionWorker(cfg)
        self.voice_service=VoiceService()
        self.brain_service=BrainService()
        QTimer.singleShot(1800, self.brain_service.warm_up_async)
        self.speech_service=SpeechInputService()
        self.update_service=UpdateService(cfg)
        self._speech_session_active=False
        self._speech_waiting_question=False
        self._speech_waiting_brain=False
        self._speech_pending_question=""
        self._speech_last_wake_reply=""
        self._speech_session_token=0
        self._speech_cache_waiting=False

        self.bridge.trigger_state.connect(self.pet.play_state)
        self.bridge.open_settings.connect(self.open_settings)
        self.bridge.toggle_lock.connect(self.pet.toggle_interaction_lock)
        self.bridge.show_hide.connect(self.pet.toggle_show_hide)
        self.pet.request_settings.connect(self.open_settings)
        self.pet.request_abilities.connect(self.toggle_ability_sidebar)
        self.pet.config_changed.connect(self.update_tray_checks)
        self.pet.ability_hover_entered.connect(self._on_pet_ability_hover_enter)
        self.pet.ability_hover_left.connect(self._on_pet_ability_hover_leave)
        self.pet.ability_geometry_changed.connect(self._sync_ability_ui)
        self.ability_node.clicked.connect(self.toggle_ability_sidebar)
        self.ability_node.hover_entered.connect(self._on_node_ability_hover_enter)
        self.ability_node.hover_left.connect(self._on_node_ability_hover_leave)
        self.ability_sidebar.state_changed.connect(self._on_ability_state_changed)
        self.ability_sidebar.visibility_changed.connect(self._on_ability_sidebar_visibility)
        self.ability_sidebar.hover_entered.connect(self._on_sidebar_ability_hover_enter)
        self.ability_sidebar.hover_left.connect(self._on_sidebar_ability_hover_leave)
        self.vision.state_requested.connect(self.pet.play_state)
        self.vision.report_ready.connect(self.pet.show_report)
        self.vision.snapshot.connect(self.on_vision_snapshot)
        self.update_service.restart_requested.connect(self.quit)
        self.speech_service.utterance_ready.connect(self._on_speech_utterance)
        self.speech_service.state_changed.connect(self._on_speech_engine_state)
        self.speech_service.setup_finished.connect(self._on_speech_setup_finished)
        self.speech_service.error.connect(self._on_speech_error)
        self.voice_service.phrase_cache_ready.connect(self._on_wake_cache_ready)
        self.voice_service.playback_started.connect(self._on_voice_playback_started)
        self.voice_service.playback_finished.connect(self._on_voice_playback_finished)
        self.brain_service.generation_finished.connect(self._on_voice_brain_finished)
        self._highlight_seen_event_id=0
        self._highlight_active=False
        self._highlight_last_phrase=""
        self._highlight_phrase_key=None
        self._highlight_phrase_bag=[]
        self._highlight_pending_video=""
        self._highlight_overlay=None
        self._highlight_video_key=None
        self._highlight_video_bag=[]
        self._highlight_last_video=""
        QTimer.singleShot(2600,self._warm_highlight_cta_cache)

        self.tray=self.make_tray(); self.app.setProperty("tray",self.tray)
        self.hotkeys.register(cfg); self.pet.show(); self.vision.start(); QTimer.singleShot(1800, self.refresh_speech_interaction); QTimer.singleShot(5000, cleanup_obsolete_storage)

    def _ability_anchor_rect(self):
        return QRect(self.pet.x(), self.pet.y(), self.pet.width(), self.pet.height())

    def _ability_available(self):
        acfg = self.cfg.get("ability_sidebar", {}) if isinstance(self.cfg.get("ability_sidebar"), dict) else {}
        return bool(
            acfg.get("enabled", True)
            and self.pet.isVisible()
            and not self.cfg.get("lock_position", False)
            and not self.cfg.get("click_through", False)
        )

    def _position_ability_node(self):
        if not getattr(self, "ability_node", None):
            return
        anchor = self._ability_anchor_rect()
        side = self.ability_sidebar.side_for_anchor(anchor)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        node = self.ability_node
        y = anchor.top() + int(anchor.height() * 0.43) - node.height() // 2
        if side == "left":
            x = anchor.left() - node.width() - 6
        else:
            x = anchor.right() + 6
        x = max(area.left() + 2, min(x, area.right() - node.width() - 2))
        y = max(area.top() + 2, min(y, area.bottom() - node.height() - 2))
        node.move(int(x), int(y))

    def _sync_ability_ui(self):
        try:
            anchor = self._ability_anchor_rect()
            if self.ability_sidebar.isVisible():
                self.ability_sidebar.sync_to_anchor(anchor, force=True)
            if self.ability_node.isVisible():
                self._position_ability_node()
        except Exception:
            LOGGER.debug("同步美丽能力UI位置失败", exc_info=True)

    def _show_ability_node(self):
        if not self._ability_available() or self.ability_sidebar.isVisible():
            return
        self._ability_hover_token += 1
        self._position_ability_node()
        self.ability_node.show(); self.ability_node.raise_()

    def _cancel_ability_auto_close(self):
        self._ability_hover_token += 1

    def _schedule_close_ability_ui(self, delay_ms=520):
        # Event-driven only: no ability-specific hover polling timer. Moving
        # between pet/node/panel keeps the UI alive; leaving all three closes it.
        self._ability_hover_token += 1
        token = int(self._ability_hover_token)
        def later():
            if token != int(self._ability_hover_token):
                return
            pos = QCursor.pos()
            over_pet = self.pet.isVisible() and self.pet.frameGeometry().contains(pos)
            over_node = self.ability_node.isVisible() and self.ability_node.frameGeometry().contains(pos)
            over_panel = self.ability_sidebar.isVisible() and self.ability_sidebar.frameGeometry().contains(pos)
            if over_pet or over_node or over_panel:
                return
            self.ability_node.hide()
            if self.ability_sidebar.isVisible():
                self.ability_sidebar.hide_animated()
        QTimer.singleShot(max(160, int(delay_ms)), later)

    def _on_pet_ability_hover_enter(self):
        self._cancel_ability_auto_close()
        self._show_ability_node()

    def _on_pet_ability_hover_leave(self):
        self._schedule_close_ability_ui(520)

    def _on_node_ability_hover_enter(self):
        self._cancel_ability_auto_close()

    def _on_node_ability_hover_leave(self):
        self._schedule_close_ability_ui(420)

    def _on_sidebar_ability_hover_enter(self):
        self._cancel_ability_auto_close()

    def _on_sidebar_ability_hover_leave(self):
        self._schedule_close_ability_ui(520)

    def _on_ability_sidebar_visibility(self, visible):
        visible = bool(visible)
        self.pet.set_ability_form_requested(visible)
        if visible:
            self.ability_node.hide()
            QTimer.singleShot(0, self.pet.raise_)
        else:
            self._schedule_close_ability_ui(260)

    def toggle_ability_sidebar(self):
        if not self._ability_available():
            return
        cfg = self.cfg.setdefault("ability_sidebar", {})
        anchor = self._ability_anchor_rect()
        if self.ability_sidebar.isVisible() and self.ability_sidebar.is_open():
            self.ability_sidebar.hide_animated()
        else:
            self.ability_node.hide()
            self.ability_sidebar.set_states(cfg.get("states", {}))
            self.ability_sidebar.show_animated(anchor)

    def _on_ability_state_changed(self, feature_id, checked):
        acfg = self.cfg.setdefault("ability_sidebar", {})
        states = acfg.setdefault("states", {})
        feature_id = str(feature_id or "")
        if feature_id not in {key for key, _, _ in ABILITY_FEATURES}:
            return
        states[feature_id] = bool(checked)
        save_config(self.cfg)
        self.pet.set_ability_states(states)
        LOGGER.info("[ABILITY] %s=%s (XiaoMeili cosmetic only)", feature_id, bool(checked))

        # V0.10.0 deliberately does not hard-code the five voice lines. The
        # per-ability event signals exist now; optional phrases can be added later
        # without rewriting the sidebar.
        if not checked or not bool(acfg.get("voice_enabled", True)):
            return
        phrases = acfg.get("voice_phrases", {}) if isinstance(acfg.get("voice_phrases"), dict) else {}
        phrase = str(phrases.get(feature_id, "") or "").strip()
        voice = self._speech_voice_cfg()
        vid = str(voice.get("voice_id") or "").strip()
        if not phrase or not vid or not self.voice_service.ready():
            return
        self.voice_service.speak(
            phrase, vid, float(voice.get("speed", 1.0) or 1.0),
            str(voice.get("output_device", "default") or "default"),
            tag="ability_feedback", extra_instruct="短促、冷静、酷一点，不甜腻。",
        )

    def _refresh_ability_config(self):
        if not self._ability_available():
            self.ability_node.hide()
            if self.ability_sidebar.isVisible():
                self.ability_sidebar.hide_animated()
            self.pet.set_ability_form_requested(False)
        else:
            self._sync_ability_ui()

    def _handle_ability_voice_command(self, text):
        acfg = self.cfg.get("ability_sidebar", {}) if isinstance(self.cfg.get("ability_sidebar"), dict) else {}
        if not bool(acfg.get("enabled", True)) or not bool(acfg.get("voice_command_enabled", True)):
            return False
        raw = re.sub(r"[\s，,。.!！？?、:：]+", "", str(text or ""))
        if not raw:
            return False
        if any(k in raw for k in ("打开能力侧栏", "开启能力侧栏", "打开美丽能力", "开启美丽能力", "开挂")):
            if not self.ability_sidebar.isVisible():
                QTimer.singleShot(0, self.toggle_ability_sidebar)
            return True
        if any(k in raw for k in ("收起能力侧栏", "关闭能力侧栏", "关掉能力侧栏", "收起美丽能力", "关闭美丽能力")):
            if self.ability_sidebar.isVisible():
                QTimer.singleShot(0, self.ability_sidebar.hide_animated)
            return True
        return False

    def make_tray(self):
        tray=QSystemTrayIcon(QIcon(resource("assets/xiaomeili_icon.png")),self.app)
        menu=QMenu()
        for key,name in STATE_NAMES.items():
            act=QAction(name,menu); act.triggered.connect(lambda checked=False,s=key:self.pet.play_state(s)); menu.addAction(act)
        menu.addSeparator()
        self.lock_act=QAction("锁定（位置 + 点击穿透）",menu); self.lock_act.setCheckable(True); self.lock_act.setChecked(self.cfg.get("click_through",False)); self.lock_act.triggered.connect(self.pet.set_interaction_lock); menu.addAction(self.lock_act)
        abilities=QAction("美丽能力",menu); abilities.triggered.connect(self.toggle_ability_sidebar); menu.addAction(abilities)
        menu.addSeparator()
        settings=QAction("设置...",menu); settings.triggered.connect(self.open_settings); menu.addAction(settings)
        check_updates=QAction("检查更新",menu); check_updates.triggered.connect(self.check_updates_from_tray); menu.addAction(check_updates)
        logs=QAction("打开日志文件夹",menu); logs.triggered.connect(lambda:os.startfile(str(LOG_DIR)) if sys.platform=='win32' else None); menu.addAction(logs)
        showhide=QAction("显示/隐藏",menu); showhide.triggered.connect(self.pet.toggle_show_hide); menu.addAction(showhide)
        menu.addSeparator()
        quit_act=QAction("退出小美丽",menu); quit_act.triggered.connect(self.quit); menu.addAction(quit_act)
        tray.setContextMenu(menu); tray.setToolTip(APP_NAME); tray.activated.connect(lambda reason:self.open_settings() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None); tray.show(); return tray

    def check_updates_from_tray(self):
        self.open_settings()
        if self.settings:
            try:
                if hasattr(self.settings, "open_system_section"):
                    self.settings.open_system_section("更新")
                else:
                    for i in range(self.settings.tabs.count()):
                        if self.settings.tabs.tabText(i) == "更新":
                            self.settings.tabs.setCurrentIndex(i)
                            break
            except Exception:
                LOGGER.exception("切换到更新页失败")
            self.settings._check_update()

    def update_tray_checks(self):
        locked = bool(self.cfg.get("click_through",False) or self.cfg.get("lock_position",False))
        self.lock_act.setChecked(locked)
        if locked:
            try: self.ability_node.hide()
            except Exception: pass
            if getattr(self, "ability_sidebar", None) is not None and self.ability_sidebar.isVisible():
                self.ability_sidebar.hide_animated()
            self.pet.set_ability_form_requested(False)

    def _on_settings_changed(self):
        self.update_tray_checks()
        self._refresh_ability_config()
        self.refresh_speech_interaction()

    def _speech_cfg(self):
        return self.cfg.setdefault("speech", {})

    def _speech_voice_cfg(self):
        return self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}

    def _speech_state(self, code, label):
        try: self.speech_service._emit_state(str(code), str(label))
        except Exception: pass

    @staticmethod
    def _split_wake_phrase(text):
        raw=str(text or "").strip()
        # Accept natural ASR punctuation between the repeated wake words, but
        # only near the beginning so ordinary sentences containing “美丽” do
        # not wake the pet accidentally.
        m=re.search(r"美丽[\s ，,。.!！？?、]*美丽",raw)
        if not m or m.start()>2:
            return False, raw
        rest=raw[m.end():]
        rest=re.sub(r"^[\s ，,。.!！？?、:：]+","",rest).strip()
        return True, rest

    def _speech_fixed_replies(self):
        values=self._speech_cfg().get("wake_replies") or ["干嘛？","咋滴了？","有事你就说！"]
        values=[str(x).strip() for x in values if str(x).strip()]
        return values or ["干嘛？"]

    def _pick_wake_reply(self):
        values=self._speech_fixed_replies()
        pool=[x for x in values if x!=self._speech_last_wake_reply] or values
        choice=ASSET_RNG.choice(pool); self._speech_last_wake_reply=choice; return choice

    def _speech_phrase_instruct(self, text):
        rules=self._speech_cfg().get("phrase_voice_overrides") or {}
        if not isinstance(rules,dict):
            return ""
        raw=str(text or "").strip()
        normalized=re.sub(r"[\s，,。.!！？?、:：]+","",raw)
        for key,value in rules.items():
            k=re.sub(r"[\s，,。.!！？?、:：]+","",str(key or "").strip())
            if k and k==normalized:
                return str(value or "").strip()
        return ""

    def refresh_speech_interaction(self):
        speech=self._speech_cfg()
        if not bool(speech.get("enabled",True)):
            self._end_speech_session(resume=False); self.speech_service.stop(); return
        if not self.speech_service.ready():
            self._speech_state("not_ready","语音输入尚未准备"); return
        voice=self._speech_voice_cfg(); vid=str(voice.get("voice_id") or "")
        if not self.voice_service.ready() or not vid:
            self._speech_state("not_ready","请先准备并固定小美丽声音"); return
        if self._speech_session_active:
            return
        # Pre-generate the three tiny acknowledgements. Once cached, wake-up is
        # essentially immediate instead of waiting for TTS every time.
        self._speech_cache_waiting=True
        _replies=self._speech_fixed_replies()
        _styles={p:self._speech_phrase_instruct(p) for p in _replies}
        self.voice_service.warm_phrase_cache(_replies,vid,float(voice.get("speed",1.0) or 1.0),_styles)

    def _on_wake_cache_ready(self, ok, message):
        self._speech_cache_waiting=False
        if not bool(self._speech_cfg().get("enabled",True)):
            return
        if not ok:
            LOGGER.warning("唤醒回应缓存未完成: %s",message)
            QTimer.singleShot(3000,self.refresh_speech_interaction); return
        self.speech_service.start(str(self._speech_cfg().get("input_device","default") or "default"))

    def _on_speech_setup_finished(self, ok, message):
        if ok: QTimer.singleShot(100,self.refresh_speech_interaction)

    def _on_speech_error(self, message):
        LOGGER.warning("语音交互错误: %s",message)

    def _on_speech_engine_state(self, code, label):
        # The worker returns to its raw “listening” state immediately after ASR.
        # If a voice-session question is already in the brain, restore the
        # higher-level state on the next event-loop turn instead of confusing
        # the user with a temporary “waiting wake word” label.
        if self._speech_session_active and str(code)=="listening" and self._speech_waiting_brain:
            QTimer.singleShot(0,lambda:self._speech_state("thinking","小美丽正在想"))

    def _on_speech_utterance(self, text):
        text=str(text or "").strip()
        if not text:return
        if not self._speech_session_active:
            woke,rest=self._split_wake_phrase(text)
            if not woke:return
            if self._handle_ability_voice_command(rest):
                return
            self._begin_speech_session(rest)
            return
        if self._speech_waiting_question:
            woke,rest=self._split_wake_phrase(text)
            question=rest if woke else text
            question=str(question or "").strip()
            if question:
                if self._handle_ability_voice_command(question):
                    self._end_speech_session(resume=True)
                    return
                self._speech_waiting_question=False; self._speech_session_token+=1
                self.speech_service.pause(); self._ask_voice_question(question)

    def _begin_speech_session(self, inline_question=""):
        if self._speech_session_active:return
        self._speech_session_active=True; self._speech_waiting_question=False; self._speech_waiting_brain=False; self._speech_session_token+=1
        self.pet.set_dialogue_indicator(True); self.speech_service.pause(); self._speech_pending_question=str(inline_question or "").strip()
        self._speech_state("ack","小美丽正在回应你")
        reply=self._pick_wake_reply(); voice=self._speech_voice_cfg()
        self.voice_service.speak(reply,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="wake_ack",extra_instruct=self._speech_phrase_instruct(reply))

    def _highlight_cfg(self):
        cfg=self.cfg.get("highlight_cta",{})
        return cfg if isinstance(cfg,dict) else {}

    def _highlight_phrases_list(self):
        values=self._highlight_cfg().get("phrases") or ["愣着干嘛，点点关注呀！"]
        values=[str(x or "").strip() for x in values if str(x or "").strip()]
        return values or ["愣着干嘛，点点关注呀！"]

    def _highlight_videos_list(self):
        values=self._highlight_cfg().get("videos") or []
        out=[]
        for value in values if isinstance(values,list) else []:
            p=str(value or "").strip()
            if p and Path(p).exists() and p not in out:
                out.append(p)
        return out

    def _highlight_text_box_for_video(self,video):
        cfg=self._highlight_cfg()
        boxes=cfg.get("video_text_boxes") if isinstance(cfg.get("video_text_boxes"),dict) else {}
        key=Path(str(video or "")).name
        raw=boxes.get(key) if key else None
        if not isinstance(raw,dict):
            raw=cfg.get("text_box") or {}
        return raw

    def _pick_highlight_video(self):
        values=self._highlight_videos_list()
        if not values:
            return ""
        key=tuple(values)
        if getattr(self,"_highlight_video_key",None)!=key:
            self._highlight_video_key=key
            self._highlight_video_bag=[]
        bag=list(getattr(self,"_highlight_video_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_highlight_last_video","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        chosen=bag.pop(0)
        self._highlight_video_bag=bag
        self._highlight_last_video=chosen
        return chosen

    def _ensure_highlight_overlay(self):
        if getattr(self,"_highlight_overlay",None) is None:
            self._highlight_overlay=HighlightVideoOverlay(self.pet)
        return self._highlight_overlay

    def _highlight_font_family(self):
        try:
            self.pet.dialogue_overlay.reload_font()
            return self.pet.dialogue_overlay.font_family
        except Exception:
            return "Microsoft YaHei"

    def _warm_highlight_cta_cache(self):
        try:
            voice=self._speech_voice_cfg()
            vid=str(voice.get("voice_id") or "")
            if not vid or not self.voice_service.ready():
                return
            phrases=self._highlight_phrases_list()
            styles={p:self._speech_phrase_instruct(p) for p in phrases}
            self.voice_service.warm_phrase_cache(
                phrases,vid,float(voice.get("speed",1.0) or 1.0),styles
            )
            LOGGER.info("[HIGHLIGHT] TTS phrase cache warm requested: %s",len(phrases))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] warm cache failed")

    def _pick_highlight_phrase(self):
        values=self._highlight_phrases_list()
        key=tuple(values)
        if getattr(self,"_highlight_phrase_key",None)!=key:
            self._highlight_phrase_key=key
            self._highlight_phrase_bag=[]

        bag=list(getattr(self,"_highlight_phrase_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            if len(bag)>1 and bag[0]==self._highlight_last_phrase:
                bag[0],bag[1]=bag[1],bag[0]

        choice=bag.pop(0)
        self._highlight_phrase_bag=bag
        self._highlight_last_phrase=choice
        LOGGER.info(
            "[HIGHLIGHT] shuffle-bag pick | phrase=%s remaining=%s total=%s",
            choice,len(bag),len(values),
        )
        return choice

    def _trigger_highlight_cta(self, data):
        if self._highlight_active:
            return
        self._highlight_active=True
        LOGGER.info("[HIGHLIGHT] P100 takeover | %s",data.get("highlight_reason",""))

        # Stop/retire lower-priority dialogue. New P100 playback must not wait.
        try:
            if self._speech_session_active:
                self._end_speech_session(resume=False)
        except Exception:
            pass
        for method_name in ("stop_playback","stop_audio","cancel_playback"):
            try:
                method=getattr(self.voice_service,method_name,None)
                if callable(method):
                    method()
                    break
            except Exception:
                pass
        try:
            if getattr(self.pet,"dialogue_board_active",False):
                self.pet._end_dialogue_board()
        except Exception:
            pass

        phrase=self._pick_highlight_phrase()
        self._highlight_pending_video=self._pick_highlight_video()
        voice=self._speech_voice_cfg()
        vid=str(voice.get("voice_id") or "")
        if not vid or not self.voice_service.ready():
            LOGGER.warning("[HIGHLIGHT] voice unavailable, showing board only")
            video=str(self._highlight_pending_video or "")
            if video and self._ensure_highlight_overlay().play(
                video,phrase,4200,self._highlight_text_box_for_video(video),self._highlight_font_family()
            ):
                QTimer.singleShot(4200,lambda:self._highlight_overlay.finish(700))
            else:
                self.pet.preview_dialogue(phrase,4200)
            QTimer.singleShot(5000,lambda:setattr(self,"_highlight_active",False))
            return

        self.voice_service.speak(
            phrase,vid,float(voice.get("speed",1.0) or 1.0),
            str(voice.get("output_device","default") or "default"),
            tag="highlight_cta",
            extra_instruct=self._speech_phrase_instruct(phrase),
        )

    def _on_voice_playback_started(self, text, duration_ms, tag):
        tag=str(tag or "")
        if tag=="highlight_preview":
            return
        if tag=="highlight_cta":
            self._highlight_active=True
            # V0.9.1.1: the whiteboard always follows the actual selected
            # random phrase. Voice and board can no longer drift apart.
            board=str(text or "").strip() or "愣着干嘛，点点关注呀！"
            try:
                if getattr(self.pet,"dialogue_board_active",False):
                    self.pet._end_dialogue_board()
            except Exception:
                pass

            video=str(getattr(self,"_highlight_pending_video","") or "")
            box=self._highlight_text_box_for_video(video)
            if video:
                overlay=self._ensure_highlight_overlay()
                if overlay.play(video,board,int(duration_ms),box,self._highlight_font_family()):
                    return
            self.pet.start_dialogue_board(board,int(duration_ms))
            return
        if not self._speech_session_active:return
        self._speech_state("speaking","小美丽正在说话")
        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.start_dialogue_board(str(text),int(duration_ms))

    def _on_voice_playback_finished(self, ok, message, tag):
        tag=str(tag or "")
        if tag=="highlight_preview":
            return
        if tag=="highlight_cta":
            # Keep the talking whiteboard clip moving for a full 3-second tail.
            # HighlightVideoOverlay.finish() only schedules stop; the frame
            # timer continues looping, so there is no frozen talking pose.
            hold_ms=3000
            try:
                if getattr(self,"_highlight_overlay",None) and self._highlight_overlay.isVisible():
                    self._highlight_overlay.finish(hold_ms)
                else:
                    self.pet.finish_dialogue_board(hold_ms)
            except Exception:
                pass
            self._highlight_pending_video=""
            QTimer.singleShot(hold_ms,lambda:setattr(self,"_highlight_active",False))
            if bool(self._speech_cfg().get("enabled",True)) and self.speech_service.ready():
                QTimer.singleShot(hold_ms+120,self.refresh_speech_interaction)
            return

        if not self._speech_session_active:return
        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))
        if not ok:
            LOGGER.warning("语音播报失败: %s",message); self._end_speech_session(resume=True); return
        if tag=="wake_ack":
            if self._speech_pending_question:
                question=self._speech_pending_question; self._speech_pending_question=""; self._ask_voice_question(question)
            else:
                self._arm_speech_followup()
        elif tag=="dialogue_answer":
            self._arm_speech_followup()

    def _arm_speech_followup(self):
        """Resume listening for another turn and start a rolling inactivity timer."""
        if not self._speech_session_active:
            return
        self._speech_waiting_question=True
        self._speech_waiting_brain=False
        self._speech_state("listening","正在听你继续说")
        self.speech_service.resume()
        token=self._speech_session_token
        timeout=max(5000,int(self._speech_cfg().get("listen_timeout_ms",15000)))
        QTimer.singleShot(timeout,lambda t=token:self._speech_listen_timeout(t))

    def _speech_listen_timeout(self, token):
        if int(token)!=int(self._speech_session_token) or not self._speech_session_active or not self._speech_waiting_question:return
        self._end_speech_session(resume=True)

    def _speech_finish_if_token(self, token):
        if int(token)==int(self._speech_session_token) and self._speech_session_active:
            self._end_speech_session(resume=True)

    def _ask_voice_question(self, question):
        question=str(question or "").strip()
        if not question:return
        self._speech_waiting_brain=True; self._speech_state("thinking","小美丽正在想")
        setattr(self.brain_service,"_voice_session_request",True)
        brain=self.cfg.get("brain",{})
        self.brain_service.ask(question,brain.get("persona") or DEFAULT_PERSONA,float(brain.get("temperature",0.78)),int(brain.get("max_tokens",220)),int(brain.get("context_turns",6)),bool(brain.get("long_term_memory",True)))

    @staticmethod
    def _compact_speech_answer(text, limit=60):
        text=re.sub(r"\s+"," ",str(text or "").strip())
        if len(text)<=limit:return text
        parts=re.split(r"(?<=[。！？?!])",text); out=""
        for part in parts:
            if not part:continue
            if len(out)+len(part)>limit:break
            out+=part
        return out.strip() if out.strip() else text[:limit].rstrip("，,；; ")+"……"

    def _on_voice_brain_finished(self, ok, answer, message):
        if not self._speech_waiting_brain:return
        self._speech_waiting_brain=False
        # Keep marker through the rest of this signal dispatch, so the Settings
        # chat page does not start a second preview playback for the same answer.
        QTimer.singleShot(0,lambda:setattr(self.brain_service,"_voice_session_request",False))
        if not ok:
            LOGGER.warning("语音问题大脑回答失败: %s",message); self._end_speech_session(resume=True); return
        spoken=self._compact_speech_answer(str(answer.get("spoken_text") or "").strip())
        if not spoken:
            spoken="我没听明白，再说一次。"
        voice=self._speech_voice_cfg(); self._speech_state("speaking","正在生成小美丽语音")
        self.voice_service.speak(spoken,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="dialogue_answer",extra_instruct=self._speech_phrase_instruct(spoken))

    def _end_speech_session(self, resume=True):
        self._speech_session_token+=1; self._speech_session_active=False; self._speech_waiting_question=False; self._speech_waiting_brain=False; self._speech_pending_question=""
        setattr(self.brain_service,"_voice_session_request",False); self.pet.set_dialogue_indicator(False)
        if resume and bool(self._speech_cfg().get("enabled",True)) and self.speech_service.ready():
            self.speech_service.resume(); self._speech_state("listening","等待“美丽美丽”")
        else:
            self._speech_state("stopped","语音监听已停止")

    def on_vision_snapshot(self,data):
        if self.settings:
            self.settings.update_vision_snapshot(data)
        try:
            event_id=int(data.get("highlight_event_id",0) or 0)
            if event_id>0 and event_id!=int(self._highlight_seen_event_id):
                self._highlight_seen_event_id=event_id
                self._trigger_highlight_cta(data)
        except Exception:
            LOGGER.exception("[HIGHLIGHT] controller snapshot handling failed")

    def open_settings(self):
        if self.settings and self.settings.isVisible():
            # If the settings window is minimized, tray/hotkey/open requests should
            # restore it just like a normal Windows application.
            if self.settings.isMinimized():
                self.settings.showNormal()
            self.settings.raise_(); self.settings.activateWindow(); return
        self.settings=SettingsDialog(self.cfg,self.pet,self.vision,self.voice_service,self.brain_service,self.update_service,self.speech_service)
        self.settings.hotkeys_changed.connect(lambda:self.hotkeys.register(self.cfg))
        self.settings.config_changed.connect(self._on_settings_changed)
        self.settings.storage_migration_requested.connect(self.start_storage_migration)
        if self.vision.last_snapshot:
            self.settings.update_vision_snapshot(self.vision.last_snapshot)
        self.settings.show(); self.settings.raise_(); self.settings.activateWindow()

    def start_storage_migration(self, target):
        try:
            if not getattr(sys, "frozen", False):
                raise RuntimeError("开发模式不执行存储迁移，请在正式 XiaoMeili.exe 中操作。")
            helper = Path(resource("assets/storage_migrate.ps1"))
            if not helper.exists():
                raise FileNotFoundError(f"存储迁移助手缺失：{helper}")

            source = xiaomeili_logical_data_root()
            requested = Path(str(target or r"D:\XiaoMeiliData"))
            target = Path(r"D:\XiaoMeiliData")
            if os.path.normcase(str(requested)) != os.path.normcase(str(target)):
                raise RuntimeError("V0.10.0 只允许迁移到 D:\\XiaoMeiliData 安全目录。")
            migration_token = uuid.uuid4().hex[:10]
            desktop_log = STORAGE_DIAGNOSTIC_DIR / f"migration_{time.strftime('%Y%m%d_%H%M%S')}_{migration_token}.log"
            ready_file = Path(tempfile.gettempdir()) / f"XiaoMeili_storage_ready_{os.getpid()}_{migration_token}.txt"

            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(helper),
                "-Source", str(source),
                "-Target", str(target),
                "-ParentPid", str(os.getpid()),
                "-ExePath", str(Path(sys.executable)),
                "-DesktopLog", str(desktop_log),
                "-ReadyFile", str(ready_file),
            ]
            proc = subprocess.Popen(
                args,
                cwd=str(Path(sys.executable).parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )

            # V0.7.7.2: Windows Defender / PowerShell cold start can take longer than the
            # old 4-second window. Wait up to 20 seconds. We accept either the explicit
            # READY file or the helper's first log line as proof that the script parsed
            # and entered its protected try/catch path.
            ready = False
            for _ in range(200):
                if ready_file.exists():
                    ready = True
                    break

                rc = proc.poll()
                if rc is not None:
                    detail = ""
                    try:
                        if desktop_log.exists():
                            detail = desktop_log.read_text(
                                encoding="utf-8-sig", errors="replace"
                            )[-3000:]
                    except Exception:
                        pass
                    raise RuntimeError(f"存储迁移助手启动失败（exit={rc}）。{detail}")

                try:
                    if desktop_log.exists():
                        probe = desktop_log.read_text(
                            encoding="utf-8-sig", errors="replace"
                        )
                        if "D-drive migration helper started." in probe:
                            ready = True
                            break
                except Exception:
                    pass

                time.sleep(0.10)

            if not ready:
                try:
                    proc.terminate()
                except Exception:
                    pass
                detail = ""
                try:
                    if desktop_log.exists():
                        detail = desktop_log.read_text(
                            encoding="utf-8-sig", errors="replace"
                        )[-3000:]
                except Exception:
                    pass
                raise RuntimeError(
                    "存储迁移助手 20 秒内没有完成启动握手。"
                    "为保护现有数据，小美丽保持运行且没有开始迁移。"
                    + (f"\n\n迁移助手日志：\n{detail}" if detail else "")
                )

            LOGGER.info("D盘迁移助手握手成功：%s -> %s", source, target)
            self.quit()
        except Exception as exc:
            LOGGER.exception("启动 D 盘迁移失败")
            QMessageBox.critical(
                None,
                "小美丽存储迁移失败",
                f"没有改动现有数据。错误：{type(exc).__name__}: {exc}\n\n"
                f"迁移诊断会保存在：{STORAGE_DIAGNOSTIC_DIR}",
            )
            if self.settings:
                try:
                    self.settings.storage_migrate_btn.setEnabled(True)
                    self.settings._refresh_storage_status()
                except Exception:
                    pass

    def quit(self):
        try:
            self.cfg["x"],self.cfg["y"]=self.pet.x(),self.pet.y(); save_config(self.cfg)
            try: self.ability_sidebar.hide()
            except Exception: pass
            try: self.ability_node.hide()
            except Exception: pass
            self.pet.lock_bubble.hide(); self.hotkeys.unregister_all(); self.vision.stop(); self.vision.wait(1800)
            try: self.speech_service.shutdown()
            except Exception: pass
            try: self.voice_service.shutdown()
            except Exception: pass
            try: self.brain_service.shutdown()
            except Exception: pass
            LOGGER.info("正常退出")
        finally:
            self.app.quit()


def ensure_desktop_launcher():
    """Create a stable desktop XiaoMeili launcher without touching existing files."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        target = desktop_dir() / "小美丽.exe"
        if target.exists():
            return target

        candidates = [
            Path(sys.executable).resolve().parent / "XiaoMeiliLauncher.exe",
        ]
        local = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local:
            candidates.append(Path(local).absolute() / "XiaoMeiliApp" / "XiaoMeiliLauncher.exe")

        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            LOGGER.warning("稳定桌面启动器源文件不存在；跳过桌面入口创建")
            return None

        target.parent.mkdir(parents=True, exist_ok=True)
        # xb = create-new only.  This deliberately cannot overwrite an existing
        # Desktop file, matching XiaoMeili's no-delete/no-replace safety policy.
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        LOGGER.info("已创建稳定桌面启动器：%s -> active.json 当前版本", target)
        return target
    except FileExistsError:
        return desktop_dir() / "小美丽.exe"
    except Exception:
        LOGGER.warning("创建稳定桌面启动器失败（不影响小美丽运行）", exc_info=True)
        return None


def main():
    set_windows_app_identity()
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); app.setApplicationName(APP_NAME); app.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
    ensure_desktop_launcher()
    cfg=load_config()
    maybe_adopt_report_font(cfg)
    def excepthook(exc_type,exc,tb):
        LOGGER.critical("未捕获异常:\n%s",''.join(traceback.format_exception(exc_type,exc,tb)), exc_info=(exc_type,exc,tb))
        try: QMessageBox.critical(None,"小美丽发生异常",f"错误诊断已保存到：\n{DESKTOP_ERROR_LOG}\n\n{exc}")
        except Exception: pass
    sys.excepthook=excepthook
    if hasattr(threading, "excepthook"):
        def thread_excepthook(args):
            LOGGER.critical("后台线程未捕获异常：%s", args.thread.name if args.thread else "unknown", exc_info=(args.exc_type,args.exc_value,args.exc_traceback))
        threading.excepthook=thread_excepthook
    ctl=AppController(app,cfg)
    sys.exit(app.exec())


def runtime_self_test():
    # Qwen3-TTS is installed into an isolated external runtime on first use.
    # The frozen desktop app only verifies the lightweight bridge module.
    from voice_qwen import VoiceService
    from brain_qwen import BrainService
    from speech_input import SpeechInputService
    _ = VoiceService
    _ = BrainService
    _ = SpeechInputService
    return True


def settings_ui_self_test():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    cfg = load_config()
    pet = PetWindow(cfg)
    vision = VisionWorker(cfg)
    voice = VoiceService()
    brain = BrainService()
    speech = SpeechInputService()
    updater = UpdateService(cfg)
    dialog = SettingsDialog(cfg, pet, vision, voice, brain, updater, speech)
    try:
        expected = ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]
        if list(getattr(dialog, "v774_nav_names", [])) != expected:
            raise RuntimeError(f"V0.7.7.4 nav mismatch: {getattr(dialog, 'v774_nav_names', None)}")
        system_titles = [
            dialog.v774_system_tabs.tabText(i)
            for i in range(dialog.v774_system_tabs.count())
        ]
        for title in ("资源占用", "更新", "存储", "组件与下载", "游戏识别", "日志"):
            if title not in system_titles:
                raise RuntimeError(f"V0.8.8 system tab missing: {title}")
        for attr in ("v080_speech_value", "v080_wake_value", "v080_input_value", "v080_whiteboard_value", "speech_status", "speech_prepare_btn"):
            if not hasattr(dialog, attr):
                raise RuntimeError(f"V0.8.8 UI control missing: {attr}")
        if not Path(resource("assets/whiteboard_template_v080.mp4")).exists():
            raise RuntimeError("V0.8.8 bundled whiteboard video missing")
        test_pm = render_dialogue_text_pixmap(280, 298, normalized_whiteboard_layout(cfg.get("whiteboard", {})), "你又要保枪？", "Microsoft YaHei", 4)
        if test_pm.isNull():
            raise RuntimeError("V0.8.8 whiteboard text renderer failed")
        if dialog.windowTitle() != "小美丽 设置":
            raise RuntimeError(f"unexpected settings title: {dialog.windowTitle()}")

        # V0.10.0.2: vector glass sidebar + the user's keyed animated ability form.
        form_asset = Path(resource("assets/xiaomeili_ability_form_v01002.webp"))
        if not form_asset.exists() or form_asset.stat().st_size < 500_000:
            raise RuntimeError("V0.10.0.2 animated ability-form asset missing")
        if not getattr(pet, "_ability_form_movie", None) or not pet._ability_form_movie.isValid():
            raise RuntimeError("V0.10.0.2 ability-form movie failed to load")
        ability_probe = AbilitySidebar()
        try:
            if ability_probe.PANEL_W != 230 or ability_probe.PANEL_H != 320:
                raise RuntimeError("V0.10.0.2 panel geometry regressed")
            if ability_probe._sweep_timer.isActive():
                raise RuntimeError("V0.10.0.2 border sweep timer must be stopped while hidden")
            ability_probe.set_states({"beauty_insight": True})
            if not ability_probe.states().get("beauty_insight", False):
                raise RuntimeError("V0.10.0.2 ability switch state failed")
        finally:
            ability_probe.hide()
            ability_probe.deleteLater()
        if not hasattr(dialog, "v0100_ability_value"):
            raise RuntimeError("V0.10.0.2 美丽能力 settings entry missing")

        for legacy_title in ("快捷键", "大脑", "动画素材"):
            child, page, original_idx = dialog._v0775_build_legacy_dialog(
                legacy_title, f"UI smoke: {legacy_title}", (820, 580)
            )
            if child is None or page is None:
                raise RuntimeError(f"legacy page missing: {legacy_title}")
            try:
                child.show()
                page.show()
                app.processEvents()
                if not page.isVisible():
                    raise RuntimeError(f"legacy page stayed hidden after reparent: {legacy_title}")
                visible_controls = [
                    w for w in page.findChildren(QWidget)
                    if w.isVisible() and not isinstance(w, QLabel)
                ]
                if len(visible_controls) < 1:
                    raise RuntimeError(f"legacy page has no visible controls: {legacy_title}")
            finally:
                child.hide()
                dialog._v0775_restore_legacy_dialog(child, page, original_idx, legacy_title)

        dialog._v0775_apply_theme("dark", False)
        app.processEvents()
        if dialog._v0775_theme_mode != "dark":
            raise RuntimeError("dark theme did not apply")
        dialog._v0775_apply_theme("light", False)
        app.processEvents()

        # General page no longer exposes the retired controls.
        general = dialog.v774_stack.widget(0)
        texts = []
        widgets = []
        widgets.extend(general.findChildren(QLabel))
        widgets.extend(general.findChildren(QCheckBox))
        widgets.extend(general.findChildren(QPushButton))
        for w in widgets:
            try:
                texts.append(str(w.text() or ""))
            except Exception:
                pass
        joined = "\n".join(texts)
        for retired in ("点击穿透", "透明度", "桌宠位置"):
            if retired in joined:
                raise RuntimeError(f"retired General control is still visible: {retired}")

        if not isinstance(getattr(dialog, "v0776_avatar", None), EditableAvatar):
            raise RuntimeError("editable avatar widget missing")

        theme_buttons = list(getattr(dialog, "v0777_theme_buttons", []))
        if len(theme_buttons) != 6:
            raise RuntimeError(f"expected 6 in-layout theme buttons, got {len(theme_buttons)}")
        before_mode = dialog._v0775_theme_mode
        theme_buttons[0].click()
        app.processEvents()
        if dialog._v0775_theme_mode == before_mode:
            raise RuntimeError("theme button click did not switch mode")
        theme_buttons[0].click()
        app.processEvents()

        pet.set_interaction_lock(True)
        app.processEvents()
        if not bool(cfg.get("lock_position", False)) or not bool(cfg.get("click_through", False)):
            raise RuntimeError("game-safe lock did not enable click-through")
        if not pet.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            raise RuntimeError("locked pet is still accepting Qt mouse events")
        pet.set_interaction_lock(False)
        app.processEvents()
        if bool(cfg.get("lock_position", False)) or bool(cfg.get("click_through", False)):
            raise RuntimeError("unlock did not restore interactive state")

        # Long-term memory is file-light and does not require the model to be loaded.
        marker = f"CI memory {time.time_ns()}"
        mid = brain.add_memory(marker, "manual", "selftest")
        if not mid or marker not in [x.get("text") for x in brain.list_memories()]:
            raise RuntimeError("long-term memory add/list failed")
        brain.delete_memory(mid)

        rx1, ry1, rx2, ry2 = ROI_REPORT_CARDS
        if not (rx1 <= 0.03 and rx2 >= 0.95 and 0.49 <= ry1 <= 0.51 and 0.81 <= ry2 <= 0.83):
            raise RuntimeError(f"result-card ROI regressed: {ROI_REPORT_CARDS}")
        span = rx2 - rx1
        centers = [rx1 + span * ((i + 0.5) / 5.0) for i in range(5)]
        targets = [0.11, 0.30, 0.49, 0.68, 0.87]
        if any(abs(a - b) > 0.025 for a, b in zip(centers, targets)):
            raise RuntimeError(f"result-card slot centers misaligned: {centers}")

        dark_css = dialog._v0775_stylesheet(True)
        if "settingsScrollViewport" not in dark_css or "#1C3028" not in dark_css:
            raise RuntimeError("dark theme scroll/card palette regression")

        # V0.7.7.9 deletion regression + group lifecycle.
        probe_q = "__V0779_DELETE_RESURRECTION_PROBE__"
        brain.save_feedback("down", probe_q, "old", "new", "fixed")
        probe = next(
            (r for r in brain.list_rules() if str(r.get("user_text") or "") == probe_q),
            None,
        )
        if not probe:
            raise RuntimeError("v0779 probe rule was not created")
        probe_id = str(probe.get("id") or "")

        group, err = brain.create_rule_group("__V0779_TEST_GROUP__")
        if group is None:
            # A previous interrupted local smoke run may have left the group.
            group = next(
                (g for g in brain.list_rule_groups() if str(g.get("name") or "") == "__V0779_TEST_GROUP__"),
                None,
            )
        if group is None:
            raise RuntimeError(f"v0779 group create failed: {err}")
        gid = str(group.get("id") or "")
        if not brain.move_rule_to_group(probe_id, gid):
            raise RuntimeError("v0779 group move failed")
        moved = brain.get_rule(probe_id)
        if not moved or str(moved.get("group_id") or "") != gid:
            raise RuntimeError("v0779 group assignment did not persist")
        ok, err = brain.rename_rule_group(gid, "__V0779_TEST_GROUP_RENAMED__")
        if not ok:
            raise RuntimeError(f"v0779 group rename failed: {err}")
        if not brain.delete_rule_group(gid):
            raise RuntimeError("v0779 group delete failed")
        moved = brain.get_rule(probe_id)
        if not moved or str(moved.get("group_id") or "") != "":
            raise RuntimeError("v0779 group delete did not return rules to ungrouped")

        if not brain.delete_rule(probe_id):
            raise RuntimeError("v0779 rule delete failed")
        # Critical call: list_rules invokes feedback sync. The deleted lesson
        # must remain absent instead of being rebuilt from feedback.jsonl.
        if any(str(r.get("id") or "") == probe_id for r in brain.list_rules()):
            raise RuntimeError("v0779 deleted rule resurrected after feedback sync")
        if brain.get_rule(probe_id) is not None:
            raise RuntimeError("v0779 deleted rule is still addressable")

        # Voice list sync must work while the settings dialog is not visible,
        # which is the exact regression that left the user's selector greyed out.
        dialog.hide()
        dialog._voice_list_ready(["design_xiaomeili_cool"])
        app.processEvents()
        if dialog.voice_combo.count() != 1:
            raise RuntimeError("voice selector ignored hidden-dialog voice list")
        if str(dialog.voice_combo.currentData() or "") != "design_xiaomeili_cool":
            raise RuntimeError("recommended cool voice did not populate selector")
        if not dialog.voice_combo.isEnabled():
            raise RuntimeError("voice selector remained disabled after voice list sync")

        if voice.display_name("design_xiaomeili_cool") != "小美丽｜战斗贤者（推荐）":
            raise RuntimeError("battle-sage XiaoMeili voice preset missing")
        humanized = voice._humanize_spoken_text("你今天还行但是别得意")
        if "，但是" not in humanized:
            raise RuntimeError(f"human pause text transform failed: {humanized}")

        # V0.7.7.11 startup notice must be fully retired.
        source_text = Path(__file__).read_text(encoding="utf-8")
        retired_title = "设置中心" + "焕新完成"
        if retired_title in source_text:
            raise RuntimeError("retired settings-center startup popup text returned")
        retired_timer = "QTimer.singleShot(350, " + "self._v774_first_run_notice)"
        if retired_timer in source_text:
            raise RuntimeError("retired settings-center startup popup timer returned")

        return True
    finally:
        try:
            dialog.close()
        except Exception:
            pass
        try:
            speech.shutdown()
        except Exception:
            pass
        try:
            brain.shutdown()
        except Exception:
            pass
        try:
            voice.shutdown()
        except Exception:
            pass


if __name__=="__main__":
    if "--settings-ui-self-test" in sys.argv:
        try:
            settings_ui_self_test()
            raise SystemExit(0)
        except Exception:
            LOGGER.exception("V0.7.7.4 设置中心自检失败")
            raise SystemExit(8)
    if "--runtime-self-test" in sys.argv:
        try:
            runtime_self_test()
            raise SystemExit(0)
        except Exception:
            LOGGER.exception("冻结版运行时自检失败")
            raise SystemExit(7)
    main()
