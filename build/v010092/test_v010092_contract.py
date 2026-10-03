# -*- coding: utf-8 -*-
import ast, sys
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    main_py = root/'app'/'src'/'main.py'
    speech = root/'app'/'src'/'speech_input.py'
    ndm = root/'app'/'src'/'ndm_bridge.py'
    voice = root/'app'/'src'/'voice_dual.py'
    files = [main_py, speech, ndm, voice]
    combined = ''
    for p in files:
        text = p.read_text(encoding='utf-8-sig')
        ast.parse(text, filename=str(p))
        combined += '\n' + text
    required = [
        'APP_VERSION = "0.10.0.9.2"',
        'QMovie.CacheMode.CacheNone', '_release_movie_slot', 'deleteLater()',
        '_speech_thinking_restore_pending', '_is_hard_silence_command', '_hard_silence_now',
        '你给我闭嘴', '你别说话了', '先别说话',
        'appearance_timeout_seconds=25', 'stall_timeout_seconds=75',
        'ctx["queue"] = None', 'XiaoMeili_V{APP_VERSION}_SourceProject.zip',
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError('contract missing: ' + token)
    print('V010092_CONTRACT_PASS')

if __name__ == '__main__':
    main()