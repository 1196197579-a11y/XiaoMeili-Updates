# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, shutil, sys

root=Path(sys.argv[1]).resolve()
repo=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else Path(__file__).resolve().parents[0]
src=root/'app'/'src'
main=src/'main.py'
diag_old=src/'resource_diagnostic_v010093.py'
diag_new=src/'resource_diagnostic_v0100931.py'
requirements=root/'app'/'requirements.txt'


def rd(p): return p.read_text(encoding='utf-8-sig')
def wr(p,s): p.write_text(s,encoding='utf-8',newline='\n')
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError(f'missing patch anchor: {name}')
    return s.replace(a,b,count)

# ---------- main.py ----------
s=rd(main)
if 'APP_VERSION = "0.10.0.9.3"' not in s:
    raise RuntimeError('V0.10.0.9.3 baseline required')
s=rep(s,
      'from resource_diagnostic_v010093 import ResourceDiagnosticRunnerV2',
      'from resource_diagnostic_v0100931 import ResourceDiagnosticRunnerV2',
      'resource diagnostic import')
s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3｜Automatic Resource Diagnostic 2.0"',
      'APP_NAME = "小美丽 V0.10.0.9.3.1｜Automatic Resource Diagnostic 2.0 Fix"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3"','APP_VERSION = "0.10.0.9.3.1"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3"','APP_UPDATE_VERSION = "0.10.0.9.3.1"','update version')
s=s.replace('cfg["config_version"] = max(32, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(33, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 32','cfg["config_version"] = 33')

old='''    def _v01005_diagnostic_finished(self, ok, report_path, message):
        self.v01005_diag_btn.setEnabled(True); self.v01005_diag_btn.setText("开始一键深度资源测试 2.0")
        self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(100 if report_path else 0)
        self.v01005_diag_status.setText(str(message))
        if report_path:
            QMessageBox.information(self,"一键深度资源测试 2.0 完成",
                f"{message}\\n\\n桌面已生成脱敏诊断 ZIP，请直接上传给 ChatGPT。\\n"
                "测试不需要打开 VALORANT，也不会删除、移动或覆盖你的现有文件。")
        else:
            QMessageBox.warning(self,"一键深度资源测试 2.0 失败",str(message))
'''
new='''    def _v01005_diagnostic_finished(self, ok, report_path, message):
        self.v01005_diag_btn.setEnabled(True); self.v01005_diag_btn.setText("开始一键深度资源测试 2.0")
        self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(100 if ok and report_path else (90 if report_path else 0))
        self.v01005_diag_status.setText(str(message))
        if ok and report_path:
            QMessageBox.information(self,"一键深度资源测试 2.0 完成",
                f"{message}\\n\\n桌面已生成脱敏诊断 ZIP，请直接上传给 ChatGPT。\\n"
                "测试不需要打开 VALORANT，也不会删除、移动或覆盖你的现有文件。")
        elif report_path:
            QMessageBox.warning(self,"测试中止，已生成故障报告",
                f"{message}\\n\\n桌面已生成故障诊断 ZIP，请直接上传给 ChatGPT。\\n"
                "测试器不会把中止误标成完成，也不会删除、移动或覆盖你的现有文件。")
        else:
            QMessageBox.warning(self,"一键深度资源测试 2.0 失败",str(message))
'''
s=rep(s,old,new,'diagnostic finished modal')
wr(main,s)

# ---------- resource diagnostic ----------
if not diag_old.is_file():
    raise RuntimeError('V0.10.0.9.3 diagnostic module missing')
d=rd(diag_old)

# Version/profile wording.
d=d.replace('XiaoMeili V0.10.0.9.3 fully automatic resource diagnostic 2.0.',
            'XiaoMeili V0.10.0.9.3.1 fully automatic resource diagnostic 2.0 fix.')
d=d.replace('app_version="0.10.0.9.3"','app_version="0.10.0.9.3.1"')

# NVML first, hidden nvidia-smi fallback only.
d=rep(d,
'''try:
    import cv2
    import numpy as np
except Exception:  # covered by normal app dependency validation
    cv2 = None
    np = None
''',
'''try:
    import cv2
    import numpy as np
except Exception:  # covered by normal app dependency validation
    cv2 = None
    np = None

try:
    import pynvml
except Exception:
    pynvml = None
''','optional pynvml import')

# Init fields.
d=rep(d,
'''        self._gpu_tick = 0
        self._gpu_cache = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        self._gpu_proc_cache = []
        self._proc_cache = {}
''',
'''        self._gpu_tick = 0
        self._gpu_cache = {"gpu_util": None, "vram_used_mb": None, "vram_total_mb": None, "gpu_temp_c": None}
        self._gpu_proc_cache = []
        self._gpu_source = "unavailable"
        self._gpu_stop = threading.Event()
        self._nvml_handle = None
        self._nvml_ready = False
        self._proc_handles = {}
''','diagnostic monitor fields')

# Fix duplicate kind crash by renaming first parameter.
d=rep(d,
'''    def _event(self, kind, **payload):
        row = {
            "t": round(max(0.0, time.monotonic() - self._started), 3),
            "stage": self._stage,
            "event": str(kind),
        }
''',
'''    def _event(self, event_name, **payload):
        row = {
            "t": round(max(0.0, time.monotonic() - self._started), 3),
            "stage": self._stage,
            "event": str(event_name),
        }
''','event parameter collision')

# Replace GPU functions with in-process NVML + hidden fallback.
start=d.index('    def _nvidia_total(self):\n')
end=d.index('    def _process_rows(self):\n',start)
gpu_block='''    @staticmethod
    def _hidden_subprocess_kwargs():
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

    def _init_nvml(self):
        if self._nvml_ready or pynvml is None:
            return bool(self._nvml_ready)
        try:
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._nvml_ready = True
            self._gpu_source = "NVML"
            return True
        except Exception:
            self._nvml_handle = None
            self._nvml_ready = False
            return False

    def _nvidia_total(self):
        out = dict(self._gpu_cache)
        if self._init_nvml():
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(self._nvml_handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = None
                out = {
                    "gpu_util": self._safe_float(getattr(util, "gpu", None)),
                    "vram_used_mb": self._safe_float(getattr(mem, "used", 0) / 1024 / 1024),
                    "vram_total_mb": self._safe_float(getattr(mem, "total", 0) / 1024 / 1024),
                    "gpu_temp_c": self._safe_float(temp),
                }
                self._gpu_cache = out
                return out
            except Exception:
                self._nvml_ready = False
                self._nvml_handle = None
        try:
            raw = subprocess.check_output([
                "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits"
            ], text=True, encoding="utf-8", errors="replace", timeout=3,
               **self._hidden_subprocess_kwargs()).strip().splitlines()
            if raw:
                p = [x.strip() for x in raw[0].split(",")]
                if len(p) >= 4:
                    out = {
                        "gpu_util": self._safe_float(p[0]),
                        "vram_used_mb": self._safe_float(p[1]),
                        "vram_total_mb": self._safe_float(p[2]),
                        "gpu_temp_c": self._safe_float(p[3]),
                    }
                    self._gpu_source = "nvidia-smi-hidden"
        except Exception:
            pass
        self._gpu_cache = out
        return out

    def _nvidia_processes(self):
        rows = []
        if self._init_nvml():
            seen = set()
            for fn_name, source in (("nvmlDeviceGetComputeRunningProcesses_v3", "compute"),
                                    ("nvmlDeviceGetComputeRunningProcesses_v2", "compute"),
                                    ("nvmlDeviceGetComputeRunningProcesses", "compute"),
                                    ("nvmlDeviceGetGraphicsRunningProcesses_v3", "graphics"),
                                    ("nvmlDeviceGetGraphicsRunningProcesses_v2", "graphics"),
                                    ("nvmlDeviceGetGraphicsRunningProcesses", "graphics")):
                fn = getattr(pynvml, fn_name, None)
                if not callable(fn):
                    continue
                try:
                    for rec in fn(self._nvml_handle) or []:
                        pid = int(getattr(rec, "pid", 0) or 0)
                        if pid <= 0 or pid in seen:
                            continue
                        seen.add(pid)
                        used = getattr(rec, "usedGpuMemory", None)
                        if used is not None and int(used) >= 0:
                            used = float(used) / 1024 / 1024
                        else:
                            used = None
                        try:
                            name = psutil.Process(pid).name()
                        except Exception:
                            name = ""
                        rows.append({"pid": pid, "name": name, "used_gpu_memory_mb": self._safe_float(used), "source": source})
                except Exception:
                    continue
            self._gpu_proc_cache = rows
            return rows
        try:
            raw = subprocess.check_output([
                "nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits"
            ], text=True, encoding="utf-8", errors="replace", timeout=3,
               **self._hidden_subprocess_kwargs()).strip().splitlines()
            for line in raw:
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 3:
                    rows.append({"pid": int(p[0]), "name": p[1], "used_gpu_memory_mb": self._safe_float(p[2]), "source": "compute"})
            self._gpu_source = "nvidia-smi-hidden"
        except Exception:
            pass
        self._gpu_proc_cache = rows
        return rows

    def _gpu_loop(self):
        proc_tick = 0
        while not self._gpu_stop.is_set():
            try:
                self._nvidia_total()
                if proc_tick % 2 == 0:
                    self._nvidia_processes()
            except Exception as exc:
                self._event("gpu_sample_error", error=f"{type(exc).__name__}: {exc}")
            proc_tick += 1
            self._gpu_stop.wait(1.0)

'''
d=d[:start]+gpu_block+d[end:]

# Replace process_rows with persistent psutil handles.
start=d.index('    def _process_rows(self):\n')
end=d.index('    @staticmethod\n    def _qsize',start)
proc_block='''    def _process_rows(self):
        try:
            root = self._proc_handles.get(os.getpid())
            if root is None:
                root = psutil.Process(os.getpid())
                root.cpu_percent(None)
                self._proc_handles[root.pid] = root
            current = [root]
            try:
                current.extend(root.children(recursive=True))
            except Exception:
                pass
        except Exception:
            return []
        rows = []
        live = set()
        for raw in current:
            try:
                pid = int(raw.pid); live.add(pid)
                p = self._proc_handles.get(pid)
                is_new = p is None
                if p is None:
                    p = psutil.Process(pid)
                    p.cpu_percent(None)
                    self._proc_handles[pid] = p
                with p.oneshot():
                    info = p.as_dict(attrs=["pid", "ppid", "name", "cmdline", "memory_info"])
                cpu = 0.0 if is_new else float(p.cpu_percent(None) or 0.0)
                cmd = " ".join(info.get("cmdline") or [])[:180]
                rows.append({
                    "pid": pid, "ppid": info.get("ppid"), "name": info.get("name"),
                    "rss_bytes": int(getattr(info.get("memory_info"), "rss", 0) or 0),
                    "cpu_percent": cpu, "cmd_hint": cmd,
                })
            except Exception:
                continue
        for pid in list(self._proc_handles):
            if pid not in live:
                self._proc_handles.pop(pid, None)
        return rows

'''
d=d[:start]+proc_block+d[end:]

# Sampler must read GPU cache only; GPU queries run in separate thread.
old='''        if self._gpu_tick % 4 == 0:
            gpu = self._nvidia_total()
        else:
            gpu = dict(self._gpu_cache)
        if self._gpu_tick % 8 == 0:
            gp = self._nvidia_processes()
        else:
            gp = list(self._gpu_proc_cache)
        self._gpu_tick += 1
'''
new='''        gpu = dict(self._gpu_cache)
        gp = list(self._gpu_proc_cache)
'''
d=rep(d,old,new,'sampler cached GPU data')

# No catch-up bursts after a slow sample.
old='''    def _sampler_loop(self):
        next_t = time.monotonic()
        while self._sampling:
            try:
                self._sample_once()
            except Exception as exc:
                self._event("sample_error", error=f"{type(exc).__name__}: {exc}")
            next_t += SAMPLE_INTERVAL_SECONDS
            time.sleep(max(0.02, next_t - time.monotonic()))
'''
new='''    def _sampler_loop(self):
        while self._sampling:
            started = time.monotonic()
            try:
                self._sample_once()
            except Exception as exc:
                self._event("sample_error", error=f"{type(exc).__name__}: {exc}")
            elapsed = time.monotonic() - started
            time.sleep(max(0.02, SAMPLE_INTERVAL_SECONDS - elapsed))
'''
d=rep(d,old,new,'sampler no catch-up')

# Preflight self-test catches the round/event API bug before waiting 60 seconds.
anchor='''    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            time.sleep(min(0.20, max(0.02, end - time.monotonic())))

'''
insert=anchor+'''    def _preflight_self_test(self):
        before_rounds = len(self._rounds)
        self._event("preflight_event_api", kind="round_payload", index=0)
        rec = self._round_start("preflight", 0)
        if len(self._rounds) != before_rounds + 1 or rec.get("kind") != "preflight":
            raise RuntimeError("诊断轮次事件接口自检失败")
        self._rounds.pop()
        try:
            self._process_rows()
            time.sleep(0.30)
            rows = self._process_rows()
            if not rows:
                raise RuntimeError("进程CPU采样预热失败")
        except Exception as exc:
            raise RuntimeError(f"CPU采样自检失败: {exc}") from exc
        self._event("preflight_pass", gpu_source=str(self._gpu_source or "pending"))

'''
d=rep(d,anchor,insert,'preflight self-test')

# Run preflight before long baseline, then start dedicated GPU + sampler threads.
old='''        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v010093_{token}"
        self.session_dir.mkdir(parents=True,exist_ok=False)
        wav_path=None; ok=True; err=""
        self._sampling=True
        sampler=threading.Thread(target=self._sampler_loop,name="XiaoMeiliResourceSamplerV010093",daemon=True); sampler.start()
        setattr(self.brain,"_resource_diag_no_persist",True)
        try:
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
new='''        self.session_dir=self.data_root/"diagnostics"/"resource"/f"v0100931_{token}"
        self.session_dir.mkdir(parents=True,exist_ok=False)
        wav_path=None; ok=True; err=""
        self._sampling=True
        self._gpu_stop.clear()
        sampler=threading.Thread(target=self._sampler_loop,name="XiaoMeiliResourceSamplerV0100931",daemon=True)
        gpu_thread=threading.Thread(target=self._gpu_loop,name="XiaoMeiliGpuSamplerV0100931",daemon=True)
        setattr(self.brain,"_resource_diag_no_persist",True)
        try:
            self._set_stage("preflight",1,"启动前快速自检：事件、CPU与GPU采样接口")
            self._preflight_self_test()
            gpu_thread.start(); sampler.start(); self._sleep(1.0)
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
d=rep(d,old,new,'run preflight and threads')

# Stop GPU thread and shutdown NVML in finally.
old='''            self._sampling=False
            try: sampler.join(timeout=4)
            except Exception: pass
'''
new='''            self._sampling=False
            self._gpu_stop.set()
            try:
                if sampler.is_alive(): sampler.join(timeout=4)
            except Exception: pass
            try:
                if gpu_thread.is_alive(): gpu_thread.join(timeout=4)
            except Exception: pass
            if self._nvml_ready and pynvml is not None:
                try: pynvml.nvmlShutdown()
                except Exception: pass
            self._nvml_ready=False; self._nvml_handle=None
'''
d=rep(d,old,new,'monitor thread shutdown')

# Accurate status wording on failure.
old='''            report=self._write_reports(); self._progress(100,"测试完成：桌面已生成诊断ZIP")
            msg=f"诊断完成：{report}" if ok else f"部分阶段失败，但已生成可分析报告：{report}\\n{err}"
'''
new='''            report=self._write_reports()
            if ok:
                self._progress(100,"测试完成：桌面已生成诊断ZIP")
                msg=f"诊断完成：{report}"
            else:
                self._progress(90,"测试中止：已生成故障诊断ZIP")
                msg=f"测试中止，已生成故障报告：{report}\\n{err}"
'''
d=rep(d,old,new,'failure wording')

# Add collector metadata so report tells us which GPU backend was used.
old='''meta={"app_version":self.app_version,"platform":platform.platform(),"python":platform.python_version(),"sample_interval_seconds":SAMPLE_INTERVAL_SECONDS,"chat_rounds":CHAT_ROUNDS,"baseline_seconds":BASELINE_SECONDS,"final_cooldown_seconds":FINAL_COOLDOWN_SECONDS,"vision_mode":"offline standard-frame replay; VALORANT is not required","vision_coverage":self._vision_coverage,"privacy":"不保存聊天原文、回答原文、麦克风录音、游戏截图、API Key、长期记忆、养成库或昵称。","safety":"只创建新的诊断目录和ZIP；不删除、不移动、不覆盖用户文件。"}'''
new='''meta={"app_version":self.app_version,"platform":platform.platform(),"python":platform.python_version(),"sample_interval_seconds":SAMPLE_INTERVAL_SECONDS,"chat_rounds":CHAT_ROUNDS,"baseline_seconds":BASELINE_SECONDS,"final_cooldown_seconds":FINAL_COOLDOWN_SECONDS,"gpu_collector":self._gpu_source,"vision_mode":"offline standard-frame replay; VALORANT is not required","vision_coverage":self._vision_coverage,"privacy":"不保存聊天原文、回答原文、麦克风录音、游戏截图、API Key、长期记忆、养成库或昵称。","safety":"只创建新的诊断目录和ZIP；不删除、不移动、不覆盖用户文件。"}'''
d=rep(d,old,new,'GPU collector metadata')

# Report title/version marker.
d=d.replace('小美丽 V{self.app_version} 一键深度资源测试 2.0','小美丽 V{self.app_version} 一键深度资源测试 2.0 修正版')
wr(diag_new,d)

# ---------- requirements ----------
r=rd(requirements)
if 'nvidia-ml-py' not in r:
    if not r.endswith('\n'): r+='\n'
    r+='nvidia-ml-py>=12,<14\n'
wr(requirements,r)

(root/'app'/'assets'/'VERSION.txt').write_text('0.10.0.9.3.1\n',encoding='ascii')
(root/'V0100931_CHANGELOG.txt').write_text('''XiaoMeili V0.10.0.9.3.1\n\n- 修复一键深度资源测试在白板第1轮因 _event(kind=...) 参数冲突而中止。\n- GPU/显存采集优先使用进程内 NVML，不再高频弹出 nvidia-smi 黑框；备用 nvidia-smi 也强制隐藏窗口。\n- GPU采集移到独立线程，不再阻塞250ms资源采样。\n- CPU采样复用 psutil.Process 并预热，修复 app_cpu_percent 长期显示0的问题。\n- 采样器错过节拍后直接进入下一周期，不再补帧造成0.03s~4s异常间隔。\n- 启动前增加快速自检，事件接口/CPU采样异常会在长时间测试前立刻中止。\n- 测试途中失败时明确显示“测试中止，已生成故障报告”，不再误标成完成。\n- 保留 V0.10.0.9.3 的全自动30轮聊天、白板、ASR、云端大脑/TTS、闭嘴、离线画面识别、综合满载与90秒回落。\n- FullSafe继续禁止删除、移动、递归清理用户文件和旧版本。\n''',encoding='utf-8')

for p in (main,diag_new):
    py_compile.compile(str(p),doraise=True)

combined=rd(main)+rd(diag_new)+rd(requirements)
for token in [
    'APP_VERSION = "0.10.0.9.3.1"','resource_diagnostic_v0100931','def _event(self, event_name, **payload)',
    'pynvml','NVML','CREATE_NO_WINDOW','XiaoMeiliGpuSamplerV0100931','_preflight_self_test',
    'self._proc_handles','测试中止，已生成故障报告','nvidia-ml-py>=12,<14','CHAT_ROUNDS = 30',
    'FINAL_COOLDOWN_SECONDS = 90'
]:
    if token not in combined:
        raise RuntimeError('contract missing: '+token)
print('PATCH_0100931_PASS')