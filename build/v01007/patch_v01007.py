# -*- coding: utf-8 -*-
"""Apply XiaoMeili V0.10.0.7 overlay to verified V0.10.0.5 source."""
from pathlib import Path
import base64, zlib, sys, re

HERE = Path(__file__).resolve().parent
PAYLOADS = {
    'app/src/brain_dual.py': 'brain_dual.py.zlib.b64',
    'app/src/cloud_support.py': 'cloud_support.py.zlib.b64',
    'app/src/cloud_usage.py': 'cloud_usage.py.zlib.b64',
    'app/src/voice_dual.py': 'voice_dual.py.zlib.b64',
}
VOICE_ID = 'qwen-audio-3.1-tts-flash-bailian-6d3dea9f00b74622854b4394fa6119f1'

def payload(name: str) -> bytes:
    return zlib.decompress(base64.b64decode((HERE / name).read_text(encoding='ascii').strip()))

def apply_unified(text: str, patch: str) -> str:
    src = text.replace('\r\n','\n').splitlines(True)
    lines = patch.splitlines(True)
    out=[]; src_i=0; i=0
    while i < len(lines):
        line=lines[i]
        if line.startswith(('--- ','+++ ')):
            i += 1; continue
        if not line.startswith('@@ '):
            i += 1; continue
        m=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if not m: raise RuntimeError('bad hunk header: '+line.rstrip())
        old_start=int(m.group(1))-1
        if old_start < src_i: raise RuntimeError('overlapping patch hunk')
        out.extend(src[src_i:old_start]); src_i=old_start; i += 1
        while i < len(lines) and not lines[i].startswith('@@ '):
            x=lines[i]
            if x.startswith(('--- ','+++ ')): break
            if x.startswith(' '):
                want=x[1:]
                if src_i>=len(src) or src[src_i]!=want: raise RuntimeError(f'context mismatch at {src_i+1}')
                out.append(src[src_i]); src_i+=1
            elif x.startswith('-'):
                want=x[1:]
                if src_i>=len(src) or src[src_i]!=want: raise RuntimeError(f'delete mismatch at {src_i+1}')
                src_i+=1
            elif x.startswith('+'):
                out.append(x[1:])
            elif x.startswith('\\'):
                pass
            else:
                raise RuntimeError('unexpected patch line')
            i += 1
    out.extend(src[src_i:])
    return ''.join(out)

def main():
    if len(sys.argv) != 2: raise SystemExit('usage: patch_v01007.py <SOURCE_ROOT>')
    root=Path(sys.argv[1]).resolve()
    mainp=root/'app/src/main.py'
    if not mainp.is_file(): raise SystemExit(f'unexpected SOURCE_ROOT: {root}')
    if 'APP_VERSION = "0.10.0.5"' not in mainp.read_text(encoding='utf-8-sig'):
        raise SystemExit('baseline must be V0.10.0.5')
    patch=payload('main_patch.zlib.b64').decode('utf-8')
    mainp.write_text(apply_unified(mainp.read_text(encoding='utf-8-sig'), patch), encoding='utf-8', newline='\n')
    for rel,name in PAYLOADS.items():
        target=(root/rel).resolve(); target.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(payload(name))
    req=root/'app/requirements.txt'
    rt=req.read_text(encoding='utf-8-sig')
    if 'dashscope' not in rt.lower(): rt=rt.rstrip()+"\ndashscope>=1.27,<2\n"
    req.write_text(rt,encoding='utf-8',newline='\n')
    ver=root/'app/assets/VERSION.txt'; ver.write_text('0.10.0.7\n',encoding='ascii')
    mt=mainp.read_text(encoding='utf-8-sig')
    checks=[
        'APP_VERSION = "0.10.0.7"', VOICE_ID,
        'qwen-audio-3.1-tts-flash', 'cloud_usage', 'latest_safe.json'
    ]
    for s in checks:
        if s not in mt and s not in (root/'app/src/voice_dual.py').read_text(encoding='utf-8-sig'):
            raise SystemExit('verification missing: '+s)
    print('V0.10.0.7 verified overlay PASS')

if __name__ == '__main__': main()
