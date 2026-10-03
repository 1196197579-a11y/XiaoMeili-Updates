# -*- coding: utf-8 -*-
import hashlib, json, os, sys, tempfile, zipfile
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: test_fullsafe_no_delete_v010092.py <source_root>')
    source_root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(source_root / 'app' / 'src'))
    from native_updater import install_update_package

    base = Path(tempfile.mkdtemp(prefix='xm092_fullsafe_'))
    local = base / 'LocalAppData'; public = base / 'Public'
    desktop = base / 'Desktop'; downloads = base / 'Downloads'; docs = base / 'Documents'; drive = base / 'D'
    for p in (local, public, desktop, downloads, docs, drive):
        p.mkdir(parents=True, exist_ok=True)
    os.environ['LOCALAPPDATA'] = str(local)
    os.environ['PUBLIC'] = str(public)

    root = local / 'XiaoMeiliApp'; versions = root / 'versions'; versions.mkdir(parents=True)
    (root / 'XiaoMeiliLauncher.exe').write_bytes(b'launcher')
    (root / '.xiaomeili-install.json').write_text(json.dumps({
        'product':'XiaoMeili','schema':2,'install_id':'test',
        'deletion_policy':'NO_AUTOMATIC_FILE_DELETION'
    }), encoding='utf-8')
    old = versions / 'v0.10.0.9.1_old'; (old / '_internal' / 'assets').mkdir(parents=True)
    (old / 'XiaoMeili.exe').write_bytes(b'old')
    (old / '_internal' / 'assets' / 'VERSION.txt').write_text('0.10.0.9.1', encoding='ascii')
    (root / 'active.json').write_text(json.dumps({
        'version':'0.10.0.9.1',
        'relative_exe':(old/'XiaoMeili.exe').relative_to(root).as_posix()
    }), encoding='utf-8')

    sentinels = {}
    for i, p in enumerate((
        desktop/'keep.txt', downloads/'keep.zip', docs/'keep.docx', drive/'keep.bin',
        public/'keep-user.txt', old/'keep-old.txt'
    )):
        p.parent.mkdir(parents=True, exist_ok=True)
        data = f'SENTINEL-{i}'.encode('ascii')
        p.write_bytes(data); sentinels[p] = data

    pkg = base / 'update.zip'
    with zipfile.ZipFile(pkg, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('XiaoMeili.exe', b'newexe')
        zf.writestr('_internal/assets/VERSION.txt', '0.10.0.9.2')
    sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
    result = install_update_package(
        pkg, root, '0.10.0.9.2', sha, current_exe=old/'XiaoMeili.exe',
        log_path=public/'XiaoMeiliData'/'logs'/'update'/'functional-test.log')

    for p, data in sentinels.items():
        if not p.is_file() or p.read_bytes() != data:
            raise RuntimeError(f'user/old file changed or removed: {p}')
    if not (old / 'XiaoMeili.exe').is_file():
        raise RuntimeError('old version was removed')
    if not Path(result['version_dir']).is_dir():
        raise RuntimeError('new append-only version directory missing')
    print('FULLSAFE_NO_DELETE_FUNCTIONAL_PASS')

if __name__ == '__main__':
    main()