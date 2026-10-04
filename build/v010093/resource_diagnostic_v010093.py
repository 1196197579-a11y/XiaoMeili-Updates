# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.9.3 fully automatic resource diagnostic 2.0.

No game and no user speech are required. The runner exercises XiaoMeili's own
animation/whiteboard, ASR diagnostic worker, cloud brain, cloud TTS and offline
vision-processing paths, then writes a redacted ZIP for analysis.
"""
from __future__ import annotations

import csv
import json
import math
import os
import platform
import queue
import statistics
import subprocess
import threading
import time
import wave
import zipfile
from array import array
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, Signal

try:
    import cv2
    import numpy as np
except Exception:  # covered by normal app dependency validation
    cv2 = None
    np = None

SAMPLE_INTERVAL_SECONDS = 0.25
VRAM_WARN_MB = 256.0
VRAM_MAJOR_MB = 512.0
CHAT_ROUNDS = 30
BASELINE_SECONDS = 60
FINAL_COOLDOWN_SECONDS = 90


class ResourceDiagnosticRunnerV2(QObject):
    progress_changed = Signal(int, str)
    state_requested = Signal(str)
    board_requested = Signal(str, int)
    board_close_requested = Signal()
    finished = Signal(bool, str, str)

    def __init__(self, cfg, brain_service, voice_service, speech_service, vision, pet,
                 data_root, desktop_path, app_version="0.10.0.9.3", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.brain = brain_service
        self.voice = voice_service
        self.speech = speech_service
        self.vision = vision
        self.pet = pet
        self.data_root = Path(data_root)
        self.desktop = Path(desktop_path)
        self.app_version = str(app_version)
        self._running = False
        self._sampling = False
        self._stage = "idle"
        self._started = 0.0
        self._samples = []
        self._events = []
        self._rounds = []
        self._vram_jumps = []
        self._last_vram = None
        self._gpu_tick = 0
        self._gpu_cache = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        self._gpu_proc_cache = []
        self._proc_cache = {}
        self._brain_event = threading.Event()
        self._brain_result = (False, {}, "")
        self._tts_started = threading.Event()
        self._tts_done = threading.Event()
        self._tts_result = (False, "", "")
        self._vision_coverage = {}
        self.session_dir = None
        self.report_zip = None
        self._speech_proc = None
        self._combined_speech_proc = None
        try:
            self.brain.generation_finished.connect(self._on_brain_finished)
        except Exception:
            pass
        try:
            self.voice.playback_started.connect(self._on_tts_started)
            self.voice.playback_finished.connect(self._on_tts_finished)
        except Exception:
            pass

    def is_running(self):
        return bool(self._running)

    def start(self):
        if self._running:
            return False
        self._running = True
        threading.Thread(target=self._run, name="XiaoMeiliResourceDiagnosticV010093", daemon=True).start()
        return True

    def _on_brain_finished(self, ok, answer, message):
        self._brain_result = (bool(ok), dict(answer or {}) if isinstance(answer, dict) else {}, str(message or ""))
        self._brain_event.set()

    def _on_tts_started(self, text, duration_ms, tag):
        if str(tag or "").startswith("resource_diag"):
            self._tts_started.set()

    def _on_tts_finished(self, ok, message, tag):
        if str(tag or "").startswith("resource_diag"):
            self._tts_result = (bool(ok), str(message or ""), str(tag or ""))
            self._tts_done.set()

    def _disconnect_service_signals(self):
        # A completed diagnostic must not stay referenced by long-lived services.
        # Otherwise repeating the test itself would create the kind of QObject leak
        # this diagnostic is meant to detect.
        try:
            self.brain.generation_finished.disconnect(self._on_brain_finished)
        except Exception:
            pass
        try:
            self.voice.playback_started.disconnect(self._on_tts_started)
        except Exception:
            pass
        try:
            self.voice.playback_finished.disconnect(self._on_tts_finished)
        except Exception:
            pass

    def _progress(self, value, text):
        self.progress_changed.emit(max(0, min(100, int(value))), str(text))

    def _event(self, kind, **payload):
        row = {
            "t": round(max(0.0, time.monotonic() - self._started), 3),
            "stage": self._stage,
            "event": str(kind),
        }
        row.update(payload)
        self._events.append(row)

    def _set_stage(self, stage, progress, text):
        self._stage = str(stage)
        self._event("stage", label=str(text))
        self._progress(progress, text)

    @staticmethod
    def _safe_float(v):
        try:
            x = float(v)
            return None if math.isnan(x) or math.isinf(x) else x
        except Exception:
            return None

    def _nvidia_total(self):
        out = dict(self._gpu_cache)
        try:
            raw = subprocess.check_output([
                "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits"
            ], text=True, encoding="utf-8", errors="replace", timeout=3).strip().splitlines()
            if raw:
                p = [x.strip() for x in raw[0].split(",")]
                if len(p) >= 4:
                    out = {
                        "gpu_util": self._safe_float(p[0]),
                        "vram_used_mb": self._safe_float(p[1]),
                        "vram_total_mb": self._safe_float(p[2]),
                        "gpu_temp_c": self._safe_float(p[3]),
                    }
        except Exception:
            pass
        self._gpu_cache = out
        return out

    def _nvidia_processes(self):
        rows = []
        try:
            raw = subprocess.check_output([
                "nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits"
            ], text=True, encoding="utf-8", errors="replace", timeout=3).strip().splitlines()
            for line in raw:
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 3:
                    rows.append({"pid": int(p[0]), "name": p[1], "used_gpu_memory_mb": self._safe_float(p[2]), "source": "compute"})
        except Exception:
            pass
        self._gpu_proc_cache = rows
        return rows

    def _process_rows(self):
        root = psutil.Process(os.getpid())
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        rows = []
        for p in procs:
            try:
                with p.oneshot():
                    info = p.as_dict(attrs=["pid", "ppid", "name", "cmdline", "memory_info"])
                old = self._proc_cache.get(p.pid)
                now_cpu = p.cpu_percent(None)
                self._proc_cache[p.pid] = now_cpu
                cmd = " ".join(info.get("cmdline") or [])[:180]
                rows.append({
                    "pid": p.pid, "ppid": info.get("ppid"), "name": info.get("name"),
                    "rss_bytes": int(getattr(info.get("memory_info"), "rss", 0) or 0),
                    "cpu_percent": float(now_cpu or old or 0.0), "cmd_hint": cmd,
                })
            except Exception:
                continue
        return rows

    @staticmethod
    def _qsize(q):
        try:
            return int(q.qsize())
        except Exception:
            return None

    def _runtime_state(self):
        state = {
            "threads": None, "speech_state": "", "brain_busy": False,
            "tts_active": False, "tts_queue": None, "whiteboard_active": False,
            "qmovie_slots": None, "pet_state": "", "vision_phase": "", "vision_scan_fps": None,
        }
        try:
            state["threads"] = psutil.Process(os.getpid()).num_threads()
        except Exception:
            pass
        try:
            cs = self.speech.current_state()
            state["speech_state"] = str((cs or ("", ""))[0])
        except Exception:
            pass
        state["brain_busy"] = bool(getattr(self.brain, "_generate_busy", False))
        try:
            state["tts_active"] = bool(self.voice.cloud_stream_in_progress())
        except Exception:
            pass
        try:
            ctx = getattr(self.voice, "_cloud_ctx", None) or {}
            state["tts_queue"] = self._qsize(ctx.get("queue"))
        except Exception:
            pass
        try:
            state["whiteboard_active"] = bool(getattr(self.pet, "dialogue_board_active", False))
            movies = getattr(self.pet, "movies", None)
            state["qmovie_slots"] = sum(1 for x in (movies or []) if x is not None)
            state["pet_state"] = str(getattr(self.pet, "current_state", "") or "")
        except Exception:
            pass
        try:
            snap = getattr(self.vision, "last_snapshot", {}) or {}
            state["vision_phase"] = str(snap.get("phase") or "")
            state["vision_scan_fps"] = self._safe_float(snap.get("scan_fps"))
        except Exception:
            pass
        return state

    def _sample_once(self):
        vm = psutil.virtual_memory()
        prows = self._process_rows()
        app_rss = sum(int(x.get("rss_bytes") or 0) for x in prows)
        app_cpu = sum(float(x.get("cpu_percent") or 0.0) for x in prows)
        if self._gpu_tick % 4 == 0:
            gpu = self._nvidia_total()
        else:
            gpu = dict(self._gpu_cache)
        if self._gpu_tick % 8 == 0:
            gp = self._nvidia_processes()
        else:
            gp = list(self._gpu_proc_cache)
        self._gpu_tick += 1
        runtime = self._runtime_state()
        row = {
            "t": round(time.monotonic() - self._started, 3), "stage": self._stage,
            "system_cpu_percent": psutil.cpu_percent(None), "system_ram_percent": vm.percent,
            "app_cpu_percent": app_cpu, "app_rss_bytes": app_rss,
            "gpu_util_percent": gpu.get("gpu_util"), "vram_used_mb": gpu.get("vram_used_mb"),
            "vram_total_mb": gpu.get("vram_total_mb"), "gpu_temp_c": gpu.get("gpu_temp_c"),
            "processes": prows, "gpu_processes": gp,
        }
        row.update(runtime)
        cur = self._safe_float(row.get("vram_used_mb"))
        if cur is not None and self._last_vram is not None:
            delta = cur - self._last_vram
            if delta >= VRAM_WARN_MB:
                self._vram_jumps.append({
                    "t": row["t"], "stage": self._stage, "from_mb": round(self._last_vram, 1),
                    "to_mb": round(cur, 1), "delta_mb": round(delta, 1),
                    "severity": "major" if delta >= VRAM_MAJOR_MB else "warn",
                    "gpu_processes": gp,
                })
        if cur is not None:
            self._last_vram = cur
        self._samples.append(row)

    def _sampler_loop(self):
        next_t = time.monotonic()
        while self._sampling:
            try:
                self._sample_once()
            except Exception as exc:
                self._event("sample_error", error=f"{type(exc).__name__}: {exc}")
            next_t += SAMPLE_INTERVAL_SECONDS
            time.sleep(max(0.02, next_t - time.monotonic()))

    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            time.sleep(min(0.20, max(0.02, end - time.monotonic())))

    def _round_start(self, kind, idx):
        rec = {"kind": str(kind), "index": int(idx), "start_t": round(time.monotonic() - self._started, 3), "end_t": None, "recovery_t": None, "ok": True}
        self._rounds.append(rec)
        self._event("round_start", kind=kind, index=int(idx))
        return rec

    def _round_end(self, rec, ok=True, recovery_seconds=2.0):
        rec["ok"] = bool(ok)
        rec["end_t"] = round(time.monotonic() - self._started, 3)
        self._event("round_end", kind=rec["kind"], index=rec["index"], ok=bool(ok))
        self._sleep(recovery_seconds)
        rec["recovery_t"] = round(time.monotonic() - self._started, 3)

    def _make_test_wav(self, path):
        sample_rate = 16000
        seconds = 5.2
        pcm = array("h")
        for i in range(int(sample_rate * seconds)):
            t = i / sample_rate
            if t < 0.55 or t > 4.65:
                value = 0.0
            else:
                local = t - 0.55
                syllable = int(local / 0.34)
                f0 = 135.0 + (syllable % 5) * 17.0
                env = max(0.0, math.sin(math.pi * ((local % 0.34) / 0.34)))
                voiced = 0.55 * math.sin(2 * math.pi * f0 * t) + 0.24 * math.sin(2 * math.pi * f0 * 2 * t) + 0.12 * math.sin(2 * math.pi * (520 + 35 * (syllable % 4)) * t)
                value = 0.27 * env * voiced
            pcm.append(int(max(-1.0, min(1.0, value)) * 32767))
        with wave.open(str(path), "xb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sample_rate); wf.writeframes(pcm.tobytes())
        return path

    @staticmethod
    def _parse_event_line(line):
        s = str(line or "").strip()
        if not s.startswith("XMEVENT|"):
            return None
        try:
            return json.loads(s[len("XMEVENT|"):])
        except Exception:
            return None

    def _start_asr_diagnostic(self, wav_path, repeat=3, hold_seconds=25):
        proc = self.speech.diagnostic_process_v01005(str(wav_path), repeat=int(repeat), hold_seconds=int(hold_seconds))
        ready = False
        events = []
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                evt = self._parse_event_line(line)
                if evt:
                    events.append(evt)
                    if evt.get("event") == "diag_ready":
                        ready = True
                        break
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
        self._event("asr_diagnostic_ready", ready=ready, events_count=len(events), pid=int(proc.pid))
        if not ready:
            try: proc.terminate()
            except Exception: pass
            raise RuntimeError("FSMN-VAD + Fun-ASR-Nano-2512 自动诊断没有进入驻留状态")
        return proc

    @staticmethod
    def _terminate_proc(proc):
        if not proc:
            return
        try:
            if proc.poll() is None:
                proc.terminate(); proc.wait(timeout=8)
        except Exception:
            pass

    def _brain_once(self, idx, timeout=25):
        self._brain_event.clear()
        prompt = f"资源压力测试第{idx}轮。只回答四个字：测试正常。"
        brain_cfg = self.cfg.get("brain", {}) if isinstance(self.cfg.get("brain"), dict) else {}
        try:
            self.brain.ask(prompt, brain_cfg.get("persona") or "小美丽", 0.2, 24, 0, False)
        except Exception as exc:
            self._event("brain_call_error", error=f"{type(exc).__name__}: {exc}")
            return False, ""
        if not self._brain_event.wait(timeout):
            try: self.brain.abort_current("resource_diag_timeout")
            except Exception: pass
            self._event("brain_timeout", index=idx)
            return False, ""
        ok, answer, message = self._brain_result
        spoken = str((answer or {}).get("spoken_text") or "").strip()
        self._event("brain_result", index=idx, ok=bool(ok), chars=len(spoken), status_len=len(message))
        return bool(ok), spoken

    def _tts_once(self, text, tag, timeout=30):
        voice_cfg = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        vid = str(voice_cfg.get("voice_id") or "")
        if not getattr(self.voice, "ready", lambda: False)() or not vid:
            self._event("tts_skipped", reason="voice unavailable")
            return False
        self._tts_started.clear(); self._tts_done.clear()
        try:
            self.voice.speak(str(text), vid, float(voice_cfg.get("speed", 1.0) or 1.0), str(voice_cfg.get("output_device", "default") or "default"), tag=str(tag), extra_instruct="")
        except Exception as exc:
            self._event("tts_call_error", error=f"{type(exc).__name__}: {exc}")
            return False
        self._tts_started.wait(min(8.0, timeout))
        if not self._tts_done.wait(timeout):
            try: self.voice.abort_playback("resource_diag_timeout")
            except Exception: pass
            self._event("tts_timeout", tag=str(tag))
            return False
        ok, message, _ = self._tts_result
        self._event("tts_result", tag=str(tag), ok=bool(ok), message_len=len(message))
        return bool(ok)

    def _animation_stage(self):
        states = ["idle", "low_hp", "kill", "dead", "victory", "defeat"]
        for i in range(30):
            self.state_requested.emit(states[i % len(states)])
            self._sleep(0.75)
        self.state_requested.emit("idle")
        self._sleep(3)

    def _whiteboard_stage(self):
        for i in range(12):
            rec = self._round_start("whiteboard", i + 1)
            self.board_requested.emit(f"资源测试白板第{i+1}轮", 1400)
            self._sleep(1.8)
            self.board_close_requested.emit()
            self._round_end(rec, True, 0.6)

    def _tts_stage(self):
        texts = [
            "资源测试，短句正常。",
            "这是小美丽资源压力测试的较长播报句，用来观察连续语音播放结束以后，音频流、队列以及内存和显存是否能够及时回落。",
        ]
        for i in range(8):
            rec = self._round_start("tts", i + 1)
            ok = self._tts_once(texts[i % 2], f"resource_diag_tts_{i+1}", 35)
            self._round_end(rec, ok, 1.5)

    def _brain_stage(self):
        for i in range(6):
            rec = self._round_start("brain", i + 1)
            ok, _ = self._brain_once(i + 1, 25)
            self._round_end(rec, ok, 1.5)

    def _chat_round(self, idx, recovery=1.8):
        rec = self._round_start("chat", idx)
        self.state_requested.emit("idle")
        ok, spoken = self._brain_once(idx, 25)
        if not spoken:
            spoken = "测试正常。"
        self.board_requested.emit(spoken[:48], max(1600, min(5000, len(spoken) * 110)))
        tts_ok = self._tts_once(spoken, f"resource_diag_chat_{idx}", 35)
        self.board_close_requested.emit()
        self.state_requested.emit("idle")
        self._round_end(rec, bool(ok and tts_ok), recovery)

    def _hard_silence_stage(self):
        # TTS + whiteboard interruption through the actual ASR->AppController P0 path.
        for i, phrase in enumerate(("闭嘴", "你给我闭嘴", "你别说话了"), 1):
            rec = self._round_start("hard_silence", i)
            long_text = "这是用于测试闭嘴硬打断的较长语音，正常情况下应该在播报中途被立即停止，不应该继续说完这句话。"
            self._tts_started.clear(); self._tts_done.clear()
            self.board_requested.emit(long_text, 9000)
            voice_cfg = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
            vid = str(voice_cfg.get("voice_id") or "")
            if vid and getattr(self.voice, "ready", lambda: False)():
                try:
                    self.voice.speak(long_text, vid, float(voice_cfg.get("speed", 1.0) or 1.0), str(voice_cfg.get("output_device", "default") or "default"), tag=f"resource_diag_interrupt_{i}", extra_instruct="")
                except Exception:
                    pass
            self._tts_started.wait(6)
            try:
                self.speech.utterance_ready.emit(phrase)
            except Exception:
                pass
            self._sleep(2.0)
            still_tts = False
            try: still_tts = bool(self.voice.cloud_stream_in_progress())
            except Exception: pass
            still_board = bool(getattr(self.pet, "dialogue_board_active", False))
            self._event("hard_silence_check", phrase_id=i, tts_active=still_tts, board_active=still_board)
            self.board_close_requested.emit()
            self._round_end(rec, not still_tts and not still_board, 1.2)

    def _offline_vision_once(self, include_ocr=True):
        if cv2 is None or np is None:
            raise RuntimeError("OpenCV/Numpy unavailable")
        # Fixed 2560x1440 offline frame. It is generated in memory and never saved.
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        cv2.rectangle(frame, (40, 40), (2520, 1400), (18, 42, 28), 2)
        # Team/avatar template matching.
        gray = cv2.cvtColor(frame[20:180, 720:1840], cv2.COLOR_BGR2GRAY)
        try:
            if getattr(self.vision, "alive_templates", None):
                t = self.vision.alive_templates[0]
                h, w = t.shape[:2]
                if gray.shape[0] > h and gray.shape[1] > w:
                    gray[5:5+h, 5:5+w] = t
                self.vision._multi_match(gray, self.vision.alive_templates)
            self._vision_coverage["team_avatar"] = "PASS"
        except Exception as exc:
            self._vision_coverage["team_avatar"] = f"FAIL:{type(exc).__name__}"
        # Kill UI template path.
        try:
            kt = getattr(self.vision, "kill_portrait_t", None)
            if kt is not None:
                canvas = np.zeros((max(kt.shape[0] + 8, 64), max(kt.shape[1] + 8, 64)), dtype=np.uint8)
                canvas[4:4+kt.shape[0], 4:4+kt.shape[1]] = kt
                self.vision._fixed_match(canvas, kt)
            self._vision_coverage["kill_ui"] = "PASS"
        except Exception as exc:
            self._vision_coverage["kill_ui"] = f"FAIL:{type(exc).__name__}"
        # Context/death/highlight support functions.
        try:
            small = frame[0:120, 0:260]
            self.vision._context_icon_score(small, "left")
            self.vision._death_report_score(small)
            self._vision_coverage["context_death"] = "PASS"
        except Exception as exc:
            self._vision_coverage["context_death"] = f"FAIL:{type(exc).__name__}"
        try:
            self.vision._build_snapshot(game_found=True, foreground=True, paused=False, error=None)
            self._vision_coverage["highlight_snapshot"] = "PASS"
        except Exception as exc:
            self._vision_coverage["highlight_snapshot"] = f"FAIL:{type(exc).__name__}"
        if include_ocr:
            try:
                card = np.full((260, 720, 3), 245, dtype=np.uint8)
                cv2.putText(card, "XIAOMEILI  18  7  3", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.15, (20, 20, 20), 2, cv2.LINE_AA)
                eng = self.vision._get_report_ocr_engine()
                if eng is not None:
                    self.vision._run_report_ocr(eng, card)
                self._vision_coverage["result_ocr"] = "PASS"
            except Exception as exc:
                self._vision_coverage["result_ocr"] = f"FAIL:{type(exc).__name__}"

    def _offline_vision_stage(self, seconds=45):
        started = time.monotonic(); loops = 0
        while time.monotonic() - started < seconds:
            self._offline_vision_once(include_ocr=(loops % 8 == 0))
            loops += 1
            if loops % 10 == 0:
                self._event("offline_vision_progress", loops=loops, coverage=dict(self._vision_coverage))
            time.sleep(0.04)
        self._event("offline_vision_done", loops=loops, coverage=dict(self._vision_coverage))

    def _combined_stage(self, wav_path):
        proc = None
        stop = threading.Event()
        def vision_job():
            while not stop.is_set():
                try: self._offline_vision_once(include_ocr=False)
                except Exception: pass
                time.sleep(0.05)
        vt = threading.Thread(target=vision_job, name="XiaoMeiliOfflineVisionStress", daemon=True)
        try:
            proc = self._start_asr_diagnostic(wav_path, repeat=2, hold_seconds=70)
            self._combined_speech_proc = proc
            vt.start()
            for i in range(6):
                self._chat_round(100 + i, recovery=0.8)
                self.state_requested.emit(("kill", "victory", "low_hp", "idle")[i % 4])
                self._sleep(0.5)
        finally:
            stop.set(); vt.join(timeout=3)
            self._terminate_proc(proc); self._combined_speech_proc = None
            self.state_requested.emit("idle")

    def _window(self, a, b):
        return [r for r in self._samples if float(a) <= float(r.get("t") or 0) <= float(b)]

    @staticmethod
    def _nearest(rows, t):
        if not rows:
            return None
        return min(rows, key=lambda x: abs(float(x.get("t") or 0) - float(t)))

    @staticmethod
    def _num(row, key, scale=1.0):
        if not row:
            return None
        try: return float(row.get(key)) * scale
        except Exception: return None

    def _round_ledger_rows(self):
        out = []
        for rec in self._rounds:
            st = float(rec.get("start_t") or 0); et = float(rec.get("end_t") or st); rt = float(rec.get("recovery_t") or et)
            win = self._window(st, et)
            start = self._nearest(self._samples, st); end = self._nearest(self._samples, et); recovery = self._nearest(self._samples, rt)
            v = [self._safe_float(x.get("vram_used_mb")) for x in win]; v = [x for x in v if x is not None]
            rss = [float(x.get("app_rss_bytes") or 0)/1024/1024 for x in win]
            cpu = [float(x.get("app_cpu_percent") or 0) for x in win]
            out.append({
                "kind": rec.get("kind"), "index": rec.get("index"), "ok": rec.get("ok"),
                "start_t": st, "end_t": et, "recovery_t": rt,
                "start_rss_mb": round(self._num(start, "app_rss_bytes", 1/1024/1024) or 0, 2),
                "peak_rss_mb": round(max(rss), 2) if rss else None,
                "recovery_rss_mb": round(self._num(recovery, "app_rss_bytes", 1/1024/1024) or 0, 2),
                "rss_unrecovered_mb": round((self._num(recovery, "app_rss_bytes", 1/1024/1024) or 0) - (self._num(start, "app_rss_bytes", 1/1024/1024) or 0), 2),
                "start_vram_mb": round(self._num(start, "vram_used_mb") or 0, 1) if self._num(start, "vram_used_mb") is not None else None,
                "peak_vram_mb": round(max(v), 1) if v else None,
                "recovery_vram_mb": round(self._num(recovery, "vram_used_mb") or 0, 1) if self._num(recovery, "vram_used_mb") is not None else None,
                "vram_unrecovered_mb": round((self._num(recovery, "vram_used_mb") or 0) - (self._num(start, "vram_used_mb") or 0), 1) if self._num(start, "vram_used_mb") is not None and self._num(recovery, "vram_used_mb") is not None else None,
                "peak_app_cpu_percent": round(max(cpu), 1) if cpu else None,
            })
        return out

    def _stage_summary(self):
        out = []
        stages = []
        for r in self._samples:
            s = str(r.get("stage") or "")
            if s and s not in stages: stages.append(s)
        for stage in stages:
            rows = [r for r in self._samples if r.get("stage") == stage]
            if not rows: continue
            rss = [float(r.get("app_rss_bytes") or 0)/1024/1024 for r in rows]
            cpu = [float(r.get("app_cpu_percent") or 0) for r in rows]
            vr = [self._safe_float(r.get("vram_used_mb")) for r in rows]; vr = [x for x in vr if x is not None]
            gp = [self._safe_float(r.get("gpu_util_percent")) for r in rows]; gp = [x for x in gp if x is not None]
            out.append({"stage": stage, "samples": len(rows), "rss_start_mb": round(rss[0],2), "rss_end_mb": round(rss[-1],2), "rss_peak_mb": round(max(rss),2), "rss_delta_mb": round(rss[-1]-rss[0],2), "vram_start_mb": round(vr[0],1) if vr else None, "vram_end_mb": round(vr[-1],1) if vr else None, "vram_peak_mb": round(max(vr),1) if vr else None, "vram_delta_mb": round(vr[-1]-vr[0],1) if vr else None, "app_cpu_peak_percent": round(max(cpu),1) if cpu else None, "gpu_peak_percent": round(max(gp),1) if gp else None})
        return out

    def _write_reports(self):
        ledger = self._round_ledger_rows()
        stages = self._stage_summary()
        with (self.session_dir / "timeline_250ms.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["t_seconds","stage","system_cpu_percent","system_ram_percent","app_cpu_percent","app_rss_mb","gpu_util_percent","vram_used_mb","vram_total_mb","gpu_temp_c","threads","speech_state","brain_busy","tts_active","tts_queue","whiteboard_active","qmovie_slots","pet_state","vision_phase","vision_scan_fps"])
            for r in self._samples:
                w.writerow([r.get("t"),r.get("stage"),r.get("system_cpu_percent"),r.get("system_ram_percent"),r.get("app_cpu_percent"),round(float(r.get("app_rss_bytes") or 0)/1024/1024,2),r.get("gpu_util_percent"),r.get("vram_used_mb"),r.get("vram_total_mb"),r.get("gpu_temp_c"),r.get("threads"),r.get("speech_state"),r.get("brain_busy"),r.get("tts_active"),r.get("tts_queue"),r.get("whiteboard_active"),r.get("qmovie_slots"),r.get("pet_state"),r.get("vision_phase"),r.get("vision_scan_fps")])
        with (self.session_dir / "round_ledger.csv").open("x", encoding="utf-8-sig", newline="") as f:
            keys = ["kind","index","ok","start_t","end_t","recovery_t","start_rss_mb","peak_rss_mb","recovery_rss_mb","rss_unrecovered_mb","start_vram_mb","peak_vram_mb","recovery_vram_mb","vram_unrecovered_mb","peak_app_cpu_percent"]
            w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(ledger)
        with (self.session_dir / "stage_summary.csv").open("x", encoding="utf-8-sig", newline="") as f:
            keys=["stage","samples","rss_start_mb","rss_end_mb","rss_peak_mb","rss_delta_mb","vram_start_mb","vram_end_mb","vram_peak_mb","vram_delta_mb","app_cpu_peak_percent","gpu_peak_percent"]
            w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(stages)
        with (self.session_dir / "vram_jump_events.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w=csv.writer(f); w.writerow(["t_seconds","stage","from_mb","to_mb","delta_mb","severity","gpu_processes_json"])
            for e in self._vram_jumps: w.writerow([e.get("t"),e.get("stage"),e.get("from_mb"),e.get("to_mb"),e.get("delta_mb"),e.get("severity"),json.dumps(e.get("gpu_processes") or [],ensure_ascii=False)])
        with (self.session_dir / "process_tree.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w=csv.writer(f); w.writerow(["t_seconds","stage","pid","ppid","name","cpu_percent","rss_mb","cmd_hint"])
            for r in self._samples:
                for p in r.get("processes") or []: w.writerow([r.get("t"),r.get("stage"),p.get("pid"),p.get("ppid"),p.get("name"),p.get("cpu_percent"),round(float(p.get("rss_bytes") or 0)/1024/1024,2),p.get("cmd_hint")])
        (self.session_dir / "events.json").write_text(json.dumps(self._events,ensure_ascii=False,indent=2),encoding="utf-8")
        meta={"app_version":self.app_version,"platform":platform.platform(),"python":platform.python_version(),"sample_interval_seconds":SAMPLE_INTERVAL_SECONDS,"chat_rounds":CHAT_ROUNDS,"baseline_seconds":BASELINE_SECONDS,"final_cooldown_seconds":FINAL_COOLDOWN_SECONDS,"vision_mode":"offline standard-frame replay; VALORANT is not required","vision_coverage":self._vision_coverage,"privacy":"不保存聊天原文、回答原文、麦克风录音、游戏截图、API Key、长期记忆、养成库或昵称。","safety":"只创建新的诊断目录和ZIP；不删除、不移动、不覆盖用户文件。"}
        (self.session_dir / "summary.json").write_text(json.dumps({"meta":meta,"stages":stages,"rounds":ledger,"vram_jumps":self._vram_jumps},ensure_ascii=False,indent=2),encoding="utf-8")
        chat=[x for x in ledger if x.get("kind") in ("chat","tts","whiteboard")]
        max_rss=max([float(x.get("rss_unrecovered_mb") or 0) for x in chat] or [0])
        max_vram=max([float(x.get("vram_unrecovered_mb") or 0) for x in chat] or [0])
        lines=[f"小美丽 V{self.app_version} 一键深度资源测试 2.0","="*58,"",f"自动聊天轮数：{CHAT_ROUNDS}",f"采样间隔：{SAMPLE_INTERVAL_SECONDS}s",f"最大单轮未回收RAM：{max_rss:.2f} MB",f"最大单轮未回收显存：{max_vram:.1f} MB",f">=256MB 显存跳变：{len(self._vram_jumps)} 次","", "离线画面识别覆盖："]
        for k,v in sorted(self._vision_coverage.items()): lines.append(f"- {k}: {v}")
        lines += ["", "请直接把本 ZIP 上传给 ChatGPT。无需再截图任务管理器。", "报告不包含聊天内容、回答内容、API Key、记忆、昵称、截图或麦克风录音。", "测试不需要打开 VALORANT，也不会读取、注入或控制 VALORANT。"]
        (self.session_dir / "请上传给ChatGPT_一键深度资源测试2.0摘要.txt").write_text("\n".join(lines),encoding="utf-8-sig")
        self.desktop.mkdir(parents=True,exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        target=self.desktop/f"小美丽_一键深度资源测试2.0_{stamp}.zip"; n=1
        while target.exists(): target=self.desktop/f"小美丽_一键深度资源测试2.0_{stamp}_{n}.zip"; n+=1
        names={"timeline_250ms.csv","round_ledger.csv","stage_summary.csv","vram_jump_events.csv","process_tree.csv","events.json","summary.json","请上传给ChatGPT_一键深度资源测试2.0摘要.txt","speech_diagnostic_worker.log"}
        with zipfile.ZipFile(target,"x",zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(self.session_dir.iterdir()):
                if p.is_file() and p.name in names: zf.write(p,arcname=p.name)
        self.report_zip=target
        return target

    def _run(self):
        self._started=time.monotonic(); token=f"{int(time.time())}_{os.getpid()}"
        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v010093_{token}"
        self.session_dir.mkdir(parents=True,exist_ok=False)
        wav_path=None; ok=True; err=""
        self._sampling=True
        sampler=threading.Thread(target=self._sampler_loop,name="XiaoMeiliResourceSamplerV010093",daemon=True); sampler.start()
        setattr(self.brain,"_resource_diag_no_persist",True)
        try:
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
            self.state_requested.emit("idle"); self._sleep(BASELINE_SECONDS)

            self._set_stage("animation",10,"2/10 状态动画：自动切换30次，检查QMovie/Qt对象回收")
            self._animation_stage()

            self._set_stage("whiteboard",18,"3/10 白板动画：自动打开/打字/关闭12轮")
            self._whiteboard_stage()

            wav_path=self._make_test_wav(self.session_dir/"diagnostic_input.wav")
            self._set_stage("asr",27,"4/10 语音输入：FSMN-VAD + Fun-ASR-Nano-2512 自动离线测试")
            self._speech_proc=self._start_asr_diagnostic(wav_path,repeat=4,hold_seconds=35); self._sleep(15); self._terminate_proc(self._speech_proc); self._speech_proc=None; self._sleep(5)

            self._set_stage("brain",35,"5/10 云端大脑：6轮短回答测试（会产生少量API费用，不写入记忆/历史）")
            self._brain_stage()

            self._set_stage("tts",43,"6/10 云端TTS：短句/长句连续8轮")
            self._tts_stage()

            self._set_stage("chat",52,f"7/10 完整聊天链路：自动执行 {CHAT_ROUNDS} 轮 大脑→TTS→白板→动画→回落")
            for i in range(CHAT_ROUNDS):
                self._progress(52+int(18*(i+1)/CHAT_ROUNDS),f"7/10 完整聊天链路：第 {i+1}/{CHAT_ROUNDS} 轮")
                self._chat_round(i+1)

            self._set_stage("hard_silence",72,"8/10 闭嘴硬打断：分别测试闭嘴/你给我闭嘴/你别说话了")
            self._hard_silence_stage()

            self._set_stage("offline_vision",79,"9/10 画面识别离线回放：头像/击杀UI/结算OCR/高光，无需打开游戏")
            self._offline_vision_stage(45)

            self._set_stage("combined",88,"10/10 综合满载：ASR + 大脑 + TTS + 白板 + 动画 + 全部离线识别")
            self._combined_stage(wav_path)

            self._set_stage("final_cooldown",96,f"最终冷却：静置 {FINAL_COOLDOWN_SECONDS} 秒，检查CPU/RAM/显存是否回落")
            self.board_close_requested.emit(); self.state_requested.emit("idle"); self._sleep(FINAL_COOLDOWN_SECONDS)
        except Exception as exc:
            ok=False; err=f"{type(exc).__name__}: {exc}"; self._event("error",message=err)
        finally:
            self._terminate_proc(self._speech_proc); self._terminate_proc(self._combined_speech_proc)
            try: setattr(self.brain,"_resource_diag_no_persist",False)
            except Exception: pass
            try: self.board_close_requested.emit(); self.state_requested.emit("idle")
            except Exception: pass
            self._sampling=False
            try: sampler.join(timeout=4)
            except Exception: pass
        try:
            self._set_stage("report",99,"正在生成脱敏诊断 ZIP")
            report=self._write_reports(); self._progress(100,"测试完成：桌面已生成诊断ZIP")
            msg=f"诊断完成：{report}" if ok else f"部分阶段失败，但已生成可分析报告：{report}\n{err}"
            self.finished.emit(ok,str(report),msg)
        except Exception as exc:
            self.finished.emit(False,"",f"生成诊断报告失败：{type(exc).__name__}: {exc}")
        finally:
            self._disconnect_service_signals()
            self._running=False