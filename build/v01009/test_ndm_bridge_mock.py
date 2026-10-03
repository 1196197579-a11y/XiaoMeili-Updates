# -*- coding: utf-8 -*-
"""Integration test for XiaoMeili's NDM WebSocket bridge.

This does not fake the bridge call itself: it starts a protocol-compatible local
WebSocket endpoint on NDM's real port/subprotocol, then exercises
test_connection() + download_and_import() end to end.
"""
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

PAYLOAD = (b"XiaoMeili-NDM-integration-test-" * 8192)

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_ndm_bridge_mock.py <source_root>")
    source_root=Path(sys.argv[1]).resolve()
    sys.path.insert(0,str(source_root/"app"/"src"))
    from ndm_bridge import test_connection, download_and_import

    base=Path(tempfile.mkdtemp(prefix="xm_ndm_test_"))
    downloads=base/"Downloads"
    local=base/"LocalAppData"
    public=base/"Public"
    downloads.mkdir(parents=True,exist_ok=False)
    (local/"XiaoMeiliApp"/"updates").mkdir(parents=True,exist_ok=False)
    (public/"XiaoMeiliData").mkdir(parents=True,exist_ok=False)
    os.environ["LOCALAPPDATA"]=str(local)
    os.environ["PUBLIC"]=str(public)

    received=[]
    stop=threading.Event()

    async def handler(ws, path):
        try:
            msg=await ws.recv()
        except Exception:
            return
        received.append(str(msg))
        filename=""
        for line in str(msg).splitlines():
            if line.startswith("4:"):
                filename=line[2:].strip()
                break
        if not filename:
            return
        # NDM writes the requested final name into its configured download folder.
        target=downloads/Path(filename).name
        with target.open("xb") as f:
            f.write(PAYLOAD)

    async def server_loop():
        from websockets.server import serve
        async with serve(
            handler,"127.0.0.1",10007,
            subprotocols=["neatextension.v1"],
        ):
            while not stop.is_set():
                await asyncio.sleep(0.05)

    def runner():
        asyncio.run(server_loop())

    t=threading.Thread(target=runner,daemon=True)
    t.start()
    time.sleep(0.8)

    ok,msg=test_connection(timeout=2.0)
    if not ok:
        raise RuntimeError("NDM handshake failed: "+str(msg))

    filename="XiaoMeili_NDM_bridge_test.bin"
    dest=local/"XiaoMeiliApp"/"updates"/"bridge_test.part"
    out=download_and_import(
        url="https://example.invalid/XiaoMeili_NDM_bridge_test.bin",
        filename=filename,
        download_root=downloads,
        destination=dest,
        min_bytes=1024,
        expected_bytes=len(PAYLOAD),
        timeout_seconds=30,
    )
    source_file=downloads/filename
    if not received or "1:GET" not in received[-1] or f"4:{filename}" not in received[-1]:
        raise RuntimeError("NDM task message was not delivered using expected protocol")
    if Path(out).read_bytes()!=PAYLOAD:
        raise RuntimeError("Imported NDM payload mismatch")
    if not source_file.is_file() or source_file.read_bytes()!=PAYLOAD:
        raise RuntimeError("NDM source file was moved/deleted/changed")
    stop.set()
    t.join(timeout=2)
    print("NDM_INTEGRATION_PASS")
    print("handshake=PASS task_submit=PASS file_detect=PASS import_copy=PASS source_retained=PASS")

if __name__=="__main__":
    main()
