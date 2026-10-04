# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, shutil, sys

root = Path(sys.argv[1]).resolve()
repo = Path(__file__).resolve().parents[2]
src = root / "app" / "src"
assets = root / "app" / "assets"
main = src / "main.py"
diag_old = src / "resource_diagnostic_v0100933.py"
diag_new = src / "resource_diagnostic_v0100934.py"
watchdog_src = repo / "build" / "v0100934" / "resource_diag_watchdog_v0100934.ps1"
watchdog_dst = assets / "resource_diag_watchdog_v0100934.ps1"


def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p, s): p.write_text(s, encoding="utf-8", newline="\n")
def rep(s, a, b, name, count=1):
    if a not in s:
        raise RuntimeError(f"missing patch anchor: {name}")
    return s.replace(a, b, count)


def replace_method(s, method_name, new_text):
    marker = f"    def {method_name}("
    start = s.find(marker)
    if start < 0:
        raise RuntimeError(f"method missing: {method_name}")
    nxt = s.find("\n    def ", start + len(marker))
    if nxt < 0:
        nxt = len(s)
    return s[:start] + new_text.rstrip() + "\n\n" + s[nxt + 1:]


if not watchdog_src.is_file():
    raise RuntimeError("watchdog source missing")
shutil.copyfile(watchdog_src, watchdog_dst)

# ---------------- main.py ----------------
s = rd(main)
if 'APP_VERSION = "0.10.0.9.3.3"' not in s:
    raise RuntimeError("V0.10.0.9.3.3 baseline required")

s = rep(
    s,
    "from resource_diagnostic_v0100933 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics",
    "from resource_diagnostic_v0100934 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics",
    "diagnostic import",
)
s = rep(
    s,
    'APP_NAME = "小美丽 V0.10.0.9.3.3｜Crash-Safe Resource Diagnostic 2.0"',
    'APP_NAME = "小美丽 V0.10.0.9.3.4｜Crash-Safe Resource Diagnostic 3.0"',
    "app name",
)
s = rep(s, 'APP_VERSION = "0.10.0.9.3.3"', 'APP_VERSION = "0.10.0.9.3.4"', "app version")
s = rep(s, 'APP_UPDATE_VERSION = "0.10.0.9.3.3"', 'APP_UPDATE_VERSION = "0.10.0.9.3.4"', "update version")
s = s.replace('cfg["config_version"] = max(35, int(cfg.get("config_version", 0) or 0))',
              'cfg["config_version"] = max(36, int(cfg.get("config_version", 0) or 0))')
s = s.replace('cfg["config_version"] = 35', 'cfg["config_version"] = 36')

# The runner now owns explicit queued main-thread dispatch. Remove the old duplicate
# direct UI connections, especially Python lambdas, so every risky action has one path.
old_connections = '''        runner.progress_changed.connect(self._v01005_diagnostic_progress)
        runner.state_requested.connect(lambda state:self.pet.play_state(str(state),force_new_clip=True))
        runner.board_requested.connect(self.pet.start_dialogue_board)
        runner.board_close_requested.connect(lambda:self.pet._end_dialogue_board() if getattr(self.pet,"dialogue_board_active",False) else None)
        runner.finished.connect(self._v01005_diagnostic_finished)
'''
new_connections = '''        runner.progress_changed.connect(self._v01005_diagnostic_progress)
        runner.finished.connect(self._v01005_diagnostic_finished)
'''
s = rep(s, old_connections, new_connections, "remove duplicate diagnostic UI connections")

# UI wording makes the architectural change visible.
s = s.replace("一键深度资源测试 2.0", "一键深度资源测试 3.0")
s = s.replace("全自动依次测试：纯待机、状态动画、白板、FSMN-VAD + Fun-ASR-Nano-2512、云端大脑、云端TTS、",
              "先进行高风险TTS→闭嘴预检，再全自动测试：纯待机、状态动画、白板、FSMN-VAD + Fun-ASR-Nano-2512、云端大脑、云端TTS、")
wr(main, s)

# ---------------- resource diagnostic ----------------
if not diag_old.is_file():
    raise RuntimeError("V0.10.0.9.3.3 diagnostic module missing")
d = rd(diag_old)
d = d.replace("XiaoMeili V0.10.0.9.3.3 crash-safe fully automatic resource diagnostic 2.0.",
              "XiaoMeili V0.10.0.9.3.4 crash-safe resource diagnostic 3.0 with queued main-thread dispatcher and independent watchdog.")
d = d.replace('app_version="0.10.0.9.3.3"', 'app_version="0.10.0.9.3.4"')
d = d.replace('f"v0100933_{token}"', 'f"v0100934_{token}"')
d = d.replace("XiaoMeiliResourceSamplerV0100933", "XiaoMeiliResourceSamplerV0100934")
d = d.replace("XiaoMeiliGpuSamplerV0100933", "XiaoMeiliGpuSamplerV0100934")
d = d.replace("XiaoMeiliResourceDiagnosticV010093", "XiaoMeiliResourceDiagnosticV0100934")
d = d.replace("一键深度资源测试2.0", "一键深度资源测试3.0")

d = rep(d, "import os\n", "import os\nimport sys\nimport faulthandler\n", "diagnostic imports")
d = rep(d, "from PySide6.QtCore import QObject, Signal\n",
           "from PySide6.QtCore import QObject, Signal, Slot, Qt\n", "Qt queued imports")

# Add watchdog/fault evidence to both automatic recovery and normal final ZIP.
d = d.replace(
    '"speech_diagnostic_worker.log", "diagnostic_input.wav", "events.json", "summary.json",',
    '"speech_diagnostic_worker.log", "diagnostic_input.wav", "events.json", "summary.json",\n'
    '        "python_faulthandler.log", "watchdog_started.json", "watchdog_heartbeat.jsonl", "watchdog_debug.jsonl",\n'
    '        "watchdog_exit_evidence.txt", "windows_event_crash_evidence.txt",',
)
d = d.replace('legacy = session.name.startswith("v0100932_")',
              'legacy = session.name.startswith(("v0100932_","v0100933_","v0100934_"))')
d = d.replace(
    '"live_timeline.jsonl","live_events.jsonl","live_rounds.jsonl","live_status.jsonl"}',
    '"live_timeline.jsonl","live_events.jsonl","live_rounds.jsonl","live_status.jsonl","python_faulthandler.log","watchdog_started.json","watchdog_heartbeat.jsonl","watchdog_debug.jsonl"}',
)

# Insert the one and only dispatcher before the runner class. This QObject is created
# on the GUI thread and every mutating Brain/TTS/Speech/Pet action reaches it through
# an explicit Qt.QueuedConnection.
class_anchor = "class ResourceDiagnosticRunnerV2(QObject):\n"
dispatcher = r'''
class ResourceDiagnosticMainThreadDispatcher(QObject):
    dispatch_finished = Signal(str, bool, str)
    runtime_probe_finished = Signal(bool, bool)

    def __init__(self, brain, voice, speech, pet, parent=None):
        super().__init__(parent)
        self.brain = brain
        self.voice = voice
        self.speech = speech
        self.pet = pet

    @Slot(str)
    def play_state(self, state):
        try:
            self.pet.play_state(str(state), force_new_clip=True)
            self.dispatch_finished.emit("state", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("state", False, f"{type(exc).__name__}: {exc}")

    @Slot(str, int)
    def show_board(self, text, duration_ms):
        try:
            self.pet.start_dialogue_board(str(text), int(duration_ms))
            self.dispatch_finished.emit("board", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("board", False, f"{type(exc).__name__}: {exc}")

    @Slot()
    def close_board(self):
        try:
            if bool(getattr(self.pet, "dialogue_board_active", False)):
                self.pet._end_dialogue_board()
            self.dispatch_finished.emit("board_close", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("board_close", False, f"{type(exc).__name__}: {exc}")

    @Slot(str, str, float, int, int, bool)
    def brain_ask(self, prompt, persona, temperature, max_tokens, context_turns, long_term_memory):
        try:
            self.brain.ask(
                str(prompt), str(persona), float(temperature), int(max_tokens),
                int(context_turns), bool(long_term_memory)
            )
            self.dispatch_finished.emit("brain", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("brain", False, f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def brain_abort(self, reason):
        try:
            self.brain.abort_current(str(reason))
            self.dispatch_finished.emit("brain_abort", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("brain_abort", False, f"{type(exc).__name__}: {exc}")

    @Slot(str, str, float, str, str)
    def tts_speak(self, text, voice_id, speed, output_device, tag):
        try:
            if not str(voice_id or ""):
                raise RuntimeError("voice_id unavailable")
            ready = getattr(self.voice, "ready", None)
            if callable(ready) and not bool(ready()):
                raise RuntimeError("voice service unavailable")
            self.voice.speak(
                str(text), str(voice_id), float(speed), str(output_device),
                tag=str(tag), extra_instruct=""
            )
            self.dispatch_finished.emit("tts", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("tts", False, f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def tts_abort(self, reason):
        try:
            self.voice.abort_playback(str(reason))
            self.dispatch_finished.emit("tts_abort", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("tts_abort", False, f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def hard_silence(self, phrase):
        try:
            # Re-emit from the GUI thread so AppController's real P0 path executes
            # on its owning thread. Never emit this service signal from the diagnostic worker.
            self.speech.utterance_ready.emit(str(phrase))
            self.dispatch_finished.emit("hard_silence", True, "")
        except Exception as exc:
            self.dispatch_finished.emit("hard_silence", False, f"{type(exc).__name__}: {exc}")

    @Slot()
    def runtime_probe(self):
        try:
            tts_active = bool(self.voice.cloud_stream_in_progress())
        except Exception:
            tts_active = False
        try:
            board_active = bool(getattr(self.pet, "dialogue_board_active", False))
        except Exception:
            board_active = False
        self.runtime_probe_finished.emit(tts_active, board_active)


'''
d = rep(d, class_anchor, dispatcher + class_anchor, "main-thread dispatcher")

# Extended runner request signals.
old_signals = '''class ResourceDiagnosticRunnerV2(QObject):
    progress_changed = Signal(int, str)
    state_requested = Signal(str)
    board_requested = Signal(str, int)
    board_close_requested = Signal()
    finished = Signal(bool, str, str)
'''
new_signals = '''class ResourceDiagnosticRunnerV2(QObject):
    progress_changed = Signal(int, str)
    state_requested = Signal(str)
    board_requested = Signal(str, int)
    board_close_requested = Signal()
    brain_requested = Signal(str, str, float, int, int, bool)
    brain_abort_requested = Signal(str)
    tts_requested = Signal(str, str, float, str, str)
    tts_abort_requested = Signal(str)
    hard_silence_requested = Signal(str)
    runtime_probe_requested = Signal()
    finished = Signal(bool, str, str)
'''
d = rep(d, old_signals, new_signals, "runner request signals")

# Dispatcher/watchdog/fault-handler state is inserted beside the existing journal lock.
d = rep(
    d,
    "        self._journal_lock = threading.Lock()\n",
    '''        self._journal_lock = threading.Lock()
        self._dispatch_event = threading.Event()
        self._dispatch_expected = ""
        self._dispatch_result = (False, "")
        self._probe_event = threading.Event()
        self._probe_result = (False, False)
        self._watchdog_proc = None
        self._fault_fp = None
        self._dispatcher = ResourceDiagnosticMainThreadDispatcher(
            self.brain, self.voice, self.speech, self.pet, self
        )
        queued = Qt.ConnectionType.QueuedConnection
        self.state_requested.connect(self._dispatcher.play_state, queued)
        self.board_requested.connect(self._dispatcher.show_board, queued)
        self.board_close_requested.connect(self._dispatcher.close_board, queued)
        self.brain_requested.connect(self._dispatcher.brain_ask, queued)
        self.brain_abort_requested.connect(self._dispatcher.brain_abort, queued)
        self.tts_requested.connect(self._dispatcher.tts_speak, queued)
        self.tts_abort_requested.connect(self._dispatcher.tts_abort, queued)
        self.hard_silence_requested.connect(self._dispatcher.hard_silence, queued)
        self.runtime_probe_requested.connect(self._dispatcher.runtime_probe, queued)
        self._dispatcher.dispatch_finished.connect(self._on_dispatch_finished, queued)
        self._dispatcher.runtime_probe_finished.connect(self._on_runtime_probe_finished, queued)
''',
    "dispatcher state",
)

# Add fault handler, watchdog and dispatch helpers immediately before is_running().
is_running_anchor = '''    def is_running(self):
        return bool(self._running)
'''
helpers = r'''    def _on_dispatch_finished(self, kind, ok, message):
        if str(kind) != str(self._dispatch_expected):
            return
        self._dispatch_result = (bool(ok), str(message or ""))
        self._dispatch_event.set()

    def _request_dispatch(self, kind, signal, args=(), timeout=4.0):
        self._dispatch_expected = str(kind)
        self._dispatch_result = (False, "dispatch timeout")
        self._dispatch_event.clear()
        try:
            signal.emit(*tuple(args))
        except Exception as exc:
            self._event("dispatch_emit_error", kind=str(kind), error=f"{type(exc).__name__}: {exc}")
            return False, f"{type(exc).__name__}: {exc}"
        if not self._dispatch_event.wait(float(timeout)):
            self._event("dispatch_timeout", kind=str(kind))
            return False, "dispatch timeout"
        ok, message = self._dispatch_result
        if not ok:
            self._event("dispatch_failed", kind=str(kind), message_len=len(str(message or "")))
        return bool(ok), str(message or "")

    def _on_runtime_probe_finished(self, tts_active, board_active):
        self._probe_result = (bool(tts_active), bool(board_active))
        self._probe_event.set()

    def _probe_runtime_main_thread(self, timeout=2.5):
        self._probe_event.clear()
        self.runtime_probe_requested.emit()
        if not self._probe_event.wait(float(timeout)):
            self._event("runtime_probe_timeout")
            return False, False
        return self._probe_result

    def _watchdog_path(self):
        roots = []
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(Path(bundle) / "assets" / "resource_diag_watchdog_v0100934.ps1")
        roots.append(Path(__file__).resolve().parents[1] / "assets" / "resource_diag_watchdog_v0100934.ps1")
        for p in roots:
            if p.is_file():
                return p
        return None

    def _start_watchdog(self):
        script = self._watchdog_path()
        if script is None or self.session_dir is None:
            self._event("watchdog_unavailable")
            return False
        system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
        powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        exe = str(powershell if powershell.is_file() else "powershell.exe")
        args = [
            exe, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-ParentPid", str(os.getpid()),
            "-SessionDir", str(self.session_dir),
            "-DesktopDir", str(self.desktop),
            "-AppVersion", str(self.app_version),
            "-StartedUtc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        ]
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True
            )
            time.sleep(0.35)
            if proc.poll() is not None:
                self._event("watchdog_early_exit", returncode=proc.returncode)
                return False
            self._watchdog_proc = proc
            self._event("watchdog_started", pid=int(proc.pid))
            return True
        except Exception as exc:
            self._event("watchdog_start_error", error=f"{type(exc).__name__}: {exc}")
            return False

    def _enable_fault_handler(self):
        try:
            path = self.session_dir / "python_faulthandler.log"
            self._fault_fp = path.open("x", encoding="utf-8", buffering=1)
            faulthandler.enable(file=self._fault_fp, all_threads=True)
            self._event("faulthandler_enabled")
            return True
        except Exception as exc:
            self._event("faulthandler_error", error=f"{type(exc).__name__}: {exc}")
            return False

    def _disable_fault_handler(self):
        try:
            if faulthandler.is_enabled():
                faulthandler.disable()
        except Exception:
            pass
        fp = self._fault_fp
        self._fault_fp = None
        if fp is not None:
            try: fp.flush()
            except Exception: pass
            try: fp.close()
            except Exception: pass

    def _write_watchdog_heartbeat(self):
        if self.session_dir is None:
            return
        p = self.session_dir / "watchdog_heartbeat.jsonl"
        try:
            payload = {
                "t": round(max(0.0, time.monotonic() - self._started), 3),
                "stage": str(self._stage), "pid": os.getpid(),
            }
            with p.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            pass

    def is_running(self):
        return bool(self._running)
'''
d = rep(d, is_running_anchor, helpers, "dispatch/watchdog helpers")

# Heartbeat no faster than the existing sample tick cadence gate.
sample_append = '''        self._samples.append(row)
        self._journal_write(self._live_timeline_fp, row)
'''
sample_new = '''        self._samples.append(row)
        self._journal_write(self._live_timeline_fp, row)
        if int(float(row.get("t") or 0) * 4) % 4 == 0:
            self._write_watchdog_heartbeat()
'''
d = rep(d, sample_append, sample_new, "watchdog heartbeat")

# Replace all mutating cloud service calls with queued main-thread requests.
brain_method = r'''    def _brain_once(self, idx, timeout=25):
        self._brain_event.clear()
        prompt = f"资源压力测试第{idx}轮。只回答四个字：测试正常。"
        brain_cfg = self.cfg.get("brain", {}) if isinstance(self.cfg.get("brain"), dict) else {}
        accepted, message = self._request_dispatch(
            "brain", self.brain_requested,
            (
                prompt, str(brain_cfg.get("persona") or "小美丽"), 0.2,
                24, 0, False,
            ),
            timeout=5.0,
        )
        if not accepted:
            self._event("brain_call_error", error=str(message))
            return False, ""
        if not self._brain_event.wait(timeout):
            self._request_dispatch(
                "brain_abort", self.brain_abort_requested,
                ("resource_diag_timeout",), timeout=4.0
            )
            self._event("brain_timeout", index=idx)
            return False, ""
        ok, answer, message = self._brain_result
        spoken = str((answer or {}).get("spoken_text") or "").strip()
        self._event("brain_result", index=idx, ok=bool(ok), chars=len(spoken), status_len=len(message))
        return bool(ok), spoken
'''
d = replace_method(d, "_brain_once", brain_method)

tts_method = r'''    def _tts_once(self, text, tag, timeout=30):
        voice_cfg = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        vid = str(voice_cfg.get("voice_id") or "")
        if not vid:
            self._event("tts_skipped", reason="voice_id unavailable")
            return False
        self._tts_started.clear()
        self._tts_done.clear()
        accepted, message = self._request_dispatch(
            "tts", self.tts_requested,
            (
                str(text), vid, float(voice_cfg.get("speed", 1.0) or 1.0),
                str(voice_cfg.get("output_device", "default") or "default"), str(tag),
            ),
            timeout=5.0,
        )
        if not accepted:
            self._event("tts_call_error", error=str(message))
            return False
        self._tts_started.wait(min(8.0, timeout))
        if not self._tts_done.wait(timeout):
            self._request_dispatch(
                "tts_abort", self.tts_abort_requested,
                ("resource_diag_timeout",), timeout=4.0
            )
            self._event("tts_timeout", tag=str(tag))
            return False
        ok, message, _ = self._tts_result
        self._event("tts_result", tag=str(tag), ok=bool(ok), message_len=len(message))
        return bool(ok)
'''
d = replace_method(d, "_tts_once", tts_method)

hard_method = r'''    def _hard_silence_once(self, phrase, index, kind="hard_silence", recovery=1.2):
        rec = self._round_start(str(kind), int(index))
        long_text = "这是用于测试闭嘴硬打断的较长语音，正常情况下应该在播报中途被立即停止，不应该继续说完这句话。"
        self._tts_started.clear()
        self._tts_done.clear()
        self.board_requested.emit(long_text, 9000)
        voice_cfg = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        vid = str(voice_cfg.get("voice_id") or "")
        if vid:
            self._request_dispatch(
                "tts", self.tts_requested,
                (
                    long_text, vid, float(voice_cfg.get("speed", 1.0) or 1.0),
                    str(voice_cfg.get("output_device", "default") or "default"),
                    f"resource_diag_interrupt_{kind}_{index}",
                ),
                timeout=5.0,
            )
            self._tts_started.wait(6.0)
        accepted, message = self._request_dispatch(
            "hard_silence", self.hard_silence_requested,
            (str(phrase),), timeout=5.0
        )
        if not accepted:
            self._event("hard_silence_dispatch_error", phrase_id=int(index), message_len=len(str(message or "")))
        self._sleep(2.0)
        still_tts, still_board = self._probe_runtime_main_thread()
        self._event(
            "hard_silence_check", phrase_id=int(index),
            tts_active=bool(still_tts), board_active=bool(still_board),
            dispatched=bool(accepted)
        )
        self.board_close_requested.emit()
        passed = bool(accepted and not still_tts and not still_board)
        self._round_end(rec, passed, float(recovery))
        return passed

    def _hard_silence_smoke(self):
        return self._hard_silence_once("闭嘴", 0, kind="hard_silence_smoke", recovery=0.5)

    def _hard_silence_stage(self):
        for i, phrase in enumerate(("闭嘴", "你给我闭嘴", "你别说话了"), 1):
            self._hard_silence_once(phrase, i, kind="hard_silence", recovery=1.2)
'''
d = replace_method(d, "_hard_silence_stage", hard_method)

# Open live crash evidence, then require the independent watchdog BEFORE the user
# waits through the baseline. The dangerous interrupt path is smoke-tested first.
d = rep(
    d,
    '''        self._open_live_journals()
        wav_path=None; ok=True; err=""
''',
    '''        self._open_live_journals()
        self._enable_fault_handler()
        wav_path=None; ok=True; err=""
''',
    "fault handler startup",
)

d = rep(
    d,
    '''        try:
            self._set_stage("preflight",1,"启动前快速自检：事件、CPU、GPU与ASR测试音频")
''',
    '''        try:
            if not self._start_watchdog():
                raise RuntimeError("独立看门狗启动失败，为避免再次出现无报告黑箱，本次测试已安全停止")
            self._set_stage("preflight",1,"启动前快速自检：事件、CPU、GPU、ASR音频与独立看门狗")
''',
    "watchdog required",
)

preflight_anchor = '''            gpu_thread.start(); sampler.start(); self._sleep(1.0)
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
preflight_new = '''            gpu_thread.start(); sampler.start(); self._sleep(1.0)
            self._set_stage("preflight_interrupt",1,"高风险预检：TTS→闭嘴→白板关闭（主线程排队执行）")
            if not self._hard_silence_smoke():
                raise RuntimeError("高风险闭嘴预检未通过，已在正式长测前停止")
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
d = rep(d, preflight_anchor, preflight_new, "hard silence preflight")

# Flush faulthandler before building a normal report; watchdog remains independent.
d = rep(
    d,
    '''            self._journal_status("reporting", "report")
            self._close_live_journals()
            report=self._write_reports()
''',
    '''            self._journal_status("reporting", "report")
            self._disable_fault_handler()
            self._close_live_journals()
            report=self._write_reports()
''',
    "fault handler report flush",
)

# If report generation itself throws, close faulthandler too.
d = rep(
    d,
    '''        except Exception as exc:
            self._journal_status("report_failed", "report", error=f"{type(exc).__name__}: {exc}")
            self._close_live_journals()
''',
    '''        except Exception as exc:
            self._journal_status("report_failed", "report", error=f"{type(exc).__name__}: {exc}")
            self._disable_fault_handler()
            self._close_live_journals()
''',
    "fault handler failure flush",
)

wr(diag_new, d)

(assets / "VERSION.txt").write_text("0.10.0.9.3.4\n", encoding="ascii")
(root / "V0100934_CHANGELOG.txt").write_text(
    """XiaoMeili V0.10.0.9.3.4

- 一键深度资源测试升级为 Crash-Safe Diagnostic 3.0。
- 修复诊断后台线程直接调用 Brain/TTS/Speech/Pet Qt 对象的跨线程竞态；所有会修改运行状态的动作统一通过 Qt.QueuedConnection 回到GUI主线程串行执行。
- “闭嘴”测试不再从诊断线程直接调用 voice.speak 或 speech.utterance_ready.emit；TTS启动、P0闭嘴、白板关闭均由主线程调度。
- 正式60秒基线前增加10秒级高风险 TTS→闭嘴→白板关闭预检；预检失败立即停止，避免再次白等整轮。
- 新增独立PowerShell看门狗，隐藏运行、与XiaoMeili.exe分离；若主程序原生闪退，看门狗仍会在桌面生成崩溃ZIP。
- 看门狗会收集最后阶段、最后事件、Windows Application Error/WER、crashrpt/Sogou相关进程线索，并持续保留live日志。
- 新增 Python faulthandler 全线程日志，原生异常发生时尽可能留下Python线程栈。
- 所有崩溃证据均为追加/复制式；不删除、不移动、不覆盖用户文件、诊断原件或旧版本。
- 保留NDM真实URL文件名识别、快速回退、WAV/ASR、NVML无黑框、真实CPU、250ms采样与FullSafe。
""",
    encoding="utf-8",
)

for p in (main, diag_new):
    py_compile.compile(str(p), doraise=True)

combined = rd(main) + rd(diag_new)
required = [
    'APP_VERSION = "0.10.0.9.3.4"',
    "resource_diagnostic_v0100934",
    "ResourceDiagnosticMainThreadDispatcher",
    "Qt.ConnectionType.QueuedConnection",
    "hard_silence_requested",
    "self._hard_silence_smoke()",
    "resource_diag_watchdog_v0100934.ps1",
    "python_faulthandler.log",
    "watchdog_heartbeat.jsonl",
    "独立看门狗启动失败",
]
for token in required:
    if token not in combined:
        raise RuntimeError("contract missing: " + token)

# Direct mutating service calls may exist inside the dispatcher only, never in runner methods.
runner_text = rd(diag_new).split("class ResourceDiagnosticRunnerV2(QObject):", 1)[1]
for forbidden in ("self.voice.speak(", "self.brain.ask(", "self.speech.utterance_ready.emit("):
    if forbidden in runner_text:
        raise RuntimeError("cross-thread mutating call remains in runner: " + forbidden)

# FullSafe runtime guard.
for bad in ("shutil.rmtree", "os.remove(", ".unlink(", "shutil.move(", "Remove-Item"):
    if bad in rd(diag_new) or bad in watchdog_dst.read_text(encoding="utf-8-sig"):
        raise RuntimeError("unsafe delete/move token: " + bad)

print("PATCH_0100934_PASS")
