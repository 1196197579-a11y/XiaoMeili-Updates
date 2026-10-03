from pathlib import Path
import py_compile, shutil, sys

root=Path(sys.argv[1]).resolve(); repo=Path(sys.argv[2]).resolve()
src=root/"app"/"src"; main=src/"main.py"; out=src/"interaction_diagnostic_v010091.py"
shutil.copyfile(repo/"build/v010091/interaction_diagnostic_v010091.py",out)

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,n):
    if a not in s: raise RuntimeError(n)
    return s.replace(a,b,1)

s=rd(main)
if 'APP_VERSION = "0.10.0.9"' not in s: raise RuntimeError("baseline")
s=rep(s,"from resource_diagnostic_v01009 import ResourceDiagnosticRunner",
      "from interaction_diagnostic_v010091 import InteractionDiagnosticRunner, interaction_diag_note","import")
s=rep(s,'APP_NAME = "小美丽 V0.10.0.9｜Real Match Diagnostic + NDM Preferred"',
      'APP_NAME = "小美丽 V0.10.0.9.1｜Long Interaction Diagnostic + NDM Preferred"',"name")
s=rep(s,'APP_VERSION = "0.10.0.9"','APP_VERSION = "0.10.0.9.1"',"ver")
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9"','APP_UPDATE_VERSION = "0.10.0.9.1"',"uver")
s=rep(s,'QGroupBox("一键深度资源诊断")','QGroupBox("长时间真实聊天资源诊断")',"group")
s=rep(s,'QPushButton("开始一键深度资源测试")','QPushButton("开始长时间交互诊断")',"button")

old='''        note = QLabel(
            "提示：上方 GPU/显存仍显示整机占用。V0.10.0.9 会先等待并记录一整局真实 VALORANT 对局，"
            "再自动隔离测试白板、语音输入、云端大脑与云端TTS；识别链继续共享一个 ScreenGrabber。"
        )'''
new='''        note = QLabel(
            "提示：V0.10.0.9.1 改为长时间真实聊天追踪。只旁观真实使用时的资源变化，"
            "不会主动启停组件、发送模拟问题或修改任何设置。"
        )'''
s=rep(s,old,new,"note")
old='''        diag_desc = QLabel(
            "实战采集模式：点击一次后切回 VALORANT，正常打一局即可。检测到真实对局 HUD 后自动开始，"
            "整局记录显存/CPU/RAM、进程、屏幕采集与识别事件；检测到赛后结算后，自动继续测试 "
            "FSMN-VAD + Fun-ASR-Nano-2512、云端 Qwen3-8B、云端复刻TTS、白板与赛后综合压力。"
            "你不需要故意掉血、击杀或死亡；本局没发生的识别事件会明确标记为“未观察到”。"
        )'''
new='''        diag_desc = QLabel(
            "点击开始后像平时一样不断和小美丽聊天；想结束时再次点击“结束并生成报告”。"
            "每250ms记录CPU/RAM/GPU/显存、进程、ASR、大脑、TTS、白板、线程/队列及每轮对话。"
            "显存单次增加>=256MB自动标记；不保存聊天原文、麦克风录音、API Key、记忆、昵称或截图。"
        )'''
s=rep(s,old,new,"desc")

a=s.index("    def _v01005_start_deep_resource_test(self):\n")
b=s.index("    def _v01005_diagnostic_progress(self, value, text):\n",a)
s=s[:a]+'''    def _v01005_start_deep_resource_test(self):
        runner=getattr(self,"_v01005_diag_runner",None)
        if runner is not None and runner.is_running():
            self.v01005_diag_btn.setEnabled(False)
            self.v01005_diag_btn.setText("正在生成报告…")
            self.v01005_diag_status.setText("正在结束记录并生成脱敏 ZIP；不会关闭小美丽或任何功能…")
            runner.stop_and_report(); return
        self.v01005_diag_progress.setRange(0,0)
        self.v01005_diag_btn.setText("结束并生成报告")
        self.v01005_diag_status.setText("诊断已启动：现在正常和小美丽聊天，想结束时再点一次按钮。")
        runner=InteractionDiagnosticRunner(
            self.cfg,self.brain_service,self.voice_service,self.speech_service,self.pet,
            xiaomeili_logical_data_root(),desktop_dir(),APP_VERSION,self)
        self._v01005_diag_runner=runner
        runner.status_changed.connect(self.v01005_diag_status.setText)
        runner.elapsed_changed.connect(self.v01005_diag_status.setText)
        runner.finished.connect(self._v01005_diagnostic_finished)
        if not runner.start():
            self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(0)
            self.v01005_diag_btn.setText("开始长时间交互诊断")
            self.v01005_diag_status.setText("诊断未启动，请稍后重试。")

'''+s[b:]

a=s.index("    def _v01005_diagnostic_finished(self, ok, report_path, message):\n")
b=s.index('    def open_system_section(self, name="更新"):\n',a)
s=s[:a]+'''    def _v01005_diagnostic_finished(self, ok, report_path, message):
        self.v01005_diag_btn.setEnabled(True); self.v01005_diag_btn.setText("开始长时间交互诊断")
        self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(100 if report_path else 0)
        self.v01005_diag_status.setText(str(message))
        if report_path:
            QMessageBox.information(self,"长时间交互诊断完成",
                f"{message}\\n\\n请把桌面上的诊断 ZIP 直接上传给 ChatGPT。\\n"
                "结束诊断没有关闭小美丽、语音、大脑、TTS或白板，也没有修改设置。")
        else:
            QMessageBox.warning(self,"长时间交互诊断失败",str(message))

'''+s[b:]

hooks=[
('''    def _on_speech_engine_state(self, code, label):
''','''    def _on_speech_engine_state(self, code, label):
        interaction_diag_note("speech_state",code=str(code or ""))
''',"speechstate"),
('''    def _on_speech_interrupt(self, text):
''','''    def _on_speech_interrupt(self, text):
        interaction_diag_note("voice_interrupt")
''',"interrupt"),
('''        if not text:return
        if not self._speech_session_active:
''','''        if not text:return
        interaction_diag_note("speech_utterance",chars=len(text))
        if not self._speech_session_active:
''',"utterance"),
('''    def _begin_speech_session(self, inline_question=""):
        if self._speech_session_active:return
''','''    def _begin_speech_session(self, inline_question=""):
        if self._speech_session_active:return
        interaction_diag_note("speech_session_start")
''',"sessionstart"),
('''    def _end_speech_session(self, resume=True):
        self._speech_session_token+=1;''','''    def _end_speech_session(self, resume=True):
        interaction_diag_note("speech_session_end")
        self._speech_session_token+=1;''',"sessionend"),
('''    def _on_voice_playback_started(self, text, duration_ms, tag):
        tag=str(tag or "")
''','''    def _on_voice_playback_started(self, text, duration_ms, tag):
        tag=str(tag or "")
        interaction_diag_note("tts_playback_start",tag=tag,duration_ms=int(duration_ms or 0))
''',"ttsstart"),
('''    def _on_voice_playback_finished(self, ok, message, tag):
        tag=str(tag or "")
''','''    def _on_voice_playback_finished(self, ok, message, tag):
        tag=str(tag or "")
        interaction_diag_note("tts_playback_end",tag=tag,ok=bool(ok))
''',"ttsend"),
('''    def _brain_generation_started(self):
        self.brain_send_btn.setEnabled(False)
''','''    def _brain_generation_started(self):
        interaction_diag_note("turn_start")
        interaction_diag_note("brain_generation_start")
        self.brain_send_btn.setEnabled(False)
''',"brainstart"),
('''    def _brain_generation_finished(self, ok, answer, message):
        self.brain_send_btn.setEnabled(True)
''','''    def _brain_generation_finished(self, ok, answer, message):
        interaction_diag_note("brain_generation_end",ok=bool(ok),chars=len(str((answer or {}).get("spoken_text") or "")) if isinstance(answer,dict) else 0)
        self.brain_send_btn.setEnabled(True)
''',"brainend"),
('''    def start_dialogue_board(self, text, duration_ms):
        self.dialogue_visual_generation += 1
''','''    def start_dialogue_board(self, text, duration_ms):
        interaction_diag_note("whiteboard_start",duration_ms=int(duration_ms or 0))
        self.dialogue_visual_generation += 1
''',"boardstart"),
]
for x,y,n in hooks: s=rep(s,x,y,n)
s=rep(s,'''    def _end_dialogue_board(self, generation=None):
        if generation is not None and int(generation) != int(self.dialogue_visual_generation):
            return
''','''    def _end_dialogue_board(self, generation=None):
        if generation is not None and int(generation) != int(self.dialogue_visual_generation):
            return
        interaction_diag_note("whiteboard_end")
''',"boardend")

if "GitHub 更新包自动使用小美丽内置下载器" in s: raise RuntimeError("ndm bypass")
if "NDM is the preferred downloader for every update URL" not in s: raise RuntimeError("ndm marker")
s=s.replace('cfg["config_version"] = max(29, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(30, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 29','cfg["config_version"] = 30')
wr(main,s); (root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.1\n",encoding="ascii")
py_compile.compile(str(main),doraise=True); py_compile.compile(str(out),doraise=True)
for n in ['APP_VERSION = "0.10.0.9.1"',"InteractionDiagnosticRunner","结束并生成报告","conversation_turns.csv"]:
    if n not in (s+rd(out)): raise RuntimeError(n)
print("PATCH_010091_PASS")
