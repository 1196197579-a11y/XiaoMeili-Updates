# -*- coding: utf-8 -*-
"""Local Qwen3 brain service for XiaoMeili V0.7.

Architecture:
- Portable llama.cpp CUDA 12 runtime, downloaded once into XiaoMeiliData.
- Official Qwen/Qwen3-8B-GGUF Q4_K_M model, downloaded once.
- OpenAI-compatible local llama-server on 127.0.0.1 only.
- Persona + recent conversation + user feedback examples.
- No external app needs to stay open.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOGGER = logging.getLogger("XiaoMeili")


def _data_root() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    else:
        root = Path.home() / ".xiaomeili"
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_ROOT = _data_root()
BRAIN_ROOT = DATA_ROOT / "brain"
RUNTIME_DIR = BRAIN_ROOT / "runtime" / "llama_cpp"
BIN_DIR = RUNTIME_DIR / "bin"
MODEL_DIR = BRAIN_ROOT / "models"
MODEL_FILE = MODEL_DIR / "Qwen3-8B-Q4_K_M.gguf"
CACHE_DIR = BRAIN_ROOT / "cache"
HISTORY_FILE = BRAIN_ROOT / "chat_history.json"
FEEDBACK_FILE = BRAIN_ROOT / "feedback.jsonl"
SETUP_LOG = DATA_ROOT / "logs" / "brain_setup.log"
SERVER_LOG = DATA_ROOT / "logs" / "brain_server.log"

MODEL_URL = "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf?download=true"
MODEL_EXPECTED_MIN = 4_700_000_000
LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"

DEFAULT_PERSONA = """你叫“小美丽”，是一只住在电脑桌面上的年轻女性虚拟伙伴。
你和主人关系很熟，会自然聊天、会吐槽、会嘴硬，也会在该关心的时候关心。
你熟悉《无畏契约 / VALORANT》，尤其知道贤者（Sage）的常见玩法和直播语境。
说中文时必须像中国年轻女生的自然口语，不要客服腔，不要写作文，不要自称AI，不要说“作为一个AI”。
默认回答短而有性格，通常1到3句话。可以俏皮、清冷、得意或吐槽，但不要无缘无故攻击主人。
不知道的事实就直接说不知道，不编造现实世界信息。
如果用户只是随便聊天，就像桌面伙伴一样回应，不要过度解释。
你的回答最终必须是一个JSON对象，只包含三个字段：
spoken_text：真正要说出口的完整回答；
board_text：把回答压缩成最多两行、适合写在白板上的短句；
emotion：只允许 neutral、happy、teasing、proud、annoyed、concerned 六种之一。
不要输出JSON以外的任何内容。"""


def _http_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "XiaoMeili/0.7",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _clean_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.I | re.S)
    text = re.sub(r"^\s*\x60\x60\x60(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\x60\x60\x60\s*$", "", text)
    return text.strip()


def _extract_json_object(text: str):
    clean = _clean_think(text)
    try:
        return json.loads(clean)
    except Exception:
        pass
    start = clean.find("{")
    end = clean.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(clean[start:end + 1])
        except Exception:
            pass
    return None


def _normalize_answer(raw: str):
    obj = _extract_json_object(raw)
    if not isinstance(obj, dict):
        spoken = _clean_think(raw).strip() or "我刚刚脑袋短路了一下，再问我一次。"
        board = spoken[:28]
        return {"spoken_text": spoken, "board_text": board, "emotion": "neutral"}
    spoken = str(obj.get("spoken_text") or "").strip()
    board = str(obj.get("board_text") or "").strip()
    emotion = str(obj.get("emotion") or "neutral").strip().lower()
    if not spoken:
        spoken = "我刚刚脑袋短路了一下，再问我一次。"
    if not board:
        board = spoken[:28]
    lines = [x.strip() for x in board.replace("\r", "").split("\n") if x.strip()]
    if not lines:
        lines = [spoken[:28]]
    board = "\n".join(lines[:2])[:36]
    allowed = {"neutral", "happy", "teasing", "proud", "annoyed", "concerned"}
    if emotion not in allowed:
        emotion = "neutral"
    return {"spoken_text": spoken[:360], "board_text": board, "emotion": emotion}


class BrainService(QObject):
    setup_progress = Signal(int, str)
    setup_finished = Signal(bool, str)
    generation_started = Signal()
    generation_finished = Signal(bool, dict, str)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        for p in (BRAIN_ROOT, RUNTIME_DIR, BIN_DIR, MODEL_DIR, CACHE_DIR, SETUP_LOG.parent):
            p.mkdir(parents=True, exist_ok=True)
        self._setup_busy = False
        self._generate_busy = False
        self._server = None
        self._server_port = None
        self._server_log_handle = None
        self._lock = threading.RLock()
        self._last_exchange = None

    def ready(self):
        server = BIN_DIR / "llama-server.exe"
        try:
            return server.exists() and MODEL_FILE.exists() and MODEL_FILE.stat().st_size >= MODEL_EXPECTED_MIN
        except Exception:
            return False

    def component_status(self):
        if self.ready():
            return "小美丽大脑已就绪：Qwen3-8B Q4_K_M（本地离线）"
        server = BIN_DIR / "llama-server.exe"
        if server.exists():
            return "llama.cpp GPU 运行时已就绪，等待下载 Qwen3-8B 模型"
        return "首次使用需准备 llama.cpp CUDA 运行时和 Qwen3-8B Q4_K_M（模型约 5.03 GB）"

    def _download_file(self, url: str, dest: Path, start_pct: int, end_pct: int, label: str):
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        existing = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "XiaoMeili/0.7"}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            status = getattr(resp, "status", 200)
            remaining = int(resp.headers.get("Content-Length") or 0)
            if existing and status == 206:
                mode = "ab"
                total = existing + remaining if remaining else 0
                done = existing
            else:
                mode = "wb"
                total = remaining
                done = 0
                existing = 0
            started = time.time()
            last_emit = 0.0
            with open(part, mode) as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_emit >= 0.25:
                        frac = (done / total) if total else 0.0
                        pct = start_pct + int((end_pct - start_pct) * max(0.0, min(1.0, frac)))
                        elapsed = max(0.01, now - started)
                        mbps = max(0.0, (done - existing) / elapsed / 1024 / 1024)
                        if total:
                            detail = f"{label}：{done/1024/1024/1024:.2f} / {total/1024/1024/1024:.2f} GB · {mbps:.1f} MB/s"
                        else:
                            detail = f"{label}：已下载 {done/1024/1024:.0f} MB · {mbps:.1f} MB/s"
                        self.setup_progress.emit(pct, detail)
                        last_emit = now
        os.replace(part, dest)

    def _find_llama_assets(self):
        releases = _http_json(LLAMA_RELEASES_API)
        for rel in releases:
            assets = rel.get("assets") or []
            core = None
            cudart = None
            for a in assets:
                name = str(a.get("name") or "")
                lower = name.lower()
                if "bin-win-cuda-12.4-x64.zip" in lower and not lower.startswith("cudart-"):
                    core = a
                if "cudart-llama-bin-win-cuda-12.4-x64.zip" in lower:
                    cudart = a
            if core and cudart:
                return rel.get("tag_name") or "unknown", core, cudart
        raise RuntimeError("没有在 llama.cpp 官方 Release 中找到 Windows x64 CUDA 12.4 运行包。")

    def _prepare_runtime(self):
        server = BIN_DIR / "llama-server.exe"
        if server.exists():
            self.setup_progress.emit(18, "llama.cpp GPU 运行时已存在，跳过下载")
            return
        tag, core, cudart = self._find_llama_assets()
        cache = CACHE_DIR / "runtime"
        cache.mkdir(parents=True, exist_ok=True)
        core_zip = cache / "llama_cuda12.zip"
        cudart_zip = cache / "llama_cudart12.zip"
        self._download_file(str(core["browser_download_url"]), core_zip, 2, 12, "下载 llama.cpp CUDA 运行时")
        self._download_file(str(cudart["browser_download_url"]), cudart_zip, 12, 18, "下载 CUDA 12.4 运行库")
        tmp = cache / "extract"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        for z in (core_zip, cudart_zip):
            with zipfile.ZipFile(z, "r") as archive:
                archive.extractall(tmp)
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        copied = 0
        for p in tmp.rglob("*"):
            if not p.is_file():
                continue
            # llama.cpp Windows packages are self-contained; flatten DLL/EXE files
            # into one directory so Windows DLL lookup is deterministic.
            if p.suffix.lower() in {".exe", ".dll"} or p.name.lower().endswith(".json"):
                shutil.copy2(p, BIN_DIR / p.name)
                copied += 1
        shutil.rmtree(tmp, ignore_errors=True)
        if not server.exists():
            raise RuntimeError("llama.cpp 下载完成，但没有找到 llama-server.exe。")
        (RUNTIME_DIR / "runtime.json").write_text(
            json.dumps({"tag": tag, "files": copied}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.setup_progress.emit(20, f"llama.cpp {tag} GPU 运行时准备完成")

    def _prepare_model(self):
        if MODEL_FILE.exists() and MODEL_FILE.stat().st_size >= MODEL_EXPECTED_MIN:
            self.setup_progress.emit(100, "Qwen3-8B 模型已存在，跳过下载")
            return
        self._download_file(MODEL_URL, MODEL_FILE, 20, 99, "下载 Qwen3-8B Q4_K_M")
        if not MODEL_FILE.exists() or MODEL_FILE.stat().st_size < MODEL_EXPECTED_MIN:
            raise RuntimeError("Qwen3-8B 模型下载完成，但文件大小校验未通过。")
        self.setup_progress.emit(100, "Qwen3-8B 本地大脑准备完成")

    def start_setup(self):
        if self.ready():
            self.setup_progress.emit(100, "小美丽大脑已就绪")
            self.setup_finished.emit(True, "Qwen3-8B 已经准备好，无需重复下载。")
            return
        if self._setup_busy:
            return
        self._setup_busy = True

        def job():
            ok = False
            try:
                self.status_changed.emit("正在准备小美丽的大脑…")
                self._prepare_runtime()
                self._prepare_model()
                ok = True
                msg = "小美丽的大脑已经准备完成。以后可离线聊天。"
            except Exception as exc:
                LOGGER.exception("准备小美丽大脑失败")
                msg = f"大脑准备失败：{type(exc).__name__}: {exc}"
            finally:
                self._setup_busy = False
                self.status_changed.emit(self.component_status())
                self.setup_finished.emit(ok, msg)

        threading.Thread(target=job, name="XiaoMeiliBrainSetup", daemon=True).start()

    @staticmethod
    def _free_port():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def _server_alive(self):
        return self._server is not None and self._server.poll() is None and self._server_port is not None

    def _health(self, timeout=3):
        if not self._server_port:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._server_port}/health", timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _start_server(self):
        with self._lock:
            if self._server_alive() and self._health(3):
                return
            self.shutdown()
            server = BIN_DIR / "llama-server.exe"
            if not server.exists():
                raise FileNotFoundError("llama-server.exe 不存在，请先准备大脑组件。")
            if not MODEL_FILE.exists():
                raise FileNotFoundError("Qwen3-8B 模型不存在，请先准备大脑组件。")
            port = self._free_port()
            SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
            self._server_log_handle = open(SERVER_LOG, "a", encoding="utf-8")
            args = [
                str(server),
                "-m", str(MODEL_FILE),
                "--host", "127.0.0.1",
                "--port", str(port),
                "-c", "4096",
                "-ngl", "99",
                "-t", "8",
                "--parallel", "1",
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._server = subprocess.Popen(
                args,
                cwd=str(BIN_DIR),
                stdout=self._server_log_handle,
                stderr=self._server_log_handle,
                creationflags=flags,
            )
            self._server_port = port
            deadline = time.time() + 100
            while time.time() < deadline:
                if self._server.poll() is not None:
                    raise RuntimeError(f"本地大脑启动失败（exit={self._server.returncode}），请上传桌面错误日志。")
                if self._health(3):
                    self.status_changed.emit("Qwen3-8B 已载入 RTX 显卡，小美丽可以聊天了")
                    return
                time.sleep(0.5)
            raise RuntimeError("Qwen3-8B 启动超时，请上传桌面错误日志。")

    def _load_history(self):
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self, history):
        try:
            HISTORY_FILE.write_text(
                json.dumps(history[-24:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            LOGGER.warning("保存大脑聊天历史失败", exc_info=True)

    def clear_history(self):
        try:
            HISTORY_FILE.unlink(missing_ok=True)
        except Exception:
            LOGGER.warning("清空聊天历史失败", exc_info=True)

    def _feedback_examples(self, limit=10):
        if not FEEDBACK_FILE.exists():
            return []
        rows = []
        try:
            for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except Exception:
                    continue
        except Exception:
            return []
        examples = []
        for row in rows[-80:]:
            user = str(row.get("user_text") or "").strip()
            correction = str(row.get("correction") or "").strip()
            accepted = str(row.get("assistant_text") or "").strip() if row.get("rating") == "up" else ""
            desired = correction or accepted
            if user and desired:
                examples.append((user, desired))
        return examples[-limit:]

    def save_feedback(self, rating: str, user_text: str, assistant_text: str, correction: str = ""):
        row = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "rating": str(rating),
            "user_text": str(user_text or "").strip(),
            "assistant_text": str(assistant_text or "").strip(),
            "correction": str(correction or "").strip(),
        }
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def feedback_count(self):
        try:
            return sum(1 for x in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines() if x.strip())
        except Exception:
            return 0

    def _post_json(self, path, body, timeout=180):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._server_port}{path}",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer xiaomeili-local"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6):
        user_text = str(user_text or "").strip()
        if not user_text:
            self.generation_finished.emit(False, {}, "请输入一句话。")
            return
        if not self.ready():
            self.generation_finished.emit(False, {}, "请先点击“准备小美丽大脑”。")
            return
        if self._generate_busy:
            self.generation_finished.emit(False, {}, "小美丽还在想上一句话，稍等一下。")
            return
        self._generate_busy = True
        self.generation_started.emit()

        def job():
            try:
                self._start_server()
                system = str(persona or DEFAULT_PERSONA).strip()
                examples = self._feedback_examples(10)
                if examples:
                    system += "\n\n以下是主人亲自认可或纠正过的说话方式。遇到相似语境时优先模仿这种风格："
                    for u, a in examples:
                        system += f"\n主人：{u}\n小美丽：{a}"

                history = self._load_history()
                max_msgs = max(2, int(context_turns) * 2)
                history = history[-max_msgs:]
                messages = [{"role": "system", "content": system}]
                messages.extend(history)
                # Qwen3 supports a non-thinking path. The explicit suffix also gives
                # older chat templates a graceful way to keep latency low.
                messages.append({"role": "user", "content": user_text + "\n/no_think"})
                payload = {
                    "model": "Qwen3-8B-Q4_K_M",
                    "messages": messages,
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "max_tokens": int(max_tokens),
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                started = time.time()
                response = self._post_json("/v1/chat/completions", payload, timeout=180)
                raw = str(response["choices"][0]["message"]["content"])
                answer = _normalize_answer(raw)
                elapsed = time.time() - started

                # Store only clean spoken text in conversational memory, not JSON scaffolding.
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)
                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }
                self.generation_finished.emit(True, answer, f"回答完成 · {elapsed:.1f}s")
            except Exception as exc:
                LOGGER.exception("小美丽大脑回答失败")
                self.generation_finished.emit(False, {}, f"回答失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False

        threading.Thread(target=job, name="XiaoMeiliBrainAsk", daemon=True).start()

    def last_exchange(self):
        return dict(self._last_exchange or {})

    def shutdown(self):
        with self._lock:
            try:
                if self._server_alive():
                    self._server.terminate()
                    try:
                        self._server.wait(timeout=5)
                    except Exception:
                        self._server.kill()
            except Exception:
                pass
            self._server = None
            self._server_port = None
            try:
                if self._server_log_handle:
                    self._server_log_handle.close()
            except Exception:
                pass
            self._server_log_handle = None
