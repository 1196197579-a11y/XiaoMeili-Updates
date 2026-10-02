# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "src" / "main.py").read_text(encoding="utf-8")
DIAG = (ROOT / "app" / "src" / "resource_diagnostic_v01005.py").read_text(encoding="utf-8")
SPEECH = (ROOT / "app" / "src" / "speech_input.py").read_text(encoding="utf-8")

assert 'APP_VERSION = "0.10.0.5"' in MAIN
assert 'APP_UPDATE_VERSION = "0.10.0.5"' in MAIN
assert '"config_version": 27' in MAIN

# UI + unattended contract.
assert 'from resource_diagnostic_v01005 import ResourceDiagnosticRunner' in MAIN
assert '开始一键深度资源测试' in MAIN
assert '完全无人值守' in MAIN
assert 'def _v01005_start_deep_resource_test' in MAIN
assert 'def _v01005_diagnostic_progress' in MAIN
assert 'def _v01005_diagnostic_finished' in MAIN
assert '_resource_diagnostic_active' in MAIN
assert 'runner.board_requested.connect' in MAIN
assert 'self.pet.preview_dialogue' in MAIN

# The diagnostic never uses the user's microphone or normal memory-writing brain path.
assert 'SAMPLE_INTERVAL_SECONDS = 0.50' in DIAG
assert 'DIAGNOSTIC_BRAIN_RUNS = 4' in DIAG
assert 'DIAGNOSTIC_TTS_RUNS = 4' in DIAG
assert 'DIAGNOSTIC_SPEECH_RUNS = 4' in DIAG
assert 'DIAGNOSTIC_COMBINED_RUNS = 3' in DIAG
for stage in (
    'idle_baseline', 'whiteboard_only', 'brain_only', 'brain_cooldown',
    'tts_only', 'tts_cooldown', 'speech_input_only', 'speech_cooldown',
    'combined_all', 'final_cooldown',
):
    assert stage in DIAG

assert 'self.brain._start_server()' in DIAG
assert 'self.brain._post_json(' in DIAG
assert 'self.voice._start_worker()' in DIAG
assert 'self.voice._request(' in DIAG
assert 'diagnostic_process_v01005' in DIAG
assert 'zipfile.ZipFile(target, mode="x"' in DIAG
assert 'nvidia-smi' in DIAG
assert '--query-compute-apps=pid,process_name,used_gpu_memory' in DIAG
assert '不保存用户聊天内容' in DIAG

# No learning/history pollution from the diagnostic helper.
for forbidden in (
    'brain.ask(',
    '_save_history(',
    'save_feedback(',
    'auto_remember(',
    'FEEDBACK_FILE',
    'HISTORY_FILE',
):
    assert forbidden not in DIAG, forbidden

# No destructive user-file operations in the new diagnostic helper.
for forbidden in (
    '.unlink(',
    'rmtree(',
    'os.remove(',
    'shutil.move(',
    'Remove-Item',
    '/MIR',
    '/PURGE',
):
    assert forbidden not in DIAG, forbidden

# Speech input is tested through an internal WAV, not the microphone.
for token in (
    'def diagnostic_file(args):',
    '--diagnostic-wav',
    '--diagnostic-repeat',
    '--diagnostic-hold',
    'SpeechInputService.diagnostic_process_v01005',
    'diag_models_loaded',
    'diag_run',
    'diag_ready',
    'device="cpu"',
):
    assert token in SPEECH, token
assert 'sounddevice.InputStream' not in SPEECH[SPEECH.find('def diagnostic_file(args):'):SPEECH.find('def main():', SPEECH.find('def diagnostic_file(args):'))]

# Existing protected features must remain present.
assert 'QTimer.singleShot(1800, self.brain_service.warm_up_async)' in MAIN
assert 'setMaxLength(4)' in MAIN
assert 'ability_aura.hide()' in MAIN

print("V01005_DEEP_RESOURCE_DIAGNOSTIC_CONTRACT_PASS")
