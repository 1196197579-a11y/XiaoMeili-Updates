# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.8 unattended full-module resource diagnostic.

Safety:
- creates diagnostic files only under XiaoMeiliData/diagnostics and one new Desktop ZIP
- does not delete, move, mirror, purge, overwrite, or clean any existing user file
- does not read VALORANT process memory or inject anything
- does not include API keys, chat history, memories, nicknames, or microphone recordings
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
import wave
import zipfile
from array import array
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, Signal

from cloud_support import cloud_cfg, load_api_key, test_brain_connection

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAMPLE_INTERVAL_SECONDS = 0.25
GPU_PROCESS_INTERVAL_SAMPLES = 4
SPEECH_RUNS = 3

VISION_MODULES = [
    ("shared_capture", "统一屏幕采集器", "VisionWorker.run 内单个 ScreenGrabber 共享给全部识别", "capture"),
    ("match_context", "对局上下文", "双方HUD/顶部信息判断是否处于实战", "context"),
    ("sage_alive", "贤者存活", "己方贤者头像模板识别", "alive"),
    ("hp", "生命值/低血量", "HUD血量数字与状态投票", "hp"),
    ("killfeed", "击杀UI", "击杀栏事件探针与必要时昵称OCR", "kill"),
    ("enemy_alive", "敌方存活数", "敌方顶部头像状态", "kill"),
    ("death", "死亡确认", "死亡面板/多证据确认", "death"),
    ("round_result", "回合胜负", "胜利/失败结果识别", "result"),
    ("whole_match_report", "结算页/战报", "五人卡片、昵称、Sage、K/OCR", "ocr"),
    ("highlight", "高光判定", ">=2杀+最后一人+存活+胜利/拆包条件", "kill"),
]

class ResourceDiagnosticRunner(QObject):
    progress_changed = Signal(int, str)
    board_requested = Signal(str, int)
    finished = Signal(bool, str, str)

    def __init__(self, cfg, brain_service, voice_service, speech_service, vision,
                 data_root, desktop_path, app_version="0.10.0.8", parent=None):
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
        self._gpu_process_cache = []
        self._gpu_process_tick = 0
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
        threading.Thread(target=self._run, name="XiaoMeiliFullResourceDiagnostic", daemon=True).start()
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
            vcfg = self.cfg.setdefault("vision", {})
            vcfg["enabled"] = bool(enabled)
        except Exception:
            pass

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
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
                })
        except Exception:
            pass
        return rows

    def _process_rows(self):
        root = psutil.Process(os.getpid())
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        live = []
        app_cpu = 0.0
        app_rss = 0
        for p in procs:
            try:
                pid = int(p.pid)
                cached = self._proc_cache.get(pid)
                if cached is None:
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
            "match_context": bool(getattr(v, "match_context", False)),
            "scan_fps": self._safe_float(getattr(v, "scan_fps", None)),
            "cpu_estimate": self._safe_float(getattr(v, "cpu_estimate", None)),
            "ocr_trigger_count": int(getattr(v, "ocr_trigger_count", 0) or 0),
            "hp_read_count": int(getattr(v, "hp_read_count", 0) or 0),
            "skipped_cycles": int(getattr(v, "skipped_cycles", 0) or 0),
            "timings": timings,
        }

    def _sample_once(self):
        gpu = self._nvidia_total()
        self._gpu_process_tick += 1
        if self._gpu_process_tick % GPU_PROCESS_INTERVAL_SAMPLES == 1:
            self._gpu_process_cache = self._nvidia_processes()
        proc_rows, app_cpu, app_rss = self._process_rows()
        vm = psutil.virtual_memory()
        row = {
            "t": round(max(0.0, time.monotonic() - self._started_monotonic), 3),
            "stage": self._stage,
            "system_cpu_percent": round(float(psutil.cpu_percent(interval=None)), 3),
            "system_ram_percent": round(float(vm.percent), 3),
            "app_cpu_percent": round(float(app_cpu), 3),
            "app_rss_bytes": int(app_rss),
            "gpu_util_percent": gpu["gpu_util"],
            "vram_used_mb": gpu["vram_used_mb"],
            "vram_total_mb": gpu["vram_total_mb"],
            "gpu_temp_c": gpu["gpu_temp_c"],
            "processes": proc_rows,
            "nvidia_compute_processes": list(self._gpu_process_cache),
            "vision": self._vision_row(),
        }
        self._samples.append(row)

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
        with wave.open(str(path), "wb") as wf:
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
        tag = "resource_diag_v01008"
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
            "app_ram_peak_mb": round(max(appram), 1) if appram else None,
        }
        if vram and isolated_vram is not None:
            result["vram_peak_delta_vs_isolated_mb"] = round(max(vram) - float(isolated_vram), 1)
        return result

    def _write_reports(self):
        isolated_rows = [r for r in self._samples if r.get("stage") == "isolated_baseline" and r.get("vram_used_mb") is not None]
        isolated_vram = statistics.median([float(r["vram_used_mb"]) for r in isolated_rows]) if isolated_rows else None

        timeline = self.session_dir / "timeline_250ms.csv"
        with timeline.open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","system_cpu_percent","system_ram_percent","app_cpu_percent",
                        "app_rss_mb","gpu_util_percent","vram_used_mb","vram_total_mb","gpu_temp_c"])
            for r in self._samples:
                w.writerow([r.get("t"),r.get("stage"),r.get("system_cpu_percent"),r.get("system_ram_percent"),
                            r.get("app_cpu_percent"),round(float(r.get("app_rss_bytes") or 0)/1024/1024,2),
                            r.get("gpu_util_percent"),r.get("vram_used_mb"),r.get("vram_total_mb"),r.get("gpu_temp_c")])

        proc_csv = self.session_dir / "process_tree.csv"
        with proc_csv.open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","pid","ppid","name","cpu_percent","rss_mb","cmd_hint"])
            for r in self._samples:
                for p in r.get("processes") or []:
                    w.writerow([r.get("t"),r.get("stage"),p.get("pid"),p.get("ppid"),p.get("name"),
                                p.get("cpu_percent"),round(float(p.get("rss_bytes") or 0)/1024/1024,2),p.get("cmd_hint")])

        gpu_csv = self.session_dir / "process_gpu.csv"
        with gpu_csv.open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","pid","process_name","used_gpu_memory_mb"])
            last = None
            for r in self._samples:
                key = (r.get("t"), r.get("stage"))
                for p in r.get("nvidia_compute_processes") or []:
                    w.writerow([key[0],key[1],p.get("pid"),p.get("name"),p.get("used_gpu_memory_mb")])

        vision_csv = self.session_dir / "vision_timeline.csv"
        with vision_csv.open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds","stage","backend","game_found","foreground","paused","match_context",
                        "scan_fps","vision_cpu_estimate","ocr_trigger_count","hp_read_count","skipped_cycles","timings_json"])
            for r in self._samples:
                v = r.get("vision") or {}
                w.writerow([r.get("t"),r.get("stage"),v.get("backend"),v.get("game_found"),v.get("foreground"),
                            v.get("paused"),v.get("match_context"),v.get("scan_fps"),v.get("cpu_estimate"),
                            v.get("ocr_trigger_count"),v.get("hp_read_count"),v.get("skipped_cycles"),
                            json.dumps(v.get("timings") or {}, ensure_ascii=False)])

        topo = {
            "app_version": self.app_version,
            "current_architecture_already_unified": True,
            "screen_grabber_instances_in_vision_worker": 1,
            "continuous_capture_thread": False,
            "backend_at_report": str(getattr(self.vision, "backend_name", "") or ""),
            "owner": "VisionWorker.run",
            "note": "当前识别链已经由同一个 ScreenGrabber 按需抓取各 ROI；V0.10.0.8 只测量，不重写已稳定识别逻辑。",
            "modules": [{"id":x[0],"name":x[1],"description":x[2],"timing_key":x[3]} for x in VISION_MODULES],
        }
        (self.session_dir / "capture_topology.json").write_text(
            json.dumps(topo, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with (self.session_dir / "recognition_modules.csv").open("x", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id","name","description","timing_key","shared_capture"])
            for x in VISION_MODULES:
                w.writerow([x[0],x[1],x[2],x[3],"yes"])

        stages_order = [
            "current_runtime", "isolated_baseline", "whiteboard_only", "vision_all",
            "vision_cooldown", "speech_input_only", "speech_cooldown",
            "cloud_brain", "cloud_tts", "combined_live", "final_cooldown",
        ]
        stage_summary = [self._stage_summary(x, isolated_vram) for x in stages_order]

        meta = {
            "app_version": self.app_version,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "cpu_logical": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total/1024/1024/1024,2),
            "isolated_vram_mb": round(isolated_vram,1) if isolated_vram is not None else None,
            "speech_execution_device": "cpu (Fun-ASR-Nano-2512 and FSMN-VAD are explicitly loaded with device=cpu)",
            "privacy": "固定合成测试内容；不保存用户聊天、记忆、养成库、API Key、账号昵称或麦克风录音。",
            "safety": "仅创建新的诊断文件和ZIP；不删除、不移动、不覆盖、不镜像清理任何用户文件。",
        }
        payload = {"meta":meta,"stages":stage_summary,"events":self._events}
        (self.session_dir / "summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        (self.session_dir / "events.json").write_text(json.dumps(self._events,ensure_ascii=False,indent=2),encoding="utf-8")

        title = {
            "current_runtime":"测试开始时的真实运行状态",
            "isolated_baseline":"隔离后的纯小美丽基线",
            "whiteboard_only":"仅白板/说话动画",
            "vision_all":"全部现有画面识别",
            "vision_cooldown":"画面识别暂停后",
            "speech_input_only":"FSMN-VAD + Fun-ASR-Nano-2512",
            "speech_cooldown":"语音输入退出后",
            "cloud_brain":"云端 Qwen3-8B",
            "cloud_tts":"云端 Qwen-Audio 复刻TTS",
            "combined_live":"语音输入 + 云端双引擎 + 白板 + 全部画面识别",
            "final_cooldown":"最终冷却",
        }
        lines = [
            f"小美丽 V{self.app_version} 全模块深度资源诊断",
            "="*58, "",
            "本版重点：先记录当前真实状态，再逐项隔离，不再把本地大模型当成云端模式的代表。",
            "语音输入代码已确认强制 device=cpu；如果显存仍暴涨，应重点看 current_runtime→isolated_baseline 的回落和 process_gpu.csv。",
            "当前画面识别已经使用一个共享 ScreenGrabber，本次只测量，不改识别算法。",
            "",
            f"隔离基线显存中位数：{meta['isolated_vram_mb']} MB",
            "",
            "阶段结果：",
        ]
        for row in stage_summary:
            name = title.get(row["stage"],row["stage"])
            if not row.get("samples"):
                lines.append(f"- {name}: 无采样")
                continue
            lines.append(
                f"- {name}: 显存峰值 {row.get('vram_peak_mb')} MB"
                f"｜较隔离基线 {row.get('vram_peak_delta_vs_isolated_mb')} MB"
                f"｜GPU峰值 {row.get('gpu_peak_percent')}%"
                f"｜小美丽进程组RAM峰值 {row.get('app_ram_peak_mb')} MB"
                f"｜CPU峰值 {row.get('app_cpu_peak_percent')}%"
            )
        # Highlight suspicious runtime processes from any sample.
        names = {}
        for r in self._samples:
            for p in r.get("processes") or []:
                n = str(p.get("name") or "").lower()
                if n in ("llama-server.exe","python.exe","python"):
                    key=(n,int(p.get("pid") or 0))
                    rec=names.setdefault(key,{"rss":0.0,"cpu":0.0,"stages":set()})
                    rec["rss"]=max(rec["rss"],float(p.get("rss_bytes") or 0)/1024/1024)
                    rec["cpu"]=max(rec["cpu"],float(p.get("cpu_percent") or 0))
                    rec["stages"].add(str(r.get("stage")))
        lines.extend(["","重点进程："])
        if names:
            for (n,pid),rec in sorted(names.items()):
                lines.append(f"- {n} PID {pid}: RAM峰值 {rec['rss']:.1f} MB｜CPU峰值 {rec['cpu']:.1f}%｜出现阶段 {','.join(sorted(rec['stages']))}")
        else:
            lines.append("- 未检测到 llama-server/Python 子进程。")
        lines.extend([
            "",
            "请直接把本 ZIP 上传给 ChatGPT；不需要再截图任务管理器。",
            "安全：报告不含 API Key、聊天内容、长期记忆、养成库、昵称或麦克风录音。",
        ])
        (self.session_dir / "请上传给ChatGPT_全模块资源诊断摘要.txt").write_text("\n".join(lines),encoding="utf-8-sig")

        self.desktop.mkdir(parents=True, exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        target=self.desktop/f"小美丽_全模块资源诊断_{stamp}.zip"
        n=1
        while target.exists():
            target=self.desktop/f"小美丽_全模块资源诊断_{stamp}_{n}.zip"; n+=1
        include = {
            "timeline_250ms.csv","process_tree.csv","process_gpu.csv","vision_timeline.csv",
            "capture_topology.json","recognition_modules.csv","summary.json","events.json",
            "请上传给ChatGPT_全模块资源诊断摘要.txt","speech_diagnostic_worker.log",
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
        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v01008_{token}"
        self.session_dir.mkdir(parents=True,exist_ok=False)
        wav_path=self._make_test_wav(self.session_dir/"diagnostic_input.wav")
        setattr(self.speech,"_resource_diagnostic_active",True)
        self._sampling=True
        sampler=threading.Thread(target=self._sampler_loop,name="XiaoMeiliResourceSamplerV01008",daemon=True)
        sampler.start()
        ok=True
        error_text=""
        speech_proc=None
        combined_proc=None
        try:
            self._set_stage("current_runtime",3,"1/9 记录当前真实运行状态：不卸载任何组件")
            self._sleep(8)

            self._set_stage("preparing",10,"隔离组件：停止AI/语音并暂停画面识别，等待资源回落")
            try:self.speech.stop()
            except Exception:pass
            try:self.brain.shutdown()
            except Exception:pass
            try:self.voice.shutdown()
            except Exception:pass
            self._set_vision_enabled(False)
            self._sleep(7)

            self._set_stage("isolated_baseline",17,"2/9 记录隔离后的纯小美丽基线")
            self._sleep(8)

            self._set_stage("whiteboard_only",25,"3/9 单独测试白板/说话动画")
            self.board_requested.emit("全模块资源诊断：仅白板动画",7000)
            self._sleep(8)

            self._set_stage("vision_all",33,"4/9 测试全部现有画面识别：共享 ScreenGrabber")
            self._set_vision_enabled(True)
            self._sleep(22)
            self._event("vision_snapshot",data=self._vision_row())
            self._set_vision_enabled(False)
            self._set_stage("vision_cooldown",43,"观察画面识别暂停后的资源回落")
            self._sleep(6)

            self._set_stage("speech_input_only",49,"5/9 测试 FSMN-VAD + Fun-ASR-Nano-2512：CPU加载/推理/驻留")
            speech_proc=self._speech_start_resident(wav_path,SPEECH_RUNS,35)
            self._sleep(15)
            self._terminate_diag_proc(speech_proc); speech_proc=None
            self._set_stage("speech_cooldown",59,"观察语音输入退出后的资源回落")
            self._sleep(8)

            self._set_stage("cloud_brain",64,"6/9 测试当前云端 Qwen3-8B 链路")
            self._cloud_brain_probe()
            self._sleep(5)

            self._set_stage("cloud_tts",70,"7/9 测试当前云端复刻音色 TTS 链路")
            self._cloud_tts_probe()
            self._sleep(5)

            self._set_stage("combined_live",77,"8/9 综合：语音输入 + 云端双引擎 + 白板 + 全部画面识别")
            self._set_vision_enabled(True)
            combined_proc=self._speech_start_resident(wav_path,2,55)
            self.board_requested.emit("全模块资源诊断：综合压力测试",18000)
            self._cloud_brain_probe()
            self._cloud_tts_probe()
            self._sleep(16)
            self._terminate_diag_proc(combined_proc); combined_proc=None
            try:self.voice.shutdown()
            except Exception:pass
            try:self.brain.shutdown()
            except Exception:pass
            self._set_vision_enabled(False)

            self._set_stage("final_cooldown",92,"9/9 最终冷却：确认组件退出后资源是否回落")
            self._sleep(12)
        except Exception as exc:
            ok=False
            error_text=f"{type(exc).__name__}: {exc}"
            self._event("error",message=error_text)
        finally:
            self._terminate_diag_proc(speech_proc)
            self._terminate_diag_proc(combined_proc)
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
            self._set_stage("report",97,"正在生成脱敏诊断 ZIP")
            report=self._write_reports()
            self._emit_progress(100,"测试完成，桌面诊断包已生成")
            msg=(f"诊断完成：{report}" if ok else
                 f"部分阶段失败，但已生成可分析报告：{report}\n{error_text}")
            self.finished.emit(ok,str(report),msg)
        except Exception as exc:
            self.finished.emit(False,"",f"生成诊断报告失败：{type(exc).__name__}: {exc}")
        finally:
            self._running=False
