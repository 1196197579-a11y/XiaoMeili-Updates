import importlib.util, sys
from pathlib import Path

root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('.')
main=(root/'app/src/main.py').read_text(encoding='utf-8')
desk=(root/'app/src/desktop_actions.py').read_text(encoding='utf-8')

required_main=[
    'APP_VERSION = "0.11.0.3"',
    'validate_update_ndm_download_root',
    'asset_aliases',
    "menu.addAction('重命名')",
    '不改原文件名、不移动、不覆盖文件',
    'parent_window=dlg',
]
for token in required_main:
    if token not in main: raise SystemExit(f'main contract missing: {token}')
required_desk=[
    "'exit_chain': '爬出屏幕后接下一支动作'",
    "'fixed': '固定位置播放（视频内部自己动）'",
    "self.profile['ending'] in ('chain','exit_chain')",
    'WindowModal if parent_window is not None',
    '下一支动作使用它自己的模板位置和运动方式',
]
for token in required_desk:
    if token not in desk: raise SystemExit(f'desktop contract missing: {token}')

sys.path.insert(0,str(root/'app/src'))
import desktop_actions as da
p=da.normalized({'motion':'fixed','start_x':0.5,'start_y':0.0,'ending':'idle'})
start,end=da.trajectory(p,(0,0,1920,1080),(0,0,1920,1040),(280,280))
if start != end: raise SystemExit('fixed action unexpectedly moves whole window')
if not (810 <= start[0] <= 830 and start[1] == 0): raise SystemExit(f'fixed placement unexpected: {start}')
p=da.normalized({'motion':'edge','edge':'left','direction':'up','ending':'exit_chain','start_y':0.5})
start,end=da.trajectory(p,(0,0,1920,1080),(0,0,1920,1040),(280,280))
if end[1] >= -280: raise SystemExit(f'exit_chain does not fully clear top edge: {end}')
if da.display_name({'asset_aliases':{da.asset_key('C:/x/a.webp'):'美蜘蛛'}},'C:/x/a.webp') != '美蜘蛛':
    raise SystemExit('asset display alias failed')
print('V01103_CONTRACT_OK')
