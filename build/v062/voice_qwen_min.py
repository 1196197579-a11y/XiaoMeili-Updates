# -*- coding: utf-8 -*-
"""Qwen3-TTS backend for XiaoMeili V0.6.2."""
from __future__ import annotations

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
MODEL_DIR = DATA_ROOT / "voice" / "qwen3_tts_1_7b_customvoice"
MODEL_MARKER = MODEL_DIR / ".xiaomeili_model_ready_v062"
RUNTIME_MARKER = RUNTIME_ROOT / ".xiaomeili_runtime_ready_v062"
WORKER_SCRIPT = RUNTIME_ROOT / "qwen_worker.py"
WORKER_LOG = DATA_ROOT / "logs" / "qwen3_tts_worker.log"
SETUP_LOG = DATA_ROOT / "logs" / "qwen3_tts_setup.log"
CACHE_DIR = DATA_ROOT / "voice_cache"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

PRESETS = {
    "vivian_natural": {
        "name": "Vivian｜清亮自然少女",
        "speaker": "Vivian",
        "instruct": "用标准普通话，自然清亮的年轻女声说话。像真实日常聊天，咬字准确，语气灵动但克制。不要播音腔，不要夸张卖萌。",
    },
    "vivian_cool": {
        "name": "Vivian｜清冷小美丽",
        "speaker": "Vivian",
        "instruct": "用标准普通话，以年轻清冷、自信、略带一点傲娇感的女声说话。咬字自然准确，像真实聊天，不要播音腔，不要夸张表演。",
    },
    "serena_soft": {
        "name": "Serena｜温柔少女",
        "speaker": "Serena",
        "instruct": "用标准普通话，以温柔自然的年轻女声说话。声音柔和但不要气声过重，像真实聊天，咬字准确，不要播音腔。",
    },
    "serena_lively": {
        "name": "Serena｜活泼少女",
        "speaker": "Serena",
        "instruct": "用标准普通话，以活泼自然的年轻女声说话。语气轻快、略有俏皮感，但保持真实口语和准确咬字，不要夸张卖萌。",
    },
}


WORKER_CODE = r"""# -*- coding: utf-8 -*-
import argparse
import json
import logging
import socket
from pathlib import Path

def setup_log(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        encoding="utf-8",
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

def download_model(model_dir):
    model_dir = str(Path(model_dir))
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download
        logging.info("Downloading with ModelScope")
        snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", local_dir=model_dir)
        return
    except Exception:
        logging.exception("ModelScope failed, fallback to Hugging Face")
    from huggingface_hub import snapshot_download
    snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", local_dir=model_dir)

def load_model(model_dir):
    import torch
    from qwen_tts import Qwen3TTSModel
    if torch.cuda.is_available():
        return Qwen3TTSModel.from_pretrained(
            str(model_dir),
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
    return Qwen3TTSModel.from_pretrained(
        str(model_dir),
        device_map="cpu",
        dtype=torch.float32,
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

def serve(port, model_dir):
    import soundfile as sf
    model = None
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
                    import torch
                    send_json(conn, {"ok": True, "cuda": bool(torch.cuda.is_available())})
                    continue
                if cmd == "shutdown":
                    send_json(conn, {"ok": True})
                    break
                if cmd != "synthesize":
                    raise ValueError("unknown command")
                if model is None:
                    model = load_model(model_dir)
                text = str(req.get("text") or "").strip()
                out = str(req.get("output") or "").strip()
                if not text or not out:
                    raise ValueError("missing text/output")
                wavs, sr = model.generate_custom_voice(
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
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    setup_log(args.log)
    if args.self_test:
        import torch
        import qwen_tts
        print(json.dumps({"ok": True, "cuda": bool(torch.cuda.is_available()), "torch": torch.__version__}))
        return 0
    if args.download:
        download_model(args.model_dir)
        return 0
    if args.serve:
        serve(args.port, args.model_dir)
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
        for p in (RUNTIME_ROOT, MODEL_DIR, CACHE_DIR, WORKER_LOG.parent):
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

    def _model_ready(self):
        if not MODEL_MARKER.exists():
            return False
        try:
            size = sum(p.stat().st_size for p in MODEL_DIR.rglob("*") if p.is_file())
            return size > 2_500_000_000
        except Exception:
            return False

    def ready(self):
        return self._runtime_ready() and self._model_ready()

    def component_status(self):
        if self.ready():
            return "Qwen3-TTS 1.7B 中文语音已就绪（本地离线）"
        if self._runtime_ready():
            return "Qwen3-TTS 运行环境已就绪，等待首次下载中文语音模型"
        return "首次使用需准备 Qwen3-TTS 中文语音环境与模型（约 7–9 GB，仅一次）"

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
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                ).returncode
                if rc == 0:
                    return str(exe), prefix
            except Exception:
                pass
        raise RuntimeError("未找到可用的 Python 3.10+。请保留小美丽安装时创建的 Python 环境。")

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
        self.download_progress.emit(7, "正在更新语音运行环境…")
        self._run([str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], 300)
        self.download_progress.emit(10, "正在安装 RTX 4070 Ti GPU 语音运行库…")
        self._run([
            str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
            "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu128",
        ], 1800)
        self.download_progress.emit(18, "正在安装 Qwen3-TTS 官方运行库…")
        self._run([
            str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
            "qwen-tts", "modelscope>=1.29,<2", "huggingface_hub>=0.34,<2",
        ], 1500)
        check = subprocess.run(
            [str(VENV_PYTHON), str(WORKER_SCRIPT), "--self-test", "--model-dir", str(MODEL_DIR), "--log", str(WORKER_LOG)],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if check.returncode != 0:
            raise RuntimeError("Qwen3-TTS 运行环境自检失败，请上传桌面错误日志。")
        try:
            info = json.loads((check.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            info = {}
        if not info.get("cuda"):
            raise RuntimeError("没有检测到 NVIDIA CUDA。你的 RTX 4070 Ti 应支持，请上传桌面错误日志。")
        RUNTIME_MARKER.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

    def _download_model(self):
        if self._model_ready():
            self.download_progress.emit(99, "Qwen3-TTS 模型已存在，跳过下载")
            return
        self.download_progress.emit(25, "正在下载 Qwen3-TTS 1.7B 中文模型（约 4.5 GB）…")
        SETUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(SETUP_LOG, "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(VENV_PYTHON), str(WORKER_SCRIPT), "--download", "--model-dir", str(MODEL_DIR), "--log", str(WORKER_LOG)],
                stdout=log,
                stderr=log,
                creationflags=flags,
            )
        while proc.poll() is None:
            try:
                size = sum(p.stat().st_size for p in MODEL_DIR.rglob("*") if p.is_file())
            except Exception:
                size = 0
            pct = min(97, 25 + int(min(1.0, size / 4_500_000_000) * 72))
            self.download_progress.emit(pct, f"正在下载 Qwen3-TTS… 已写入约 {size/1024/1024/1024:.2f} GB")
            time.sleep(1)
        if proc.returncode != 0:
            raise RuntimeError(f"Qwen3-TTS 模型下载失败（exit={proc.returncode}），详情见 {SETUP_LOG}")
        MODEL_MARKER.write_text("0.6.2", encoding="utf-8")
        if not self._model_ready():
            raise RuntimeError("Qwen3-TTS 模型下载完成，但本地文件校验未通过。")

    def start_download(self):
        if self.ready():
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
                self._prepare_runtime()
                self._download_model()
                ok = True
                self.download_progress.emit(100, "Qwen3-TTS 中文语音已就绪")
                msg = "Qwen3-TTS 1.7B 中文语音准备完成，以后可离线使用。"
            except Exception as exc:
                LOGGER.exception("Qwen3-TTS 准备失败")
                msg = f"语音组件准备失败：{type(exc).__name__}: {exc}"
            finally:
                self._setup_busy = False
                self.download_finished.emit(ok, msg)
                if ok:
                    self.load_voices_async()

        threading.Thread(target=job, name="XiaoMeiliQwenSetup", daemon=True).start()

    def load_voices_async(self):
        self.voices_ready.emit(list(PRESETS.keys()) if self.ready() else [])

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
                [str(VENV_PYTHON), str(WORKER_SCRIPT), "--serve", "--port", str(port), "--model-dir", str(MODEL_DIR), "--log", str(WORKER_LOG)],
                stdout=self._worker_log_handle,
                stderr=self._worker_log_handle,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._worker_port = port
            deadline = time.time() + 60
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

    def preview(self, text, voice_id, speed=1.0):
        text = str(text or "").strip()
        voice_id = str(voice_id or "").strip()
        if not text:
            self.synthesis_finished.emit(False, "请输入试听文字。")
            return
        if voice_id not in PRESETS:
            self.synthesis_finished.emit(False, "请先选择一个 Qwen3-TTS 中文声线。")
            return
        if not self.ready():
            self.synthesis_finished.emit(False, "请先准备 Qwen3-TTS 语音组件。")
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
                preset = PRESETS[voice_id]
                out = CACHE_DIR / "xiaomeili_qwen3_preview.wav"
                resp = self._request({
                    "cmd": "synthesize",
                    "text": text,
                    "speaker": preset["speaker"],
                    "instruct": preset["instruct"] + self._speed_instruction(speed),
                    "output": str(out),
                }, 300)
                if not resp.get("ok"):
                    raise RuntimeError(resp.get("error") or "Qwen3-TTS 合成失败")
                if sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(str(out), winsound.SND_FILENAME | winsound.SND_ASYNC)
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
                        self._worker.wait(timeout=4)
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
