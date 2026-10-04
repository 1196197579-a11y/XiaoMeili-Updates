# -*- coding: utf-8 -*-
import ast, csv, json, os, subprocess, sys, tempfile, time, zipfile
from pathlib import Path

def wait_for(path, timeout=8.0):
    end=time.time()+timeout
    while time.time()<end:
        if Path(path).exists():
            return True
        time.sleep(0.05)
    return False

def main():
    root=Path(sys.argv[1]).resolve()
    monitor_exe=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else None
    src=root/"app"/"src"
    main_p=src/"main.py"
    diag_p=src/"resource_diagnostic_v0100934.py"
    mon_p=src/"resource_monitor_v0100940.py"
    for p in (main_p,diag_p,mon_p):
        s=p.read_text(encoding="utf-8-sig")
        ast.parse(s,filename=str(p))
    main_s=main_p.read_text(encoding="utf-8-sig")
    diag_s=diag_p.read_text(encoding="utf-8-sig")
    mon_s=mon_p.read_text(encoding="utf-8-sig")
    combined=main_s+"\n"+diag_s+"\n"+mon_s

    required=[
        'APP_VERSION = "0.10.0.9.4.0"',
        'XiaoMeiliResourceMonitor.exe',
        'authoritative_resource_collector',
        'external_timeline_250ms.csv',
        'external_process_tree.csv',
        'external_monitor_summary.json',
        'external_monitor_stop.flag',
        'external_monitor_stopped.flag',
        'watchdog_ready.flag',
        'CHAT_ROUNDS = 30',
        'FINAL_COOLDOWN_SECONDS = 90',
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError("contract missing: "+token)

    for bad in ('shutil.rmtree','os.remove(','Path.unlink','shutil.move','Remove-Item','Move-Item','robocopy /MIR'):
        if bad in diag_s or bad in mon_s:
            raise RuntimeError("unsafe destructive token: "+bad)
    for bad in ('_main_action("tts_abort"','abort_playback(','_main_action("hard_silence"','utterance_ready.emit('):
        if bad in diag_s:
            raise RuntimeError("forbidden deep-test action: "+bad)
    if 'powershell.exe","-NoProfile"' in diag_s:
        raise RuntimeError("legacy PowerShell watchdog launch still in diagnostic")

    tmp=Path(tempfile.mkdtemp(prefix="xm0940-contract-"))
    desktop=tmp/"desktop"; desktop.mkdir()
    env=dict(os.environ)
    env["XIAOMEILI_MONITOR_SKIP_WINDOWS_EVENTS"]="1"

    # ----- normal stop path -----
    session=tmp/"session-normal"; session.mkdir()
    host=subprocess.Popen([sys.executable,"-c","import time; time.sleep(12)"])
    mon_cmd=([str(monitor_exe)] if monitor_exe else [sys.executable,str(mon_p)])
    mon=subprocess.Popen(mon_cmd+[
        "--pid",str(host.pid),"--session",str(session),"--desktop",str(desktop),
        "--app-version","0.10.0.9.4.0"
    ],env=env)
    try:
        if not wait_for(session/"watchdog_ready.flag",4):
            raise RuntimeError("monitor ready handshake failed")
        (session/"live_status.jsonl").write_text(
            json.dumps({"state":"running","stage":"baseline"},ensure_ascii=False)+"\n",
            encoding="utf-8")
        time.sleep(1.2)
        (session/"external_monitor_stop.flag").write_text("stop",encoding="utf-8")
        if not wait_for(session/"external_monitor_stopped.flag",5):
            raise RuntimeError("normal monitor stop flag missing")
        (session/"finalized.flag").write_text("done",encoding="utf-8")
        code=mon.wait(timeout=5)
        if code!=0:
            raise RuntimeError(f"normal monitor exit code {code}")
        summary=json.loads((session/"external_monitor_summary.json").read_text(encoding="utf-8"))
        if summary.get("host_crashed"):
            raise RuntimeError("normal path marked host_crashed")
        if int(summary.get("samples") or 0)<2:
            raise RuntimeError("too few monitor samples")
        with (session/"external_timeline_250ms.csv").open("r",encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        if len(rows)<2 or not any(r.get("stage")=="baseline" for r in rows):
            raise RuntimeError("timeline/stage capture failed")
    finally:
        if host.poll() is None:
            host.terminate()
            try: host.wait(timeout=3)
            except Exception: host.kill()
        if mon.poll() is None:
            mon.terminate()

    # ----- host crash path -----
    session2=tmp/"session-crash"; session2.mkdir()
    host2=subprocess.Popen([sys.executable,"-c","import time; time.sleep(1.5)"])
    mon2=subprocess.Popen(mon_cmd+[
        "--pid",str(host2.pid),"--session",str(session2),"--desktop",str(desktop),
        "--app-version","0.10.0.9.4.0"
    ],env=env)
    if not wait_for(session2/"watchdog_ready.flag",4):
        raise RuntimeError("crash-path ready handshake failed")
    host2.wait(timeout=5)
    try:
        code2=mon2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        mon2.terminate()
        raise RuntimeError("crash-path monitor did not survive/finish")
    zips=list(desktop.glob("小美丽_外部监控闪退报告_*.zip"))
    if not zips:
        raise RuntimeError("crash-path desktop ZIP missing")
    with zipfile.ZipFile(zips[-1],"r") as zf:
        names=set(zf.namelist())
    for req in ("external_timeline_250ms.csv","external_monitor_summary.json","external_monitor_status.jsonl"):
        if req not in names:
            raise RuntimeError("crash ZIP missing "+req)
    if not (session2/"external_timeline_250ms.csv").exists():
        raise RuntimeError("crash ZIP creation removed source evidence")

    print("V0100940_EXTERNAL_MONITOR_CONTRACT_PASS")

if __name__=="__main__":
    main()
