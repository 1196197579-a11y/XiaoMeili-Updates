"""Reassemble the locally tested EXE and packages; no rebuild or installation."""
import argparse,base64,hashlib,io,json,sys,urllib.request,zipfile,zlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('--baseline-directory');a=p.parse_args()
root=Path(a.root);out=Path(a.out);out.mkdir(exist_ok=False,parents=True)
proof=json.loads((root/'candidate.json').read_text())
assert sys.version_info[:3]==(3,12,10) and zlib.ZLIB_RUNTIME_VERSION==proof['zlib'], 'Accepted Python/zlib runtime required'
sha=lambda b:hashlib.sha256(b).hexdigest()
raw=b''.join(f.read_bytes() for f in sorted((root/'accepted-payload').glob('*.part')))
assert sha(raw)==proof['payload_sha256']
patch=json.loads(zlib.decompress(raw))
def baseline(name,digest,local_name):
    if a.baseline_directory:b=(Path(a.baseline_directory)/local_name).read_bytes()
    else:
        url='https://github.com/1196197579-a11y/XiaoMeili-Updates/releases/download/v0.10.0.9.4.3/'+name
        with urllib.request.urlopen(url,timeout=180) as r:b=r.read()
    assert sha(b)==digest,name
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        assert z.testzip() is None
        return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}
def writezip(path,entries,compression):
    with zipfile.ZipFile(path,'x',compression,compresslevel=6 if compression==zipfile.ZIP_DEFLATED else None) as z:
        for name,b in sorted(entries.items()):
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o600<<16;info.compress_type=compression;z.writestr(info,b)
source=baseline('XiaoMeili_V0.10.0.9.4.3_SourceProject.zip',proof['baseline_source_sha256'],'baseline-source943.zip')
source.update({n:base64.b64decode(b) for n,b in patch['source'].items()})
src=out/'XiaoMeili_V0.11.0_SourceProject.zip';writezip(src,source,zipfile.ZIP_STORED)
bundle=baseline('XiaoMeili_0.10.0.9.4.3_update.zip',proof['baseline_update_sha256'],'baseline-update943.zip')
bundle.update({n:base64.b64decode(b) for n,b in patch['runtime'].items()})
assert sha(bundle['XiaoMeili.exe'])==proof['main_exe_sha256']
bundle['_internal/assets/XiaoMeili_V0.11.0_SourceProject.zip']=src.read_bytes()
update=out/'XiaoMeili_0.11.0_update.zip';writezip(update,bundle,zipfile.ZIP_DEFLATED)
for name,v in proof['assets'].items():
    f=out/name;assert f.stat().st_size==v['size'] and sha(f.read_bytes())==v['sha256'],name
    with zipfile.ZipFile(f) as z:assert z.testzip() is None
(out/'candidate.json').write_text(json.dumps(proof,indent=2))
print('V0110_ACCEPTED_BYTES_REASSEMBLED_AND_VERIFIED',flush=True)
