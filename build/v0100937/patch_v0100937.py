# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root=Path(sys.argv[1]).resolve()
src=root/"app"/"src"
main=src/"main.py"
diag=src/"resource_diagnostic_v0100934.py"

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError("missing patch anchor: "+name)
    return s.replace(a,b,count)

s=rd(main)
if 'APP_VERSION = "0.10.0.9.3.6"' not in s:
    raise RuntimeError("V0.10.0.9.3.6 baseline required")
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3.6｜Stable Resource Diagnostic 3.1"',
      'APP_NAME = "小美丽 V0.10.0.9.3.7｜Stable Resource Diagnostic 3.2"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3.6"','APP_VERSION = "0.10.0.9.3.7"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3.6"','APP_UPDATE_VERSION = "0.10.0.9.3.7"','update version')
s=s.replace('cfg["config_version"] = max(38, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(39, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 38','cfg["config_version"] = 39')
wr(main,s)

d=rd(diag)

old=r'''    def _tts_once(self, text, tag, timeout=30):
        self._tts_started.clear(); self._tts_done.clear()
        ok,msg,_=self._main_action("tts_speak",{"text":str(text),"tag":str(tag)},timeout=8)
        if not ok:
            self._event("tts_call_error", error=msg)
            return False
        self._tts_started.wait(min(8.0, timeout))
        if not self._tts_done.wait(timeout):
            self._main_action("tts_abort",{"reason":"resource_diag_timeout"},timeout=5)
            self._event("tts_timeout", tag=str(tag))
            return False
        ok, message, _ = self._tts_result
        self._event("tts_result", tag=str(tag), ok=bool(ok), message_len=len(message))
        return bool(ok)
'''
new=r'''    def _tts_once(self, text, tag, timeout=30):
        self._tts_started.clear(); self._tts_done.clear()
        ok,msg,_=self._main_action("tts_speak",{"text":str(text),"tag":str(tag)},timeout=8)
        if not ok:
            self._event("tts_call_error", error=msg)
            return False
        self._tts_started.wait(min(8.0, timeout))
        if not self._tts_done.wait(timeout):
            self._event("tts_timeout_fail_stop", tag=str(tag), timeout_seconds=float(timeout))
            raise RuntimeError("TTS自然播放超时：为避免强制abort导致原生闪退，资源测试已安全停止")
        ok, message, _ = self._tts_result
        self._event("tts_result", tag=str(tag), ok=bool(ok), message_len=len(message))
        return bool(ok)
'''
d=rep(d,old,new,'remove TTS abort on timeout')

start=d.index('    def _safe_interrupt_once(self, index, kind="safe_interrupt"):\n')
end=d.index('    def _offline_vision_once(self, include_ocr=True):\n',start)
natural=r'''    def _natural_tts_recovery_once(self, index, kind="natural_tts_recovery"):
        rec=self._round_start(kind,index)
        text="这是资源测试的自然播放回收检查。语音会正常播放结束，然后关闭白板并观察资源是否回落。"
        self.board_requested.emit(text,9000)
        ok=self._tts_once(text,f"resource_diag_natural_recovery_{index}",timeout=35)
        self.board_close_requested.emit()
        self._sleep(1.2)
        ok_state,msg_state,state=self._main_action("interrupt_snapshot",{},timeout=5)
        still_tts=bool((state or {}).get("tts_active",True))
        still_board=bool((state or {}).get("board_active",True))
        passed=bool(ok and ok_state and not still_tts and not still_board)
        self._event("natural_tts_recovery_check",index=index,tts_active=still_tts,board_active=still_board,ok=passed)
        self._round_end(rec,passed,1.0)
        return passed

    def _hard_silence_preflight(self):
        self._event("natural_tts_preflight_begin")
        passed=self._natural_tts_recovery_once(0,kind="natural_tts_preflight")
        self._event("natural_tts_preflight_end",ok=bool(passed))
        if not passed:
            raise RuntimeError("TTS自然播放/白板回收预检未通过，已停止后续长时间测试")

    def _hard_silence_stage(self):
        for i in range(1,4):
            if not self._natural_tts_recovery_once(i,kind="natural_tts_recovery"):
                raise RuntimeError("TTS自然播放回收阶段未通过，已停止后续测试")

'''
d=d[:start]+natural+d[end:]

d=d.replace('安全预检：主线程TTS→安全中止→白板关闭（约10秒）',
            '安全预检：TTS自然播完→白板关闭→资源回落（约10秒）')
d=d.replace('8/10 TTS/白板中止回收：不伪造ASR口令，不触碰输入法状态',
            '8/10 TTS自然播放回收：3轮自然播完→白板关闭→资源回落')

old=r'''$Start = Get-Date
while ($true) {{
  if (Test-Path (Join-Path $Session 'finalized.flag')) {{ exit 0 }}
'''
new=r'''$Start = Get-Date
$ready = Join-Path $Session 'watchdog_ready.flag'
Set-Content -LiteralPath $ready -Value ((Get-Date).ToString('o')) -Encoding UTF8
while ($true) {{
  if (Test-Path (Join-Path $Session 'finalized.flag')) {{ exit 0 }}
'''
d=rep(d,old,new,'watchdog ready flag')

old=r'''        self._event("watchdog_started",pid=int(self._watchdog_proc.pid))

    def is_running(self):
'''
new=r'''        self._event("watchdog_started",pid=int(self._watchdog_proc.pid))
        ready=self.session_dir/"watchdog_ready.flag"
        deadline=time.monotonic()+4.0
        while time.monotonic()<deadline:
            if ready.exists():
                self._event("watchdog_ready",pid=int(self._watchdog_proc.pid))
                return True
            try:
                if self._watchdog_proc.poll() is not None:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        self._event("watchdog_not_ready")
        return False

    def is_running(self):
'''
d=rep(d,old,new,'watchdog readiness return')

old='''        self._open_live_journals()
        self._start_watchdog()
        wav_path=None; ok=True; err=""
        self._sampling=True
'''
new='''        self._open_live_journals()
        watchdog_ready=self._start_watchdog()
        wav_path=None; ok=True; err=""
        self._sampling=True
'''
d=rep(d,old,new,'watchdog ready variable')

anchor='''            self._set_stage("preflight_interrupt",1,"安全预检：TTS自然播完→白板关闭→资源回落（约10秒）")
'''
insert='''            if not watchdog_ready:
                raise RuntimeError("独立闪退监控器未确认启动，已停止资源长测，避免再次出现无证据闪退")
            self._set_stage("preflight_interrupt",1,"安全预检：TTS自然播完→白板关闭→资源回落（约10秒）")
'''
d=rep(d,anchor,insert,'watchdog fail-stop before TTS preflight')

d=d.replace('"resource_diag_watchdog.ps1","windows_event_log.txt","watchdog_summary.json"}',
            '"resource_diag_watchdog.ps1","windows_event_log.txt","watchdog_summary.json","watchdog_ready.flag"}')
d=d.replace("'windows_event_log.txt','watchdog_summary.json'",
            "'windows_event_log.txt','watchdog_summary.json','watchdog_ready.flag'")

if '_main_action("tts_abort"' in d:
    raise RuntimeError("resource diagnostic still contains tts_abort")
if 'abort_playback(' in d:
    raise RuntimeError("resource diagnostic still contains abort_playback")
if '_main_action("hard_silence"' in d:
    raise RuntimeError("resource diagnostic still synthesizes hard silence")
if 'utterance_ready.emit(' in d:
    raise RuntimeError("resource diagnostic still fabricates ASR utterances")
for bad in ("Remove-Item","shutil.rmtree","os.remove","Path.unlink","shutil.move"):
    if bad in d:
        raise RuntimeError("unsafe diagnostic token: "+bad)

wr(diag,d)

(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.3.7\n",encoding="ascii")
(root/"V0100937_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.3.7

- 深度资源测试彻底移除所有强制TTS中止测试：不再调用 tts_abort / abort_playback，不再伪造“闭嘴”ASR口令。
- 启动前预检改为“正常TTS自然播完 → 白板关闭 → 资源回落”。
- 第8阶段改为3轮“正常TTS自然播完 → 白板关闭 → 资源回落”。
- _tts_once() 若自然播放超时，只记录错误并安全停止整个资源测试；绝不强制abort，避免再次触发原生音频层闪退。
- 真实“闭嘴”功能本身保持不变，仅从资源压力测试中移除危险的强制中断场景。
- 独立Watchdog新增ready握手；未确认监控器已启动时不会进入长测，避免再次出现无证据闪退。
- Watchdog继续脱离主进程启动，且不计入小美丽RAM/CPU统计。
- 保留ASR、大脑、TTS、白板、30轮聊天、动画、离线识别、综合满载、90秒回落、实时追加日志。
- FullSafe继续生效：不删除、不移动、不覆盖、不递归清理用户文件、D盘数据或任何旧版本。
""",encoding="utf-8")

for p in (main,diag):
    py_compile.compile(str(p),doraise=True)

combined=rd(main)+rd(diag)
for token in [
    'APP_VERSION = "0.10.0.9.3.7"',
    'natural_tts_preflight_begin',
    'natural_tts_recovery_check',
    'watchdog_ready.flag',
    'watchdog_ready=self._start_watchdog()',
    'CHAT_ROUNDS = 30',
    'FINAL_COOLDOWN_SECONDS = 90'
]:
    if token not in combined:
        raise RuntimeError("contract missing: "+token)
print("PATCH_0100937_PASS")
