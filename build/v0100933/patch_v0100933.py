# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, shutil, sys

root = Path(sys.argv[1]).resolve()
src = root / 'app' / 'src'
main = src / 'main.py'
diag_old = src / 'resource_diagnostic_v0100932.py'
diag_new = src / 'resource_diagnostic_v0100933.py'


def rd(p): return p.read_text(encoding='utf-8-sig')
def wr(p, s): p.write_text(s, encoding='utf-8', newline='\n')
def rep(s, a, b, name, count=1):
    if a not in s:
        raise RuntimeError(f'missing patch anchor: {name}')
    return s.replace(a, b, count)

# ---------- main.py ----------
s = rd(main)
if 'APP_VERSION = "0.10.0.9.3.2"' not in s:
    raise RuntimeError('V0.10.0.9.3.2 baseline required')
s = rep(s,
        'from resource_diagnostic_v0100932 import ResourceDiagnosticRunnerV2',
        'from resource_diagnostic_v0100933 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics',
        'resource diagnostic import')
s = rep(s,
        'APP_NAME = "小美丽 V0.10.0.9.3.2｜Automatic Resource Diagnostic 2.0 WAV Fix"',
        'APP_NAME = "小美丽 V0.10.0.9.3.3｜Crash-Safe Resource Diagnostic 2.0"',
        'app name')
s = rep(s, 'APP_VERSION = "0.10.0.9.3.2"', 'APP_VERSION = "0.10.0.9.3.3"', 'app version')
s = rep(s, 'APP_UPDATE_VERSION = "0.10.0.9.3.2"', 'APP_UPDATE_VERSION = "0.10.0.9.3.3"', 'update version')
s = s.replace('cfg["config_version"] = max(34, int(cfg.get("config_version", 0) or 0))',
              'cfg["config_version"] = max(35, int(cfg.get("config_version", 0) or 0))')
s = s.replace('cfg["config_version"] = 34', 'cfg["config_version"] = 35')

# Recover a previously interrupted diagnostic on startup without deleting or moving anything.
old = '''    cfg=load_config()\n    maybe_adopt_report_font(cfg)\n'''
new = '''    cfg=load_config()\n    maybe_adopt_report_font(cfg)\n    try:\n        recovered = recover_interrupted_resource_diagnostics(\n            xiaomeili_logical_data_root(), desktop_dir(), APP_VERSION\n        )\n        for recovered_path in recovered:\n            LOGGER.warning("已恢复上次中断的资源诊断：%s", recovered_path)\n    except Exception:\n        LOGGER.warning("恢复上次中断的资源诊断失败（不影响启动）", exc_info=True)\n'''
s = rep(s, old, new, 'startup diagnostic recovery')
wr(main, s)

# ---------- resource diagnostic ----------
if not diag_old.is_file():
    raise RuntimeError('V0.10.0.9.3.2 diagnostic module missing')
d = rd(diag_old)
d = d.replace('XiaoMeili V0.10.0.9.3.2 fully automatic resource diagnostic 2.0 WAV fix.',
              'XiaoMeili V0.10.0.9.3.3 crash-safe fully automatic resource diagnostic 2.0.')
d = d.replace('app_version="0.10.0.9.3.2"', 'app_version="0.10.0.9.3.3"')
d = d.replace('f"v0100932_{token}"', 'f"v0100933_{token}"')
d = d.replace('XiaoMeiliResourceSamplerV0100932', 'XiaoMeiliResourceSamplerV0100933')
d = d.replace('XiaoMeiliGpuSamplerV0100932', 'XiaoMeiliGpuSamplerV0100933')

# Add crash-recovery helper before the runner class. It only creates new files/ZIPs.
anchor = 'FINAL_COOLDOWN_SECONDS = 90\n\n\nclass ResourceDiagnosticRunnerV2(QObject):\n'
helper = '''FINAL_COOLDOWN_SECONDS = 90\n\n\ndef _unique_desktop_zip(desktop, stem):\n    desktop = Path(desktop)\n    desktop.mkdir(parents=True, exist_ok=True)\n    stamp = time.strftime("%Y%m%d_%H%M%S")\n    target = desktop / f"{stem}_{stamp}.zip"\n    n = 1\n    while target.exists():\n        target = desktop / f"{stem}_{stamp}_{n}.zip"\n        n += 1\n    return target\n\n\ndef recover_interrupted_resource_diagnostics(data_root, desktop_path, app_version=""):\n    """Package orphaned diagnostic evidence without deleting/moving source files."""\n    root = Path(data_root) / "diagnostics" / "resource"\n    if not root.is_dir():\n        return []\n    recovered = []\n    safe_names = {\n        "live_timeline.jsonl", "live_events.jsonl", "live_rounds.jsonl", "live_status.jsonl",\n        "speech_diagnostic_worker.log", "diagnostic_input.wav", "events.json", "summary.json",\n        "stage_summary.csv", "round_ledger.csv", "timeline_250ms.csv",\n        "vram_jump_events.csv", "process_tree.csv"\n    }\n    sessions = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:12]\n    for session in sessions:\n        if (session / "finalized.flag").exists() or (session / "recovered.flag").exists():\n            continue\n        live = session / "live_status.jsonl"\n        legacy = session.name.startswith("v0100932_")\n        if not live.exists() and not legacy:\n            continue\n        files = [p for p in session.iterdir() if p.is_file() and p.name in safe_names]\n        if not files:\n            continue\n        target = _unique_desktop_zip(desktop_path, "小美丽_上次中断资源测试_自动恢复")\n        summary = {\n            "recovered_by_version": str(app_version or ""),\n            "source_session": session.name,\n            "reason": "previous diagnostic process ended before final desktop report",\n            "safety": "source files were copied into ZIP only; nothing was deleted or moved",\n            "files": [p.name for p in files],\n        }\n        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as zf:\n            for p in files:\n                zf.write(p, arcname=p.name)\n            zf.writestr("recovery_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))\n        try:\n            (session / "recovered.flag").write_text(str(target), encoding="utf-8")\n        except Exception:\n            pass\n        recovered.append(str(target))\n    return recovered\n\n\nclass ResourceDiagnosticRunnerV2(QObject):\n'''
d = rep(d, anchor, helper, 'recovery helper')

# Crash-safe journal fields.
old = '''        self._speech_proc = None\n        self._combined_speech_proc = None\n'''
new = '''        self._speech_proc = None\n        self._combined_speech_proc = None\n        self._live_timeline_fp = None\n        self._live_events_fp = None\n        self._live_rounds_fp = None\n        self._live_status_fp = None\n        self._journal_lock = threading.Lock()\n'''
d = rep(d, old, new, 'journal fields')

# Insert journal helpers before is_running.
anchor = '''    def is_running(self):\n        return bool(self._running)\n'''
journal = '''    def _open_live_journals(self):\n        # Session directory is unique. x-mode ensures no existing diagnostic file is overwritten.\n        self._live_timeline_fp = (self.session_dir / "live_timeline.jsonl").open("x", encoding="utf-8", buffering=1)\n        self._live_events_fp = (self.session_dir / "live_events.jsonl").open("x", encoding="utf-8", buffering=1)\n        self._live_rounds_fp = (self.session_dir / "live_rounds.jsonl").open("x", encoding="utf-8", buffering=1)\n        self._live_status_fp = (self.session_dir / "live_status.jsonl").open("x", encoding="utf-8", buffering=1)\n        self._journal_status("running", "created")\n\n    def _journal_write(self, fp, payload):\n        if fp is None:\n            return\n        try:\n            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\\n"\n            with self._journal_lock:\n                fp.write(line)\n                fp.flush()\n        except Exception:\n            pass\n\n    def _journal_status(self, state, stage=None, **extra):\n        payload = {\n            "t": round(max(0.0, time.monotonic() - self._started), 3) if self._started else 0.0,\n            "state": str(state), "stage": str(stage or self._stage or ""),\n            "app_version": self.app_version,\n        }\n        payload.update(extra)\n        self._journal_write(self._live_status_fp, payload)\n\n    def _close_live_journals(self):\n        for attr in ("_live_timeline_fp", "_live_events_fp", "_live_rounds_fp", "_live_status_fp"):\n            fp = getattr(self, attr, None)\n            if fp is not None:\n                try: fp.flush()\n                except Exception: pass\n                try: fp.close()\n                except Exception: pass\n                setattr(self, attr, None)\n\n    def is_running(self):\n        return bool(self._running)\n'''
d = rep(d, anchor, journal, 'journal helpers')

# Persist every event and stage transition.
old = '''        row.update(payload)\n        self._events.append(row)\n'''
new = '''        row.update(payload)\n        self._events.append(row)\n        self._journal_write(self._live_events_fp, row)\n'''
d = rep(d, old, new, 'event journaling')
old = '''        self._stage = str(stage)\n        self._event("stage", label=str(text))\n        self._progress(progress, text)\n'''
new = '''        self._stage = str(stage)\n        self._event("stage", label=str(text))\n        self._journal_status("running", self._stage, label=str(text))\n        self._progress(progress, text)\n'''
d = rep(d, old, new, 'stage journaling')

# Persist compact timeline rows as they are collected so a native crash still leaves evidence.
old = '''        self._samples.append(row)\n'''
new = '''        self._samples.append(row)\n        self._journal_write(self._live_timeline_fp, row)\n'''
d = rep(d, old, new, 'sample journaling')

# Persist each completed round.
old = '''        rec["recovery_t"] = round(time.monotonic() - self._started, 3)\n'''
new = '''        rec["recovery_t"] = round(time.monotonic() - self._started, 3)\n        self._journal_write(self._live_rounds_fp, dict(rec))\n'''
d = rep(d, old, new, 'round journaling')

# Include live journals in the final ZIP.
d = rep(d,
'''        names={"timeline_250ms.csv","round_ledger.csv","stage_summary.csv","vram_jump_events.csv","process_tree.csv","events.json","summary.json","请上传给ChatGPT_一键深度资源测试2.0摘要.txt","speech_diagnostic_worker.log"}\n''',
'''        names={"timeline_250ms.csv","round_ledger.csv","stage_summary.csv","vram_jump_events.csv","process_tree.csv","events.json","summary.json","请上传给ChatGPT_一键深度资源测试2.0摘要.txt","speech_diagnostic_worker.log","live_timeline.jsonl","live_events.jsonl","live_rounds.jsonl","live_status.jsonl"}\n''',
'final zip live journals')

# Open journals immediately after creating the unique session directory.
old = '''        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v0100933_{token}"\n        self.session_dir.mkdir(parents=True,exist_ok=False)\n        wav_path=None; ok=True; err=""\n'''
new = '''        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v0100933_{token}"\n        self.session_dir.mkdir(parents=True,exist_ok=False)\n        self._open_live_journals()\n        wav_path=None; ok=True; err=""\n'''
d = rep(d, old, new, 'open live journals')

# Critical order fix: stop sampling, write the desktop report FIRST, and only then perform
# child-process cleanup. Do not call nvmlShutdown during app lifetime because a native DLL
# teardown fault would bypass Python exception handling and kill the whole application.
old = '''        finally:\n            self._terminate_proc(self._speech_proc); self._terminate_proc(self._combined_speech_proc)\n            try: setattr(self.brain,"_resource_diag_no_persist",False)\n            except Exception: pass\n            try: self.board_close_requested.emit(); self.state_requested.emit("idle")\n            except Exception: pass\n            self._sampling=False\n            self._gpu_stop.set()\n            try:\n                if sampler.is_alive(): sampler.join(timeout=4)\n            except Exception: pass\n            try:\n                if gpu_thread.is_alive(): gpu_thread.join(timeout=4)\n            except Exception: pass\n            if self._nvml_ready and pynvml is not None:\n                try: pynvml.nvmlShutdown()\n                except Exception: pass\n            self._nvml_ready=False; self._nvml_handle=None\n        try:\n            self._set_stage("report",99,"正在生成脱敏诊断 ZIP")\n            report=self._write_reports()\n            if ok:\n                self._progress(100,"测试完成：桌面已生成诊断ZIP")\n                msg=f"诊断完成：{report}"\n            else:\n                self._progress(90,"测试中止：已生成故障诊断ZIP")\n                msg=f"测试中止，已生成故障报告：{report}\\n{err}"\n            self.finished.emit(ok,str(report),msg)\n        except Exception as exc:\n            self.finished.emit(False,"",f"生成诊断报告失败：{type(exc).__name__}: {exc}")\n        finally:\n            self._disconnect_service_signals()\n            self._running=False\n'''
new = '''        finally:\n            try: setattr(self.brain,"_resource_diag_no_persist",False)\n            except Exception: pass\n            try: self.board_close_requested.emit(); self.state_requested.emit("idle")\n            except Exception: pass\n            self._sampling=False\n            self._gpu_stop.set()\n            try:\n                if sampler.is_alive(): sampler.join(timeout=6)\n            except Exception: pass\n            try:\n                if gpu_thread.is_alive(): gpu_thread.join(timeout=6)\n            except Exception: pass\n            # Intentionally keep NVML initialized. Do not call pynvml.nvmlShutdown() here.\n            # The diagnostic must never risk a native DLL teardown before its report is saved.\n        report = None\n        try:\n            self._set_stage("report",99,"正在生成脱敏诊断 ZIP")\n            self._journal_status("reporting", "report")\n            self._close_live_journals()\n            report=self._write_reports()\n            try:\n                (self.session_dir / "finalized.flag").write_text(str(report), encoding="utf-8")\n            except Exception:\n                pass\n            if ok:\n                self._progress(100,"测试完成：桌面已生成诊断ZIP")\n                msg=f"诊断完成：{report}"\n            else:\n                self._progress(90,"测试中止：已生成故障诊断ZIP")\n                msg=f"测试中止，已生成故障报告：{report}\\n{err}"\n            self.finished.emit(ok,str(report),msg)\n        except Exception as exc:\n            self._journal_status("report_failed", "report", error=f"{type(exc).__name__}: {exc}")\n            self._close_live_journals()\n            self.finished.emit(False,"",f"生成诊断报告失败：{type(exc).__name__}: {exc}")\n        finally:\n            # Riskier child-process/native cleanup happens only after report generation.\n            self._terminate_proc(self._speech_proc); self._terminate_proc(self._combined_speech_proc)\n            self._speech_proc=None; self._combined_speech_proc=None\n            self._disconnect_service_signals()\n            self._running=False\n'''
d = rep(d, old, new, 'crash-safe finalization order')

# Ensure any journal handles are closed if _write_reports itself exits unexpectedly.
# No explicit NVML shutdown is allowed in the final diagnostic module.
if 'pynvml.nvmlShutdown()' in d:
    raise RuntimeError('unsafe NVML shutdown still present')

wr(diag_new, d)

(root / 'app' / 'assets' / 'VERSION.txt').write_text('0.10.0.9.3.3\n', encoding='ascii')
(root / 'V0100933_CHANGELOG.txt').write_text('''XiaoMeili V0.10.0.9.3.3\n\n- 修复完整测试结束后主程序可能在报告生成前直接退出的问题。\n- 诊断结果改为“先落盘、再清理”：停止采样后优先生成桌面ZIP，ASR子进程等清理移动到报告之后。\n- 取消诊断结束时主动调用 pynvml.nvmlShutdown()，避免原生NVML DLL退出路径在报告生成前造成进程级崩溃。\n- 新增崩溃安全实时日志：timeline/events/rounds/status 以追加方式持续写入受控诊断目录，主程序即使异常退出也保留大部分数据。\n- 新版启动时自动扫描上次中断的诊断会话并生成“自动恢复”ZIP；只复制，不删除、不移动任何原始文件。\n- 兼容恢复V0.10.0.9.3.2遗留的 speech_diagnostic_worker.log 等安全证据。\n- 保留NVML无黑框采样、真实CPU、稳定250ms、WAV/ASR修复、NDM和FullSafe。\n''', encoding='utf-8')

for p in (main, diag_new):
    py_compile.compile(str(p), doraise=True)
combined = rd(main) + rd(diag_new)
for token in [
    'APP_VERSION = "0.10.0.9.3.3"', 'resource_diagnostic_v0100933',
    'recover_interrupted_resource_diagnostics', 'live_timeline.jsonl', 'live_events.jsonl',
    'live_rounds.jsonl', 'live_status.jsonl', 'finalized.flag',
    'Do not call pynvml.nvmlShutdown()', '测试完成：桌面已生成诊断ZIP'
]:
    if token not in combined:
        raise RuntimeError('contract missing: ' + token)
if 'pynvml.nvmlShutdown()' in rd(diag_new):
    raise RuntimeError('NVML shutdown still present')
print('PATCH_0100933_PASS')
