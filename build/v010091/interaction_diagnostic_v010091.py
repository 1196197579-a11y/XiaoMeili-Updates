# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.9.1 long-running real interaction resource diagnostic.

The runner is passive by design:
- it never starts/stops/restarts AI, ASR, TTS, vision or whiteboard components
- it never sends synthetic requests
- it never changes user settings
- it records no chat text, microphone audio, screenshots, API keys, nicknames or memories
- stopping the diagnostic only stops sampling and creates a new report ZIP
- no existing user file is deleted, moved, purged, mirrored or overwritten
"""
from __future__ import annotations

import csv
import json
import math
import os
import platform
import statistics
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, Signal

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAMPLE_INTERVAL_SECONDS = 0.25
GPU_TOTAL_INTERVAL_SAMPLES = 4       # refresh total VRAM about once per second
GPU_PROCESS_INTERVAL_SAMPLES = 8     # refresh per-process GPU memory about every 2s
VRAM_JUMP_WARN_MB = 256.0
VRAM_JUMP_MAJOR_MB = 512.0

_ACTIVE_LOCK = threading.RLock()
_ACTIVE_RUNNER = None


def _set_active(runner):
    global _ACTIVE_RUNNER
    with _ACTIVE_LOCK:
        _ACTIVE_RUNNER = runner


def interaction_diag_note(kind, **payload):
    """Record a metadata-only event if a diagnostic is active.

    Callers must not pass user text. The function also strips suspicious keys so
    an accidental future caller cannot leak conversation/API content into reports.
    """
    with _ACTIVE_LOCK:
        runner = _ACTIVE_RUNNER
    if runner is None:
        return
    blocked = ("text", "question", "answer", "prompt", "content", "api", "key", "token", "nickname", "memory", "audio")
    clean = {}
    for k, v in payload.items():
        key = str(k)
        if any(x in key.lower() for x in blocked):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            clean[key] = v
    runner.note_event(str(kind), **clean)


class InteractionDiagnosticRunner(QObject):
    status_changed = Signal(str)
    elapsed_changed = Signal(str)
    finished = Signal(bool, str, str)

    def __init__(self, cfg, brain_service, voice_service, speech_service, pet,
                 data_root, desktop_path, app_version="0.10.0.9.1", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.brain = brain_service
        self.voice = voice_service
        self.speech = speech_service
        self.pet = pet
        self.data_root = Path(data_root)
        self.desktop = Path(desktop_path)
        self.app_version = str(app_version)
        self._running = False
        self._stop = threading.Event()
        self._started_monotonic = 0.0
        self._samples = []
        self._events = []
        self._events_lock = threading.RLock()
        self._proc_cache = {}
        self._gpu_total_cache = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        self._gpu_process_cache = []
        self._gpu_tick = 0
        self._last_vram = None
        self._vram_jumps = []
        self._turn_seq = 0
        self._turns = []
        self._open_turn = None
        self.session_dir = None
        self.report_zip = None

    def is_running(self):
        return bool(self._running)

    def start(self):
        if self._running:
            return False
        self._running = True
        self._stop.clear()
        self._started_monotonic = time.monotonic()
        token = f"{int(time.time())}_{os.getpid()}"
        self.session_dir = self.data_root/"diagnostics"/"interaction"/f"v010091_{token}"
        self.session_dir.mkdir(parents=True, exist_ok=False)
        _set_active(self)
        self.note_event("diagnostic_start")
        threading.Thread(target=self._run, name="XiaoMeiliInteractionDiagnostic", daemon=True).start()
        return True

    def stop_and_report(self):
        if not self._running:
            return False
        self.note_event("diagnostic_stop_requested")
        self._stop.set()
        return True

    def note_event(self, kind, **payload):
        t = round(max(0.0, time.monotonic() - self._started_monotonic), 3)
        row = {"t": t, "event": str(kind)}
        row.update(payload)
        with self._events_lock:
            self._events.append(row)
            if kind == "turn_start":
                if self._open_turn is not None:
                    self._open_turn["end_t"] = t
                    self._open_turn["end_reason"] = "next_turn_started"
                self._turn_seq += 1
                self._open_turn = {
                    "turn": self._turn_seq,
                    "start_t": t,
                    "end_t": None,
                    "end_reason": "",
                    "events": [str(kind)],
                }
                self._turns.append(self._open_turn)
            elif self._open_turn is not None:
                self._open_turn["events"].append(str(kind))
                if kind in ("turn_end", "speech_session_end", "voice_interrupt"):
                    self._open_turn["end_t"] = t
                    self._open_turn["end_reason"] = str(kind)
                    self._open_turn = None

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

        # WDDM often reports N/A via nvidia-smi. Use Windows dedicated GPU memory
        # performance counters as a best-effort fallback.
        if os.name == "nt" and (not rows or not any(x.get("used_gpu_memory_mb") is not None for x in rows)):
            try:
                cmd = (
                    "$ErrorActionPreference='SilentlyContinue';"
                    "$s=(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples;"
                    "$s|ForEach-Object{if($_.InstanceName -match 'pid_(\\d+)_'){"
                    "'{0},{1}' -f $matches[1],[int64]$_.CookedValue}}"
                )
                out = subprocess.check_output(
                    ["powershell.exe","-NoProfile","-NonInteractive","-Command",cmd],
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
                if per_pid:
                    rows = []
                    for pid, used in per_pid.items():
                        try:
                            name = psutil.Process(pid).name()
                        except Exception:
                            name = ""
                        rows.append({
                            "pid": pid, "name": name,
                            "used_gpu_memory_mb": round(used/1024/1024, 3),
                            "source": "windows-gpu-counter",
                        })
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
        rows = []
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
                name = str(cached.name())
                app_cpu += cpu
                app_rss += rss
                rows.append({
                    "pid": pid, "ppid": ppid, "name": name,
                    "cpu_percent": round(cpu, 3), "rss_bytes": rss,
                })
            except Exception:
                continue
        return rows, app_cpu, app_rss

    @staticmethod
    def _qsize(q):
        try:
            return int(q.qsize())
        except Exception:
            return None

    def _runtime_state(self):
        # Metadata only. Never read text/prompt/audio payloads.
        cloud = getattr(self.voice, "_cloud_active", None)
        if isinstance(cloud, dict):
            tts_queue = self._qsize(cloud.get("queue"))
            tts_active = True
            tts_finished = bool(cloud.get("finished", False))
            tts_aborted = bool(cloud.get("aborted", False))
            tts_stream_open = cloud.get("stream") is not None
        else:
            tts_queue = 0
            tts_active = False
            tts_finished = False
            tts_aborted = False
            tts_stream_open = False

        speech_worker = getattr(self.speech, "_worker", None)
        try:
            speech_pid = int(speech_worker.pid) if speech_worker is not None and speech_worker.poll() is None else 0
        except Exception:
            speech_pid = 0

        threads = threading.enumerate()
        thread_names = {}
        for th in threads:
            n = str(getattr(th, "name", "") or "unnamed")
            group = (
                "QwenAudioTTS" if "QwenAudio" in n else
                "Speech" if "Speech" in n else
                "Brain" if "Brain" in n else
                "OtherXiaoMeili" if "XiaoMeili" in n else
                "Other"
            )
            thread_names[group] = thread_names.get(group, 0) + 1

        return {
            "thread_count": len(threads),
            "thread_groups": thread_names,
            "speech_worker_pid": speech_pid,
            "speech_reader_alive": bool(getattr(getattr(self.speech, "_reader_thread", None), "is_alive", lambda: False)()),
            "brain_generate_busy": bool(getattr(self.brain, "_generate_busy", False)),
            "brain_cloud_response_open": getattr(self.brain, "_cloud_response", None) is not None,
            "tts_cloud_active": tts_active,
            "tts_queue_size": tts_queue,
            "tts_finished": tts_finished,
            "tts_aborted": tts_aborted,
            "tts_audio_stream_open": tts_stream_open,
            "whiteboard_active": bool(getattr(self.pet, "dialogue_board_active", False)),
            "dialogue_indicator_visible": bool(getattr(getattr(self.pet, "dialogue_indicator", None), "isVisible", lambda: False)()),
        }

    def _sample_once(self):
        self._gpu_tick += 1
        if self._gpu_tick == 1 or self._gpu_tick % GPU_TOTAL_INTERVAL_SAMPLES == 0:
            self._gpu_total_cache = self._nvidia_total()
        if self._gpu_tick == 1 or self._gpu_tick % GPU_PROCESS_INTERVAL_SAMPLES == 0:
            self._gpu_process_cache = self._nvidia_processes()
        gpu = dict(self._gpu_total_cache)
        proc_rows, app_cpu, app_rss = self._process_rows()
        vm = psutil.virtual_memory()
        runtime = self._runtime_state()
        t = round(max(0.0, time.monotonic() - self._started_monotonic), 3)
        row = {
            "t": t,
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
            "runtime": runtime,
        }
        self._samples.append(row)

        cur = self._safe_float(row.get("vram_used_mb"))
        if cur is not None and self._last_vram is not None:
            delta = cur - self._last_vram
            if delta >= VRAM_JUMP_WARN_MB:
                severity = "major" if delta >= VRAM_JUMP_MAJOR_MB else "warn"
                evt = {
                    "t": t, "severity": severity,
                    "from_mb": round(self._last_vram,1),
                    "to_mb": round(cur,1),
                    "delta_mb": round(delta,1),
                    "thread_count": runtime.get("thread_count"),
                    "tts_queue_size": runtime.get("tts_queue_size"),
                    "brain_generate_busy": runtime.get("brain_generate_busy"),
                    "tts_cloud_active": runtime.get("tts_cloud_active"),
                    "whiteboard_active": runtime.get("whiteboard_active"),
                    "gpu_processes": list(self._gpu_process_cache),
                }
                self._vram_jumps.append(evt)
                self.note_event("vram_jump", severity=severity, delta_mb=round(delta,1))
        if cur is not None:
            self._last_vram = cur

    def _run(self):
        psutil.cpu_percent(interval=None)
        self.status_changed.emit("长时间交互诊断已开始：现在正常和小美丽聊天，想结束时点击“结束并生成报告”。")
        last_elapsed = -1
        ok = True
        message = ""
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                self._sample_once()
                elapsed = int(time.monotonic() - self._started_monotonic)
                if elapsed != last_elapsed and elapsed % 2 == 0:
                    self.elapsed_changed.emit(f"已记录 {elapsed//60}分{elapsed%60:02d}秒｜对话轮次 {self._turn_seq}｜显存跳变 {len(self._vram_jumps)} 次")
                    last_elapsed = elapsed
                wait = SAMPLE_INTERVAL_SECONDS - (time.monotonic() - started)
                if wait > 0:
                    self._stop.wait(wait)
        except Exception as exc:
            ok = False
            message = f"{type(exc).__name__}: {exc}"
            self.note_event("sampler_error")
        finally:
            # Take one final sample. Do not stop or reconfigure any XiaoMeili component.
            try:
                self._sample_once()
            except Exception:
                pass
            if self._open_turn is not None:
                self._open_turn["end_t"] = round(max(0.0, time.monotonic() - self._started_monotonic), 3)
                self._open_turn["end_reason"] = "diagnostic_stopped"
                self._open_turn = None
            _set_active(None)

        try:
            report = self._write_reports()
            self.report_zip = report
            self.status_changed.emit("诊断结束，报告已生成。小美丽和语音功能保持原状态。")
            final = f"诊断完成：{report}" if ok else f"诊断记录出现异常，但报告已生成：{report}｜{message}"
            self.finished.emit(ok, str(report), final)
        except Exception as exc:
            self.finished.emit(False, "", f"生成诊断报告失败：{type(exc).__name__}: {exc}")
        finally:
            self._running = False

    def _window_samples(self, start_t, end_t):
        return [r for r in self._samples if float(start_t) <= float(r.get("t") or 0) <= float(end_t)]

    @staticmethod
    def _median(rows, key):
        vals = []
        for r in rows:
            try:
                if r.get(key) is not None:
                    vals.append(float(r.get(key)))
            except Exception:
                pass
        return statistics.median(vals) if vals else None

    @staticmethod
    def _max(rows, key):
        vals = []
        for r in rows:
            try:
                if r.get(key) is not None:
                    vals.append(float(r.get(key)))
            except Exception:
                pass
        return max(vals) if vals else None

    def _turn_ledger(self):
        ledger = []
        stop_t = float(self._samples[-1]["t"]) if self._samples else 0.0
        for idx, turn in enumerate(self._turns):
            start = float(turn.get("start_t") or 0.0)
            end = turn.get("end_t")
            if end is None:
                end = float(self._turns[idx+1].get("start_t") or stop_t) if idx+1 < len(self._turns) else stop_t
            end = float(end)
            before = self._window_samples(max(0.0,start-2.0), start)
            during = self._window_samples(start, end)
            after = self._window_samples(max(start,end-2.0), end)
            base = self._median(before, "vram_used_mb")
            peak = self._max(during, "vram_used_mb")
            finish = self._median(after, "vram_used_mb")
            row = {
                "turn": int(turn.get("turn") or idx+1),
                "start_t": round(start,3),
                "end_t": round(end,3),
                "duration_s": round(max(0.0,end-start),3),
                "baseline_vram_mb": round(base,1) if base is not None else None,
                "peak_vram_mb": round(peak,1) if peak is not None else None,
                "end_vram_mb": round(finish,1) if finish is not None else None,
                "peak_delta_mb": round(peak-base,1) if peak is not None and base is not None else None,
                "retained_delta_mb": round(finish-base,1) if finish is not None and base is not None else None,
                "end_reason": str(turn.get("end_reason") or ""),
                "events": ",".join(turn.get("events") or []),
            }
            ledger.append(row)
        return ledger

    def _write_reports(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)

        with (self.session_dir/"timeline_250ms.csv").open("x",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f)
            w.writerow([
                "t_seconds","system_cpu_percent","system_ram_percent","app_cpu_percent","app_rss_mb",
                "gpu_util_percent","vram_used_mb","vram_total_mb","gpu_temp_c",
                "thread_count","speech_worker_pid","speech_reader_alive","brain_generate_busy",
                "brain_cloud_response_open","tts_cloud_active","tts_queue_size","tts_finished",
                "tts_aborted","tts_audio_stream_open","whiteboard_active","dialogue_indicator_visible",
                "thread_groups_json"
            ])
            for r in self._samples:
                rt=r.get("runtime") or {}
                w.writerow([
                    r.get("t"),r.get("system_cpu_percent"),r.get("system_ram_percent"),r.get("app_cpu_percent"),
                    round(float(r.get("app_rss_bytes") or 0)/1024/1024,2),r.get("gpu_util_percent"),
                    r.get("vram_used_mb"),r.get("vram_total_mb"),r.get("gpu_temp_c"),
                    rt.get("thread_count"),rt.get("speech_worker_pid"),rt.get("speech_reader_alive"),
                    rt.get("brain_generate_busy"),rt.get("brain_cloud_response_open"),rt.get("tts_cloud_active"),
                    rt.get("tts_queue_size"),rt.get("tts_finished"),rt.get("tts_aborted"),
                    rt.get("tts_audio_stream_open"),rt.get("whiteboard_active"),rt.get("dialogue_indicator_visible"),
                    json.dumps(rt.get("thread_groups") or {},ensure_ascii=False),
                ])

        with (self.session_dir/"process_tree.csv").open("x",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f); w.writerow(["t_seconds","pid","ppid","name","cpu_percent","rss_mb"])
            for r in self._samples:
                for p in r.get("processes") or []:
                    w.writerow([r.get("t"),p.get("pid"),p.get("ppid"),p.get("name"),p.get("cpu_percent"),
                                round(float(p.get("rss_bytes") or 0)/1024/1024,2)])

        with (self.session_dir/"process_gpu.csv").open("x",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f); w.writerow(["t_seconds","pid","process_name","used_gpu_memory_mb","source"])
            for r in self._samples:
                for p in r.get("gpu_processes") or []:
                    w.writerow([r.get("t"),p.get("pid"),p.get("name"),p.get("used_gpu_memory_mb"),p.get("source")])

        with self._events_lock:
            events=list(self._events)
        with (self.session_dir/"events.csv").open("x",encoding="utf-8-sig",newline="") as f:
            keys=["t","event","code","tag","ok","duration_ms","chars","severity","delta_mb"]
            w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader()
            for e in events: w.writerow(e)

        ledger=self._turn_ledger()
        with (self.session_dir/"conversation_turns.csv").open("x",encoding="utf-8-sig",newline="") as f:
            fields=["turn","start_t","end_t","duration_s","baseline_vram_mb","peak_vram_mb","end_vram_mb","peak_delta_mb","retained_delta_mb","end_reason","events"]
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(ledger)

        with (self.session_dir/"vram_jump_events.csv").open("x",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f)
            w.writerow(["t_seconds","severity","from_mb","to_mb","delta_mb","thread_count","tts_queue_size","brain_generate_busy","tts_cloud_active","whiteboard_active","gpu_processes_json"])
            for e in self._vram_jumps:
                w.writerow([e.get("t"),e.get("severity"),e.get("from_mb"),e.get("to_mb"),e.get("delta_mb"),
                            e.get("thread_count"),e.get("tts_queue_size"),e.get("brain_generate_busy"),
                            e.get("tts_cloud_active"),e.get("whiteboard_active"),
                            json.dumps(e.get("gpu_processes") or [],ensure_ascii=False)])

        vram=[float(r["vram_used_mb"]) for r in self._samples if r.get("vram_used_mb") is not None]
        summary={
            "app_version":self.app_version,
            "platform":platform.platform(),
            "python":platform.python_version(),
            "sample_interval_seconds":SAMPLE_INTERVAL_SECONDS,
            "duration_seconds":round(float(self._samples[-1]["t"]),3) if self._samples else 0,
            "conversation_turns":len(ledger),
            "vram_start_mb":round(vram[0],1) if vram else None,
            "vram_peak_mb":round(max(vram),1) if vram else None,
            "vram_end_mb":round(vram[-1],1) if vram else None,
            "vram_total_growth_mb":round(vram[-1]-vram[0],1) if len(vram)>=2 else None,
            "vram_jump_warn_count":sum(1 for x in self._vram_jumps if x.get("severity")=="warn"),
            "vram_jump_major_count":sum(1 for x in self._vram_jumps if x.get("severity")=="major"),
            "privacy":"不记录聊天原文、问题/回答内容、API Key、长期记忆、养成库、昵称、游戏截图或麦克风录音。",
            "safety":"被动监控；不启停组件、不发送测试请求、不改设置；仅新建诊断文件和ZIP，不删除、不移动、不覆盖、不镜像清理任何用户文件。",
        }
        (self.session_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")

        lines=[
            f"小美丽 V{self.app_version} 长时间真实聊天资源诊断",
            "="*62,
            "",
            f"记录时长：{int(summary['duration_seconds'])//60}分{int(summary['duration_seconds'])%60:02d}秒",
            f"实际对话轮次：{summary['conversation_turns']}",
            f"显存：开始 {summary['vram_start_mb']} MB｜峰值 {summary['vram_peak_mb']} MB｜结束 {summary['vram_end_mb']} MB",
            f"从开始到结束显存变化：{summary['vram_total_growth_mb']} MB",
            f">=256MB 跳变：{summary['vram_jump_warn_count']} 次｜>=512MB 大跳变：{summary['vram_jump_major_count']} 次",
            "",
            "轮次资源账本（前20轮）：",
        ]
        for row in ledger[:20]:
            lines.append(
                f"- 第{row['turn']}轮：基线 {row['baseline_vram_mb']} MB｜峰值 {row['peak_vram_mb']} MB"
                f"｜结束 {row['end_vram_mb']} MB｜保留增量 {row['retained_delta_mb']} MB"
            )
        if len(ledger)>20:
            lines.append(f"- 其余 {len(ledger)-20} 轮详见 conversation_turns.csv")
        lines.extend([
            "",
            "诊断是纯旁观模式：结束诊断不会关闭小美丽、语音、大脑、TTS或白板，也不会修改任何设置。",
            "请把本 ZIP 直接上传给 ChatGPT。",
            "报告不含聊天内容、麦克风录音、API Key、长期记忆、养成库、昵称或截图。",
        ])
        (self.session_dir/"请上传给ChatGPT_长时间交互诊断摘要.txt").write_text("\n".join(lines),encoding="utf-8-sig")

        self.desktop.mkdir(parents=True,exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        target=self.desktop/f"小美丽_长时间交互资源诊断_{stamp}.zip"
        n=1
        while target.exists():
            target=self.desktop/f"小美丽_长时间交互资源诊断_{stamp}_{n}.zip"; n+=1
        include={
            "timeline_250ms.csv","process_tree.csv","process_gpu.csv","events.csv",
            "conversation_turns.csv","vram_jump_events.csv","summary.json",
            "请上传给ChatGPT_长时间交互诊断摘要.txt",
        }
        with zipfile.ZipFile(target,mode="x",compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(self.session_dir.iterdir()):
                if p.is_file() and p.name in include:
                    zf.write(p,arcname=p.name)
        return target
