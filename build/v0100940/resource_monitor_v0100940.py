# -*- coding: utf-8 -*-
"""XiaoMeili external resource monitor V0.10.0.9.4.0.

Authoritative resource collection lives OUTSIDE XiaoMeili.exe.
Safety contract:
- create/append only inside the supplied diagnostic session directory
- create a new Desktop ZIP only after a host crash
- never delete, move, rename, overwrite, recursively clean, or modify user files
"""
from __future__ import annotations
import argparse, csv, json, os, subprocess, sys, time, zipfile
from pathlib import Path

import psutil

try:
    import pynvml
except Exception:
    pynvml = None

INTERVAL = 0.25
PROCESS_INTERVAL_TICKS = 4
MAX_SECONDS = 60 * 60

def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = folder / f"{stem}_{stamp}{suffix}"
    n = 1
    while p.exists():
        p = folder / f"{stem}_{stamp}_{n}{suffix}"
        n += 1
    return p

def write_json_new(path: Path, payload):
    if path.exists():
        # Session folders are unique. Never overwrite.
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def append_jsonl(fp, payload):
    fp.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    fp.flush()

def hidden_kwargs():
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
            si.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
            kw["startupinfo"] = si
        except Exception:
            pass
    return kw

def windows_events_text(minutes=8):
    if os.environ.get("XIAOMEILI_MONITOR_SKIP_WINDOWS_EVENTS") == "1":
        return "Windows event query skipped by test environment.\n"
    if os.name != "nt":
        return ""
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-Command",
        (
            "$s=(Get-Date).AddMinutes(-%d); "
            "Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$s} "
            "-ErrorAction SilentlyContinue | "
            "Where-Object {$_.LevelDisplayName -eq 'Error' -or "
            "$_.ProviderName -match 'Application Error|Windows Error Reporting'} | "
            "Select-Object -First 80 TimeCreated,ProviderName,Id,LevelDisplayName,Message | "
            "Format-List | Out-String -Width 4096"
        ) % int(minutes)
    ]
    try:
        return subprocess.check_output(
            cmd, text=True, encoding="utf-8", errors="replace", timeout=12,
            **hidden_kwargs()
        )
    except Exception as exc:
        return f"Windows event query unavailable: {type(exc).__name__}: {exc}\n"

def current_stage(session: Path) -> str:
    p = session / "live_status.jsonl"
    try:
        if not p.exists():
            return ""
        # File stays small: one line per stage/status transition.
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-20:]):
            try:
                o = json.loads(line)
                stage = str(o.get("stage") or "")
                if stage:
                    return stage
            except Exception:
                continue
    except Exception:
        pass
    return ""

class Nvml:
    def __init__(self):
        self.ready = False
        self.handle = None
        self.source = "unavailable"
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.ready = True
                self.source = "NVML"
            except Exception:
                self.ready = False
                self.handle = None

    def total(self):
        out = {"gpu_util_percent": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        if not self.ready:
            return out
        try:
            u = pynvml.nvmlDeviceGetUtilizationRates(self.handle)
            m = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
            try:
                t = pynvml.nvmlDeviceGetTemperature(self.handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                t = None
            out.update({
                "gpu_util_percent": float(getattr(u, "gpu", 0) or 0),
                "vram_used_mb": float(getattr(m, "used", 0) or 0) / 1024 / 1024,
                "vram_total_mb": float(getattr(m, "total", 0) or 0) / 1024 / 1024,
                "gpu_temp_c": None if t is None else float(t),
            })
        except Exception:
            pass
        return out

    def app_vram(self, pids):
        if not self.ready:
            return None
        total = 0.0
        seen = set()
        fns = [
            "nvmlDeviceGetComputeRunningProcesses_v3",
            "nvmlDeviceGetComputeRunningProcesses_v2",
            "nvmlDeviceGetComputeRunningProcesses",
            "nvmlDeviceGetGraphicsRunningProcesses_v3",
            "nvmlDeviceGetGraphicsRunningProcesses_v2",
            "nvmlDeviceGetGraphicsRunningProcesses",
        ]
        for name in fns:
            fn = getattr(pynvml, name, None)
            if fn is None:
                continue
            try:
                for row in fn(self.handle) or []:
                    pid = int(getattr(row, "pid", -1))
                    if pid not in pids or pid in seen:
                        continue
                    used = getattr(row, "usedGpuMemory", 0)
                    try:
                        if used is None or int(used) < 0:
                            used = 0
                    except Exception:
                        used = 0
                    total += float(used or 0) / 1024 / 1024
                    seen.add(pid)
            except Exception:
                continue
        return total

def process_tree(root_pid: int, handles: dict[int, psutil.Process]):
    root = handles.get(root_pid)
    if root is None:
        root = psutil.Process(root_pid)
        root.cpu_percent(None)
        handles[root_pid] = root
    procs = [root]
    try:
        procs.extend(root.children(recursive=True))
    except Exception:
        pass
    rows = []
    live = set()
    for raw in procs:
        try:
            pid = int(raw.pid)
            live.add(pid)
            p = handles.get(pid)
            new = p is None
            if p is None:
                p = psutil.Process(pid)
                p.cpu_percent(None)
                handles[pid] = p
            with p.oneshot():
                info = p.as_dict(attrs=["pid","ppid","name","cmdline","memory_info","num_threads","create_time"])
            cpu = 0.0 if new else float(p.cpu_percent(None) or 0.0)
            rows.append({
                "pid": pid,
                "ppid": int(info.get("ppid") or 0),
                "name": str(info.get("name") or ""),
                "rss_bytes": int(getattr(info.get("memory_info"), "rss", 0) or 0),
                "cpu_percent": cpu,
                "threads": int(info.get("num_threads") or 0),
                "cmd_hint": " ".join(info.get("cmdline") or [])[:220],
                "create_time": float(info.get("create_time") or 0),
            })
        except Exception:
            continue
    for pid in list(handles):
        if pid not in live:
            handles.pop(pid, None)
    return rows

def make_crash_zip(session: Path, desktop: Path) -> str:
    target = unique_path(desktop, "小美丽_外部监控闪退报告", ".zip")
    allowed = {
        "external_timeline_250ms.csv","external_process_tree.csv","external_monitor_status.jsonl",
        "external_monitor_summary.json","external_windows_event_log.txt",
        "live_timeline.jsonl","live_events.jsonl","live_rounds.jsonl","live_status.jsonl",
        "speech_diagnostic_worker.log","events.json","summary.json","stage_summary.csv",
        "round_ledger.csv","timeline_250ms.csv","vram_jump_events.csv","process_tree.csv",
        "watchdog_ready.flag","external_monitor_stopped.flag","external_monitor_stop.flag",
    }
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as zf:
        for p in session.iterdir():
            if p.is_file() and p.name in allowed:
                zf.write(p, arcname=p.name)
    return str(target)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--desktop", required=True)
    ap.add_argument("--app-version", default="")
    args = ap.parse_args()

    session = Path(args.session).resolve()
    desktop = Path(args.desktop).resolve()
    session.mkdir(parents=True, exist_ok=True)

    ready = session / "watchdog_ready.flag"
    if not ready.exists():
        ready.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")

    status_path = session / "external_monitor_status.jsonl"
    timeline_path = session / "external_timeline_250ms.csv"
    process_path = session / "external_process_tree.csv"
    summary_path = session / "external_monitor_summary.json"
    stopped_path = session / "external_monitor_stopped.flag"
    stop_path = session / "external_monitor_stop.flag"
    finalized_path = session / "finalized.flag"

    status_fp = status_path.open("x", encoding="utf-8", buffering=1)
    timeline_fp = timeline_path.open("x", encoding="utf-8-sig", newline="", buffering=1)
    process_fp = process_path.open("x", encoding="utf-8-sig", newline="", buffering=1)

    timeline_fields = [
        "t","stage","system_cpu_percent","system_ram_percent",
        "app_cpu_percent","app_rss_bytes","app_threads",
        "gpu_util_percent","vram_used_mb","vram_total_mb","app_vram_mb","gpu_temp_c","process_count"
    ]
    process_fields = ["t","stage","pid","ppid","name","rss_bytes","cpu_percent","threads","cmd_hint"]
    tw = csv.DictWriter(timeline_fp, fieldnames=timeline_fields); tw.writeheader(); timeline_fp.flush()
    pw = csv.DictWriter(process_fp, fieldnames=process_fields); pw.writeheader(); process_fp.flush()

    start_mono = time.monotonic()
    start_wall = time.time()
    handles = {}
    nv = Nvml()
    samples = 0
    peak_rss = 0
    peak_app_vram = 0.0
    first_rss = None
    last_rss = None
    last_stage = ""
    exit_reason = "normal_stop"
    crashed = False
    root_create_time = None

    try:
        root = psutil.Process(args.pid)
        root_create_time = root.create_time()
        root.cpu_percent(None)
        handles[args.pid] = root
    except Exception as exc:
        append_jsonl(status_fp, {"event":"root_missing_at_start","error":f"{type(exc).__name__}: {exc}"})
        exit_reason = "host_missing_at_start"
        crashed = True
        root = None

    append_jsonl(status_fp, {
        "event":"external_monitor_ready","pid":os.getpid(),"host_pid":args.pid,
        "app_version":args.app_version,"gpu_source":nv.source,
        "safety":"create/copy only; no delete, move, overwrite, or recursive cleanup"
    })

    tick = 0
    process_rows = []
    stop_requested = False
    while not crashed:
        now = time.monotonic()
        t = round(now - start_mono, 3)
        if t > MAX_SECONDS:
            exit_reason = "monitor_max_duration"
            break

        if stop_path.exists():
            stop_requested = True

        try:
            host = psutil.Process(args.pid)
            if root_create_time is not None and abs(host.create_time() - root_create_time) > 0.1:
                raise psutil.NoSuchProcess(args.pid)
            if not host.is_running():
                raise psutil.NoSuchProcess(args.pid)
        except Exception:
            if finalized_path.exists():
                exit_reason = "finalized_then_host_exit"
                break
            crashed = True
            exit_reason = "host_process_exited"
            break

        try:
            rows = process_tree(args.pid, handles)
        except Exception:
            rows = []
        if not rows:
            crashed = True
            exit_reason = "host_tree_unavailable"
            break

        stage = current_stage(session)
        if stage:
            last_stage = stage
        pids = {int(r["pid"]) for r in rows}
        app_cpu = sum(float(r["cpu_percent"] or 0) for r in rows)
        app_rss = sum(int(r["rss_bytes"] or 0) for r in rows)
        app_threads = sum(int(r["threads"] or 0) for r in rows)
        first_rss = app_rss if first_rss is None else first_rss
        last_rss = app_rss
        peak_rss = max(peak_rss, app_rss)

        gpu = nv.total()
        app_vram = nv.app_vram(pids)
        if app_vram is not None:
            peak_app_vram = max(peak_app_vram, float(app_vram))

        row = {
            "t":t,"stage":last_stage,
            "system_cpu_percent":float(psutil.cpu_percent(None) or 0),
            "system_ram_percent":float(psutil.virtual_memory().percent or 0),
            "app_cpu_percent":round(app_cpu,3),"app_rss_bytes":app_rss,"app_threads":app_threads,
            "gpu_util_percent":gpu["gpu_util_percent"],"vram_used_mb":gpu["vram_used_mb"],
            "vram_total_mb":gpu["vram_total_mb"],"app_vram_mb":app_vram,
            "gpu_temp_c":gpu["gpu_temp_c"],"process_count":len(rows),
        }
        tw.writerow(row); timeline_fp.flush(); samples += 1

        if tick % PROCESS_INTERVAL_TICKS == 0:
            for pr in rows:
                pw.writerow({
                    "t":t,"stage":last_stage,"pid":pr["pid"],"ppid":pr["ppid"],"name":pr["name"],
                    "rss_bytes":pr["rss_bytes"],"cpu_percent":pr["cpu_percent"],
                    "threads":pr["threads"],"cmd_hint":pr["cmd_hint"],
                })
            process_fp.flush()

        if stop_requested:
            exit_reason = "normal_stop_requested"
            break

        tick += 1
        elapsed = time.monotonic() - now
        time.sleep(max(0.02, INTERVAL - elapsed))

    duration = round(time.monotonic() - start_mono, 3)
    summary = {
        "monitor_version":"0.10.0.9.4.0",
        "app_version":args.app_version,
        "host_pid":args.pid,
        "monitor_pid":os.getpid(),
        "duration_seconds":duration,
        "samples":samples,
        "exit_reason":exit_reason,
        "host_crashed":bool(crashed),
        "last_stage":last_stage,
        "first_app_rss_bytes":first_rss,
        "last_app_rss_bytes":last_rss,
        "peak_app_rss_bytes":peak_rss,
        "peak_app_vram_mb":peak_app_vram,
        "gpu_source":nv.source,
        "safety":"create/copy only; no delete, move, overwrite, or recursive cleanup",
    }

    if crashed:
        events = windows_events_text()
        p = session / "external_windows_event_log.txt"
        if not p.exists():
            p.write_text(events, encoding="utf-8", errors="replace")
        summary["windows_events_file"] = p.name

    write_json_new(summary_path, summary)
    if not stopped_path.exists():
        stopped_path.write_text(json.dumps({"time":time.time(),"reason":exit_reason}, ensure_ascii=False), encoding="utf-8")

    timeline_fp.flush(); process_fp.flush(); status_fp.flush()
    timeline_fp.close(); process_fp.close()
    append_jsonl(status_fp, {"event":"external_monitor_stopped","reason":exit_reason,"crashed":bool(crashed)})
    status_fp.close()

    if crashed:
        try:
            report = make_crash_zip(session, desktop)
            p = session / "external_report_path.txt"
            if not p.exists():
                p.write_text(report, encoding="utf-8")
        except Exception as exc:
            p = session / "external_monitor_zip_error.txt"
            if not p.exists():
                p.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return 2

    # Normal completion: keep process alive briefly until the main app marks
    # finalized.flag. If the host dies during report generation, create a crash ZIP.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if finalized_path.exists():
            return 0
        try:
            host = psutil.Process(args.pid)
            if root_create_time is not None and abs(host.create_time() - root_create_time) > 0.1:
                raise psutil.NoSuchProcess(args.pid)
        except Exception:
            try:
                events = windows_events_text()
                p = session / "external_windows_event_log.txt"
                if not p.exists():
                    p.write_text(events, encoding="utf-8", errors="replace")
                report = make_crash_zip(session, desktop)
                rp = session / "external_report_path.txt"
                if not rp.exists():
                    rp.write_text(report, encoding="utf-8")
            except Exception:
                pass
            return 3
        time.sleep(0.20)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
