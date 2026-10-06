from pathlib import Path
import json,urllib.request,time
root=Path('build/v0110');m=json.loads((root/'candidate.json').read_text());g=json.loads((root/'local-gates.json').read_text())
assert g['all_local_gates_pass'] and g['main_exe_sha256']==m['main_exe_sha256'] and all(x['passed'] for x in g['gates'])
for directory,tag in (('public-candidate-readback','v0.11.0-rc1'),('public-formal-readback','v0.11.0')):
    evidence=json.loads((Path(directory)/'public-readback.json').read_text())
    assert evidence['all_pass'] and evidence['tag']==tag and len(evidence['assets'])==2
    for item in evidence['assets']:
        name=item['url'].split('/')[-1]
        assert item['sha256']==m['assets'][name]['sha256'] and item['size']==m['assets'][name]['size']
assert json.loads(Path('latest_safe.json').read_text(encoding='utf-8-sig'))['version']=='0.10.0.9.4.3'
v=m['assets']['XiaoMeili_0.11.0_update.zip']
manifest=dict(protocol=1,version='0.11.0',package_url='https://github.com/1196197579-a11y/XiaoMeili-Updates/releases/download/v0.11.0/XiaoMeili_0.11.0_update.zip',sha256=v['sha256'],package_size=v['size'],notes=[
    '新增第8类桌面动作：导入、管理、每支视频独立模板、真实桌面测试',
    '百分比锚点与起点、四方向、速度与预计时间、自然攀爬、五类结束行为、冷却、右侧镜像',
    '真实测试可拖动角色校准并保存；游戏状态立即抢占，恢复角色正常位置，游戏动画结束回到待机',
    '支持游戏中随机桌面动作；测试视频不写入正式素材库',
    '打包EXE真实左右攀爬、三种分辨率几何适配、20次资源释放、完整原功能资源回归通过',
    'NDM优先/HTTPS回退及FullSafe保留；候选与正式源码/更新包均已公开SHA-256回读'])
Path('latest_safe.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('V0110_SAFE_MANIFEST_PREPARED_AFTER_ALL_GATES')
