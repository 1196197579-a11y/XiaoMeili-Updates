# -*- coding: utf-8 -*-
import os, sys, tempfile, time
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: test_ndm_fast_fallback_v010092.py <source_root>')
    source_root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(source_root / 'app' / 'src'))
    import ndm_bridge

    base = Path(tempfile.mkdtemp(prefix='xm092_ndm_realname_'))
    downloads = base / 'Downloads'; downloads.mkdir()
    local = base / 'LocalAppData'; public = base / 'Public'
    (local / 'XiaoMeiliApp' / 'updates').mkdir(parents=True)
    (public / 'XiaoMeiliData').mkdir(parents=True)
    os.environ['LOCALAPPDATA'] = str(local)
    os.environ['PUBLIC'] = str(public)

    ndm_bridge.test_connection = lambda timeout=3: (True, 'mock connected')

    # Real NDM behavior: ignore requested field-4 filename and write URL basename.
    payload = b'NDM-real-name-' * 4096
    requested = 'XiaoMeili_0.10.0.10_123456_update.zip'
    remote_name = 'XiaoMeili_0.10.0.9.2_update.zip'
    def send_download(url, filename, mime='application/octet-stream'):
        (downloads / remote_name).write_bytes(payload)
    ndm_bridge.send_download = send_download

    dest = local/'XiaoMeiliApp'/'updates'/'update.part'
    out = ndm_bridge.download_and_import(
        url='https://example.invalid/' + remote_name,
        filename=requested,
        download_root=downloads,
        destination=dest,
        min_bytes=1,
        expected_bytes=len(payload),
        timeout_seconds=10,
        appearance_timeout_seconds=2.0,
        stall_timeout_seconds=2.0,
    )
    if Path(out).read_bytes() != payload:
        raise RuntimeError('NDM URL-basename import payload mismatch')
    src = downloads / remote_name
    if not src.exists() or src.read_bytes() != payload:
        raise RuntimeError('NDM source file was moved/deleted/changed')
    print('NDM_REAL_FILENAME_PASS')

    # No file at all must still fall back quickly.
    ndm_bridge.send_download = lambda *args, **kwargs: None
    started = time.time()
    try:
        ndm_bridge.download_and_import(
            url='https://example.invalid/missing.zip',
            filename='unique_missing_name.zip',
            download_root=downloads,
            destination=local/'XiaoMeiliApp'/'updates'/'missing.part',
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
