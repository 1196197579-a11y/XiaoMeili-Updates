# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root=Path(sys.argv[1]).resolve()
src=root/"app"/"src"
main=src/"main.py"
diag=src/"resource_diagnostic_v0100934.py"
monitor=src/"resource_monitor_v0100940.py"

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError("missing patch anchor: "+name)
    return s.replace(a,b,count)

if not monitor.is_file():
    raise RuntimeError("external monitor source missing from source tree")

# ---------- main.py ----------
s=rd(main)
if 'APP_VERSION = "0.10.0.9.3.7"' not in s:
    raise RuntimeError("V0.10.0.9.3.7 baseline required")
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3.7｜Stable Resource Diagnostic 3.2"',
      'APP_NAME = "小美丽 V0.10.0.9.4.0｜External Resource Diagnostic 4.0"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3.7"','APP_VERSION = "0.10.0.9.4.0"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3.7"','APP_UPDATE_VERSION = "0.10.0.9.4.0"','update version')
s=s.replace('cfg["config_version"] = max(39, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(40, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 39','cfg["config_version"] = 40')
wr(main,s)

# ---------- diagnostic coordinator ----------
d=rd(diag)
if 'import sys\n' not in d:
    d=d.replace('import subprocess\n','import subprocess\nimport sys\n',1)

# Replace the old PowerShell watchdog implementation with a dedicated EXE.
block_start=d.index('    @staticmethod\n    def _ps_quote')
block_end=d.index('    def is_running(self):\n',block_start)
new_methods=r'''    def _start_watchdog(self):
        """Launch the authoritative external resource monitor.

        The helper is a separate executable next to XiaoMeili.exe. It owns the
        250ms CPU/RAM/GPU/VRAM timeline and survives a host crash. This method
        only performs a ready handshake; it never deletes/moves user files.
        """
        helper=Path(sys.executable).resolve().with_name("XiaoMeiliResourceMonitor.exe")
        if not helper.is_file():
            self._event("external_monitor_missing",helper_name=helper.name)
            return False
        flags=(getattr(subprocess,"CREATE_NO_WINDOW",0)
               | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
               | getattr(subprocess,"DETACHED_PROCESS",0)
               | getattr(subprocess,"CREATE_BREAKAWAY_FROM_JOB",0))
        cmd=[
            str(helper),
            "--pid",str(os.getpid()),
            "--session",str(self.session_dir),
            "--desktop",str(self.desktop),
            "--app-version",str(self.app_version),
        ]
        try:
            self._watchdog_proc=subprocess.Popen(
                cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=flags,cwd=str(self.session_dir),close_fds=True)
        except OSError:
            flags=(getattr(subprocess,"CREATE_NO_WINDOW",0)
                   | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
                   | getattr(subprocess,"DETACHED_PROCESS",0))
            self._watchdog_proc=subprocess.Popen(
                cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=flags,cwd=str(self.session_dir),close_fds=True)
        self._event("external_monitor_started",pid=int(self._watchdog_proc.pid))
        ready=self.session_dir/"watchdog_ready.flag"
        deadline=time.monotonic()+8.0
        while time.monotonic()<deadline:
            if ready.exists():
                self._event("external_monitor_ready",pid=int(self._watchdog_proc.pid))
                return True
            try:
                code=self._watchdog_proc.poll()
                if code is not None:
                    self._event("external_monitor_early_exit",exit_code=int(code))
                    return False
            except Exception:
                pass
            time.sleep(0.05)
        self._event("external_monitor_not_ready")
        return False

    def _stop_external_monitor_for_report(self, timeout=10.0):
        if self.session_dir is None:
            return False
        stop=self.session_dir/"external_monitor_stop.flag"
        stopped=self.session_dir/"external_monitor_stopped.flag"
        try:
            if not stop.exists():
                stop.write_text(str(time.time()),encoding="utf-8")
        except Exception as exc:
            self._event("external_monitor_stop_flag_error",error=f"{type(exc).__name__}: {exc}")
            return False
        deadline=time.monotonic()+float(timeout)
        while time.monotonic()<deadline:
            if stopped.exists():
                self._event("external_monitor_stopped")
                return True
            try:
                if self._watchdog_proc is not None and self._watchdog_proc.poll() is not None:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        self._event("external_monitor_stop_timeout")
        return False

'''
d=d[:block_start]+new_methods+d[block_end:]

# Use explicit external-monitor wording for the ready gate.
d=d.replace(
    'raise RuntimeError("独立闪退监控器未确认启动，已停止资源长测，避免再次出现无证据闪退")',
    'raise RuntimeError("外部资源诊断器未确认启动，已停止长测；不会降级回内置监控")'
)

# Before the normal ZIP is written, stop external sampling and wait for its
# CSV/summary files to close. The helper then lingers until finalized.flag.
old='''            self._set_stage("report",99,"正在生成脱敏诊断 ZIP")
            self._journal_status("reporting", "report")
            self._close_live_journals()
            report=self._write_reports()
'''
new='''            self._set_stage("report",99,"正在生成脱敏诊断 ZIP")
            self._journal_status("reporting", "report")
            external_stopped=self._stop_external_monitor_for_report(timeout=10.0)
            self._event("external_monitor_report_ready",ok=bool(external_stopped))
            self._close_live_journals()
            report=self._write_reports()
'''
d=rep(d,old,new,'stop external monitor before report')

# Include authoritative external files in both normal and recovered ZIPs.
external_names=[
    "external_timeline_250ms.csv","external_process_tree.csv",
    "external_monitor_status.jsonl","external_monitor_summary.json",
    "external_windows_event_log.txt","external_monitor_stopped.flag",
    "external_monitor_stop.flag","external_report_path.txt","watchdog_ready.flag",
]
for name in external_names:
    if f'"{name}"' not in d:
        # Add to the final names set via a stable existing member.
        d=d.replace('"live_status.jsonl"',f'"live_status.jsonl","{name}"')

# Report metadata explicitly identifies the external observer as authoritative.
needle='"gpu_collector":self._gpu_source'
if needle in d:
    d=d.replace(needle,needle+',"authoritative_resource_collector":"XiaoMeiliResourceMonitor.exe (external process)"',1)

# Old PowerShell watchdog must be gone from executable source.
if 'resource_diag_watchdog.ps1' in d:
    d=d.replace('"resource_diag_watchdog.ps1",','')
    d=d.replace(',"resource_diag_watchdog.ps1"','')
if 'powershell.exe","-NoProfile"' in d:
    raise RuntimeError("legacy PowerShell watchdog launch remains")
if '_main_action("tts_abort"' in d or 'abort_playback(' in d:
    raise RuntimeError("resource diagnostic force-abort path returned")
if '_main_action("hard_silence"' in d or 'utterance_ready.emit(' in d:
    raise RuntimeError("resource diagnostic synthetic hard-silence path returned")

for bad in ("Remove-Item","shutil.rmtree","os.remove","Path.unlink","shutil.move"):
    if bad in d:
        raise RuntimeError("unsafe diagnostic token: "+bad)

wr(diag,d)

(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.4.0\n",encoding="ascii")
(root/"V0100940_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.4.0

- 一键深度资源测试重构为 External Resource Diagnostic 4.0。
- CPU/RAM/GPU/显存/线程/进程的权威采样迁移到独立 XiaoMeiliResourceMonitor.exe；小美丽内部只负责正常业务自动化与阶段标记。
- 外部监控器每250ms持续落盘，即使 XiaoMeili.exe 原生崩溃也能独立生成桌面闪退ZIP。
- 正常测试结束前由小美丽发送只创建不覆盖的 stop flag，外部监控器关闭CSV后再由正常报告ZIP统一打包。
- 外部监控器启动必须通过ready握手；否则立即停止，不再降级到旧PowerShell Watchdog。
- 深度资源测试继续禁止强制TTS abort和伪造闭嘴ASR；只测试自然TTS完成后的资源回落。
- 保留ASR、大脑、TTS、白板、动画、30轮聊天、离线识别、综合满载、90秒回落。
- FullSafe继续生效：不删除、不移动、不覆盖、不递归清理用户文件、D盘数据或任何旧版本。
""",encoding="utf-8")

for p in (main,diag,monitor):
    py_compile.compile(str(p),doraise=True)

combined=rd(main)+rd(diag)+rd(monitor)
for token in [
    'APP_VERSION = "0.10.0.9.4.0"',
    'XiaoMeiliResourceMonitor.exe',
    'authoritative_resource_collector',
    'external_timeline_250ms.csv',
    'external_monitor_summary.json',
    'external_monitor_stop.flag',
    'external_monitor_stopped.flag',
    'watchdog_ready.flag',
    'CHAT_ROUNDS = 30',
    'FINAL_COOLDOWN_SECONDS = 90',
]:
    if token not in combined:
        raise RuntimeError("contract missing: "+token)
print("PATCH_0100940_PASS")
