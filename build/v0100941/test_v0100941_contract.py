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

def stop_proc(p):
    if p is None:
        return
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()

def run_monitor_cmd(mon_exe, mon_py):
    if mon_exe:
        return [str(mon_exe)]
    return [sys.executable,str(mon_py)]

def main():
    root=Path(sys.argv[1]).resolve()
    mon_exe=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else None
    src=root/"app"/"src"
    main_p=src/"main.py"
    diag_p=src/"resource_diagnostic_v0100934.py"
    mon_p=src/"resource_monitor_v0100941.py"

    texts={}
    for k,p in (("main",main_p),("diag",diag_p),("mon",mon_p)):
        s=p.read_text(encoding="utf-8-sig")
        ast.parse(s,filename=str(p))
        texts[k]=s
    combined="\n".join(texts.values())

    required=[
        'APP_VERSION = "0.10.0.9.4.1"',
        'ResourceMonitor',
        'fixed_onedir',
        '正在启动外部资源监控器',
        '外部资源监控器已连接，开始测试',
        'external_monitor_stdout.log',
        'external_monitor_stderr.log',
        'external_timeline_250ms.csv',
        'external_monitor_summary.json',
        'watchdog_ready.flag',
        'CHAT_ROUNDS = 30',
        'FINAL_COOLDOWN_SECONDS = 90',
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError("contract missing: "+token)

    diag=texts["diag"]
    mon=texts["mon"]
    for bad in ('shutil.rmtree','os.remove(','Path.unlink','shutil.move','Remove-Item','Move-Item','robocopy /MIR'):
        if bad in diag or bad in mon:
            raise RuntimeError("unsafe destructive token: "+bad)
    for bad in ('_main_action("tts_abort"','abort_playback(','_main_action("hard_silence"','utterance_ready.emit('):
        if bad in diag:
            raise RuntimeError("forbidden deep-test action: "+bad)
    if 'with_name("XiaoMeiliResourceMonitor.exe")' in diag:
        raise RuntimeError("old one-file root monitor path remains")
    if "CREATE_BREAKAWAY_FROM_JOB" in diag or "DETACHED_PROCESS" in diag:
        raise RuntimeError("legacy monitor launch flags remain")

    tmp=Path(tempfile.mkdtemp(prefix="xm0941-contract-"))
    desktop=tmp/"desktop"; desktop.mkdir()
    env=dict(os.environ)
    env["XIAOMEILI_MONITOR_SKIP_WINDOWS_EVENTS"]="1"
    mon_cmd=run_monitor_cmd(mon_exe,mon_p)

    latencies=[]

    # Five packaged/source ready-handshake + normal-stop cycles.
    for idx in range(1,6):
        session=tmp/f"session-normal-{idx}"; session.mkdir()
        host=subprocess.Popen([sys.executable,"-c","import time; time.sleep(12)"])
        monproc=None
        started=time.time()
        try:
            monproc=subprocess.Popen(mon_cmd+[
                "--pid",str(host.pid),
                "--session",str(session),
                "--desktop",str(desktop),
                "--app-version","0.10.0.9.4.1"
            ],env=env)
            if not wait_for(session/"watchdog_ready.flag",4):
                raise RuntimeError(f"cycle {idx}: monitor ready handshake failed")
            latency=time.time()-started
            latencies.append(latency)
            if latency>3.0:
                raise RuntimeError(f"cycle {idx}: onedir ready too slow: {latency:.2f}s")

            (session/"live_status.jsonl").write_text(
                json.dumps({"state":"running","stage":"baseline"},ensure_ascii=False)+"\n",
                encoding="utf-8")
            time.sleep(0.9)
            (session/"external_monitor_stop.flag").write_text("stop",encoding="utf-8")
            if not wait_for(session/"external_monitor_stopped.flag",5):
                raise RuntimeError(f"cycle {idx}: normal stop flag missing")
            (session/"finalized.flag").write_text("done",encoding="utf-8")
            code=monproc.wait(timeout=5)
            if code!=0:
                raise RuntimeError(f"cycle {idx}: monitor exit code {code}")

            summary=json.loads((session/"external_monitor_summary.json").read_text(encoding="utf-8"))
            if summary.get("host_crashed"):
                raise RuntimeError(f"cycle {idx}: normal path marked host_crashed")
            if int(summary.get("samples") or 0)<2:
                raise RuntimeError(f"cycle {idx}: too few samples")
            with (session/"external_timeline_250ms.csv").open("r",encoding="utf-8-sig",newline="") as f:
                rows=list(csv.DictReader(f))
            if len(rows)<2 or not any(r.get("stage")=="baseline" for r in rows):
                raise RuntimeError(f"cycle {idx}: timeline/stage capture failed")
            # External monitor must not count itself as XiaoMeili.
            with (session/"external_process_tree.csv").open("r",encoding="utf-8-sig",newline="") as f:
                prows=list(csv.DictReader(f))
            if any(int(r.get("pid") or -1)==int(monproc.pid) for r in prows):
                raise RuntimeError(f"cycle {idx}: monitor counted itself in app resources")
        finally:
            stop_proc(host)
            stop_proc(monproc)

    # One host-crash path: monitor must survive and create Desktop crash ZIP.
    session2=tmp/"session-crash"; session2.mkdir()
    host2=subprocess.Popen([sys.executable,"-c","import time; time.sleep(1.3)"])
    mon2=subprocess.Popen(mon_cmd+[
        "--pid",str(host2.pid),
        "--session",str(session2),
        "--desktop",str(desktop),
        "--app-version","0.10.0.9.4.1"
    ],env=env)
    try:
        if not wait_for(session2/"watchdog_ready.flag",4):
            raise RuntimeError("crash path ready handshake failed")
        host2.wait(timeout=5)
        code2=mon2.wait(timeout=12)
        if code2 not in (2,3):
            raise RuntimeError(f"unexpected crash-path monitor exit code {code2}")
        zips=sorted(desktop.glob("小美丽_外部监控闪退报告_*.zip"))
        if not zips:
            raise RuntimeError("crash-path desktop ZIP missing")
        with zipfile.ZipFile(zips[-1],"r") as zf:
            names=set(zf.namelist())
        for req in ("external_timeline_250ms.csv","external_monitor_summary.json","external_monitor_status.jsonl"):
            if req not in names:
                raise RuntimeError("crash ZIP missing "+req)
        if not (session2/"external_timeline_250ms.csv").exists():
            raise RuntimeError("crash report removed source evidence")
    finally:
        stop_proc(host2)
        stop_proc(mon2)

    print("V0100941_ONEDIR_MONITOR_5X_READY_PASS",",".join(f"{x:.3f}" for x in latencies))
    print("V0100941_ONEDIR_MONITOR_CRASH_PATH_PASS")

if __name__=="__main__":
    main()
