# -*- coding: utf-8 -*-
import ast, os, subprocess, sys, tempfile, threading, time, zipfile
from pathlib import Path


def pump(app, worker, timeout=12.0):
    deadline=time.time()+timeout
    while worker.is_alive() and time.time()<deadline:
        app.processEvents()
        time.sleep(0.01)
    worker.join(timeout=0.2)
    for _ in range(30):
        app.processEvents(); time.sleep(0.005)
    if worker.is_alive():
        raise RuntimeError("queued-dispatch worker timed out")


def main():
    root=Path(sys.argv[1]).resolve()
    src=root/"app"/"src"
    assets=root/"app"/"assets"
    main_p=src/"main.py"
    diag_p=src/"resource_diagnostic_v0100934.py"
    watchdog=assets/"resource_diag_watchdog_v0100934.ps1"
    for p in (main_p,diag_p):
        text=p.read_text(encoding="utf-8-sig")
        ast.parse(text,filename=str(p))
    if not watchdog.is_file():
        raise RuntimeError("watchdog asset missing")

    main_text=main_p.read_text(encoding="utf-8-sig")
    diag_text=diag_p.read_text(encoding="utf-8-sig")
    wd_text=watchdog.read_text(encoding="utf-8-sig")
    combined=main_text+"\n"+diag_text+"\n"+wd_text
    required=[
        'APP_VERSION = "0.10.0.9.3.4"',
        "ResourceDiagnosticMainThreadDispatcher",
        "Qt.ConnectionType.QueuedConnection",
        "hard_silence_requested = Signal(str)",
        "brain_requested = Signal(",
        "tts_requested = Signal(",
        "runtime_probe_requested = Signal()",
        "self._hard_silence_smoke()",
        "python_faulthandler.log",
        "watchdog_heartbeat.jsonl",
        "watchdog_debug.jsonl",
        "watchdog_exit_evidence",
        "windows_event_crash_evidence",
        "FileMode]::CreateNew",
        "CHAT_ROUNDS = 30",
        "FINAL_COOLDOWN_SECONDS = 90",
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError("contract missing: "+token)

    runner_text=diag_text.split("class ResourceDiagnosticRunnerV2(QObject):",1)[1]
    for forbidden in ("self.voice.speak(", "self.brain.ask(", "self.speech.utterance_ready.emit("):
        if forbidden in runner_text:
            raise RuntimeError("cross-thread mutating call remains: "+forbidden)
    for bad in ("shutil.rmtree","os.remove(","unlink(","Path.unlink","shutil.move(","Remove-Item","Move-Item"):
        if bad in diag_text or bad in wd_text:
            raise RuntimeError("unsafe delete/move token: "+bad)

    sys.path.insert(0,str(src))
    from PySide6.QtCore import QCoreApplication, QObject, Signal
    app=QCoreApplication.instance() or QCoreApplication([])
    import resource_diagnostic_v0100934 as mod

    main_tid=threading.get_ident()
    calls=[]

    class Brain(QObject):
        generation_finished=Signal(bool,object,str)
        def __init__(self):
            super().__init__(); self._generate_busy=False
        def ask(self,*args):
            calls.append(("brain",threading.get_ident()))
            self.generation_finished.emit(True,{"spoken_text":"测试正常。"},"ok")
        def abort_current(self,reason):
            calls.append(("brain_abort",threading.get_ident()))

    class Voice(QObject):
        playback_started=Signal(str,int,str)
        playback_finished=Signal(bool,str,str)
        def __init__(self):
            super().__init__(); self._cloud_ctx={}
        def ready(self): return True
        def speak(self,text,vid,speed,output_device,tag="",extra_instruct=""):
            calls.append(("tts",threading.get_ident()))
            self.playback_started.emit(str(text),100,str(tag))
            self.playback_finished.emit(True,"ok",str(tag))
        def abort_playback(self,reason):
            calls.append(("tts_abort",threading.get_ident()))
        def cloud_stream_in_progress(self): return False

    class Speech(QObject):
        utterance_ready=Signal(str)
        def __init__(self):
            super().__init__()
            self.utterance_ready.connect(self._seen)
        def _seen(self,text):
            calls.append(("hard_silence",threading.get_ident()))
        def current_state(self): return ("idle","")

    class Pet:
        dialogue_board_active=False
        movies=[]
        current_state="idle"
        def play_state(self,state,force_new_clip=False):
            calls.append(("state",threading.get_ident()))
        def start_dialogue_board(self,text,duration_ms):
            self.dialogue_board_active=True
            calls.append(("board",threading.get_ident()))
        def _end_dialogue_board(self):
            self.dialogue_board_active=False
            calls.append(("board_close",threading.get_ident()))

    class Vision:
        last_snapshot={}

    tmp=Path(tempfile.mkdtemp(prefix="xm0934-contract-"))
    data=tmp/"data"; desk=tmp/"desktop"; data.mkdir(); desk.mkdir()
    brain=Brain(); voice=Voice(); speech=Speech(); pet=Pet()
    r=mod.ResourceDiagnosticRunnerV2({},brain,voice,speech,Vision(),pet,data,desk,"0.10.0.9.3.4")

    results={}
    def worker():
        r.state_requested.emit("idle")
        r.board_requested.emit("ci",500)
        results["brain"]=r._request_dispatch("brain",r.brain_requested,("p","persona",0.2,24,0,False),3.0)
        results["tts"]=r._request_dispatch("tts",r.tts_requested,("hi","voice",1.0,"default","resource_diag_ci"),3.0)
        results["hard"]=r._request_dispatch("hard_silence",r.hard_silence_requested,("闭嘴",),3.0)
        r.board_close_requested.emit()
    t=threading.Thread(target=worker,name="CIQueuedDispatchWorker")
    t.start(); pump(app,t)
    for key in ("brain","tts","hard"):
        if not results.get(key,(False,""))[0]:
            raise RuntimeError(f"queued dispatch failed: {key} {results.get(key)}")
    names={name for name,_ in calls}
    for name in ("state","board","brain","tts","hard_silence","board_close"):
        if name not in names:
            raise RuntimeError("missing queued action: "+name)
    wrong=[(name,tid) for name,tid in calls if tid!=main_tid]
    if wrong:
        raise RuntimeError("mutating action escaped GUI thread: "+repr(wrong))

    # Fault-handler evidence must be creatable without overwriting.
    r._started=time.monotonic()
    r.session_dir=data/"diagnostics"/"resource"/"v0100934_ci"
    r.session_dir.mkdir(parents=True)
    r._events=[]
    if not r._enable_fault_handler():
        raise RuntimeError("faulthandler did not start")
    r._disable_fault_handler()
    if not (r.session_dir/"python_faulthandler.log").is_file():
        raise RuntimeError("faulthandler evidence missing")

    # Independent watchdog must outlive a sacrificial parent and create its own ZIP,
    # while leaving the source evidence untouched.
    wd_session=data/"diagnostics"/"resource"/"v0100934_watchdog_ci"
    wd_session.mkdir(parents=True)
    status=wd_session/"live_status.jsonl"
    events=wd_session/"live_events.jsonl"
    status.write_text('{"state":"running","stage":"hard_silence"}\n',encoding="utf-8")
    events.write_text('{"event":"stage","stage":"hard_silence"}\n',encoding="utf-8")
    parent=subprocess.Popen([sys.executable,"-c","import time; time.sleep(1.2)"])
    flags=int(getattr(subprocess,"CREATE_NO_WINDOW",0))
    ps=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32"/"WindowsPowerShell"/"v1.0"/"powershell.exe"
    ps_exe=str(ps if ps.is_file() else "powershell.exe")
    wd=subprocess.Popen([
        ps_exe,"-NoProfile","-NonInteractive","-WindowStyle","Hidden","-ExecutionPolicy","Bypass",
        "-File",str(watchdog),"-ParentPid",str(parent.pid),"-SessionDir",str(wd_session),
        "-DesktopDir",str(desk),"-AppVersion","0.10.0.9.3.4"
    ],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",errors="replace",
      creationflags=flags,close_fds=True)
    parent.wait(timeout=10)
    wd_out,wd_err=wd.communicate(timeout=35)
    zips=sorted(desk.glob("小美丽_资源测试_独立看门狗崩溃报告_*.zip"))
    if not zips:
        dbg=wd_session/"watchdog_debug.jsonl"
        detail=dbg.read_text(encoding="utf-8",errors="replace")[-4000:] if dbg.is_file() else "<no watchdog debug>"
        raise RuntimeError(f"independent watchdog did not create crash ZIP; rc={wd.returncode}; stdout={(wd_out or "")[-3000:]}; stderr={(wd_err or "")[-3000:]}; debug={detail}")
    if not status.is_file() or not events.is_file():
        raise RuntimeError("watchdog deleted or moved source evidence")
    with zipfile.ZipFile(zips[-1],"r") as zf:
        names=set(zf.namelist())
        for req in ("live_status.jsonl","live_events.jsonl","watchdog_summary.json"):
            if req not in names:
                raise RuntimeError("watchdog ZIP missing "+req)

    print("V0100934_QUEUED_WATCHDOG_CONTRACT_PASS")


if __name__=="__main__":
    main()
