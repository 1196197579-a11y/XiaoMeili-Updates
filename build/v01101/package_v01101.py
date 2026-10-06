import argparse, hashlib, json, os, zipfile
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--source',required=True)
p.add_argument('--bundle',required=True)
p.add_argument('--out',required=True)
p.add_argument('--version',required=True)
p.add_argument('--source-zip')
a=p.parse_args()
source=Path(a.source); bundle=Path(a.bundle); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def zip_tree(root,dst):
    root=Path(root)
    with zipfile.ZipFile(dst,'x',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            rel=path.relative_to(root).as_posix()
            if rel.startswith('/') or '..' in Path(rel).parts: raise RuntimeError(rel)
            z.write(path,rel)
    with zipfile.ZipFile(dst,'r') as z:
        bad=z.testzip()
        if bad: raise RuntimeError(f'CRC failure: {bad}')

version_file=bundle/'_internal/assets/VERSION.txt'
if not version_file.is_file() or version_file.read_text(encoding='utf-8-sig').strip()!=a.version:
    raise SystemExit('Bundle VERSION.txt mismatch')
if not (bundle/'XiaoMeili.exe').is_file(): raise SystemExit('Bundle XiaoMeili.exe missing')
ffmpeg=list((bundle/'_internal/imageio_ffmpeg').rglob('ffmpeg*.exe'))
if not ffmpeg: raise SystemExit('Bundled imageio_ffmpeg binary missing')
if not (source/'app/src/video_import_alpha.py').is_file(): raise SystemExit('Source Alpha helper missing')
main=(source/'app/src/main.py').read_text(encoding='utf-8')
if f'APP_VERSION = "{a.version}"' not in main or 'convert_transparent_webm_to_webp' not in main:
    raise SystemExit('Source version/Alpha integration mismatch')

source_zip=out/f'XiaoMeili_V{a.version}_SourceProject.zip'
update_zip=out/f'XiaoMeili_{a.version}_update.zip'
if a.source_zip:
    prebuilt=Path(a.source_zip)
    if not prebuilt.is_file(): raise SystemExit('Prebuilt source archive missing')
    with zipfile.ZipFile(prebuilt,'r') as z:
        bad=z.testzip()
        if bad: raise SystemExit(f'Prebuilt source ZIP CRC failure: {bad}')
    source_zip.write_bytes(prebuilt.read_bytes())
else:
    zip_tree(source,source_zip)
embedded=bundle/'_internal/assets'/source_zip.name
embedded.parent.mkdir(parents=True,exist_ok=True)
if embedded.exists(): raise SystemExit('Refusing to overwrite embedded source archive')
embedded.write_bytes(source_zip.read_bytes())
zip_tree(bundle,update_zip)
meta={
    'version':a.version,
    'all_pass':True,
    'update':{'name':update_zip.name,'sha256':sha(update_zip),'size':update_zip.stat().st_size},
    'source':{'name':source_zip.name,'sha256':sha(source_zip),'size':source_zip.stat().st_size},
    'runtime':{
        'exe_sha256':sha(bundle/'XiaoMeili.exe'),
        'version_file':version_file.read_text(encoding='utf-8-sig').strip(),
        'ffmpeg_asset_count':len(ffmpeg),
        'ffmpeg_assets':[x.relative_to(bundle).as_posix() for x in ffmpeg],
    },
    'safety':{
        'baseline':'0.11.0',
        'append_only_native_updater':True,
        'user_source_media_read_only':True,
        'user_files_deleted':False,
    }
}
(out/'build-metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(meta,ensure_ascii=False))
