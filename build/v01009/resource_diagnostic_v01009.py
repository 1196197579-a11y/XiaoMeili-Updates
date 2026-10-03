# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.9 real-match full resource diagnostic.

User flow:
1) click once in XiaoMeili;
2) return to VALORANT and play one normal match;
3) after the match/result stage is detected, XiaoMeili automatically runs the
   remaining synthetic module tests and creates a redacted ZIP on Desktop.

Safety:
- creates new diagnostic files only under XiaoMeiliData/diagnostics and one new Desktop ZIP
- does not delete, move, purge, mirror, overwrite, or clean any existing user file
- does not read VALORANT process memory, inject code, or control keyboard/mouse
- does not save screenshots, microphone recordings, chat history, memories, nicknames or API keys
"""
from __future__ import annotations

import csv
import json
import math
import os
import platform
import re
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

from cloud_support import cloud_cfg, load_api_key, test_brain_connection

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAMPLE_INTERVAL_SECONDS = 0.25
GPU_TOTAL_INTERVAL_SAMPLES = 4          # nvidia-smi total VRAM every ~1s
GPU_PROCESS_INTERVAL_SAMPLES = 8        # per-process GPU snapshot every ~2s
SPEECH_RUNS = 3
REAL_MATCH_WAIT_SECONDS = 30 * 60
REAL_MATCH_MAX_SECONDS = 75 * 60
REAL_MATCH_END_GRACE_SECONDS = 10.0
VRAM_JUMP_MB = 512.0

VISION_MODULES = [
    ("shared_capture", "统一屏幕采集器", "VisionWorker.run 内单个 ScreenGrabber 共享给全部识别", "capture"),
    ("match_context", "对局上下文", "双方HUD/顶部信息判断是否处于实战", "context"),
    ("sage_alive", "贤者存活", "己方贤者头像模板识别", "alive"),
    ("hp", "生命值/低血量", "HUD血量数字与状态投票", "hp"),
    ("killfeed", "击杀UI", "击杀栏事件探针与必要时昵称OCR", "kill"),
    ("enemy_alive", "敌方存活数", "敌方顶部头像状态", "kill"),
    ("death", "死亡确认", "死亡面板/多证据确认", "death"),
    ("round_result", "回合胜负", "胜利/失败结果识别", "result"),
    ("whole_match_report", "结算页/战报", "五人卡片、Sage、K/OCR", "ocr"),
    ("highlight", "高光判定", ">=2杀+最后一人+存活+胜利/拆包条件", "kill"),
]


class ResourceDiagnosticRunner(QObject):
    progress_changed = Signal(int, str)
    board_requested = Signal(str, int)
    finished = Signal(bool, str, str)

    def __init__(self, cfg, brain_service, voice_service, speech_service, vision,
                 data_root, desktop_path, app_version="0.10.0.9", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.brain = brain_service
        self.voice = voice_service
        self.speech = speech_service
        self.vision = vision
        self.data_root = Path(data_root)
        self.desktop = Path(desktop_path)
        self.app_version = str(app_version)
        self._running = False
        self._sampling = False
        self._stage = "idle"
        self._started_monotonic = 0.0
        self._samples = []
        self._events = []
        self._proc_cache = {}
        self._gpu_total_cache = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        self._gpu_process_cache = []
        self._gpu_tick = 0
        self._last_vram = None
        self._vram_jumps = []
        self._coverage = {
            x[0]: {"status": "未观察到", "first_seen_t": None, "evidence": ""}
            for x in VISION_MODULES
        }
        self._real_match_end_reason = ""
        self.session_dir = None
        self.report_zip = None
        self._original_vision_enabled = bool(
            (cfg.get("vision", {}) if isinstance(cfg.get("vision"), dict) else {}).get("enabled", True)
        )

    def is_running(self):
        return bool(self._running)

    def start(self):
        if self._running:
            return False
        self._running = True
        threading.Thread(target=self._run, name="XiaoMeiliRealMatchResourceDiagnostic", daemon=True).start()
        return True

    def _emit_progress(self, value, text):
        self.progress_changed.emit(max(0, min(100, int(value))), str(text))

    def _event(self, kind, **payload):
        row = {
            "t": round(max(0.0, time.monotonic() - self._started_monotonic), 3),
            "stage": self._stage,
            "event": str(kind),
        }
        row.update(payload)
        self._events.append(row)

    def _set_stage(self, stage, progress, label):
        self._stage = str(stage)
        self._event("stage", label=str(label))
        self._emit_progress(progress, label)

    def _set_vision_enabled(self, enabled):
        try:
            self.cfg.setdefault("vision", {})["enabled"] = bool(enabled)
        except Exception:
            pass

    @staticmethod
    def _safe_float(value):
        try:
            v = float(value)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except Exception:
            return None

    def _nvidia_total(self):
        result = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        try:
            out = subprocess.check_output(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                text=True, timeout=2.5, creationflags=CREATE_NO_WINDOW, stderr=subprocess.DEVNULL,
            )
            parts = [x.strip() for x in str(out).strip().splitlines()[0].split(",")]
            if len(parts) >= 4:
                result = {
                    "gpu_util": self._safe_float(parts[0]),
                    "vram_used_mb": self._safe_float(parts[1]),
                    "vram_total_mb": self._safe_float(parts[2]),
                    "gpu_temp_c": self._safe_float(parts[3]),
                }
        except Exception:
            pass
        return result

    def _nvidia_processes(self):
        rows = []
        try:
            out = subprocess.check_output(
                ["nvidia-smi",
                 "--query-compute-apps=pid,process_name,used_gpu_memory",
                 "--format=csv,noheader,nounits"],
                text=True, timeout=2.5, creationflags=CREATE_NO_WINDOW, stderr=subprocess.DEVNULL,
            )
            for line in str(out).splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) < 3:
                    continue
                try:
                    pid = int(parts[0])
                except Exception:
                    continue
                rows.append({
                    "pid": pid,
                    "name": ",".join(parts[1:-1]).strip(),
                    "used_gpu_memory_mb": self._safe_float(parts[-1]),
                    "source": "nvidia-smi",
                })
        except Exception:
            pass
        # Windows/WDDM often returns N/A for per-process memory. Use the Windows
        # GPU Process Memory performance counter as a best-effort fallback.
        if os.name == "nt" and (not rows or not any(x.get("used_gpu_memory_mb") is not None for x in rows)):
            try:
                cmd = (
                    "$ErrorActionPreference='SilentlyContinue';"
                    "$s=(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples;"
                    "$s|ForEach-Object{"
                    "if($_.InstanceName -match 'pid_(\\d+)_'){"
                    "'{0},{1}' -f $matches[1],[int64]$_.CookedValue"
                    "}}"
                )
                out = subprocess.check_output(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                    text=True, timeout=5, creationflags=CREATE_NO_WINDOW, stderr=subprocess.DEVNULL,
                )
                per_pid = {}
                for line in str(out).splitlines():
                    parts = [x.strip() for x in line.split(",")]
                    if len(parts) != 2:
                        continue
                    try:
                        pid = int(parts[0]); used = int(parts[1])
                    except Exception:
                        continue
                    per_pid[pid] = max(per_pid.get(pid, 0), used)
                wrows = []
                for pid, used in per_pid.items():
                    try:
                        name = psutil.Process(pid).name()
                    except Exception:
                        name = ""
                    wrows.append({
                        "pid": pid,
                        "name": name,
                        "used_gpu_memory_mb": round(used / 1024 / 1024, 3),
                        "source": "windows-gpu-counter",
                    })
                if wrows:
                    rows = wrows
            except Exception:
                pass
        return rows

    def _process_rows(self):
        root = psutil.Process(os.getpid())
        by_pid = {int(root.pid): root}
        try:
            for p in root.children(recursive=True):
                by_pid.setdefault(int(p.pid), p)
        except Exception:
            pass
        live = []
        app_cpu = 0.0
        app_rss = 0
        for pid, p in list(by_pid.items()):
            try:
                cached = self._proc_cache.get(pid)
                if cached is None or not cached.is_running():
                    cached = p
                    self._proc_cache[pid] = cached
                    try:
                        cached.cpu_percent(interval=None)
                    except Exception:
                        pass
                cpu = float(cached.cpu_percent(interval=None))
                rss = int(cached.memory_info().rss)
                try:
                    ppid = int(cached.ppid())
                except Exception:
                    ppid = 0
                try:
                    cmd = " ".join(cached.cmdline()[:4])
                except Exception:
                    cmd = ""
                name = str(cached.name())
                app_cpu += cpu
                app_rss += rss
                live.append({
                    "pid": pid, "ppid": ppid, "name": name,
                    "cpu_percent": round(cpu, 3), "rss_bytes": rss,
                    "cmd_hint": cmd[:240],
                })
            except Exception:
                continue
        return live, app_cpu, app_rss

    def _vision_row(self):
        v = self.vision
        snap = dict(getattr(v, "last_snapshot", {}) or {})
        timings = dict(getattr(v, "timings", {}) or {})
        return {
            "backend": str(getattr(v, "backend_name", "") or ""),
            "game_found": bool(snap.get("game_found", False)),
            "foreground": snap.get("foreground"),
            "paused": snap.get("paused"),
            "match_context": bool(snap.get("match_context", getattr(v, "match_context", False))),
            "phase": str(snap.get("phase", getattr(v, "phase", "")) or ""),
            "state": str(snap.get("state", getattr(v, "current_display_state", "")) or ""),
            "alive": snap.get("alive", getattr(v, "alive_state", None)),
            "hp": snap.get("hp", getattr(v, "last_hp", None)),
            "low_hp": bool(snap.get("low_hp", getattr(v, "low_state", False))),
            "kill_count": int(snap.get("kill_count", getattr(v, "last_kill_count", 0)) or 0),
            "round_self_kills": int(snap.get("round_self_kills", getattr(v, "round_self_kills", 0)) or 0),
            "enemy_alive": int(snap.get("enemy_alive", getattr(v, "enemy_alive", 5)) or 0),
            "enemy_alive_confident": bool(snap.get("enemy_alive_confident", getattr(v, "enemy_alive_confident", False))),
            "death_latched": bool(snap.get("death_latched", getattr(v, "death_latched", False))),
            "win_score": self._safe_float(snap.get("win_score", getattr(v, "last_win_score", None))),
            "loss_score": self._safe_float(snap.get("loss_score", getattr(v, "last_loss_score", None))),
            "highlight_triggered": bool(snap.get("highlight_triggered", getattr(v, "highlight_triggered", False))),
            "highlight_event_id": int(snap.get("highlight_event_id", getattr(v, "highlight_event_id", 0)) or 0),
            "report_done": bool(snap.get("report_done", getattr(v, "report_done", False))),
            "report_waiting_result": bool(snap.get("report_waiting_result", getattr(v, "report_waiting_result", False))),
            "report_capture_active": bool(snap.get("report_capture_active", getattr(v, "report_capture_active", False))),
            "report_snapshot_locked": bool(snap.get("report_snapshot_locked", getattr(v, "report_snapshot_locked", False))),
            "report_parse_status": str(snap.get("report_parse_status", getattr(v, "report_parse_status", "")) or ""),
            "scan_fps": self._safe_float(getattr(v, "scan_fps", None)),
            "cpu_estimate": self._safe_float(getattr(v, "cpu_estimate", None)),
            "ocr_trigger_count": int(getattr(v, "ocr_trigger_count", 0) or 0),
            "hp_read_count": int(getattr(v, "hp_read_count", 0) or 0),
            "skipped_cycles": int(getattr(v, "skipped_cycles", 0) or 0),
            "timings": timings,
        }

    def _mark_coverage(self, module_id, evidence):
        rec = self._coverage.get(module_id)
        if not rec or rec["status"] == "已实测":
            return
        rec["status"] = "已实测"
        rec["first_seen_t"] = round(max(0.0, time.monotonic() - self._started_monotonic), 3)
        rec["evidence"] = str(evidence or "")[:240]
        self._event("coverage", module=module_id, evidence=rec["evidence"])

    def _update_coverage(self, v):
        if v.get("game_found") and v.get("backend"):
            self._mark_coverage("shared_capture", f"backend={v.get('backend')}")
        if v.get("match_context"):
            self._mark_coverage("match_context", f"phase={v.get('phase')}")
        if v.get("alive") is not None:
            self._mark_coverage("sage_alive", f"alive={v.get('alive')}")
        if int(v.get("hp_read_count") or 0) > 0 or v.get("hp") is not None:
            extra = " low_hp=true" if v.get("low_hp") else ""
            self._mark_coverage("hp", f"hp={v.get('hp')} reads={v.get('hp_read_count')}{extra}")
        if int(v.get("kill_count") or 0) > 0 or int(v.get("round_self_kills") or 0) > 0:
            self._mark_coverage("killfeed", f"kill_count={v.get('kill_count')} round_self_kills={v.get('round_self_kills')}")
        if v.get("enemy_alive_confident"):
            self._mark_coverage("enemy_alive", f"enemy_alive={v.get('enemy_alive')}")
        if v.get("death_latched"):
            self._mark_coverage("death", "death_latched=true")
        result_threshold = float((self.cfg.get("vision", {}) or {}).get("result_threshold", 0.75) or 0.75)
        if v.get("state") in ("victory", "defeat") or (v.get("win_score") or 0) >= result_threshold or (v.get("loss_score") or 0) >= result_threshold:
            self._mark_coverage("round_result", f"state={v.get('state')} win={v.get('win_score')} loss={v.get('loss_score')}")
        if v.get("report_done") or v.get("report_snapshot_locked"):
            self._mark_coverage("whole_match_report", f"done={v.get('report_done')} locked={v.get('report_snapshot_locked')}")
        if v.get("highlight_triggered") or int(v.get("highlight_event_id") or 0) > 0:
            self._mark_coverage("highlight", f"event_id={v.get('highlight_event_id')}")

    def _sample_once(self):
        self._gpu_tick += 1
        if self._gpu_tick == 1 or self._gpu_tick % GPU_TOTAL_INTERVAL_SAMPLES == 0:
            self._gpu_total_cache = self._nvidia_total()
        if self._gpu_tick == 1 or self._gpu_tick % GPU_PROCESS_INTERVAL_SAMPLES == 0:
            self._gpu_process_cache = self._nvidia_processes()
        gpu = dict(self._gpu_total_cache)
        proc_rows, app_cpu, app_rss = self._process_rows()
        vm = psutil.virtual_memory()
        vision_row = self._vision_row()
        row = {
            "t": round(max(0.0, time.monotonic() - self._started_monotonic), 3),
            "stage": self._stage,
            "system_cpu_percent": round(float(psutil.cpu_percent(interval=None)), 3),
            "system_ram_percent": round(float(vm.percent), 3),
            "app_cpu_percent": round(float(app_cpu), 3),
            "app_rss_bytes": int(app_rss),
            "gpu_util_percent": gpu.get("gpu_util"),
            "vram_used_mb": gpu.get("vram_used_mb"),
            "vram_total_mb": gpu.get("vram_total_mb"),
            "gpu_temp_c": gpu.get("gpu_temp_c"),
            "processes": proc_rows,
            "gpu_processes": list(self._gpu_process_cache),
            "vision": vision_row,
        }
        self._samples.append(row)
        if self._stage in ("waiting_real_match", "real_match"):
            self._update_coverage(vision_row)
        cur_vram = self._safe_float(row.get("vram_used_mb"))
        if cur_vram is not None and self._last_vram is not None:
            delta = cur_vram - self._last_vram
            if delta >= VRAM_JUMP_MB:
                evt = {
                    "t": row["t"], "stage": self._stage,
                    "from_mb": round(self._last_vram, 1),
                    "to_mb": round(cur_vram, 1),
                    "delta_mb": round(delta, 1),
                    "gpu_processes": list(self._gpu_process_cache),
                }
                self._vram_jumps.append(evt)
                self._event("vram_jump", **evt)
        if cur_vram is not None:
            self._last_vram = cur_vram

    def _sampler_loop(self):
        psutil.cpu_percent(interval=None)
        self._sample_once()
        while self._sampling:
            started = time.monotonic()
            self._sample_once()
            wait = SAMPLE_INTERVAL_SECONDS - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)

    def _sleep(self, seconds):
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            time.sleep(min(0.20, max(0.01, deadline - time.monotonic())))

    def _wait_for_real_match(self):
        self._set_vision_enabled(True)
        self._set_stage(
            "waiting_real_match", 3,
            "等待真实对局：请切回 VALORANT 正常进入一局游戏；检测到真实 HUD 后会自动开始实战采集"
        )
        deadline = time.monotonic() + REAL_MATCH_WAIT_SECONDS
        last_label = 0.0
        while time.monotonic() < deadline:
            v = self._vision_row()
            self._update_coverage(v)
            if v.get("game_found") and v.get("foreground") is not False and v.get("match_context"):
                self._event("real_match_detected", backend=v.get("backend"), phase=v.get("phase"))
                return
            now = time.monotonic()
            if now - last_label >= 5.0:
                state = (
                    f"等待真实对局｜游戏窗口={'已找到' if v.get('game_found') else '未找到'}"
                    f"｜前台={v.get('foreground')}｜实战HUD={'是' if v.get('match_context') else '否'}"
                )
                self._emit_progress(4, state)
                last_label = now
            time.sleep(0.25)
        raise TimeoutError("30分钟内没有检测到真实 VALORANT 对局 HUD，本次诊断停止。")

    def _collect_real_match(self):
        self._set_stage(
            "real_match", 8,
            "实战采集中：现在只需要正常打一局，不要为了测试刻意改变玩法；小美丽会自动记录真实资源和识别事件"
        )
        started = time.monotonic()
        waiting_result_since = None
        lost_match_since = None
        last_status = 0.0
        while time.monotonic() - started < REAL_MATCH_MAX_SECONDS:
            v = self._vision_row()
            self._update_coverage(v)
            now = time.monotonic()
            if v.get("match_context"):
                waiting_result_since = None
                lost_match_since = None
            else:
                if v.get("report_done") or v.get("report_snapshot_locked"):
                    self._real_match_end_reason = "结算页已锁定/解析"
                    break
                if v.get("report_waiting_result") or v.get("report_capture_active"):
                    if waiting_result_since is None:
                        waiting_result_since = now
                    if now - waiting_result_since >= REAL_MATCH_END_GRACE_SECONDS:
                        self._real_match_end_reason = "已进入赛后结算等待"
                        break
                elif v.get("game_found"):
                    if lost_match_since is None:
                        lost_match_since = now
                    # A full minute outside match context after a real match started
                    # is treated as post-match/lobby fallback only if report watcher did not fire.
                    if now - lost_match_since >= 60.0:
                        self._real_match_end_reason = "真实对局HUD已结束超过60秒"
                        break
            if now - last_status >= 5.0:
                done = sum(1 for rec in self._coverage.values() if rec.get("status") == "已实测")
                elapsed = int(now - started)
                pct = min(52, 8 + int(elapsed / 60))
                self._emit_progress(
                    pct,
                    f"实战采集中｜已覆盖 {done}/{len(self._coverage)} 个识别模块｜已记录 {elapsed//60}分{elapsed%60:02d}秒"
                )
                last_status = now
            time.sleep(0.25)
        else:
            self._real_match_end_reason = "实战采集达到75分钟上限"
        self._event("real_match_finished", reason=self._real_match_end_reason, coverage=self._coverage)

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
                voiced = (
                    0.55 * math.sin(2 * math.pi * f0 * t)
                    + 0.24 * math.sin(2 * math.pi * f0 * 2 * t)
                    + 0.12 * math.sin(2 * math.pi * (520 + 35 * (syllable % 4)) * t)
                )
                value = 0.27 * env * voiced
            pcm.append(int(max(-1.0, min(1.0, value)) * 32767))
        with wave.open(str(path), "xb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return path

    @staticmethod
    def _parse_event_line(line):
        line = str(line or "").strip()
        if not line.startswith("XMEVENT|"):
            return None
        try:
            return json.loads(line[len("XMEVENT|"):])
        except Exception:
            return None

    def _speech_start_resident(self, wav_path, repeat=SPEECH_RUNS, hold_seconds=30):
        proc = self.speech.diagnostic_process_v01005(
            str(wav_path), repeat=int(repeat), hold_seconds=int(hold_seconds)
        )
        events = []
        ready = False
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
        self._event("speech_diagnostic", pid=int(proc.pid), ready=ready, events=events)
        if not ready:
            try:
                proc.terminate()
            except Exception:
                pass
            raise RuntimeError("FSMN-VAD + Fun-ASR-Nano-2512 诊断进程未进入驻留状态")
        return proc

    def _cloud_brain_probe(self):
        c = cloud_cfg(self.cfg)
        if c.get("mode") == "local":
            self._event("cloud_brain_probe", skipped=True, reason="local mode")
            return
        key = load_api_key()
        if not key:
            self._event("cloud_brain_probe", skipped=True, reason="API key unavailable")
            return
        ok, msg, ms = test_brain_connection(
            key, c.get("brain_base_url"), c.get("brain_model"), timeout=10
        )
        self._event("cloud_brain_probe", ok=bool(ok), elapsed_ms=ms, message=str(msg)[:240])

    def _cloud_tts_probe(self):
        if not getattr(self.voice, "cloud_ready", lambda: False)():
            self._event("cloud_tts_probe", skipped=True, reason="cloud TTS unavailable")
            return
        tag = "resource_diag_v01009"
        try:
            self.voice.speak(
                "资源诊断，声音链路正常。",
                "", 1.0,
                str((self.cfg.get("voice", {}) or {}).get("output_device", "default") or "default"),
                tag=tag,
                extra_instruct="",
            )
            deadline = time.monotonic() + 20
            seen = False
            while time.monotonic() < deadline:
                active = bool(self.voice.cloud_stream_in_progress(tag))
                seen = seen or active
                if seen and not active:
                    break
                time.sleep(0.10)
            self._event("cloud_tts_probe", ok=True, latency=getattr(self.voice, "last_cloud_latency", lambda: {})())
        except Exception as exc:
            self._event("cloud_tts_probe", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _stage_summary(self, stage, isolated_vram):
        rows = [r for r in self._samples if r.get("stage") == stage]
        if not rows:
            return {"stage": stage, "samples": 0}
        def vals(key):
            return [float(r[key]) for r in rows if r.get(key) is not None]
        vram = vals("vram_used_mb")
        gpu = vals("gpu_util_percent")
        cpu = vals("system_cpu_percent")
        appcpu = vals("app_cpu_percent")
        appram = [float(r.get("app_rss_bytes") or 0) / 1024 / 1024 for r in rows]
        result = {
            "stage": stage,
            "samples": len(rows),
            "vram_median_mb": round(statistics.median(vram), 1) if vram else None,
            "vram_peak_mb": round(max(vram), 1) if vram else None,
            "gpu_peak_percent": round(max(gpu), 1) if gpu else None,
            "system_cpu_peak_percent": round(max(cpu), 1) if cpu else None,
            "app_cpu_peak_percent": round(max(appcpu), 1) if appcpu else None,
            "app_process_rss_sum_peak_mb": round(max(appram), 1) if appram else None,
        }
        if vram and isolated_vram is not None:
            result["vram_peak_delta_vs_isolated_mb"] = round(max(vram) - float(isolated_vram), 1)
        return result

    def _write_reports(self):
        isolated_rows = [r for r in self._samples if r.get("stage") == "isolated_baseline" and r.get("vram_used_mb") is not None]
        isolated_vram = statistics.median([float(r["vram_used_mb"]) for r in isolated_rows]) if isolated_rows else None

        with (self.session_dir / "timeline_250ms.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","system_cpu_percent","system_ram_percent","app_cpu_percent",
                        "app_process_rss_sum_mb","gpu_util_percent","vram_used_mb","vram_total_mb","gpu_temp_c"])
            for r in self._samples:
                w.writerow([r.get("t"),r.get("stage"),r.get("system_cpu_percent"),r.get("system_ram_percent"),
                            r.get("app_cpu_percent"),round(float(r.get("app_rss_bytes") or 0)/1024/1024,2),
                            r.get("gpu_util_percent"),r.get("vram_used_mb"),r.get("vram_total_mb"),r.get("gpu_temp_c")])

        with (self.session_dir / "process_tree.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","pid","ppid","name","cpu_percent","rss_mb","cmd_hint"])
            for r in self._samples:
                for p in r.get("processes") or []:
                    w.writerow([r.get("t"),r.get("stage"),p.get("pid"),p.get("ppid"),p.get("name"),
                                p.get("cpu_percent"),round(float(p.get("rss_bytes") or 0)/1024/1024,2),p.get("cmd_hint")])

        with (self.session_dir / "process_gpu.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","pid","process_name","used_gpu_memory_mb","source"])
            for r in self._samples:
                for p in r.get("gpu_processes") or []:
                    w.writerow([r.get("t"),r.get("stage"),p.get("pid"),p.get("name"),p.get("used_gpu_memory_mb"),p.get("source")])

        with (self.session_dir / "vision_timeline.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "t_seconds","stage","backend","game_found","foreground","paused","match_context","phase","state",
                "alive","hp","low_hp","kill_count","round_self_kills","enemy_alive","enemy_alive_confident",
                "death_latched","win_score","loss_score","highlight_triggered","highlight_event_id",
                "report_done","report_waiting_result","report_capture_active","report_snapshot_locked",
                "scan_fps","vision_cpu_estimate","ocr_trigger_count","hp_read_count","skipped_cycles","timings_json"
            ])
            for r in self._samples:
                v = r.get("vision") or {}
                w.writerow([
                    r.get("t"),r.get("stage"),v.get("backend"),v.get("game_found"),v.get("foreground"),v.get("paused"),
                    v.get("match_context"),v.get("phase"),v.get("state"),v.get("alive"),v.get("hp"),v.get("low_hp"),
                    v.get("kill_count"),v.get("round_self_kills"),v.get("enemy_alive"),v.get("enemy_alive_confident"),
                    v.get("death_latched"),v.get("win_score"),v.get("loss_score"),v.get("highlight_triggered"),
                    v.get("highlight_event_id"),v.get("report_done"),v.get("report_waiting_result"),
                    v.get("report_capture_active"),v.get("report_snapshot_locked"),v.get("scan_fps"),v.get("cpu_estimate"),
                    v.get("ocr_trigger_count"),v.get("hp_read_count"),v.get("skipped_cycles"),
                    json.dumps(v.get("timings") or {}, ensure_ascii=False)
                ])

        with (self.session_dir / "real_match_coverage.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id","name","status","first_seen_t","evidence"])
            names = {x[0]: x[1] for x in VISION_MODULES}
            for module_id, rec in self._coverage.items():
                w.writerow([module_id,names.get(module_id,module_id),rec.get("status"),rec.get("first_seen_t"),rec.get("evidence")])

        with (self.session_dir / "vram_jump_events.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","from_mb","to_mb","delta_mb","gpu_processes_json"])
            for evt in self._vram_jumps:
                w.writerow([evt.get("t"),evt.get("stage"),evt.get("from_mb"),evt.get("to_mb"),evt.get("delta_mb"),
                            json.dumps(evt.get("gpu_processes") or [], ensure_ascii=False)])

        topo = {
            "app_version": self.app_version,
            "current_architecture_already_unified": True,
            "screen_grabber_instances_in_vision_worker": 1,
            "continuous_capture_thread": False,
            "backend_at_report": str(getattr(self.vision, "backend_name", "") or ""),
            "owner": "VisionWorker.run",
            "note": "当前识别链使用同一个 ScreenGrabber 按需抓取各 ROI；V0.10.0.9 在真实对局中测量，不重写识别算法。",
            "modules": [{"id":x[0],"name":x[1],"description":x[2],"timing_key":x[3]} for x in VISION_MODULES],
        }
        (self.session_dir / "capture_topology.json").write_text(
            json.dumps(topo, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        stages_order = [
            "waiting_real_match","real_match","postmatch_runtime","isolated_baseline",
            "whiteboard_only","speech_input_only","speech_cooldown",
            "cloud_brain","cloud_tts","combined_postgame","final_cooldown",
        ]
        stage_summary = [self._stage_summary(x, isolated_vram) for x in stages_order]
        covered = sum(1 for x in self._coverage.values() if x.get("status") == "已实测")

        meta = {
            "app_version": self.app_version,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "gpu_total_query_interval_seconds": SAMPLE_INTERVAL_SECONDS * GPU_TOTAL_INTERVAL_SAMPLES,
            "gpu_process_query_interval_seconds": SAMPLE_INTERVAL_SECONDS * GPU_PROCESS_INTERVAL_SAMPLES,
            "cpu_logical": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total/1024/1024/1024,2),
            "isolated_vram_mb": round(isolated_vram,1) if isolated_vram is not None else None,
            "speech_execution_device": "cpu (Fun-ASR-Nano-2512 and FSMN-VAD are explicitly loaded with device=cpu)",
            "real_match_end_reason": self._real_match_end_reason,
            "vision_coverage": f"{covered}/{len(self._coverage)}",
            "vram_jump_threshold_mb": VRAM_JUMP_MB,
            "privacy": "不保存用户聊天、记忆、养成库、API Key、账号昵称、游戏截图或麦克风录音。",
            "safety": "仅创建新的诊断文件和ZIP；不删除、不移动、不覆盖、不镜像清理任何用户文件。",
        }
        payload = {
            "meta":meta,
            "stages":stage_summary,
            "coverage":self._coverage,
            "vram_jumps":self._vram_jumps,
            "events":self._events,
        }
        (self.session_dir / "summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        (self.session_dir / "events.json").write_text(json.dumps(self._events,ensure_ascii=False,indent=2),encoding="utf-8")

        title = {
            "waiting_real_match":"等待真实对局",
            "real_match":"真实对局实战采集",
            "postmatch_runtime":"实战结束后的真实运行状态",
            "isolated_baseline":"隔离后的纯小美丽基线",
            "whiteboard_only":"仅白板/说话动画",
            "speech_input_only":"FSMN-VAD + Fun-ASR-Nano-2512",
            "speech_cooldown":"语音输入退出后",
            "cloud_brain":"云端 Qwen3-8B",
            "cloud_tts":"云端 Qwen-Audio 复刻TTS",
            "combined_postgame":"赛后综合：ASR + 云端双引擎 + 白板",
            "final_cooldown":"最终冷却",
        }
        lines = [
            f"小美丽 V{self.app_version} 实战全模块深度资源诊断",
            "="*62, "",
            f"真实对局识别覆盖：{covered}/{len(self._coverage)}",
            f"实战结束判定：{self._real_match_end_reason or '未记录'}",
            f"检测到 >= {int(VRAM_JUMP_MB)}MB 的显存跳变次数：{len(self._vram_jumps)}",
            f"隔离基线显存中位数：{meta['isolated_vram_mb']} MB",
            "",
            "实战识别覆盖：",
        ]
        names = {x[0]: x[1] for x in VISION_MODULES}
        for module_id, rec in self._coverage.items():
            lines.append(
                f"- {names.get(module_id,module_id)}：{rec.get('status')}"
                + (f"｜{rec.get('evidence')}" if rec.get("evidence") else "")
            )
        lines.extend(["", "阶段资源结果："])
        for row in stage_summary:
            name = title.get(row["stage"],row["stage"])
            if not row.get("samples"):
                lines.append(f"- {name}: 无采样")
                continue
            lines.append(
                f"- {name}: 显存峰值 {row.get('vram_peak_mb')} MB"
                f"｜较隔离基线 {row.get('vram_peak_delta_vs_isolated_mb')} MB"
                f"｜GPU峰值 {row.get('gpu_peak_percent')}%"
                f"｜小美丽子进程RSS合计峰值 {row.get('app_process_rss_sum_peak_mb')} MB"
                f"｜CPU峰值 {row.get('app_cpu_peak_percent')}%"
            )
        lines.extend(["", "显存突增事件："])
        if self._vram_jumps:
            for evt in self._vram_jumps[:20]:
                lines.append(
                    f"- t={evt.get('t')}s｜{evt.get('stage')}｜{evt.get('from_mb')}→{evt.get('to_mb')}MB｜+{evt.get('delta_mb')}MB"
                )
        else:
            lines.append("- 本次没有检测到单次 >=512MB 的显存跳变。")

        names2 = {}
        for r in self._samples:
            for p in r.get("processes") or []:
                n = str(p.get("name") or "").lower()
                if n in ("llama-server.exe","python.exe","python"):
                    key=(n,int(p.get("pid") or 0))
                    rec=names2.setdefault(key,{"rss":0.0,"cpu":0.0,"stages":set()})
                    rec["rss"]=max(rec["rss"],float(p.get("rss_bytes") or 0)/1024/1024)
                    rec["cpu"]=max(rec["cpu"],float(p.get("cpu_percent") or 0))
                    rec["stages"].add(str(r.get("stage")))
        lines.extend(["","重点进程："])
        if names2:
            for (n,pid),rec in sorted(names2.items()):
                lines.append(f"- {n} PID {pid}: RAM峰值 {rec['rss']:.1f} MB｜CPU峰值 {rec['cpu']:.1f}%｜阶段 {','.join(sorted(rec['stages']))}")
        else:
            lines.append("- 未检测到 llama-server/Python 子进程。")

        lines.extend([
            "",
            "说明：进程组RAM使用各进程RSS相加，只用于阶段比较，不等同于系统唯一物理内存占用。",
            "请直接把本 ZIP 上传给 ChatGPT；不需要再截图任务管理器。",
            "安全：报告不含 API Key、聊天内容、长期记忆、养成库、昵称、游戏截图或麦克风录音。",
        ])
        (self.session_dir / "请上传给ChatGPT_实战全模块资源诊断摘要.txt").write_text("\n".join(lines),encoding="utf-8-sig")

        self.desktop.mkdir(parents=True, exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        target=self.desktop/f"小美丽_实战全模块资源诊断_{stamp}.zip"
        n=1
        while target.exists():
            target=self.desktop/f"小美丽_实战全模块资源诊断_{stamp}_{n}.zip"; n+=1
        include = {
            "timeline_250ms.csv","process_tree.csv","process_gpu.csv","vision_timeline.csv",
            "capture_topology.json","real_match_coverage.csv","vram_jump_events.csv",
            "summary.json","events.json","请上传给ChatGPT_实战全模块资源诊断摘要.txt",
            "speech_diagnostic_worker.log",
        }
        with zipfile.ZipFile(target,mode="x",compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(self.session_dir.iterdir()):
                if path.is_file() and path.name in include:
                    zf.write(path,arcname=path.name)
        self.report_zip=target
        return target

    def _terminate_diag_proc(self, proc):
        if not proc:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=8)
        except Exception:
            pass

    def _run(self):
        self._started_monotonic=time.monotonic()
        token=f"{int(time.time())}_{os.getpid()}"
        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v01009_{token}"
        self.session_dir.mkdir(parents=True,exist_ok=False)
        wav_path=None
        self._sampling=True
        sampler=threading.Thread(target=self._sampler_loop,name="XiaoMeiliResourceSamplerV01009",daemon=True)
        sampler.start()
        ok=True
        error_text=""
        speech_proc=None
        combined_proc=None
        offline_started=False
        try:
            # Real match comes first. Do not stop/restart any XiaoMeili component
            # while the user is playing. This preserves the exact normal runtime.
            self._wait_for_real_match()
            self._collect_real_match()

            self._set_stage("postmatch_runtime",56,"实战结束：先记录10秒真实运行状态，然后自动执行剩余模块测试")
            self._sleep(10)

            # From here onward the user no longer needs to interact.
            setattr(self.speech,"_resource_diagnostic_active",True)
            offline_started=True
            wav_path=self._make_test_wav(self.session_dir/"diagnostic_input.wav")

            self._set_stage("preparing",60,"赛后隔离组件：停止小美丽AI/语音并暂停画面识别，等待资源回落")
            try:self.speech.stop()
            except Exception:pass
            try:self.brain.shutdown()
            except Exception:pass
            try:self.voice.shutdown()
            except Exception:pass
            self._set_vision_enabled(False)
            self._sleep(7)

            self._set_stage("isolated_baseline",64,"记录隔离后的纯小美丽基线")
            self._sleep(8)

            self._set_stage("whiteboard_only",68,"单独测试白板/说话动画")
            self.board_requested.emit("实战资源诊断：仅白板动画",7000)
            self._sleep(8)

            self._set_stage("speech_input_only",73,"单独测试 FSMN-VAD + Fun-ASR-Nano-2512：CPU加载/推理/驻留")
            speech_proc=self._speech_start_resident(wav_path,SPEECH_RUNS,35)
            self._sleep(15)
            self._terminate_diag_proc(speech_proc); speech_proc=None

            self._set_stage("speech_cooldown",79,"观察语音输入退出后的资源回落")
            self._sleep(8)

            self._set_stage("cloud_brain",83,"测试当前云端 Qwen3-8B 链路")
            self._cloud_brain_probe()
            self._sleep(5)

            self._set_stage("cloud_tts",87,"测试当前云端复刻音色 TTS 链路")
            self._cloud_tts_probe()
            self._sleep(5)

            self._set_stage("combined_postgame",91,"赛后综合压力：语音输入 + 云端双引擎 + 白板")
            combined_proc=self._speech_start_resident(wav_path,2,55)
            self.board_requested.emit("实战资源诊断：赛后综合压力测试",18000)
            self._cloud_brain_probe()
            self._cloud_tts_probe()
            self._sleep(16)
            self._terminate_diag_proc(combined_proc); combined_proc=None
            try:self.voice.shutdown()
            except Exception:pass
            try:self.brain.shutdown()
            except Exception:pass

            self._set_stage("final_cooldown",95,"最终冷却：确认组件退出后资源是否回落")
            self._sleep(12)
        except Exception as exc:
            ok=False
            error_text=f"{type(exc).__name__}: {exc}"
            self._event("error",message=error_text)
        finally:
            self._terminate_diag_proc(speech_proc)
            self._terminate_diag_proc(combined_proc)
            if offline_started:
                try:self.speech.stop()
                except Exception:pass
                try:self.brain.shutdown()
                except Exception:pass
                try:self.voice.shutdown()
                except Exception:pass
            self._set_vision_enabled(self._original_vision_enabled)
            self._sampling=False
            try:sampler.join(timeout=3)
            except Exception:pass
            setattr(self.speech,"_resource_diagnostic_active",False)

        try:
            self._set_stage("report",98,"正在生成脱敏实战诊断 ZIP")
            report=self._write_reports()
            self._emit_progress(100,"测试完成，桌面实战诊断包已生成")
            msg=(f"诊断完成：{report}" if ok else
                 f"部分阶段失败，但已生成可分析报告：{report}\n{error_text}")
            self.finished.emit(ok,str(report),msg)
        except Exception as exc:
            self.finished.emit(False,"",f"生成诊断报告失败：{type(exc).__name__}: {exc}")
        finally:
            self._running=False
