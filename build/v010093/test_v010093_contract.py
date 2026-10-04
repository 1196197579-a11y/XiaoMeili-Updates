# -*- coding: utf-8 -*-
import ast, re, sys
from pathlib import Path


def main():
    root=Path(sys.argv[1]).resolve()
    files={
        'main':root/'app'/'src'/'main.py',
        'diag':root/'app'/'src'/'resource_diagnostic_v010093.py',
        'brain':root/'app'/'src'/'brain_dual.py',
        'voice':root/'app'/'src'/'voice_dual.py',
        'ndm':root/'app'/'src'/'ndm_bridge.py',
        'updater':root/'app'/'src'/'native_updater.py',
    }
    text={}
    for k,p in files.items():
        s=p.read_text(encoding='utf-8-sig'); ast.parse(s,filename=str(p)); text[k]=s
    combined='\n'.join(text.values())
    required=[
        'APP_VERSION = "0.10.0.9.3"',
        'ResourceDiagnosticRunnerV2',
        '一键深度资源测试 2.0',
        'CHAT_ROUNDS = 30',
        'BASELINE_SECONDS = 60',
        'FINAL_COOLDOWN_SECONDS = 90',
        'timeline_250ms.csv','round_ledger.csv','stage_summary.csv','vram_jump_events.csv','process_tree.csv',
        'offline standard-frame replay',
        '_resource_diag_no_persist',
        'diagnostic_no_persist',
        'resource_diag',
        '_is_hard_silence_command','_hard_silence_now',
        'QMovie.CacheMode.CacheNone','_release_movie_slot',
        'appearance_timeout_seconds=25','stall_timeout_seconds=75',
        'urlparse(str(url or "")).path',
        'NO_AUTOMATIC_FILE_DELETION',
        'XiaoMeili_V{APP_VERSION}_SourceProject.zip',
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError('contract missing: '+token)
    # Automatic test must not require a live game or microphone participation.
    forbidden_diag=['wait_for_real_match','collect_real_match','VALORANT window required','input("']
    for token in forbidden_diag:
        if token in text['diag']:
            raise RuntimeError('automatic diagnostic contains manual dependency: '+token)
    # New diagnostic itself must never delete/move user files.
    for bad in ('shutil.rmtree','os.remove','unlink(','Path.unlink','shutil.move','Remove-Item','robocopy'):
        if bad in text['diag']:
            raise RuntimeError('unsafe diagnostic token: '+bad)
    # Brain diagnostic mode must not persist test content.
    if 'if not diagnostic_no_persist:' not in text['brain']:
        raise RuntimeError('brain no-persist guard missing')
    if not re.search(r'record_brain_usage\([^\n]+resource_diag',text['brain']):
        raise RuntimeError('resource diagnostic usage tag missing')
    print('V010093_CONTRACT_PASS')

if __name__=='__main__':
    main()