# -*- coding: utf-8 -*-
import os, sys, tempfile, time
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: test_ndm_fast_fallback_v010092.py <source_root>')
    source_root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(source_root / 'app' / 'src'))
    import ndm_bridge

    base = Path(tempfile.mkdtemp(prefix='xm092_ndm_fast_'))
    downloads = base / 'Downloads'; downloads.mkdir()
    local = base / 'LocalAppData'; public = base / 'Public'
    (local / 'XiaoMeiliApp' / 'updates').mkdir(parents=True)
    (public / 'XiaoMeiliData').mkdir(parents=True)
    os.environ['LOCALAPPDATA'] = str(local)
    os.environ['PUBLIC'] = str(public)

    ndm_bridge.test_connection = lambda timeout=3: (True, 'mock connected')
    ndm_bridge.send_download = lambda *args, **kwargs: None
    started = time.time()
    try:
        ndm_bridge.download_and_import(
            url='https://example.invalid/update.zip',
            filename='update.zip',
            download_root=downloads,
            destination=local/'XiaoMeiliApp'/'updates'/'update.part',
            min_bytes=1,
            expected_bytes=100,
            timeout_seconds=10,
            appearance_timeout_seconds=1.0,
            stall_timeout_seconds=2.0,
        )
    except TimeoutError as exc:
        elapsed = time.time() - started
        if elapsed > 4.0:
            raise RuntimeError(f'NDM fallback too slow: {elapsed:.2f}s') from exc
        print('NDM_FAST_FALLBACK_PASS', f'{elapsed:.2f}s')
        return
    raise RuntimeError('NDM fast fallback did not trigger')

if __name__ == '__main__':
    main()