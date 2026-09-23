# -*- coding: utf-8 -*-
"""Qwen3-TTS backend for XiaoMeili V0.7.3.

Keeps the stable 1.7B CustomVoice backend and adds an optional 1.7B VoiceDesign
"little girl" expansion. The VoiceDesign model is only downloaded if the user
chooses to install the expansion.
"""
from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOGGER = logging.getLogger("XiaoMeili")


def _data_root() -> Path:
    if sys.platform == "win32":
        root = Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    else:
        root = Path.home() / ".xiaomeili"
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_ROOT = _data_root()
RUNTIME_ROOT = DATA_ROOT / "voice_runtime" / "qwen3_tts"
VENV_DIR = RUNTIME_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
CUSTOM_MODEL_DIR = DATA_ROOT / "voice" / "qwen3_tts_1_7b_customvoice"
DESIGN_MODEL_DIR = DATA_ROOT / "voice" / "qwen3_tts_1_7b_voicedesign"
CUSTOM_MARKER = CUSTOM_MODEL_DIR / ".xiaomeili_model_ready_v062"
DESIGN_MARKER = DESIGN_MODEL_DIR / ".xiaomeili_model_ready_v073"
RUNTIME_MARKER = RUNTIME_ROOT / ".xiaomeili_runtime_ready_v062"
WORKER_SCRIPT = RUNTIME_ROOT / "qwen_worker.py"
WORKER_LOG = DATA_ROOT / "logs" / "qwen3_tts_worker.log"
SETUP_LOG = DATA_ROOT / "logs" / "qwen3_tts_setup.log"
CACHE_DIR = DATA_ROOT / "voice_cache"

CUSTOM_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DESIGN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"

# Existing presets are official speaker identities. Vivian and Serena are the
# two native-Chinese female speaker IDs in CustomVoice.
PRESETS = {
    "vivian_natural": {
        "name": "Vivian｜清亮自然少女",
        "kind": "custom",
        "speaker": "Vivian",
        "instruct": "用标准普通话，自然清亮的年轻女声说话。像真实日常聊天，咬字准确，语气灵动但克制。不要播音腔。",
    },
    "vivian_cool": {
        "name": "Vivian｜清冷小美丽",
        "kind": "custom",
        "speaker": "Vivian",
        "instruct": "用标准普通话，以年轻清冷、自信、略带一点傲娇感的女声说话。咬字自然准确，像真实聊天，不要播音腔。",
    },
    "serena_soft": {
        "name": "Serena｜温柔少女",
        "kind": "custom",
        "speaker": "Serena",
        "instruct": "用标准普通话，以温柔自然的年轻女声说话。声音柔和但不要气声过重，像真实聊天，咬字准确，不要播音腔。",
    },
    "serena_lively": {
        "name": "Serena｜活泼少女",
        "kind": "custom",
        "speaker": "Serena",
        "instruct": "用标准普通话，以活泼自然的年轻女声说话。语气轻快、略有俏皮感，但保持真实口语和准确咬字。",
    },

    # Optional VoiceDesign presets. These are genuinely generated from different
    # voice descriptions, rather than being style labels on Vivian/Serena.
    "design_mint": {
        "name": "小薄荷｜稚嫩清甜小女孩（扩展）",
        "kind": "design",
        "seed": 73125,
        "instruct": "中国普通话小女孩声音，稚嫩清甜，年龄感偏小，音调自然偏高，声音轻盈清澈，像真实小女孩日常说话。不要播音腔，不要成人女声，不要夸张夹子音，不要外国口音。",
    },
    "design_bean": {
        "name": "小豆包｜软萌自然小女孩（扩展）",
        "kind": "design",
        "seed": 18403,
        "instruct": "中国普通话小女孩声音，软萌但自然，童声感明显，声音柔软明亮，日常聊天口吻，咬字清楚。不要成人成熟感，不要故意撒娇，不要播音腔，不要外国口音。",
    },
    "design_spark": {
        "name": "小星星｜活泼灵动小女孩（扩展）",
        "kind": "design",
        "seed": 92541,
        "instruct": "中国普通话活泼小女孩声音，灵动轻快，童声感明显，音调自然偏高，带一点俏皮和元气，但不要过度卖萌。不要成人女声，不要播音腔，不要外国口音。",
    },
    "design_ice": {
        "name": "小冰块｜清冷聪明小女孩（扩展）",
        "kind": "design",
        "seed": 40617,
        "instruct": "中国普通话小女孩声音，清冷、聪明、安静，年龄感偏小，音色清澈偏高但自然，像有点嘴硬的小女孩。不要成人成熟感，不要播音腔，不要外国口音。",
    },
}


WORKER_CODE = r"""# -*- coding: utf-8 -*-
import argparse
import gc
import json
import logging
import socket
from pathlib import Path

def setup_log(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=path, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s [%(levelname)s] %(message)s")

def download_model(model_id, model_dir):
    model_dir = str(Path(model_dir))
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download
        logging.info("Downloading %s with ModelScope", model_id)
        snapshot_download(model_id, local_dir=model_dir)
        return
    except Exception:
        logging.exception("ModelScope failed for %s, fallback to Hugging Face", model_id)
    from huggingface_hub import snapshot_download
    snapshot_download(model_id, local_dir=model_dir)

def load_model(model_dir):
    import torch
    from qwen_tts import Qwen3TTSModel
    if torch.cuda.is_available():
        return Qwen3TTSModel.from_pretrained(
            str(model_dir), device_map="cuda:0", dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
    return Qwen3TTSModel.from_pretrained(
        str(model_dir), device_map="cpu", dtype=torch.float32,
        attn_implementation="sdpa",
    )

def recv_json(conn):
    data = b""
    while b"\n" not in data:
        part = conn.recv(65536)
        if not part:
            break
        data += part
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8"))

def send_json(conn, obj):
    conn.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

def serve(port, custom_model_dir, design_model_dir):
    import soundfile as sf
    import torch

    model = None
    active_kind = None

    def ensure(kind):
        nonlocal model, active_kind
        if model is not None and active_kind == kind:
            return model
        if model is not None:
            try:
                del model
            except Exception:
                pass
            model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        model_dir = custom_model_dir if kind == "custom" else design_model_dir
        logging.info("Loading TTS kind=%s from %s", kind, model_dir)
        model = load_model(model_dir)
        active_kind = kind
        return model

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", int(port)))
    server.listen(4)
    logging.info("Worker ready on port %s", port)

    while True:
        conn, _ = server.accept()
        with conn:
            try:
                req = recv_json(conn)
                cmd = req.get("cmd")
                if cmd == "ping":
                    send_json(conn, {"ok": True, "cuda": bool(torch.cuda.is_available()), "active_kind": active_kind})
                    continue
                if cmd == "shutdown":
                    send_json(conn, {"ok": True})
                    break
                if cmd != "synthesize":
                    raise ValueError("unknown command")

                text = str(req.get("text") or "").strip()
                out = str(req.get("output") or "").strip()
                kind = str(req.get("kind") or "custom").strip().lower()
                if kind not in ("custom", "design"):
                    kind = "custom"
                if not text or not out:
                    raise ValueError("missing text/output")

                tts = ensure(kind)
                if kind == "design":
                    seed = int(req.get("seed") or 0)
                    torch.manual_seed(seed)
                    if torch.cuda.is_available():
                        torch.cuda.manual_seed_all(seed)
                    wavs, sr = tts.generate_voice_design(
                        text=text,
                        language="Chinese",
                        instruct=str(req.get("instruct") or ""),
                    )
                else:
                    torch.manual_seed(20260923)
                    if torch.cuda.is_available():
                        torch.cuda.manual_seed_all(20260923)
                    wavs, sr = tts.generate_custom_voice(
                        text=text,
                        language="Chinese",
                        speaker=str(req.get("speaker") or "Vivian"),
                        instruct=str(req.get("instruct") or ""),
                    )

                Path(out).parent.mkdir(parents=True, exist_ok=True)
                sf.write(out, wavs[0], sr)
                send_json(conn, {"ok": True, "output": out, "sample_rate": int(sr)})
            except Exception as exc:
                logging.exception("request failed")
                send_json(conn, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    server.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--custom-model-dir", default="")
    ap.add_argument("--design-model-dir", default="")
    ap.add_argument("--download-custom", action="store_true")
    ap.add_argument("--download-design", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    setup_log(args.log)

    if args.self_test:
        import torch, qwen_tts
        print(json.dumps({"ok": True, "cuda": bool(torch.cuda.is_available()), "torch": torch.__version__}))
        return 0
    if args.download_custom:
        download_model("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", args.custom_model_dir)
        return 0
    if args.download_design:
        download_model("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", args.design_model_dir)
        return 0
    if args.serve:
        serve(args.port, args.custom_model_dir, args.design_model_dir)
        return 0
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
"""


class VoiceService(QObject):
    download_progress = Signal(int, str)
    download_finished = Signal(bool, str)
    voices_ready = Signal(list)
    synthesis_started = Signal()
    synthesis_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_busy = False
        self._synth_busy = False
        self._worker = None
        self._worker_port = None
        self._worker_log_handle = None
        self._lock = threading.RLock()
        for p in (RUNTIME_ROOT, CUSTOM_MODEL_DIR, DESIGN_MODEL_DIR, CACHE_DIR, WORKER_LOG.parent):
            p.mkdir(parents=True, exist_ok=True)
        self._write_worker()

    def _write_worker(self):
        current = ""
        try:
            if WORKER_SCRIPT.exists():
                current = WORKER_SCRIPT.read_text(encoding="utf-8")
        except Exception:
            pass
        if current != WORKER_CODE:
            WORKER_SCRIPT.write_text(WORKER_CODE, encoding="utf-8")

    def _runtime_ready(self):
        return VENV_PYTHON.exists() and RUNTIME_MARKER.exists()

    @staticmethod
    def _dir_size(path):
        try:
            return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
        except Exception:
            return 0

    def _custom_ready(self):
        return CUSTOM_MARKER.exists() and self._dir_size(CUSTOM_MODEL_DIR) > 2_500_000_000

    def design_ready(self):
        return DESIGN_MARKER.exists() and self._dir_size(DESIGN_MODEL_DIR) > 2_500_000_000

    def ready(self):
        return self._runtime_ready() and self._custom_ready()

    def component_status(self):
        if self.ready():
            extra = "；小女孩声线扩展已安装" if self.design_ready() else "；可选安装小女孩声线扩展"
            return "Qwen3-TTS 1.7B 中文语音已就绪（本地离线）" + extra
        if self._runtime_ready():
            return "Qwen3-TTS 运行环境已就绪，等待中文语音模型"
        return "首次使用需准备 Qwen3-TTS 中文语音环境与模型"

    def display_name(self, voice_id):
        return PRESETS.get(str(voice_id), {}).get("name", str(voice_id))

    @staticmethod
    def _bootstrap_python():
        public = Path(os.getenv("PUBLIC") or r"C:\Users\Public")
        local = Path(os.getenv("LOCALAPPDATA") or "")
        candidates = [
            (public / "XiaoMeili" / "app" / ".venv" / "Scripts" / "python.exe", []),
            (local / "Programs" / "Python" / "Python312" / "python.exe", []),
            (local / "Programs" / "Python" / "Python311" / "python.exe", []),
        ]
        py = shutil.which("py.exe") or shutil.which("py")
        if py:
            candidates.extend([(Path(py), ["-3.12"]), (Path(py), ["-3.11"])])
        python = shutil.which("python.exe") or shutil.which("python")
        if python:
            candidates.append((Path(python), []))
        for exe, prefix in candidates:
            if not exe or not exe.exists():
                continue
            try:
                rc = subprocess.run(
                    [str(exe), *prefix, "-c", "import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 1)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                ).returncode
                if rc == 0:
                    return str(exe), prefix
            except Exception:
                pass
        raise RuntimeError("未找到可用的 Python 3.10+。")

    @staticmethod
    def _run(args, timeout):
        SETUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(SETUP_LOG, "a", encoding="utf-8") as log:
            log.write("\n$ " + " ".join(map(str, args)) + "\n")
            log.flush()
            proc = subprocess.run(args, stdout=log, stderr=log, timeout=timeout, creationflags=flags)
        if proc.returncode != 0:
            raise RuntimeError(f"命令执行失败（exit={proc.returncode}），详情见 {SETUP_LOG}")

    def _prepare_runtime(self):
        self._write_worker()
        if not VENV_PYTHON.exists():
            self.download_progress.emit(3, "正在创建独立语音运行环境…")
            exe, prefix = self._bootstrap_python()
            self._run([exe, *prefix, "-m", "venv", str(VENV_DIR)], 240)
        self.download_progress.emit(7, "正在检查语音运行环境…")
        self._run([str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], 300)
        self.download_progress.emit(10, "正在检查 NVIDIA GPU 语音运行库…")
        self._run([
            str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
            "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu128",
        ], 1800)
        self.download_progress.emit(18, "正在检查 Qwen3-TTS 官方运行库…")
        self._run([
            str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
            "qwen-tts", "modelscope>=1.29,<2", "huggingface_hub>=0.34,<2",
        ], 1500)
        check = subprocess.run(
            [str(VENV_PYTHON), str(WORKER_SCRIPT), "--self-test", "--custom-model-dir", str(CUSTOM_MODEL_DIR),
             "--design-model-dir", str(DESIGN_MODEL_DIR), "--log", str(WORKER_LOG)],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if check.returncode != 0:
            raise RuntimeError("Qwen3-TTS 运行环境自检失败，请上传桌面错误日志。")
        try:
            info = json.loads((check.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            info = {}
        if not info.get("cuda"):
            raise RuntimeError("没有检测到 NVIDIA CUDA。")
        RUNTIME_MARKER.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

    def _download_model(self, kind):
        if kind == "design":
            target = DESIGN_MODEL_DIR
            marker = DESIGN_MARKER
            flag = "--download-design"
            label = "Qwen3-TTS 小女孩声线扩展"
        else:
            target = CUSTOM_MODEL_DIR
            marker = CUSTOM_MARKER
            flag = "--download-custom"
            label = "Qwen3-TTS 中文基础声线"

        ready = self.design_ready() if kind == "design" else self._custom_ready()
        if ready:
            self.download_progress.emit(99, f"{label} 已存在，跳过下载")
            return

        self.download_progress.emit(25, f"正在下载 {label}（约 4.5 GB）…")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(SETUP_LOG, "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(VENV_PYTHON), str(WORKER_SCRIPT), flag,
                 "--custom-model-dir", str(CUSTOM_MODEL_DIR),
                 "--design-model-dir", str(DESIGN_MODEL_DIR),
                 "--log", str(WORKER_LOG)],
                stdout=log, stderr=log, creationflags=flags,
            )
        while proc.poll() is None:
            size = self._dir_size(target)
            pct = min(97, 25 + int(min(1.0, size / 4_500_000_000) * 72))
            self.download_progress.emit(pct, f"正在下载 {label}… 已写入约 {size/1024/1024/1024:.2f} GB")
            time.sleep(1)
        if proc.returncode != 0:
            raise RuntimeError(f"{label} 下载失败（exit={proc.returncode}），详情见 {SETUP_LOG}")
        marker.write_text("0.7.3", encoding="utf-8")
        ready = self.design_ready() if kind == "design" else self._custom_ready()
        if not ready:
            raise RuntimeError(f"{label} 下载完成，但本地校验未通过。")

    def _start_download_kind(self, kind):
        if kind == "design" and self.design_ready():
            self.download_progress.emit(100, "小女孩声线扩展已就绪")
            self.download_finished.emit(True, "小女孩声线扩展已就绪，无需重复下载。")
            self.load_voices_async()
            return
        if kind == "custom" and self.ready():
            self.download_progress.emit(100, "Qwen3-TTS 已就绪")
            self.download_finished.emit(True, "Qwen3-TTS 已就绪，无需重复下载。")
            self.load_voices_async()
            return
        if self._setup_busy:
            return
        self._setup_busy = True

        def job():
            ok = False
            try:
                self.shutdown()
                self._prepare_runtime()
                self._download_model(kind)
                ok = True
                self.download_progress.emit(100, "语音组件准备完成")
                msg = "小女孩声线扩展准备完成。" if kind == "design" else "Qwen3-TTS 中文语音准备完成。"
            except Exception as exc:
                LOGGER.exception("Qwen3-TTS 准备失败")
                msg = f"语音组件准备失败：{type(exc).__name__}: {exc}"
            finally:
                self._setup_busy = False
                self.download_finished.emit(ok, msg)
                if ok:
                    self.load_voices_async()

        threading.Thread(target=job, name=f"XiaoMeiliQwenSetup_{kind}", daemon=True).start()

    def start_download(self):
        self._start_download_kind("custom")

    def start_design_download(self):
        self._start_download_kind("design")

    def load_voices_async(self):
        voices = []
        if self.ready():
            voices.extend([k for k,v in PRESETS.items() if v.get("kind") == "custom"])
        if self.design_ready():
            voices.extend([k for k,v in PRESETS.items() if v.get("kind") == "design"])
        self.voices_ready.emit(voices)

    @staticmethod
    def _free_port():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def _worker_alive(self):
        return self._worker is not None and self._worker.poll() is None and self._worker_port is not None

    def _request(self, payload, timeout=300):
        if not self._worker_port:
            raise RuntimeError("语音工作进程未启动")
        with socket.create_connection(("127.0.0.1", self._worker_port), timeout=8) as conn:
            conn.settimeout(timeout)
            conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            data = b""
            while b"\n" not in data:
                part = conn.recv(65536)
                if not part:
                    break
                data += part
        return json.loads(data.split(b"\n", 1)[0].decode("utf-8"))

    def _start_worker(self):
        with self._lock:
            if self._worker_alive():
                try:
                    if self._request({"cmd": "ping"}, 5).get("ok"):
                        return
                except Exception:
                    self.shutdown()
            port = self._free_port()
            self._worker_log_handle = open(WORKER_LOG, "a", encoding="utf-8")
            self._worker = subprocess.Popen(
                [str(VENV_PYTHON), str(WORKER_SCRIPT), "--serve", "--port", str(port),
                 "--custom-model-dir", str(CUSTOM_MODEL_DIR),
                 "--design-model-dir", str(DESIGN_MODEL_DIR),
                 "--log", str(WORKER_LOG)],
                stdout=self._worker_log_handle, stderr=self._worker_log_handle,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._worker_port = port
            deadline = time.time() + 80
            last = None
            while time.time() < deadline:
                if self._worker.poll() is not None:
                    raise RuntimeError(f"Qwen3-TTS 工作进程启动失败（exit={self._worker.returncode}）")
                try:
                    if self._request({"cmd": "ping"}, 3).get("ok"):
                        return
                except Exception as exc:
                    last = exc
                time.sleep(0.4)
            raise RuntimeError(f"Qwen3-TTS 工作进程启动超时：{last}")

    def output_devices(self):
        items = [("default", "系统默认播放设备")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            seen = set()
            for idx, dev in enumerate(devices):
                try:
                    if int(dev.get("max_output_channels", 0)) <= 0:
                        continue
                    name = str(dev.get("name", f"设备 {idx}"))
                    host_idx = int(dev.get("hostapi", -1))
                    host_name = str(hostapis[host_idx].get("name", "")) if 0 <= host_idx < len(hostapis) else ""
                    key = f"{idx}|{host_idx}|{name}"
                    label = f"{name} · {host_name}" if host_name else name
                    if label in seen:
                        label = f"{label} · #{idx}"
                    seen.add(label)
                    items.append((key, label))
                except Exception:
                    continue
        except Exception:
            LOGGER.exception("读取 Windows 播放设备失败")
        return items

    @staticmethod
    def _device_index(device_key):
        if str(device_key or "default") == "default":
            return None
        try:
            return int(str(device_key).split("|", 1)[0])
        except Exception:
            return None

    @staticmethod
    def _play_wav(path, device_key="default"):
        import soundfile as sf
        import sounddevice as sd
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
        sd.stop()
        sd.play(data, int(sample_rate), device=VoiceService._device_index(device_key), blocking=False)

    @staticmethod
    def _speed_instruction(speed):
        try:
            speed = float(speed)
        except Exception:
            speed = 1.0
        if speed < 0.9:
            return "语速稍微慢一点。"
        if speed > 1.1:
            return "语速稍微快一点，但保持清楚。"
        return "使用自然正常语速。"

    def preview(self, text, voice_id, speed=1.0, output_device="default"):
        text = str(text or "").strip()
        voice_id = str(voice_id or "").strip()
        preset = PRESETS.get(voice_id)
        if not text:
            self.synthesis_finished.emit(False, "请输入试听文字。")
            return
        if not preset:
            self.synthesis_finished.emit(False, "请先选择一个声线。")
            return
        if not self.ready():
            self.synthesis_finished.emit(False, "请先准备 Qwen3-TTS 语音组件。")
            return
        if preset.get("kind") == "design" and not self.design_ready():
            self.synthesis_finished.emit(False, "这是一条小女孩扩展声线，请先安装“小女孩声线扩展”。")
            return
        if self._synth_busy:
            self.synthesis_finished.emit(False, "上一条语音还在生成，请稍等。")
            return
        self._synth_busy = True
        self.synthesis_started.emit()

        def job():
            ok = False
            try:
                self._start_worker()
                out = CACHE_DIR / "xiaomeili_qwen3_preview.wav"
                req = {
                    "cmd": "synthesize",
                    "kind": preset.get("kind", "custom"),
                    "text": text,
                    "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed),
                    "output": str(out),
                }
                if preset.get("kind") == "design":
                    req["seed"] = int(preset.get("seed") or 0)
                else:
                    req["speaker"] = str(preset.get("speaker") or "Vivian")
                resp = self._request(req, 360)
                if not resp.get("ok"):
                    raise RuntimeError(resp.get("error") or "Qwen3-TTS 合成失败")
                self._play_wav(out, output_device)
                ok = True
                msg = f"已播放：{preset['name']}"
            except Exception as exc:
                LOGGER.exception("Qwen3-TTS 试听失败")
                msg = f"试听失败：{type(exc).__name__}: {exc}"
            finally:
                self._synth_busy = False
                self.synthesis_finished.emit(ok, msg)

        threading.Thread(target=job, name="XiaoMeiliQwenPreview", daemon=True).start()

    def shutdown(self):
        with self._lock:
            try:
                if self._worker_alive():
                    try:
                        self._request({"cmd": "shutdown"}, 3)
                    except Exception:
                        pass
                    try:
                        self._worker.wait(timeout=5)
                    except Exception:
                        self._worker.terminate()
            except Exception:
                pass
            self._worker = None
            self._worker_port = None
            try:
                if self._worker_log_handle:
                    self._worker_log_handle.close()
            except Exception:
                pass
            self._worker_log_handle = None
