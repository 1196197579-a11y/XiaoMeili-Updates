import os, sys
from pathlib import Path

root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('.')
main=(root/'app/src/main.py').read_text(encoding='utf-8')
desk=(root/'app/src/desktop_actions.py').read_text(encoding='utf-8')

required_main=[
    'APP_VERSION = "0.11.0.3.1"',
    'IDLE_MAX_ASSETS = 30',
    'def asset_limit(state):',
    'return IDLE_MAX_ASSETS if str(state or "") == "idle" else MAX_ASSETS_PER_STATE',
    'return pool[:asset_limit(state)]',
    '桌面 EXE 自动生成已禁用',
    '不会创建、移动、覆盖或删除桌面文件',
    'validate_update_ndm_download_root',
    'convert_action_video(path,dst,max_width=420,target_fps=12)',
]
for token in required_main:
    if token not in main:
        raise SystemExit(f'main contract missing: {token}')

for forbidden in [
    'target = desktop_dir() / "小美丽.exe"',
    'target.open("xb")',
    "target.open('xb')",
]:
    if forbidden in main:
        raise SystemExit(f'desktop EXE generation still present: {forbidden}')

required_desk=[
    "'exit_chain': '爬出屏幕后接下一支动作'",
    "'fixed': '固定位置播放（视频内部自己动）'",
    'def _qt_object_alive(obj):',
    'def live_panel(self):',
    'def close_panel_safely(self):',
    'WA_DeleteOnClose, False',
    'WindowModal if holder is not None',
]
for token in required_desk:
    if token not in desk:
        raise SystemExit(f'desktop contract missing: {token}')

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(root/'app/src'))
from PySide6.QtWidgets import QApplication, QDialog
import shiboken6
import desktop_actions as da
app=QApplication.instance() or QApplication([])

class Dummy:
    live_panel = da.DesktopController.live_panel
    clear_dead_panel = da.DesktopController.clear_dead_panel
    close_panel_safely = da.DesktopController.close_panel_safely

live=QDialog()
d=Dummy(); d.panel=live
assert d.live_panel() is live
shiboken6.delete(live)
assert not da._qt_object_alive(live)
d.close_panel_safely()
assert d.panel is None

live2=QDialog(); d.panel=live2
d.close_panel_safely()
assert d.panel is None

print('V011031_CONTRACT_OK')
