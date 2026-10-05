from pathlib import Path
import urllib.request,hashlib,tarfile,subprocess
url='https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
expected='7c45c9622400d578709a9b2cddbe8124cc21d382409d9f13406d706d28e31b14'
root=Path('ci-python943').resolve();root.mkdir(exist_ok=False)
archive=root/'python.tar.gz';digest=hashlib.sha256()
with urllib.request.urlopen(url,timeout=120) as r,archive.open('xb') as f:
    while chunk:=r.read(2**20):f.write(chunk);digest.update(chunk)
assert digest.hexdigest()==expected,'CI interpreter distribution hash mismatch'
with tarfile.open(archive) as tar:
    for item in tar.getmembers():assert (root/item.name).resolve().is_relative_to(root)
    tar.extractall(root,filter='data')
exe=root/'python/python.exe'
subprocess.run([str(exe),'-c','import sys,zlib; assert sys.version_info[:3]==(3,12,14) and zlib.ZLIB_RUNTIME_VERSION=="1.3.2"'],check=True)
print(str(exe))
