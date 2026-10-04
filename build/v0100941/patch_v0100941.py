# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root=Path(sys.argv[1]).resolve()
src=root/"app"/"src"
main=src/"main.py"
diag=src/"resource_diagnostic_v0100934.py"
monitor=src/"resource_monitor_v0100941.py"

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError("missing patch anchor: "+name)
    return s.replace(a,b,count)

if not monitor.is_file():
    raise RuntimeError("V0.10.0.9.4.1 external monitor source missing")

# ---------- main.py ----------
s=rd(main)
if 'APP_VERSION = "0.10.0.9.4.0"' not in s:
    raise RuntimeError("V0.10.0.9.4.0 baseline required")
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.4.0｜External Resource Diagnostic 4.0"',
      'APP_NAME = "小美丽 V0.10.0.9.4.1｜External Resource Diagnostic 4.1"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.4.0"','APP_VERSION = "0.10.0.9.4.1"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.4.0"','APP_UPDATE_VERSION = "0.10.0.9.4.1"','update version')
s=s.replace('cfg["config_version"] = max(40, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(41, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 40','cfg["config_version"] = 41')
wr(main,s)

# ---------- diagnostic coordinator ----------
d=rd(diag)

# Replace one-file-at-root launch with a fixed onedir component.
old_start=d.index('    def _start_watchdog(self):\n')
old_end=d.index('    def _stop_external_monitor_for_report',old_start)
new_start=r'''    def _start_watchdog(self):
        """Launch the fixed onedir external monitor component.

        The helper is installed at ResourceMonitor/XiaoMeiliResourceMonitor.exe.
        No runtime self-extraction, PowerShell, deletion, moving or overwriting is used.
        """
        helper_dir=Path(sys.executable).resolve().parent/"ResourceMonitor"
        helper=helper_dir/"XiaoMeiliResourceMonitor.exe"
        if not helper.is_file():
            self._event("external_monitor_missing",helper=str(helper))
            return False
        out_path=self.session_dir/"external_monitor_stdout.log"
        err_path=self.session_dir/"external_monitor_stderr.log"
        try:
            out_fp=out_path.open("x",encoding="utf-8",buffering=1)
            err_fp=err_path.open("x",encoding="utf-8",buffering=1)
        except Exception as exc:
            self._event("external_monitor_log_open_error",error=f"{type(exc).__name__}: {exc}")
            return False
        flags=(getattr(subprocess,"CREATE_NO_WINDOW",0)
               | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0))
        cmd=[
            str(helper),
            "--pid",str(os.getpid()),
            "--session",str(self.session_dir),
            "--desktop",str(self.desktop),
            "--app-version",str(self.app_version),
        ]
        try:
            self._watchdog_proc=subprocess.Popen(
                cmd,stdin=subprocess.DEVNULL,stdout=out_fp,stderr=err_fp,
                creationflags=flags,cwd=str(helper_dir),close_fds=True)
        except Exception as exc:
            self._event("external_monitor_launch_error",error=f"{type(exc).__name__}: {exc}")
            return False
        finally:
            try: out_fp.close()
            except Exception: pass
            try: err_fp.close()
            except Exception: pass

        self._event("external_monitor_started",pid=int(self._watchdog_proc.pid),mode="fixed_onedir")
        ready=self.session_dir/"watchdog_ready.flag"
        deadline=time.monotonic()+8.0
        while time.monotonic()<deadline:
            if ready.exists():
                self._event("external_monitor_ready",pid=int(self._watchdog_proc.pid),mode="fixed_onedir")
                return True
            try:
                code=self._watchdog_proc.poll()
                if code is not None:
                    self._event("external_monitor_early_exit",exit_code=int(code),mode="fixed_onedir")
                    return False
            except Exception:
                pass
            time.sleep(0.05)
        self._event("external_monitor_not_ready",mode="fixed_onedir")
        return False

'''
d=d[:old_start]+new_start+d[old_end:]

# Startup must live inside the main try block, so any helper failure generates a
# normal failure report instead of leaving the UI forever at 0%.
old='''        self._open_live_journals()
        watchdog_ready=self._start_watchdog()
        wav_path=None; ok=True; err=""
'''
new='''        self._open_live_journals()
        watchdog_ready=False
        wav_path=None; ok=True; err=""
'''
d=rep(d,old,new,'defer monitor startup into guarded try')

anchor='''            self._set_stage("preflight",1,"启动前快速自检：事件、CPU、GPU与ASR测试音频")
'''
insert='''            self._progress(0,"正在启动外部资源监控器…")
            self._event("external_monitor_launch_begin",mode="fixed_onedir")
            watchdog_ready=self._start_watchdog()
            if not watchdog_ready:
                raise RuntimeError("外部资源监控器启动失败或8秒内未握手；已停止长测并生成故障报告")
            self._progress(1,"外部资源监控器已连接，开始测试")
            self._set_stage("preflight",1,"启动前快速自检：事件、CPU、GPU与ASR测试音频")
'''
d=rep(d,anchor,insert,'visible onedir monitor startup state')

# Remove the old later ready gate if present; readiness is now checked before
# any preflight work and inside the exception/report path.
old_gate='''            if not watchdog_ready:
                raise RuntimeError("外部资源诊断器未确认启动，已停止长测；不会降级回内置监控")
'''
d=d.replace(old_gate,'')

# Include startup logs in both normal/recovery ZIP allowlists.
for name in ("external_monitor_stdout.log","external_monitor_stderr.log"):
    if f'"{name}"' not in d:
        d=d.replace('"external_monitor_status.jsonl"',f'"external_monitor_status.jsonl","{name}"')

# Update collector identity.
d=d.replace(
    '"authoritative_resource_collector":"XiaoMeiliResourceMonitor.exe (external process)"',
    '"authoritative_resource_collector":"ResourceMonitor/XiaoMeiliResourceMonitor.exe (fixed onedir external process)"'
)

# Architecture / safety contracts.
if 'with_name("XiaoMeiliResourceMonitor.exe")' in d:
    raise RuntimeError("old root one-file monitor path remains")
if 'CREATE_BREAKAWAY_FROM_JOB' in d or 'DETACHED_PROCESS' in d:
    raise RuntimeError("legacy complex watchdog flags remain")
if '_main_action("tts_abort"' in d or 'abort_playback(' in d:
    raise RuntimeError("resource diagnostic force-abort path returned")
if '_main_action("hard_silence"' in d or 'utterance_ready.emit(' in d:
    raise RuntimeError("resource diagnostic synthetic hard-silence path returned")
for bad in ("Remove-Item","shutil.rmtree","os.remove","Path.unlink","shutil.move"):
    if bad in d:
        raise RuntimeError("unsafe diagnostic token: "+bad)

wr(diag,d)

(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.4.1\n",encoding="ascii")
(root/"V0100941_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.4.1

- 外部资源监控器从 PyInstaller one-file 改为随程序固定安装的 onedir 组件：ResourceMonitor/XiaoMeiliResourceMonitor.exe + _internal。
- 点击一键测试后界面会明确显示“正在启动外部资源监控器…”；握手成功后显示“外部资源监控器已连接，开始测试”。
- 外部监控器8秒内未ready会立即停止并生成故障报告，不再无限卡在0%。
- 外部监控器启动日志写入诊断会话并随ZIP打包，后续若启动异常可直接定位。
- 启动参数简化为 CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP，不再使用one-file自解压、PowerShell、BREAKAWAY/DETACHED复杂组合。
- 外部监控器不计入小美丽自身资源统计。
- 保留每250ms CPU/RAM/GPU/显存/线程/进程采样、ASR、大脑、TTS、白板、动画、30轮聊天、离线识别、综合满载与90秒回落。
- 深度资源测试继续禁止强制TTS abort和伪造闭嘴ASR。
- FullSafe继续生效：不删除、不移动、不覆盖、不递归清理用户文件、D盘数据或任何旧版本。
""",encoding="utf-8")

for p in (main,diag,monitor):
    py_compile.compile(str(p),doraise=True)

combined=rd(main)+rd(diag)+rd(monitor)
for token in [
    'APP_VERSION = "0.10.0.9.4.1"',
    'ResourceMonitor',
    'fixed_onedir',
    '正在启动外部资源监控器',
    '外部资源监控器已连接，开始测试',
    'external_monitor_stdout.log',
    'external_monitor_stderr.log',
    'external_timeline_250ms.csv',
    'CHAT_ROUNDS = 30',
    'FINAL_COOLDOWN_SECONDS = 90'
]:
    if token not in combined:
        raise RuntimeError("contract missing: "+token)
print("PATCH_0100941_PASS")
