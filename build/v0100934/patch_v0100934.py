# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root = Path(sys.argv[1]).resolve()
src = root / "app" / "src"
main = src / "main.py"
diag_old = src / "resource_diagnostic_v0100933.py"
diag_new = src / "resource_diagnostic_v0100934.py"

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError("missing patch anchor: "+name)
    return s.replace(a,b,count)

# ---------------- main.py ----------------
s=rd(main)
if 'APP_VERSION = "0.10.0.9.3.3"' not in s:
    raise RuntimeError("V0.10.0.9.3.3 baseline required")
s=rep(s,
      'from resource_diagnostic_v0100933 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics',
      'from resource_diagnostic_v0100934 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics',
      'diagnostic import')
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3.3｜Crash-Safe Resource Diagnostic 2.0"',
      'APP_NAME = "小美丽 V0.10.0.9.3.4｜Crash-Safe Diagnostic 3.0"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3.3"','APP_VERSION = "0.10.0.9.3.4"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3.3"','APP_UPDATE_VERSION = "0.10.0.9.3.4"','update version')
s=s.replace('cfg["config_version"] = max(35, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(36, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 35','cfg["config_version"] = 36')

# All service mutations requested by the diagnostic are marshalled back onto
# AppController's Qt thread. No worker thread may directly start/abort brain/TTS
# or synthesize a speech signal.
start=s.index('    def _v01005_start_deep_resource_test(self):\n')
end=s.index('    def _v01005_diagnostic_progress(self, value, text):\n',start)
old_block=s[start:end]
if 'runner.finished.connect(self._v01005_diagnostic_finished)' not in old_block:
    raise RuntimeError("diagnostic start block shape changed")
new_block=old_block.replace(
    '        runner.finished.connect(self._v01005_diagnostic_finished)\n',
    '        runner.main_action_requested.connect(self._v0100934_diagnostic_main_action, Qt.ConnectionType.QueuedConnection)\n'
    '        runner.finished.connect(self._v01005_diagnostic_finished)\n'
)
s=s[:start]+new_block+s[end:]

insert_anchor='    def _v01005_diagnostic_progress(self, value, text):\n'
handler=r'''    def _v0100934_diagnostic_main_action(self, action, payload):
        """Execute diagnostic mutations only on the Qt/AppController thread."""
        runner=getattr(self,"_v01005_diag_runner",None)
        payload=dict(payload or {})
        token=int(payload.get("token") or 0)
        ok=True; message=""; result={}
        try:
            action=str(action or "")
            if action=="brain_ask":
                brain_cfg=self.cfg.get("brain",{}) if isinstance(self.cfg.get("brain"),dict) else {}
                self.brain_service.ask(
                    str(payload.get("prompt") or ""),
                    brain_cfg.get("persona") or "小美丽",
                    float(payload.get("temperature",0.2) or 0.2),
                    int(payload.get("max_tokens",24) or 24),
                    int(payload.get("context_turns",0) or 0),
                    bool(payload.get("long_term_memory",False)),
                )
            elif action=="brain_abort":
                self.brain_service.abort_current(str(payload.get("reason") or "resource_diag"))
            elif action=="tts_speak":
                voice_cfg=self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
                vid=str(voice_cfg.get("voice_id") or "")
                if not vid or not self.voice_service.ready():
                    raise RuntimeError("voice unavailable")
                self.voice_service.speak(
                    str(payload.get("text") or ""), vid,
                    float(voice_cfg.get("speed",1.0) or 1.0),
                    str(voice_cfg.get("output_device","default") or "default"),
                    tag=str(payload.get("tag") or "resource_diag"),
                    extra_instruct="",
                )
            elif action=="tts_abort":
                self.voice_service.abort_playback(str(payload.get("reason") or "resource_diag"))
            elif action=="hard_silence":
                self._hard_silence_now(str(payload.get("phrase") or "闭嘴"))
            elif action=="interrupt_snapshot":
                result={
                    "tts_active": bool(self.voice_service.cloud_stream_in_progress()),
                    "board_active": bool(getattr(self.pet,"dialogue_board_active",False)),
                }
            elif action=="board_close":
                if getattr(self.pet,"dialogue_board_active",False):
                    self.pet._end_dialogue_board()
            else:
                raise RuntimeError(f"unknown diagnostic action: {action}")
        except Exception as exc:
            ok=False; message=f"{type(exc).__name__}: {exc}"
            LOGGER.exception("资源诊断主线程动作失败: %s", action)
        finally:
            if runner is not None:
                runner.complete_main_action(token,ok,message,result)

'''
s=s.replace(insert_anchor,handler+insert_anchor,1)
wr(main,s)

# ---------------- resource diagnostic ----------------
if not diag_old.is_file():
    raise RuntimeError("V0.10.0.9.3.3 diagnostic module missing")
d=rd(diag_old)
d=d.replace('XiaoMeili V0.10.0.9.3.3 crash-safe fully automatic resource diagnostic 2.0.',
            'XiaoMeili V0.10.0.9.3.4 crash-safe diagnostic 3.0 with Qt-thread marshaling and external watchdog.')
d=d.replace('app_version="0.10.0.9.3.3"','app_version="0.10.0.9.3.4"')
d=d.replace('f"v0100933_{token}"','f"v0100934_{token}"')
d=d.replace('XiaoMeiliResourceSamplerV0100933','XiaoMeiliResourceSamplerV0100934')
d=d.replace('XiaoMeiliGpuSamplerV0100933','XiaoMeiliGpuSamplerV0100934')
d=d.replace('XiaoMeiliResourceDiagnosticV010093','XiaoMeiliResourceDiagnosticV0100934')

# New queued main-thread action signal.
d=rep(d,
'''    board_close_requested = Signal()
    finished = Signal(bool, str, str)
''',
'''    board_close_requested = Signal()
    main_action_requested = Signal(str, object)
    finished = Signal(bool, str, str)
''','main action signal')

# Coordination + watchdog fields.
d=rep(d,
'''        self._journal_lock = threading.Lock()
''',
'''        self._journal_lock = threading.Lock()
        self._main_action_lock = threading.Lock()
        self._main_action_seq = 0
        self._main_action_event = threading.Event()
        self._main_action_reply = (0, False, "", {})
        self._watchdog_proc = None
        self._watchdog_script = None
''','coordination fields')

# Add main-thread bridge + watchdog methods before is_running.
anchor='''    def is_running(self):
        return bool(self._running)
'''
methods=r'''    def complete_main_action(self, token, ok, message="", result=None):
        """Called by AppController on the Qt thread; only sets thread-safe data."""
        with self._main_action_lock:
            self._main_action_reply=(int(token),bool(ok),str(message or ""),dict(result or {}))
            self._main_action_event.set()

    def _main_action(self, action, payload=None, timeout=8.0):
        with self._main_action_lock:
            self._main_action_seq += 1
            token=self._main_action_seq
            self._main_action_event.clear()
            body=dict(payload or {})
            body["token"]=token
            self.main_action_requested.emit(str(action),body)
        if not self._main_action_event.wait(float(timeout)):
            self._event("main_action_timeout",action=str(action),token=token)
            return False,"timeout",{}
        with self._main_action_lock:
            rt,ok,msg,result=self._main_action_reply
        if rt != token:
            self._event("main_action_token_mismatch",action=str(action),expected=token,actual=rt)
            return False,"token mismatch",{}
        if not ok:
            self._event("main_action_error",action=str(action),message_len=len(msg))
        return bool(ok),str(msg),dict(result or {})

    @staticmethod
    def _ps_quote(value):
        return "'" + str(value).replace("'","''") + "'"

    def _write_watchdog_script(self):
        """Create an append-only external watchdog. It never deletes or moves files."""
        session=self.session_dir
        if session is None:
            raise RuntimeError("diagnostic session unavailable")
        script=session/"resource_diag_watchdog.ps1"
        if script.exists():
            raise FileExistsError("watchdog script already exists")
        parent_pid=os.getpid()
        desktop=str(self.desktop)
        session_s=str(session)
        ps=f"""$ErrorActionPreference = 'SilentlyContinue'
$ParentPid = {parent_pid}
$Session = {self._ps_quote(session_s)}
$Desktop = {self._ps_quote(desktop)}
$Start = Get-Date
while ($true) {{
  if (Test-Path (Join-Path $Session 'finalized.flag')) {{ exit 0 }}
  $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
  if (-not $p) {{ break }}
  Start-Sleep -Milliseconds 500
}}
Start-Sleep -Seconds 2
if (Test-Path (Join-Path $Session 'finalized.flag')) {{ exit 0 }}
$events = @()
try {{
  $events = Get-WinEvent -FilterHashtable @{{LogName='Application'; StartTime=$Start.AddMinutes(-1)}} -ErrorAction SilentlyContinue |
    Where-Object {{ $_.LevelDisplayName -eq 'Error' -or $_.ProviderName -match 'Application Error|Windows Error Reporting' }} |
    Select-Object -First 40 TimeCreated,ProviderName,Id,LevelDisplayName,Message
}} catch {{}}
$eventText = ($events | Format-List | Out-String)
Set-Content -LiteralPath (Join-Path $Session 'windows_event_log.txt') -Value $eventText -Encoding UTF8
$meta = [ordered]@{{
  detected_at=(Get-Date).ToString('o')
  parent_pid=$ParentPid
  reason='XiaoMeili process ended before diagnostic finalized.flag'
  safety='copy-only; no delete, no move, no recursive cleanup'
}}
$meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Session 'watchdog_summary.json') -Encoding UTF8
$allowed = @(
 'live_timeline.jsonl','live_events.jsonl','live_rounds.jsonl','live_status.jsonl',
 'speech_diagnostic_worker.log','events.json','summary.json','stage_summary.csv',
 'round_ledger.csv','timeline_250ms.csv','vram_jump_events.csv','process_tree.csv',
 'windows_event_log.txt','watchdog_summary.json'
)
$files = @()
foreach($n in $allowed) {{
  $p=Join-Path $Session $n
  if(Test-Path -LiteralPath $p) {{ $files += $p }}
}}
if($files.Count -gt 0) {{
  $stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
  $target=Join-Path $Desktop ("小美丽_闪退监控报告_"+$stamp+".zip")
  $i=1
  while(Test-Path -LiteralPath $target) {{
    $target=Join-Path $Desktop ("小美丽_闪退监控报告_"+$stamp+"_"+$i+".zip"); $i++
  }}
  Compress-Archive -LiteralPath $files -DestinationPath $target -CompressionLevel Optimal
}}
"""
        script.write_text(ps,encoding="utf-8-sig",newline="\r\n")
        self._watchdog_script=script
        return script

    def _start_watchdog(self):
        script=self._write_watchdog_script()
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        cmd=["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden",
             "-ExecutionPolicy","Bypass","-File",str(script)]
        self._watchdog_proc=subprocess.Popen(
            cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=flags,cwd=str(self.session_dir))
        self._event("watchdog_started",pid=int(self._watchdog_proc.pid))

    def is_running(self):
        return bool(self._running)
'''
d=rep(d,anchor,methods,'main action/watchdog methods')

# Brain/TTS service mutations are no longer called from the worker.
old=r'''    def _brain_once(self, idx, timeout=25):
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
'''
new=r'''    def _brain_once(self, idx, timeout=25):
        self._brain_event.clear()
        prompt = f"资源压力测试第{idx}轮。只回答四个字：测试正常。"
        ok,msg,_=self._main_action("brain_ask",{
            "prompt":prompt,"temperature":0.2,"max_tokens":24,
            "context_turns":0,"long_term_memory":False,
        },timeout=6)
        if not ok:
            self._event("brain_call_error", error=msg)
            return False, ""
        if not self._brain_event.wait(timeout):
            self._main_action("brain_abort",{"reason":"resource_diag_timeout"},timeout=4)
            self._event("brain_timeout", index=idx)
            return False, ""
        ok, answer, message = self._brain_result
        spoken = str((answer or {}).get("spoken_text") or "").strip()
        self._event("brain_result", index=idx, ok=bool(ok), chars=len(spoken), status_len=len(message))
        return bool(ok), spoken
'''
d=rep(d,old,new,'brain main-thread bridge')

old=r'''    def _tts_once(self, text, tag, timeout=30):
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
'''
new=r'''    def _tts_once(self, text, tag, timeout=30):
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
d=rep(d,old,new,'tts main-thread bridge')

# Replace the risky hard-silence implementation. All mutations/querying happen
# on the main Qt thread and a 10-second preflight can exercise the same path.
hs_start=d.index('    def _hard_silence_stage(self):\n')
hs_end=d.index('    def _offline_vision_once(self, include_ocr=True):\n',hs_start)
hs=r'''    def _hard_silence_once(self, phrase, index, kind="hard_silence"):
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
d=d[:hs_start]+hs+d[hs_end:]

# Start watchdog and do the risky preflight before the 60-second baseline.
old='''        self._open_live_journals()
        wav_path=None; ok=True; err=""
        self._sampling=True
'''
new='''        self._open_live_journals()
        self._start_watchdog()
        wav_path=None; ok=True; err=""
        self._sampling=True
'''
d=rep(d,old,new,'watchdog start')

old='''            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
            self.state_requested.emit("idle"); self._sleep(BASELINE_SECONDS)
'''
new='''            self._set_stage("preflight_interrupt",1,"高风险预检：主线程TTS→闭嘴→白板关闭（约10秒）")
            self._hard_silence_preflight()

            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
            self.state_requested.emit("idle"); self._sleep(BASELINE_SECONDS)
'''
d=rep(d,old,new,'hard-silence preflight')

# Watchdog files belong in both normal/recovery ZIPs.
d=d.replace('"windows_event_log.txt", "watchdog_summary.json"', '"windows_event_log.txt", "watchdog_summary.json", "resource_diag_watchdog.ps1"')
d=d.replace('"live_status.jsonl"}', '"live_status.jsonl","resource_diag_watchdog.ps1","windows_event_log.txt","watchdog_summary.json"}')

# Safety and architecture contracts.
if '.speech.utterance_ready.emit(' in d:
    raise RuntimeError("worker still synthesizes speech utterance directly")
if 'self.voice.speak(' in d or 'self.voice.abort_playback(' in d or 'self.brain.ask(' in d or 'self.brain.abort_current(' in d:
    raise RuntimeError("worker still mutates brain/voice service directly")
for bad in ("Remove-Item","shutil.rmtree","os.remove","Path.unlink","shutil.move"):
    if bad in d:
        raise RuntimeError("unsafe diagnostic token: "+bad)

wr(diag_new,d)
(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.3.4\n",encoding="ascii")
(root/"V0100934_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.3.4

- Crash-Safe Diagnostic 3.0：修复闭嘴阶段后台诊断线程直接操作TTS/ASR/AppController造成的跨线程竞态风险。
- Brain/TTS启动与中止、闭嘴硬打断、状态查询全部通过Qt QueuedConnection回到主线程串行执行。
- 正式长测前增加约10秒“高风险预检”：TTS→闭嘴→白板关闭；若失败立即停止，不再让用户先等十分钟。
- 新增独立隐藏PowerShell Watchdog：若XiaoMeili.exe在测试期间原生闪退，Watchdog继续存活，自动抓取Windows Application/WER错误并在桌面生成闪退监控ZIP。
- Watchdog与恢复器均只复制允许名单内的诊断文件；不删除、不移动、不覆盖、不递归清理任何用户文件或旧版本。
- 继续保留实时追加timeline/events/rounds/status、NVML无黑框采样、真实CPU、250ms采样、WAV/ASR、30轮聊天、离线识别、综合满载、90秒回落、NDM与FullSafe。
""",encoding="utf-8")

for p in (main,diag_new):
    py_compile.compile(str(p),doraise=True)
combined=rd(main)+rd(diag_new)
for token in [
    'APP_VERSION = "0.10.0.9.3.4"','resource_diagnostic_v0100934',
    'main_action_requested = Signal(str, object)','Qt.ConnectionType.QueuedConnection',
    '_hard_silence_preflight','resource_diag_watchdog.ps1','Get-WinEvent',
    'Compress-Archive','Riskier child-process cleanup happens only after report generation.',
    'FULLSAFE'
]:
    if token not in combined and token != 'FULLSAFE':
        raise RuntimeError("contract missing: "+token)
print("PATCH_0100934_PASS")
