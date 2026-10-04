# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, shutil, sys

root=Path(sys.argv[1]).resolve()
repo=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else Path(__file__).resolve().parents[2]
src=root/'app'/'src'
main=src/'main.py'
brain=src/'brain_dual.py'
module_src=repo/'build'/'v010093'/'resource_diagnostic_v010093.py'
module_dst=src/'resource_diagnostic_v010093.py'

def rd(p): return p.read_text(encoding='utf-8-sig')
def wr(p,s): p.write_text(s,encoding='utf-8',newline='\n')
def rep(s,a,b,name,count=1):
    if a not in s: raise RuntimeError(f'missing patch anchor: {name}')
    return s.replace(a,b,count)

if not module_src.is_file(): raise RuntimeError('resource_diagnostic_v010093.py missing')
shutil.copyfile(module_src,module_dst)

s=rd(main)
if 'APP_VERSION = "0.10.0.9.2"' not in s: raise RuntimeError('V0.10.0.9.2 baseline required')
s=rep(s,
    'from interaction_diagnostic_v010091 import InteractionDiagnosticRunner, interaction_diag_note',
    'from interaction_diagnostic_v010091 import InteractionDiagnosticRunner, interaction_diag_note\nfrom resource_diagnostic_v010093 import ResourceDiagnosticRunnerV2',
    'resource diagnostic import')
s=rep(s,'APP_NAME = "小美丽 V0.10.0.9.2｜Long Chat Stability + Hard Silence + NDM Fast Fallback"',
          'APP_NAME = "小美丽 V0.10.0.9.3｜Automatic Resource Diagnostic 2.0"','app name')
s=rep(s,'APP_VERSION = "0.10.0.9.2"','APP_VERSION = "0.10.0.9.3"','version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.2"','APP_UPDATE_VERSION = "0.10.0.9.3"','update version')

old='''        note = QLabel(
            "提示：V0.10.0.9.1 改为长时间真实聊天追踪。只旁观真实使用时的资源变化，"
            "不会主动启停组件、发送模拟问题或修改任何设置。"
        )'''
new='''        note = QLabel(
            "提示：V0.10.0.9.3 升级为一键深度资源测试 2.0。点击一次即可全自动测试，"
            "无需开 VALORANT、无需说话，也不需要手动陪小美丽聊天。"
        )'''
s=rep(s,old,new,'resource note')
old='''        diag_box = QGroupBox("长时间真实聊天资源诊断")
        diag_lay = QVBoxLayout(diag_box)
        diag_lay.setContentsMargins(14, 14, 14, 14)
        diag_lay.setSpacing(8)
        diag_desc = QLabel(
            "点击开始后像平时一样不断和小美丽聊天；想结束时再次点击“结束并生成报告”。"
            "每250ms记录CPU/RAM/GPU/显存、进程、ASR、大脑、TTS、白板、线程/队列及每轮对话。"
            "显存单次增加>=256MB自动标记；不保存聊天原文、麦克风录音、API Key、记忆、昵称或截图。"
        )
'''
new='''        diag_box = QGroupBox("一键深度资源测试 2.0")
        diag_lay = QVBoxLayout(diag_box)
        diag_lay.setContentsMargins(14, 14, 14, 14)
        diag_lay.setSpacing(8)
        diag_desc = QLabel(
            "全自动依次测试：纯待机、状态动画、白板、FSMN-VAD + Fun-ASR-Nano-2512、云端大脑、云端TTS、"
            "30轮完整聊天、闭嘴硬打断、离线画面识别（头像/击杀UI/结算OCR/高光）和综合满载，最后静置观察资源回落。"
            "每250ms记录CPU/RAM/GPU/显存、线程、TTS队列、QMovie/白板/ASR/大脑/TTS状态，并生成逐轮资源账本。"
        )
'''
s=rep(s,old,new,'diagnostic group')
s=rep(s,'self.v01005_diag_status = QLabel("尚未运行深度资源测试")',
          'self.v01005_diag_status = QLabel("尚未运行一键深度资源测试 2.0")','diag initial status')
s=rep(s,'self.v01005_diag_btn = QPushButton("开始长时间交互诊断")',
          'self.v01005_diag_btn = QPushButton("开始一键深度资源测试 2.0")','diag button')
old='''        diag_safety = QLabel(
            "测试不会读取/注入 VALORANT，不写入长期记忆、养成库或聊天历史；"
            "只启停小美丽自己的运行组件并创建新的诊断文件，不删除、移动或覆盖你的现有文件。"
        )'''
new='''        diag_safety = QLabel(
            "无需打开游戏：画面识别使用内存中的标准离线画面回放。云端大脑与TTS会产生少量真实API费用，"
            "但测试不写入聊天历史、长期记忆或养成库；报告不保存聊天原文、回答原文、录音、截图、API Key或昵称。"
            "测试只创建新的诊断文件/ZIP，不删除、移动、覆盖或递归清理你的任何现有文件。"
        )'''
s=rep(s,old,new,'diagnostic safety')

start=s.index('    def _v01005_start_deep_resource_test(self):\n')
end=s.index('    def _v01005_diagnostic_progress(self, value, text):\n',start)
s=s[:start]+'''    def _v01005_start_deep_resource_test(self):
        runner=getattr(self,"_v01005_diag_runner",None)
        if runner is not None and runner.is_running():
            QMessageBox.information(self,"一键深度资源测试 2.0","测试正在自动运行，请等待完成。")
            return
        self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(0)
        self.v01005_diag_btn.setEnabled(False)
        self.v01005_diag_btn.setText("自动测试运行中…")
        self.v01005_diag_status.setText("正在准备全自动测试；无需开游戏、无需说话、无需操作。")
        runner=ResourceDiagnosticRunnerV2(
            self.cfg,self.brain_service,self.voice_service,self.speech_service,self.vision,self.pet,
            xiaomeili_logical_data_root(),desktop_dir(),APP_VERSION,self)
        self._v01005_diag_runner=runner
        runner.progress_changed.connect(self._v01005_diagnostic_progress)
        runner.state_requested.connect(lambda state:self.pet.play_state(str(state),force_new_clip=True))
        runner.board_requested.connect(self.pet.start_dialogue_board)
        runner.board_close_requested.connect(lambda:self.pet._end_dialogue_board() if getattr(self.pet,"dialogue_board_active",False) else None)
        runner.finished.connect(self._v01005_diagnostic_finished)
        if not runner.start():
            self.v01005_diag_btn.setEnabled(True); self.v01005_diag_progress.setValue(0)
            self.v01005_diag_btn.setText("开始一键深度资源测试 2.0")
            self.v01005_diag_status.setText("测试未启动，请稍后重试。")

'''+s[end:]

start=s.index('    def _v01005_diagnostic_finished(self, ok, report_path, message):\n')
end=s.index('    def open_system_section(self, name="更新"):\n',start)
s=s[:start]+'''    def _v01005_diagnostic_finished(self, ok, report_path, message):
        self.v01005_diag_btn.setEnabled(True); self.v01005_diag_btn.setText("开始一键深度资源测试 2.0")
        self.v01005_diag_progress.setRange(0,100); self.v01005_diag_progress.setValue(100 if report_path else 0)
        self.v01005_diag_status.setText(str(message))
        if report_path:
            QMessageBox.information(self,"一键深度资源测试 2.0 完成",
                f"{message}\\n\\n桌面已生成脱敏诊断 ZIP，请直接上传给 ChatGPT。\\n"
                "测试不需要打开 VALORANT，也不会删除、移动或覆盖你的现有文件。")
        else:
            QMessageBox.warning(self,"一键深度资源测试 2.0 失败",str(message))

'''+s[end:]

# Config version bump only. Do not rewrite user settings.
s=s.replace('cfg["config_version"] = max(31, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(32, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 31','cfg["config_version"] = 32')
wr(main,s)

# Cloud brain diagnostic mode: use the real cloud path but never persist test
# prompts/replies into history, long-term memory or training rules.
b=rd(brain)
b=rep(b,
'''        c = self._ccfg()
        # Explicit local mode keeps V0.10.0.5 behaviour intact.
''',
'''        c = self._ccfg()
        diagnostic_no_persist = bool(getattr(self, "_resource_diag_no_persist", False))
        if diagnostic_no_persist:
            c = dict(c)
            c["fallback_local"] = False
            long_term_memory = False
            context_turns = 0
            max_tokens = min(32, int(max_tokens))
            temperature = 0.2
        # Explicit local mode keeps V0.10.0.5 behaviour intact.
''','brain diag flag')
b=rep(b,
'''        retrieval_started = time.time()
        exact_rule = self._exact_rule(user_text)
        best_rule = dict(exact_rule or self._v089_best_rule(user_text) or {})
        retrieval_ms = int((time.time() - retrieval_started) * 1000)
''',
'''        retrieval_started = time.time()
        if diagnostic_no_persist:
            exact_rule = None
            best_rule = {}
        else:
            exact_rule = self._exact_rule(user_text)
            best_rule = dict(exact_rule or self._v089_best_rule(user_text) or {})
        retrieval_ms = int((time.time() - retrieval_started) * 1000)
''','brain rule bypass')
b=rep(b,'        if bool(long_term_memory):\n            self.auto_remember(user_text)\n',
          '        if bool(long_term_memory) and not diagnostic_no_persist:\n            self.auto_remember(user_text)\n','brain memory bypass')
b=rep(b,
'''                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": spoken})
                self._save_history(history)
''',
'''                if not diagnostic_no_persist:
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": spoken})
                    self._save_history(history)
''','brain history bypass')
b=rep(b,'                        record_brain_usage(brain_in, brain_out, tag="dialogue")',
          '                        record_brain_usage(brain_in, brain_out, tag="resource_diag" if diagnostic_no_persist else "dialogue")','brain usage tag')
wr(brain,b)

(root/'app'/'assets'/'VERSION.txt').write_text('0.10.0.9.3\n',encoding='ascii')
(root/'V010093_CHANGELOG.txt').write_text('''XiaoMeili V0.10.0.9.3\n\n- 系统栏资源诊断升级为“一键深度资源测试 2.0”。\n- 无需打开 VALORANT、无需说话、无需手动聊天。\n- 自动测试：待机、状态动画、白板、ASR、云端大脑、云端TTS、30轮完整聊天、闭嘴硬打断、离线画面识别、综合满载、最终资源回落。\n- 每250ms记录 CPU/RAM/GPU/显存、线程、TTS队列、QMovie/白板/ASR/大脑/TTS状态。\n- 输出 timeline_250ms.csv、round_ledger.csv、stage_summary.csv、vram_jump_events.csv、process_tree.csv、summary.json 和脱敏ZIP。\n- 云端测试使用真实API但不写入聊天历史、长期记忆或养成库。\n- FullSafe：不删除、不移动、不递归清理用户文件；NDM源文件只复制不删除；旧版本继续保留回滚。\n''',encoding='utf-8')

for p in (main,brain,module_dst): py_compile.compile(str(p),doraise=True)
combined=rd(main)+rd(brain)+rd(module_dst)
for token in ['APP_VERSION = "0.10.0.9.3"','ResourceDiagnosticRunnerV2','一键深度资源测试 2.0','CHAT_ROUNDS = 30','offline standard-frame replay','_resource_diag_no_persist','round_ledger.csv','FINAL_COOLDOWN_SECONDS = 90']:
    if token not in combined: raise RuntimeError('contract missing: '+token)
print('PATCH_010093_PASS')