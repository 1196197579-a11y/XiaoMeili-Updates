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

# ---------- main.py ----------
s=rd(main)
if 'APP_VERSION = "0.10.0.9.3.5"' not in s:
    raise RuntimeError("V0.10.0.9.3.5 baseline required")
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3.5｜Crash-Safe Diagnostic 3.0 Preflight Fix"',
      'APP_NAME = "小美丽 V0.10.0.9.3.6｜Stable Resource Diagnostic 3.1"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3.5"','APP_VERSION = "0.10.0.9.3.6"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3.5"','APP_UPDATE_VERSION = "0.10.0.9.3.6"','update version')
s=s.replace('cfg["config_version"] = max(37, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(38, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 37','cfg["config_version"] = 38')
wr(main,s)

# ---------- diagnostic ----------
d=rd(diag)
# Do not synthesize "闭嘴" into a stopped SpeechInputService. The previous
# diagnostic created an impossible runtime state: speech_state=stopped while the
# production P0 handler was forced to resume listening. That is not a valid
# resource test and was the last action before the native crash.
old=r'''    def _hard_silence_once(self, phrase, index, kind="hard_silence"):
        rec=self._round_start(kind,index)
        long_text="这是用于测试闭嘴硬打断的较长语音，正常情况下应该在播报中途被立即停止，不应该继续说完这句话。"
        self._tts_started.clear(); self._tts_done.clear()
        self.board_requested.emit(long_text,9000)
        ok,msg,_=self._main_action("tts_speak",{
            "text":long_text,"tag":f"resource_diag_interrupt_{index}"
        },timeout=8)
        if not ok:
            self.board_close_requested.emit()
            self._round_end(rec,False,0.5)
            return False
        self._tts_started.wait(6)
        ok,msg,_=self._main_action("hard_silence",{"phrase":str(phrase)},timeout=8)
        if not ok:
            self.board_close_requested.emit()
            self._round_end(rec,False,0.5)
            return False
        self._sleep(2.0)
        ok,msg,state=self._main_action("interrupt_snapshot",{},timeout=5)
        still_tts=bool((state or {}).get("tts_active",True))
        still_board=bool((state or {}).get("board_active",True))
        self._event("hard_silence_check",phrase_id=index,tts_active=still_tts,board_active=still_board)
        self.board_close_requested.emit()
        passed=bool(ok and not still_tts and not still_board)
        self._round_end(rec,passed,1.2)
        return passed

    def _hard_silence_preflight(self):
        self._event("hard_silence_preflight_begin")
        passed=self._hard_silence_once("闭嘴",0,kind="hard_silence_preflight")
        self._event("hard_silence_preflight_end",ok=bool(passed))
        if not passed:
            raise RuntimeError("闭嘴主线程高风险预检未通过，已停止后续长时间测试")

    def _hard_silence_stage(self):
        for i,phrase in enumerate(("闭嘴","你给我闭嘴","你别说话了"),1):
            self._hard_silence_once(phrase,i)

'''
new=r'''    def _safe_interrupt_once(self, index, kind="safe_interrupt"):
        """Exercise TTS/whiteboard cleanup without fabricating an ASR utterance."""
        rec=self._round_start(kind,index)
        long_text="这是资源测试的安全中止播报，用于检查TTS和白板关闭以后资源是否正常回收。"
        self._tts_started.clear(); self._tts_done.clear()
        self.board_requested.emit(long_text,9000)
        ok,msg,_=self._main_action("tts_speak",{
            "text":long_text,"tag":f"resource_diag_safe_interrupt_{index}"
        },timeout=8)
        if not ok:
            self.board_close_requested.emit()
            self._round_end(rec,False,0.5)
            return False
        self._tts_started.wait(6)
        ok_abort,msg_abort,_=self._main_action("tts_abort",{
            "reason":"resource_diag_safe_interrupt"
        },timeout=8)
        self.board_close_requested.emit()
        self._sleep(1.2)
        ok_state,msg_state,state=self._main_action("interrupt_snapshot",{},timeout=5)
        still_tts=bool((state or {}).get("tts_active",True))
        still_board=bool((state or {}).get("board_active",True))
        passed=bool(ok_abort and ok_state and not still_tts and not still_board)
        self._event("safe_interrupt_check",index=index,tts_active=still_tts,board_active=still_board,ok=passed)
        self._round_end(rec,passed,1.0)
        return passed

    def _hard_silence_preflight(self):
        # Compatibility name only. This is intentionally NOT a synthetic
        # hard-silence/ASR test. It validates the same TTS+whiteboard cleanup
        # resources without forcing SpeechInputService out of a stopped state.
        self._event("safe_interrupt_preflight_begin")
        passed=self._safe_interrupt_once(0,kind="safe_interrupt_preflight")
        self._event("safe_interrupt_preflight_end",ok=bool(passed))
        if not passed:
            raise RuntimeError("TTS/白板安全中止预检未通过，已停止后续长时间测试")

    def _hard_silence_stage(self):
        for i in range(1,4):
            self._safe_interrupt_once(i,kind="safe_interrupt")

'''
d=rep(d,old,new,'replace synthetic hard silence with safe interrupt')

d=d.replace('高风险预检：主线程TTS→闭嘴→白板关闭（约10秒）',
            '安全预检：主线程TTS→安全中止→白板关闭（约10秒）')
d=d.replace('8/10 闭嘴硬打断：分别测试闭嘴/你给我闭嘴/你别说话了',
            '8/10 TTS/白板中止回收：不伪造ASR口令，不触碰输入法状态')

# External watchdog must be breakaway/detached so it survives a host crash.
old=r'''        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        cmd=["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden",
             "-ExecutionPolicy","Bypass","-File",str(script)]
        self._watchdog_proc=subprocess.Popen(
            cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=flags,cwd=str(self.session_dir))
'''
new=r'''        flags=(getattr(subprocess,"CREATE_NO_WINDOW",0)
               | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
               | getattr(subprocess,"DETACHED_PROCESS",0)
               | getattr(subprocess,"CREATE_BREAKAWAY_FROM_JOB",0))
        cmd=["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden",
             "-ExecutionPolicy","Bypass","-File",str(script)]
        try:
            self._watchdog_proc=subprocess.Popen(
                cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=flags,cwd=str(self.session_dir),close_fds=True)
        except OSError:
            # Some Windows job policies reject BREAKAWAY. Fall back to hidden
            # detached process flags without changing/deleting any user file.
            flags=(getattr(subprocess,"CREATE_NO_WINDOW",0)
                   | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
                   | getattr(subprocess,"DETACHED_PROCESS",0))
            self._watchdog_proc=subprocess.Popen(
                cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=flags,cwd=str(self.session_dir),close_fds=True)
'''
d=rep(d,old,new,'detached watchdog')

# Exclude the diagnostic watchdog from XiaoMeili resource totals.
old='''        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        rows = []
'''
new='''        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        ignored=set()
        try:
            if self._watchdog_proc is not None:
                wp=psutil.Process(int(self._watchdog_proc.pid))
                ignored.add(wp.pid)
                ignored.update(x.pid for x in wp.children(recursive=True))
        except Exception:
            pass
        procs=[p for p in procs if p.pid not in ignored]
        rows = []
'''
d=rep(d,old,new,'exclude watchdog resources')

# Architecture/safety contracts.
if '_main_action("hard_silence"' in d:
    raise RuntimeError("synthetic hard-silence action remains in resource diagnostic")
if 'self.speech.utterance_ready.emit(' in d:
    raise RuntimeError("diagnostic still fabricates ASR utterances")
for bad in ("Remove-Item","shutil.rmtree","os.remove","Path.unlink","shutil.move"):
    if bad in d:
        raise RuntimeError("unsafe diagnostic token: "+bad)

wr(diag,d)
(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.3.6\n",encoding="ascii")
(root/"V0100936_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.3.6

- 深度资源测试不再伪造“闭嘴”ASR口令。此前测试在 speech_state=stopped 时强行走真实P0恢复监听链路，属于不可能的运行状态，也是两次原生闪退前最后一个共同动作。
- 第8阶段改为“安全TTS/白板中止回收”，仍测试TTS abort、白板关闭和资源回落，但不改变真实闭嘴功能本身。
- 启动前约10秒预检同步改为安全中止预检；失败会立即停止，不浪费长测时间。
- Watchdog改为独立/脱离主进程启动，并在允许时BREAKAWAY_FROM_JOB，提高主程序原生崩溃后继续生成Windows/WER报告的可靠性。
- Watchdog及其conhost不再计入小美丽RAM/CPU统计，避免约80MB监控开销污染资源报告。
- 继续保留30轮聊天、ASR、大脑、TTS、白板、动画、离线识别、综合满载、90秒回落、实时追加日志。
- FullSafe继续生效：不删除、不移动、不覆盖、不递归清理用户文件、D盘数据或任何旧版本。
""",encoding="utf-8")

for p in (main,diag):
    py_compile.compile(str(p),doraise=True)
combined=rd(main)+rd(diag)
for token in [
    'APP_VERSION = "0.10.0.9.3.6"',
    'safe_interrupt_preflight_begin',
    'resource_diag_safe_interrupt',
    'CREATE_BREAKAWAY_FROM_JOB',
    'ignored.update(x.pid for x in wp.children(recursive=True))',
    'CHAT_ROUNDS = 30',
    'FINAL_COOLDOWN_SECONDS = 90'
]:
    if token not in combined:
        raise RuntimeError("contract missing: "+token)
print("PATCH_0100936_PASS")
