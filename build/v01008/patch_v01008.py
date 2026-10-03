# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys
import base64
import zlib

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v01008.py <source_root> <repo_root>")

root=Path(sys.argv[1]).resolve()
repo=Path(sys.argv[2]).resolve()
src=root/"app"/"src"
main=src/"main.py"
speech=src/"speech_input.py"
brain=src/"brain_dual.py"
voice=src/"voice_dual.py"

def read(p):
    return p.read_text(encoding="utf-8-sig")

def write(p,s):
    p.write_text(s,encoding="utf-8",newline="\n")

def replace_once(s, old, new, label):
    if old not in s:
        raise RuntimeError(f"{label}: anchor missing")
    return s.replace(old,new,1)

payload="".join((repo/f"build/v01008/resource_diag.part{i}").read_text(encoding="ascii").strip() for i in range(1,4))
diag=zlib.decompress(base64.b64decode(payload))
(src/"resource_diagnostic_v01008.py").write_bytes(diag)

s=read(main)
if 'APP_VERSION = "0.10.0.7"' not in s:
    raise RuntimeError("V0.10.0.8 patch requires V0.10.0.7 baseline")
s=replace_once(s,"from resource_diagnostic_v01005 import ResourceDiagnosticRunner","from resource_diagnostic_v01008 import ResourceDiagnosticRunner","diagnostic import")
s=replace_once(s,'APP_NAME = "小美丽 V0.10.0.7｜Clone Voice Cloud Usage Test"','APP_NAME = "小美丽 V0.10.0.8｜Full Resource Diagnostic + Voice Interrupt"',"app name")
s=replace_once(s,'APP_VERSION = "0.10.0.7"','APP_VERSION = "0.10.0.8"',"app version")
s=replace_once(s,'APP_UPDATE_VERSION = "0.10.0.7"','APP_UPDATE_VERSION = "0.10.0.8"',"update version")
old_desc='''        diag_desc = QLabel(
            "完全无人值守：纯待机 → 白板动画 → Qwen3-8B 大脑 → Qwen3-TTS 声音 → "
            "FSMN-VAD + Fun-ASR-Nano-2512 → 3轮完整组合压力 → 冷却观察。"
            "全程使用内置固定测试内容，不需要你说话，通常约 8–12 分钟。"
        )'''
new_desc='''        diag_desc = QLabel(
            "完全无人值守：当前真实状态 → 隔离基线 → 白板动画 → 全部现有画面识别 → "
            "FSMN-VAD + Fun-ASR-Nano-2512 → 云端 Qwen3-8B → 云端复刻TTS → 综合压力 → 冷却。"
            "250ms采样并记录进程树/显存/识别耗时，结束后桌面自动生成脱敏ZIP。"
            "最好保持无畏契约已打开；无需你说话或操作游戏。云端链路阶段会产生极少量真实测试用量。"
        )'''
s=replace_once(s,old_desc,new_desc,"diagnostic description")
old_note='''            "提示：上方 GPU/显存仍显示整机占用。下面的深度资源诊断会通过隔离阶段、"
            "模型进程和阶段增量，把大脑、声音、语音输入与白板动画分别测清楚。"'''
new_note='''            "提示：上方 GPU/显存仍显示整机占用。V0.10.0.8 会先记录你点击测试时的真实状态，"
            "再隔离白板、画面识别、语音输入、云端大脑与云端TTS；当前画面识别本身已经共享一个 ScreenGrabber。"'''
s=replace_once(s,old_note,new_note,"resource note")

a=s.find("    def _v01005_start_deep_resource_test(self):\n")
b=s.find("    def _v01005_diagnostic_progress(self, value, text):\n",a)
if a<0 or b<0:
    raise RuntimeError("diagnostic method boundaries missing")
new_start='''    def _v01005_start_deep_resource_test(self):
        runner = getattr(self, "_v01005_diag_runner", None)
        if runner is not None and runner.is_running():
            return
        if not self.speech_service.ready():
            QMessageBox.information(self, "全模块深度资源诊断", "FSMN-VAD + Fun-ASR-Nano-2512 尚未准备完成，无法完成语音输入阶段。")
            return
        self.v01005_diag_btn.setEnabled(False)
        self.v01005_diag_progress.setValue(0)
        self.v01005_diag_status.setText("正在准备全模块深度资源诊断，请不要关闭小美丽…")
        runner = ResourceDiagnosticRunner(
            self.cfg, self.brain_service, self.voice_service, self.speech_service, self.vision,
            xiaomeili_logical_data_root(), desktop_dir(), APP_VERSION, self,
        )
        self._v01005_diag_runner = runner
        runner.progress_changed.connect(self._v01005_diagnostic_progress)
        runner.board_requested.connect(lambda text, ms: self.pet.preview_dialogue(str(text), int(ms)))
        runner.finished.connect(self._v01005_diagnostic_finished)
        if not runner.start():
            self.v01005_diag_btn.setEnabled(True)
            self.v01005_diag_status.setText("全模块深度资源诊断未启动，请稍后重试。")

'''
s=s[:a]+new_start+s[b:]
s=replace_once(s,"self.speech_service.utterance_ready.connect(self._on_speech_utterance)","self.speech_service.utterance_ready.connect(self._on_speech_utterance)\n        self.speech_service.interrupt_requested.connect(self._on_speech_interrupt)","speech interrupt signal connection")
a=s.find("    def _on_speech_engine_state(self, code, label):\n")
b=s.find("    def _on_speech_utterance(self, text):\n",a)
if a<0 or b<0:
    raise RuntimeError("speech engine handler boundaries missing")
handler='''    def _on_speech_engine_state(self, code, label):
        if self._speech_session_active and not self._speech_waiting_question:
            if self._speech_waiting_brain:
                QTimer.singleShot(0,lambda:self._speech_state("thinking","小美丽正在想"))
            return

    def _on_speech_interrupt(self, text):
        if not self._speech_session_active:
            return
        LOGGER.info("[VOICE_INTERRUPT] %r", text)
        self._speech_session_token += 1
        self._speech_session_active = False
        self._speech_waiting_question = False
        self._speech_waiting_brain = False
        self._speech_pending_question = ""
        setattr(self.brain_service, "_voice_session_request", False)
        try:
            self.brain_service.abort_current("voice_interrupt")
        except Exception:
            LOGGER.warning("打断云端大脑失败", exc_info=True)
        try:
            self.voice_service.abort_playback("voice_interrupt")
        except Exception:
            LOGGER.warning("打断语音播放失败", exc_info=True)
        try:
            if getattr(self.pet, "dialogue_board_active", False):
                self.pet._end_dialogue_board()
        except Exception:
            LOGGER.debug("关闭白板失败", exc_info=True)
        try:
            self.pet.set_dialogue_indicator(False)
        except Exception:
            pass
        if bool(self._speech_cfg().get("enabled", True)) and self.speech_service.ready():
            self.speech_service.resume()
            self._speech_state("listening", "等待“美丽美丽”")
        else:
            self._speech_state("stopped", "语音监听已停止")

'''
s=s[:a]+handler+s[b:]
s=replace_once(s,'self.pet.set_dialogue_indicator(True); self.speech_service.pause(); self._speech_pending_question=str(inline_question or "").strip()','self.pet.set_dialogue_indicator(True); self.speech_service.interrupt_only(); self._speech_pending_question=str(inline_question or "").strip()',"wake session interrupt mode")
s=replace_once(s,'self.speech_service.pause(); self._ask_voice_question(question)','self.speech_service.interrupt_only(); self._ask_voice_question(question)',"followup interrupt mode")
s=replace_once(s,'        self._speech_state("speaking","小美丽正在说话")\n        if bool(self._speech_cfg().get("whiteboard_enabled",True)):','        self._speech_state("speaking","小美丽正在说话")\n        self.speech_service.interrupt_only()\n        if bool(self._speech_cfg().get("whiteboard_enabled",True)):',"speaking interrupt mode")
write(main,s)

s=read(speech)
s=replace_once(s,'HOTWORDS = "美丽美丽 小美丽 无畏契约 VALORANT 贤者 KDA 保枪 大狙 狙击枪 步枪 冰墙 玉城"','HOTWORDS = "美丽美丽 小美丽 无畏契约 VALORANT 贤者 KDA 保枪 大狙 狙击枪 步枪 冰墙 玉城 闭嘴 别说话 别说了 不要说了 安静 停一下 停止说话 别讲了 住嘴"',"speech hotwords")
s=replace_once(s,"import wave\nimport time\nfrom pathlib import Path","import wave\nimport time\nfrom difflib import SequenceMatcher\nfrom pathlib import Path","worker difflib import")
s=replace_once(s,'''    paused = threading.Event()
    stopping = threading.Event()
    q = queue.Queue(maxsize=30)
''','''    paused = threading.Event()
    stopping = threading.Event()
    interrupt_only = threading.Event()
    q = queue.Queue(maxsize=30)

    def is_interrupt_text(raw):
        normalized = re.sub(r"[\\s，,。.!！？?、:：；;~～]+", "", str(raw or "")).lower()
        if not normalized:
            return False
        phrases = ("闭嘴","别说话","别说了","不要说了","安静","停一下","停止说话","别讲了","别讲","住嘴","不要讲话","别讲话")
        if any(p in normalized for p in phrases):
            return True
        if len(normalized) > 12:
            return False
        return max(SequenceMatcher(None, normalized, p).ratio() for p in phrases) >= 0.72
''',"interrupt matcher")
s=replace_once(s,'''            if cmd == "pause":
                paused.set(); emit("state", code="paused", label="语音监听已暂停")
            elif cmd == "resume":
                paused.clear(); emit("state", code="listening", label="等待“美丽美丽”")
            elif cmd in {"stop", "quit", "shutdown"}:
                stopping.set(); return
''','''            if cmd == "pause":
                interrupt_only.clear()
                paused.set(); emit("state", code="paused", label="语音监听已暂停")
            elif cmd == "interrupt":
                paused.clear(); interrupt_only.set()
                emit("state", code="interrupt", label="可说“闭嘴”立即打断")
            elif cmd == "resume":
                interrupt_only.clear(); paused.clear()
                emit("state", code="listening", label="等待“美丽美丽”")
            elif cmd in {"stop", "quit", "shutdown"}:
                stopping.set(); return
''',"worker commands")
s=replace_once(s,'''        if text:
            emit("utterance", text=text)
        else:
            logging.warning("[ASR_EMPTY] no text returned")
''','''        if text:
            if interrupt_only.is_set():
                if is_interrupt_text(text):
                    logging.info("[INTERRUPT_MATCH] text=%r", text)
                    emit("interrupt", text=text)
                else:
                    logging.info("[INTERRUPT_DISCARD] text=%r", text)
            else:
                emit("utterance", text=text)
        else:
            logging.warning("[ASR_EMPTY] no text returned")
''',"interrupt-only ASR emit")
s=replace_once(s,'    utterance_ready = Signal(str)\n    error = Signal(str)','    utterance_ready = Signal(str)\n    interrupt_requested = Signal(str)\n    error = Signal(str)',"interrupt Qt signal")
s=replace_once(s,'''                elif kind == "utterance":
                    text = str(evt.get("text") or "").strip()
                    if text:
                        self.utterance_ready.emit(text)
                elif kind == "error":
''','''                elif kind == "utterance":
                    text = str(evt.get("text") or "").strip()
                    if text:
                        self.utterance_ready.emit(text)
                elif kind == "interrupt":
                    text = str(evt.get("text") or "").strip()
                    if text:
                        self.interrupt_requested.emit(text)
                elif kind == "error":
''',"interrupt event reader")
s=replace_once(s,'''    def pause(self):
        return self._command("pause")

    def resume(self):
        return self._command("resume")
''','''    def pause(self):
        return self._command("pause")

    def interrupt_only(self):
        return self._command("interrupt")

    def resume(self):
        return self._command("resume")
''',"interrupt service command")
write(speech,s)

s=read(brain)
s=replace_once(s,'''        self._app_cfg = {}
        self._last_cloud_latency = {}
''','''        self._app_cfg = {}
        self._last_cloud_latency = {}
        self._cloud_abort = threading.Event()
        self._cloud_response_lock = threading.Lock()
        self._cloud_response = None
''',"brain abort state")
s=replace_once(s,'''        self._generate_busy = True
        self.generation_started.emit()
        if bool(long_term_memory):
''','''        self._cloud_abort.clear()
        with self._cloud_response_lock:
            self._cloud_response = None
        self._generate_busy = True
        self.generation_started.emit()
        if bool(long_term_memory):
''',"brain abort clear")
s=replace_once(s,'''                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    while True:
                        raw_line = resp.readline()
''','''                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    with self._cloud_response_lock:
                        self._cloud_response = resp
                    while True:
                        if self._cloud_abort.is_set():
                            raise InterruptedError("voice_interrupt")
                        raw_line = resp.readline()
''',"brain response handle")
s=replace_once(s,'''                        if not raw_line:
                            break
                        line = raw_line.decode("utf-8", errors="replace").strip()
''','''                        if self._cloud_abort.is_set():
                            raise InterruptedError("voice_interrupt")
                        if not raw_line:
                            break
                        line = raw_line.decode("utf-8", errors="replace").strip()
''',"brain abort after read")
s=replace_once(s,'''            except Exception as exc:
                LOGGER.exception("云端大脑回答失败")
                reason = f"{type(exc).__name__}: {exc}"
                self._cloud_fail_or_fallback(reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
                return
''','''            except Exception as exc:
                if self._cloud_abort.is_set() or isinstance(exc, InterruptedError):
                    self._generate_busy = False
                    self.spoken_stream_done.emit(False, "")
                    self.generation_finished.emit(False, {}, "回答已被语音打断")
                    return
                LOGGER.exception("云端大脑回答失败")
                reason = f"{type(exc).__name__}: {exc}"
                self._cloud_fail_or_fallback(reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
                return
            finally:
                with self._cloud_response_lock:
                    self._cloud_response = None
''',"brain abort exception handling")
insert='''    def abort_current(self, reason="voice_interrupt"):
        self._cloud_abort.set()
        with self._cloud_response_lock:
            resp = self._cloud_response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
        try:
            self.spoken_stream_aborted.emit(str(reason or "voice_interrupt"))
        except Exception:
            pass
        if not self.cloud_mode():
            try:
                super().shutdown()
            except Exception:
                pass

'''
pos=s.find("    def _cloud_fail_or_fallback(self, reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory):\n")
if pos<0: raise RuntimeError("brain fallback method anchor missing")
s=s[:pos]+insert+s[pos:]
s=replace_once(s,'''    def _cloud_fail_or_fallback(self, reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory):
        c = self._ccfg()
''','''    def _cloud_fail_or_fallback(self, reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory):
        if self._cloud_abort.is_set():
            self._generate_busy = False
            self.spoken_stream_done.emit(False, "")
            self.generation_finished.emit(False, {}, "回答已被语音打断")
            return
        c = self._ccfg()
''',"no fallback after interrupt")
write(brain,s)

s=read(voice)
insert='''    def abort_playback(self, reason="voice_interrupt"):
        try:
            self.cloud_stream_abort(str(reason or "voice_interrupt"))
        except Exception:
            pass
        try:
            super().shutdown()
        except Exception:
            pass

'''
pos=s.find("    def shutdown(self):\n")
if pos<0: raise RuntimeError("voice shutdown anchor missing")
s=s[:pos]+insert+s[pos:]
write(voice,s)

(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.8\n",encoding="ascii")
for p in (main,speech,brain,voice,src/"resource_diagnostic_v01008.py"):
    py_compile.compile(str(p),doraise=True)

main_text=read(main); speech_text=read(speech); brain_text=read(brain); voice_text=read(voice)
checks=[
    ('APP_VERSION = "0.10.0.8"',main_text),("resource_diagnostic_v01008",main_text),
    ("self.vision,",main_text),("interrupt_requested.connect",main_text),
    ("def _on_speech_interrupt",main_text),("def interrupt_only",speech_text),
    ('emit("interrupt"',speech_text),('device="cpu"',speech_text),
    ("def abort_current",brain_text),("def abort_playback",voice_text),
]
for needle,hay in checks:
    if needle not in hay:
        raise RuntimeError("verification missing: "+needle)
print("V0.10.0.8 patch PASS")
