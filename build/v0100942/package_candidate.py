from pathlib import Path
import hashlib,json,shutil,sys,zipfile
source,bundle,out=map(Path,sys.argv[1:])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
metadata={'version':'0.10.0.9.4.2','publication':'unpublished_candidate','python':'3.12.10',
          'main_exe_sha256':sha(bundle/'XiaoMeili.exe'),'monitor_exe_sha256':sha(bundle/'ResourceMonitor/XiaoMeiliResourceMonitor.exe'),
          'core_source_sha256':{p.name:sha(p) for p in (source/'app/src').glob('*.py')}}
(source/'BUILD_PROVENANCE_V0100942.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
srczip=out/'XiaoMeili_V0.10.0.9.4.2_SourceProject.zip'
with zipfile.ZipFile(srczip,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(source.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
        if p.suffix=='.zip' and 'SourceProject' in p.name:continue
        z.write(p,p.relative_to(source).as_posix())
with srczip.open('rb') as a,(bundle/'_internal/assets'/srczip.name).open('xb') as b:shutil.copyfileobj(a,b)
update=out/'XiaoMeili_0.10.0.9.4.2_update.zip'
with zipfile.ZipFile(update,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(bundle.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(bundle).as_posix())
for p in (srczip,update):
    with zipfile.ZipFile(p) as z:assert z.testzip() is None
metadata['assets']={p.name:{'sha256':sha(p),'size':p.stat().st_size} for p in (srczip,update)}
(out/'candidate.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print(json.dumps(metadata['assets'],indent=2))
