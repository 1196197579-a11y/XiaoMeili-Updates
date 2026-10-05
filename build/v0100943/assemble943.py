"""Reconstruct the exact accepted EXE and packages; never rebuild the EXE."""
from pathlib import Path
import argparse,base64,hashlib,json,urllib.request,zipfile,zlib,sys
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('--baseline-directory');a=p.parse_args()
root=Path(a.root);out=Path(a.out);out.mkdir(exist_ok=False,parents=True)
proof=json.loads((root/'candidate.json').read_text(encoding='utf-8'))
assert sys.version_info[:3]==(3,12,14) and zlib.ZLIB_RUNTIME_VERSION=='1.3.2','Use accepted compression runtime Python 3.12.14 / zlib 1.3.2'
sha=lambda b:hashlib.sha256(b).hexdigest()
def payload(name):
    return json.loads(zlib.decompress(b''.join(f.read_bytes() for f in sorted((root/name).glob('*.part')))))
def baseline(name,digest):
    if a.baseline_directory:
        path=Path(a.baseline_directory)/name
        if not path.exists():path=Path(a.baseline_directory)/('baseline-'+name)
        data=path.read_bytes()
    else:
        url='https://github.com/1196197579-a11y/XiaoMeili-Updates/releases/download/v0.10.0.9.4.2/'+name
        with urllib.request.urlopen(url,timeout=120) as r:data=r.read()
    assert sha(data)==digest,('Baseline hash mismatch',name)
    return data
import io
with zipfile.ZipFile(io.BytesIO(baseline('XiaoMeili_V0.10.0.9.4.2_SourceProject.zip',proof['baseline_source_sha256']))) as z:
    source={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
patch=payload('source-delta-accepted-compact');assert patch['baseline_sha256']==proof['baseline_source_sha256']
source.update({n:base64.b64decode(b) for n,b in patch['files'].items()})
def writezip(path,entries,compression):
    with zipfile.ZipFile(path,'x',compression,compresslevel=6 if compression==zipfile.ZIP_DEFLATED else None) as z:
        for name,data in sorted(entries.items()):
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o600<<16;info.compress_type=compression;z.writestr(info,data)
source_zip=out/'XiaoMeili_V0.10.0.9.4.3_SourceProject.zip';writezip(source_zip,source,zipfile.ZIP_STORED)
assert sha(source_zip.read_bytes())==patch['source_sha256']
with zipfile.ZipFile(io.BytesIO(baseline('XiaoMeili_0.10.0.9.4.2_update.zip',proof['baseline_update_sha256']))) as z:
    bundle={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
old=bundle['XiaoMeili.exe'];delta=payload('exe-delta-accepted-compact');assert sha(old)==delta['baseline_sha256']
exe=b''.join(old[o['copy'][0]:sum(o['copy'])] if 'copy' in o else base64.b64decode(o['data']) for o in delta['ops'])
assert sha(exe)==delta['target_sha256']==proof['main_exe_sha256'] and len(exe)==delta['target_size']
bundle['XiaoMeili.exe']=exe;bundle['_internal/assets/VERSION.txt']=b'0.10.0.9.4.3'
bundle['_internal/assets/XiaoMeili_V0.10.0.9.4.3_SourceProject.zip']=source_zip.read_bytes()
update=out/'XiaoMeili_0.10.0.9.4.3_update.zip';writezip(update,bundle,zipfile.ZIP_DEFLATED)
for name,expected in proof['assets'].items():
    f=out/name;assert f.stat().st_size==expected['size'] and sha(f.read_bytes())==expected['sha256'],name
    with zipfile.ZipFile(f) as z:assert z.testzip() is None
(out/'candidate.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('ACCEPTED_BYTES_REASSEMBLED_AND_HASH_VERIFIED')
