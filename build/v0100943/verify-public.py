from pathlib import Path
import hashlib,io,json,urllib.request,zipfile
base=Path('build/v0100943')
proof=json.loads((base/'candidate.json').read_text(encoding='utf-8'))
local=json.loads((base/'local-gates.json').read_text(encoding='utf-8'))
readback=json.loads((base/'public-readback.json').read_text(encoding='utf-8'))
assert local['all_local_gates_pass'] and readback['pass']
assert local['main_exe_sha256']==readback['main_exe_sha256']==proof['main_exe_sha256']
for name,expected in proof['assets'].items():
    url='https://github.com/1196197579-a11y/XiaoMeili-Updates/releases/download/v0.10.0.9.4.3/'+name
    with urllib.request.urlopen(url,timeout=120) as response:data=response.read()
    assert len(data)==expected['size'] and hashlib.sha256(data).hexdigest()==expected['sha256'],name
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        if 'update' in name:assert hashlib.sha256(z.read('XiaoMeili.exe')).hexdigest()==proof['main_exe_sha256']
print('PUBLIC_READBACK_CONFIRMED_BEFORE_PROMOTION')
