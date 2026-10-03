# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.5 unattended deep resource diagnostic.

This module only starts/stops XiaoMeili's own runtime components, samples resource
usage, creates new diagnostic files, and writes one new Desktop ZIP. It never
removes, moves, overwrites, mirrors, purges, or cleans user files.
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

from voice_qwen import PRESETS


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAMPLE_INTERVAL_SECONDS = 0.50
DIAGNOSTIC_BRAIN_RUNS = 4          # 1 cold + 3 hot
DIAGNOSTIC_TTS_RUNS = 4            # 1 cold + 3 hot
DIAGNOSTIC_SPEECH_RUNS = 4         # models load once + 4 inferences
DIAGNOSTIC_COMBINED_RUNS = 3


class ResourceDiagnosticRunner(QObject):
    progress_changed = Signal(int, str)
    board_requested = Signal(str, int)
    finished = Signal(bool, str, str)

    def __init__(self, cfg, brain_service, voice_service, speech_service,
                 data_root, desktop_path, app_version="0.10.0.5", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.brain = brain_service
        self.voice = voice_service
        self.speech = speech_service
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

    def is_running(self):
        return bool(self._running)

    def start(self):
        if self._running:
            return False
        self._running = True
        threading.Thread(target=self._run, name="XiaoMeiliDeepResourceDiagnostic", daemon=True).start()
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
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=2.5,
                creationflags=CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL,
            )
            parts = [x.strip() for x in str(out).strip().splitlines()[0].split(",")]
            if len(parts) >= 4:
                result["gpu_util"] = self._safe_float(parts[0])
                result["vram_used_mb"] = self._safe_float(parts[1])
                result["vram_total_mb"] = self._safe_float(parts[2])
                result["gpu_temp_c"] = self._safe_float(parts[3])
        except Exception:
            pass
        return result

    def _nvidia_processes(self):
        rows = []
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,process_name,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=2.5,
                creationflags=CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL,
            )
            for line in str(out).splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) < 3:
                    continue
                try:
                    pid = int(parts[0])
                except Exception:
                    continue
                used = self._safe_float(parts[-1])
                rows.append({
                    "pid": pid,
                    "name": ",".join(parts[1:-1]).strip(),
                    "used_gpu_memory_mb": used,
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
                name = str(cached.name())
                app_cpu += cpu
                app_rss += rss
                live.append({"pid": pid, "name": name, "cpu_percent": round(cpu, 3), "rss_bytes": rss})
            except Exception:
                continue
        return live, app_cpu, app_rss

    def _sample_once(self):
        gpu = self._nvidia_total()
        self._gpu_process_tick += 1
        if self._gpu_process_tick % 2 == 1:
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
        """Create deterministic speech-like PCM. No microphone or external TTS is needed."""
        sample_rate = 16000
        seconds = 5.2
        total = int(sample_rate * seconds)
        pcm = array("h")
        for i in range(total):
            t = i / sample_rate
            if t < 0.55 or t > 4.65:
                value = 0.0
            else:
                local = t - 0.55
                syllable = int(local / 0.34)
                f0 = 135.0 + (syllable % 5) * 17.0
                envelope = max(0.0, math.sin(math.pi * ((local % 0.34) / 0.34)))
                voiced = (
                    0.55 * math.sin(2.0 * math.pi * f0 * t)
                    + 0.24 * math.sin(2.0 * math.pi * (f0 * 2.0) * t)
                    + 0.12 * math.sin(2.0 * math.pi * (520.0 + 35.0 * (syllable % 4)) * t)
                    + 0.08 * math.sin(2.0 * math.pi * (1450.0 + 80.0 * (syllable % 3)) * t)
                )
                value = 0.27 * envelope * voiced
            pcm.append(int(max(-1.0, min(1.0, value)) * 32767.0))
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return path

    def _brain_generate(self, run_index):
        if not self.brain.ready():
            raise RuntimeError("Qwen3-8B 大脑组件尚未准备完成")
        started = time.monotonic()
        self.brain._start_server()
        load_done = time.monotonic()
        payload = {
            "model": "Qwen3-8B-Q4_K_M",
            "messages": [
                {"role": "system", "content": "你正在执行小美丽资源诊断。不要读取记忆，不要学习，不要写入历史。"},
                {"role": "user", "content": f"这是第{run_index}轮资源诊断，只用一句很短的中文回复测试正常。\n/no_think"},
            ],
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 48,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = self.brain._post_json("/v1/chat/completions", payload, timeout=180)
        done = time.monotonic()
        text = ""
        try:
            text = str(response["choices"][0]["message"]["content"]).strip()
        except Exception:
            text = ""
        row = {
            "run": int(run_index),
            "server_load_seconds": round(load_done - started, 3),
            "generation_seconds": round(done - load_done, 3),
            "total_seconds": round(done - started, 3),
            "reply_chars": len(text),
            "server_pid": int(getattr(getattr(self.brain, "_server", None), "pid", 0) or 0),
        }
        self._event("brain_run", **row)
        return row

    def _selected_voice(self):
        voice_cfg = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        voice_id = str(voice_cfg.get("voice_id") or "").strip()
        preset = PRESETS.get(voice_id)
        if preset and (preset.get("kind") != "design" or self.voice.design_ready()):
            return voice_id, preset, float(voice_cfg.get("speed", 1.0) or 1.0)
        for fallback in ("vivian_cool", "vivian_natural", "serena_soft"):
            preset = PRESETS.get(fallback)
            if preset:
                return fallback, preset, 1.0
        if PRESETS:
            key = next(iter(PRESETS))
            return key, PRESETS[key], 1.0
        raise RuntimeError("没有可用于诊断的 Qwen3-TTS 声线")

    def _tts_synthesize(self, run_index, prefix="tts"):
        if not self.voice.ready():
            raise RuntimeError("Qwen3-TTS 声音组件尚未准备完成")
        voice_id, preset, speed = self._selected_voice()
        text = [
            "这是小美丽声音组件资源测试。",
            "正在测试小美丽语音生成占用。",
            "这一轮只记录声音模型资源数据。",
            "声音测试即将完成，请稍等一下。",
        ][(int(run_index) - 1) % 4]
        out = self.session_dir / f"{prefix}_{int(run_index):02d}.wav"
        started = time.monotonic()
        self.voice._start_worker()
        load_done = time.monotonic()
        req = {
            "cmd": "synthesize",
            "kind": preset.get("kind", "custom"),
            "text": text,
            "instruct": str(preset.get("instruct") or "") + self.voice._speed_instruction(speed),
            "output": str(out),
        }
        if preset.get("kind") == "design":
            req["seed"] = int(preset.get("seed") or 0)
        else:
            req["speaker"] = str(preset.get("speaker") or "Vivian")
        resp = self.voice._request(req, 360)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "Qwen3-TTS 诊断合成失败")
        done = time.monotonic()
        row = {
            "run": int(run_index),
            "voice_id": voice_id,
            "worker_load_seconds": round(load_done - started, 3),
            "synthesis_seconds": round(done - load_done, 3),
            "total_seconds": round(done - started, 3),
            "output_bytes": int(out.stat().st_size if out.exists() else 0),
            "worker_pid": int(getattr(getattr(self.voice, "_worker", None), "pid", 0) or 0),
        }
        self._event("tts_run", **row)
        return row

    @staticmethod
    def _parse_event_line(line):
        line = str(line or "").strip()
        prefix = "XMEVENT|"
        if not line.startswith(prefix):
            return None
        try:
            return json.loads(line[len(prefix):])
        except Exception:
            return None

    def _speech_run_and_wait(self, wav_path, repeat=4, hold_seconds=0):
        proc = self.speech.diagnostic_process_v01005(
            str(wav_path), repeat=int(repeat), hold_seconds=int(hold_seconds)
        )
        events = []
        ready = False
        deadline = time.monotonic() + max(180.0, 90.0 + 45.0 * max(1, int(repeat)))
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                row = self._parse_event_line(line)
                if row:
                    events.append(row)
                    if row.get("event") == "diag_ready":
                        ready = True
                        break
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
        if int(hold_seconds) <= 0:
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
        if int(hold_seconds) > 0 and not ready:
            try:
                proc.terminate()
            except Exception:
                pass
            raise RuntimeError("语音输入诊断工作进程未能进入驻留状态")
        self._event("speech_worker", pid=int(proc.pid), diagnostic_events=events)
        return proc, events

    def _stage_summary(self, stage, baseline_vram):
        rows = [r for r in self._samples if r.get("stage") == stage]
        if not rows:
            return {"stage": stage, "samples": 0}
        def vals(key):
            return [float(r[key]) for r in rows if r.get(key) is not None]
        vram = vals("vram_used_mb")
        gpu = vals("gpu_util_percent")
        cpu = vals("system_cpu_percent")
        appcpu = vals("app_cpu_percent")
        appram = [float(r.get("app_rss_bytes") or 0) / 1024.0 / 1024.0 for r in rows]
        result = {
            "stage": stage,
            "samples": len(rows),
            "duration_seconds": round(max(r["t"] for r in rows) - min(r["t"] for r in rows), 3) if len(rows) > 1 else 0.0,
            "vram_avg_mb": round(statistics.mean(vram), 1) if vram else None,
            "vram_peak_mb": round(max(vram), 1) if vram else None,
            "vram_end_mb": round(statistics.mean(vram[-min(5, len(vram)):]), 1) if vram else None,
            "vram_peak_delta_vs_idle_mb": round(max(vram) - baseline_vram, 1) if vram and baseline_vram is not None else None,
            "gpu_peak_percent": round(max(gpu), 1) if gpu else None,
            "system_cpu_peak_percent": round(max(cpu), 1) if cpu else None,
            "app_cpu_peak_percent": round(max(appcpu), 1) if appcpu else None,
            "app_ram_peak_mb": round(max(appram), 1) if appram else None,
        }
        return result

    def _write_reports(self):
        samples_csv = self.session_dir / "samples_500ms.csv"
        with samples_csv.open("x", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "t_seconds", "stage", "system_cpu_percent", "system_ram_percent",
                "app_cpu_percent", "app_rss_mb", "gpu_util_percent",
                "vram_used_mb", "vram_total_mb", "gpu_temp_c",
                "processes_json", "nvidia_compute_processes_json",
            ])
            for r in self._samples:
                writer.writerow([
                    r.get("t"), r.get("stage"), r.get("system_cpu_percent"), r.get("system_ram_percent"),
                    r.get("app_cpu_percent"), round(float(r.get("app_rss_bytes") or 0) / 1024 / 1024, 2),
                    r.get("gpu_util_percent"), r.get("vram_used_mb"), r.get("vram_total_mb"),
                    r.get("gpu_temp_c"),
                    json.dumps(r.get("processes") or [], ensure_ascii=False),
                    json.dumps(r.get("nvidia_compute_processes") or [], ensure_ascii=False),
                ])

        baseline_rows = [r for r in self._samples if r.get("stage") == "idle_baseline" and r.get("vram_used_mb") is not None]
        baseline_vram = (
            statistics.median([float(r["vram_used_mb"]) for r in baseline_rows])
            if baseline_rows else None
        )
        order = [
            "idle_baseline", "whiteboard_only", "brain_only", "brain_cooldown",
            "tts_only", "tts_cooldown", "speech_input_only", "speech_cooldown",
            "combined_all", "final_cooldown",
        ]
        stage_summary = [self._stage_summary(name, baseline_vram) for name in order]
        meta = {
            "app_version": self.app_version,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_logical": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 2),
            "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "brain_runs": DIAGNOSTIC_BRAIN_RUNS,
            "tts_runs": DIAGNOSTIC_TTS_RUNS,
            "speech_runs": DIAGNOSTIC_SPEECH_RUNS,
            "combined_runs": DIAGNOSTIC_COMBINED_RUNS,
            "baseline_vram_mb": round(baseline_vram, 1) if baseline_vram is not None else None,
            "privacy": "固定诊断文本；不保存用户聊天内容、长期记忆、养成库、账号昵称或API密钥。",
            "speech_device_note": "V0.10.0.5 离线诊断强制以 device=cpu 加载 FSMN-VAD 与 Fun-ASR-Nano-2512。",
        }
        summary_json = self.session_dir / "summary.json"
        with summary_json.open("x", encoding="utf-8") as f:
            json.dump({"meta": meta, "stages": stage_summary, "events": self._events}, f, ensure_ascii=False, indent=2)

        events_json = self.session_dir / "events.json"
        with events_json.open("x", encoding="utf-8") as f:
            json.dump(self._events, f, ensure_ascii=False, indent=2)

        title_map = {
            "idle_baseline": "纯待机基线",
            "whiteboard_only": "仅白板动画",
            "brain_only": "Qwen3-8B 大脑",
            "brain_cooldown": "大脑卸载后",
            "tts_only": "Qwen3-TTS 声音",
            "tts_cooldown": "TTS卸载后",
            "speech_input_only": "FSMN-VAD + Fun-ASR-Nano-2512",
            "speech_cooldown": "语音输入卸载后",
            "combined_all": "完整组合负载",
            "final_cooldown": "最终冷却",
        }
        lines = [
            f"小美丽 V{self.app_version} 深度资源诊断",
            "=" * 52,
            "",
            "说明：",
            "1. 本报告通过隔离阶段 + 完整组合阶段测量资源，不依赖用户说话。",
            "2. GPU/显存总量来自 NVIDIA 驱动；单进程GPU显存仅在驱动可报告时记录。",
            "3. 组件归因主要依据隔离阶段相对纯待机基线的增量，因此即使WDDM不提供单进程显存，也能判断主要来源。",
            "4. 语音输入诊断加载 FSMN-VAD + Fun-ASR-Nano-2512，当前实现明确使用 CPU。",
            "5. 测试不读取游戏进程、不访问游戏内存，不写入小美丽长期记忆/养成库/聊天历史。",
            "",
            f"纯待机显存中位数：{meta['baseline_vram_mb']} MB",
            "",
            "阶段结果：",
        ]
        for row in stage_summary:
            name = title_map.get(row["stage"], row["stage"])
            if not row.get("samples"):
                lines.append(f"- {name}: 无有效采样")
                continue
            lines.append(
                f"- {name}: 显存峰值 {row.get('vram_peak_mb')} MB"
                f"｜较待机 +{row.get('vram_peak_delta_vs_idle_mb')} MB"
                f"｜GPU峰值 {row.get('gpu_peak_percent')}%"
                f"｜小美丽进程组RAM峰值 {row.get('app_ram_peak_mb')} MB"
                f"｜小美丽进程组CPU峰值 {row.get('app_cpu_peak_percent')}%"
            )
        lines.extend([
            "",
            "建议上传：直接把本 ZIP 上传给 ChatGPT，无需再截图资源管理器。",
            "安全：本次诊断只创建新文件并启停小美丽自己的运行组件，没有删除、移动、覆盖或清理任何用户文件。",
        ])
        summary_txt = self.session_dir / "请上传给ChatGPT_资源诊断摘要.txt"
        summary_txt.write_text("\n".join(lines), encoding="utf-8-sig")

        self.desktop.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.desktop / f"小美丽_深度资源诊断_{stamp}.zip"
        target = base
        suffix = 1
        while target.exists():
            target = self.desktop / f"小美丽_深度资源诊断_{stamp}_{suffix}.zip"
            suffix += 1
        with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(self.session_dir.iterdir()):
                if path.is_file():
                    zf.write(path, arcname=path.name)
        self.report_zip = target
        return target

    def _run(self):
        self._started_monotonic = time.monotonic()
        token = f"{int(time.time())}_{os.getpid()}"
        self.session_dir = self.data_root / "diagnostics" / "resource" / f"v01005_{token}"
        self.session_dir.mkdir(parents=True, exist_ok=False)
        wav_path = self._make_test_wav(self.session_dir / "diagnostic_input.wav")
        setattr(self.speech, "_resource_diagnostic_active", True)
        self._sampling = True
        sampler = threading.Thread(target=self._sampler_loop, name="XiaoMeiliResourceSampler", daemon=True)
        sampler.start()
        ok = True
        error_text = ""
        combined_speech_proc = None
        try:
            self._set_stage("preparing", 2, "准备诊断：停止小美丽的AI运行进程并等待资源稳定")
            try:
                self.speech.stop()
            except Exception:
                pass
            try:
                self.brain.shutdown()
            except Exception:
                pass
            try:
                self.voice.shutdown()
            except Exception:
                pass
            self._sleep(6)

            self._set_stage("idle_baseline", 7, "1/6 记录纯待机基线")
            self._sleep(8)

            self._set_stage("whiteboard_only", 14, "2/6 单独测试白板动画")
            self.board_requested.emit("资源诊断：仅白板动画", 7000)
            self._sleep(8)

            self._set_stage("brain_only", 22, "3/6 测试 Qwen3-8B 大脑：1次冷启动 + 3次热运行")
            for i in range(1, DIAGNOSTIC_BRAIN_RUNS + 1):
                self.board_requested.emit(f"资源诊断：大脑测试 {i}/{DIAGNOSTIC_BRAIN_RUNS}", 20000)
                self._brain_generate(i)
                self._sleep(2)
            self.brain.shutdown()
            self._set_stage("brain_cooldown", 38, "观察大脑卸载后的资源回落")
            self._sleep(8)

            self._set_stage("tts_only", 43, "4/6 测试 Qwen3-TTS：1次冷启动 + 3次热运行")
            for i in range(1, DIAGNOSTIC_TTS_RUNS + 1):
                self.board_requested.emit(f"资源诊断：声音测试 {i}/{DIAGNOSTIC_TTS_RUNS}", 20000)
                self._tts_synthesize(i, "tts_only")
                self._sleep(2)
            self.voice.shutdown()
            self._set_stage("tts_cooldown", 58, "观察 TTS 卸载后的资源回落")
            self._sleep(8)

            self._set_stage("speech_input_only", 63, "5/6 测试 FSMN-VAD + Fun-ASR-Nano-2512，无需说话")
            self.board_requested.emit("资源诊断：语音输入测试", 30000)
            _proc, _events = self._speech_run_and_wait(wav_path, DIAGNOSTIC_SPEECH_RUNS, 0)
            self._set_stage("speech_cooldown", 73, "观察语音输入组件退出后的资源回落")
            self._sleep(8)

            self._set_stage("combined_all", 78, "6/6 完整组合压力测试：语音输入常驻 + 大脑 + TTS")
            self.board_requested.emit("资源诊断：完整链路组合测试", 60000)
            combined_speech_proc, _events = self._speech_run_and_wait(wav_path, DIAGNOSTIC_COMBINED_RUNS, 300)
            for i in range(1, DIAGNOSTIC_COMBINED_RUNS + 1):
                self.board_requested.emit(f"资源诊断：综合测试 {i}/{DIAGNOSTIC_COMBINED_RUNS}", 30000)
                self._brain_generate(i)
                self._tts_synthesize(i, "combined")
                self._sleep(2)
            try:
                if combined_speech_proc and combined_speech_proc.poll() is None:
                    combined_speech_proc.terminate()
                    combined_speech_proc.wait(timeout=8)
            except Exception:
                pass
            combined_speech_proc = None
            try:
                self.brain.shutdown()
            except Exception:
                pass
            try:
                self.voice.shutdown()
            except Exception:
                pass

            self._set_stage("final_cooldown", 92, "最终冷却观察：确认模型退出后资源是否回落")
            self._sleep(15)
        except Exception as exc:
            ok = False
            error_text = f"{type(exc).__name__}: {exc}"
            self._event("error", message=error_text)
        finally:
            try:
                if combined_speech_proc and combined_speech_proc.poll() is None:
                    combined_speech_proc.terminate()
            except Exception:
                pass
            try:
                self.speech.stop()
            except Exception:
                pass
            try:
                self.brain.shutdown()
            except Exception:
                pass
            try:
                self.voice.shutdown()
            except Exception:
                pass
            self._sampling = False
            try:
                sampler.join(timeout=3)
            except Exception:
                pass
            setattr(self.speech, "_resource_diagnostic_active", False)

        try:
            self._set_stage("report", 97, "正在生成桌面诊断报告")
            report = self._write_reports()
            self._emit_progress(100, "测试完成，桌面诊断包已生成")
            message = (
                f"诊断完成：{report}"
                if ok else
                f"诊断过程中有阶段失败，但已生成可分析的部分报告：{report}\n{error_text}"
            )
            self.finished.emit(ok, str(report), message)
        except Exception as exc:
            self.finished.emit(False, "", f"生成诊断报告失败：{type(exc).__name__}: {exc}")
        finally:
            self._running = False
