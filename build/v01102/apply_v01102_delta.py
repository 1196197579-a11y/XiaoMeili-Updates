from pathlib import Path
import hashlib, sys

p = Path(sys.argv[1]).resolve()
raw = p.read_bytes()
input_sha = hashlib.sha256(raw).hexdigest()
expected_in = '84c03b6ec60969f87874077188a3bf6e32e91124e749cffe48ca7437982538c3'
expected_out = 'e26b2943105e507ff9165fc87c1afe51905d6bd87e9a6af994c8cd16498afa10'
if input_sha != expected_in:
    raise SystemExit(f'V01102 input main mismatch: {input_sha}')
s = raw.decode('utf-8')

def once(old, new, label):
    global s
    n=s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    s=s.replace(old,new,1)

once(
    'APP_NAME = "小美丽 V0.11.0.1｜动作库透明 WebM"\nAPP_VERSION = "0.11.0.1"\nAPP_UPDATE_VERSION = "0.11.0.1"',
    'APP_NAME = "小美丽 V0.11.0.2｜透明 WebM + 更新桌面零落地"\nAPP_VERSION = "0.11.0.2"\nAPP_UPDATE_VERSION = "0.11.0.2"',
    'version bump')

once(
    '    p.mkdir(parents=True, exist_ok=True)\n    return p\n\n\nDESKTOP_ERROR_LOG',
    '''    p.mkdir(parents=True, exist_ok=True)
    return p


def _path_is_inside(child: Path, parent: Path) -> bool:
    """True when child is parent itself or is below it; read-only path check."""
    try:
        child_resolved = Path(child).expanduser().resolve()
        parent_resolved = Path(parent).expanduser().resolve()
        child_resolved.relative_to(parent_resolved)
        return True
    except Exception:
        return False


def validate_update_ndm_download_root(path_value) -> Path:
    """Reject Desktop as an NDM *update* landing zone.

    NDM chooses its own save directory. XiaoMeili must never solve a Desktop
    leftover by deleting it afterwards, so an update is stopped before the NDM
    task is submitted when the configured NDM folder is Desktop (or below it).
    Diagnostic ZIPs explicitly requested by the user are unaffected.
    """
    root = Path(str(path_value or "")).expanduser()
    if _path_is_inside(root, desktop_dir()):
        raise RuntimeError(
            "为避免更新压缩包出现在桌面，本次更新已在发送给 NDM 前停止。"
            "请先把 NDM 的 Default download folder 改到非桌面目录，并在小美丽中选择同一目录后重试。"
            "小美丽不会删除、移动或覆盖桌面上的任何现有文件。"
        )
    return root


DESKTOP_ERROR_LOG''',
    'desktop guard')

once(
    '                ndm_dir = Path(ndm_dir_raw) if ndm_dir_raw else Path.home() / "Downloads"\n\n                if mode == "ndm" and ndm_dir.exists():',
    '                ndm_dir = Path(ndm_dir_raw) if ndm_dir_raw else Path.home() / "Downloads"\n'
    '                if mode == "ndm":\n'
    '                    # V0.11.0.2: never let an update task land on Desktop and never\n'
    '                    # clean it afterwards. Refuse before NDM receives the URL.\n'
    '                    ndm_dir = validate_update_ndm_download_root(ndm_dir)\n\n'
    '                if mode == "ndm" and ndm_dir.exists():',
    'ndm guard call')

out=s.encode('utf-8')
out_sha=hashlib.sha256(out).hexdigest()
if out_sha != expected_out:
    raise SystemExit(f'V01102 output main mismatch: {out_sha}')
p.write_bytes(out)
print(f'V01102_MAIN_DELTA_OK {out_sha}')
