import argparse,hashlib,json,urllib.request,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--tag',required=True);p.add_argument('--out',required=True);a=p.parse_args()
root=Path(a.root);out=Path(a.out);out.mkdir(exist_ok=False,parents=True)
meta=json.loads((root/'candidate.json').read_text());results=[]
for name,value in meta['assets'].items():
    url='https://github.com/1196197579-a11y/XiaoMeili-Updates/releases/download/'+a.tag+'/'+name
    path=out/name;digest=hashlib.sha256()
    with urllib.request.urlopen(url,timeout=180) as source,path.open('xb') as target:
        while chunk:=source.read(2**20):target.write(chunk);digest.update(chunk)
    assert digest.hexdigest()==value['sha256'] and path.stat().st_size==value['size'],name
    with zipfile.ZipFile(path) as z:assert z.testzip() is None
    results.append(dict(url=url,sha256=digest.hexdigest(),size=path.stat().st_size,passed=True))
(out/'public-readback.json').write_text(json.dumps(dict(all_pass=True,tag=a.tag,assets=results),indent=2))
print(json.dumps(dict(all_pass=True,tag=a.tag,assets=results)),flush=True)
