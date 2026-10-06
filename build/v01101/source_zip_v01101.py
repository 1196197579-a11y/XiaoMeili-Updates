import argparse, hashlib, zipfile
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--source',required=True)
p.add_argument('--out',required=True)
a=p.parse_args()
root=Path(a.source); dst=Path(a.out)
dst.parent.mkdir(parents=True,exist_ok=True)
if dst.exists(): raise SystemExit('Refusing to overwrite source archive')
with zipfile.ZipFile(dst,'x',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel=path.relative_to(root).as_posix()
        if rel.startswith('/') or '..' in Path(rel).parts: raise RuntimeError(rel)
        z.write(path,rel)
with zipfile.ZipFile(dst,'r') as z:
    bad=z.testzip()
    if bad: raise SystemExit(f'Source ZIP CRC failure: {bad}')
h=hashlib.sha256(dst.read_bytes()).hexdigest()
print(f'V01101_SOURCE_ZIP_OK {dst.stat().st_size} {h}')
