import argparse, hashlib, json, time, urllib.request, zipfile
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument('--metadata',required=True); p.add_argument('--out',required=True); a=p.parse_args()
meta=json.loads(Path(a.metadata).read_text(encoding='utf-8-sig'))
version=meta['version']; repo='1196197579-a11y/XiaoMeili-Updates'; evidence=[]
for key in ('update','source'):
    item=meta[key]; name=item['name']
    url=f'https://github.com/{repo}/releases/download/v{version}/{name}'
    data=None; last=None
    for attempt in range(8):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'XiaoMeili-public-readback/1.0'})
            with urllib.request.urlopen(req,timeout=180) as r: data=r.read()
            break
        except Exception as exc:
            last=exc; time.sleep(5+attempt*2)
    if data is None: raise SystemExit(f'public download failed: {name}: {last}')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=item['sha256'] or len(data)!=item['size']:
        raise SystemExit(f'public hash/size mismatch: {name}')
    temp=Path(a.out).with_name(name); temp.write_bytes(data)
    with zipfile.ZipFile(temp,'r') as z:
        bad=z.testzip()
        if bad: raise SystemExit(f'public ZIP CRC failure: {name}: {bad}')
    temp.unlink(missing_ok=True)
    evidence.append({'name':name,'url':url,'sha256':digest,'size':len(data),'passed':True})
result={'all_pass':True,'version':version,'assets':evidence}
Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
