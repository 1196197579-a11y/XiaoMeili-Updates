# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys
import shutil

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v01009.py <source_root> <repo_root>")

root=Path(sys.argv[1]).resolve()
repo=Path(sys.argv[2]).resolve()
src=root/"app"/"src"
main=src/"main.py"
diag_src=repo/"build"/"v01009"/"resource_diagnostic_v01009.py"
diag_dst=src/"resource_diagnostic_v01009.py"

def read(p):
    return p.read_text(encoding="utf-8-sig")

def write(p,s):
    p.write_text(s,encoding="utf-8",newline="\n")

def replace_once(s, old, new, label):
    if old not in s:
        raise RuntimeError(f"{label}: anchor missing")
    return s.replace(old,new,1)

if not main.is_file():
    raise RuntimeError("main.py missing")
s=read(main)
if 'APP_VERSION = "0.10.0.8"' not in s:
    raise RuntimeError("V0.10.0.9 patch requires V0.10.0.8 baseline")

# New real-match diagnostic module. Copy only; never remove the previous module.
shutil.copyfile(diag_src,diag_dst)

s=replace_once(
    s,
    "from resource_diagnostic_v01008 import ResourceDiagnosticRunner",
    "from resource_diagnostic_v01009 import ResourceDiagnosticRunner",
    "diagnostic import",
)
s=replace_once(
    s,
    'APP_NAME = "小美丽 V0.10.0.8｜Full Resource Diagnostic + Voice Interrupt"',
    'APP_NAME = "小美丽 V0.10.0.9｜Real Match Diagnostic + NDM Preferred"',
    "app name",
)
s=replace_once(s,'APP_VERSION = "0.10.0.8"','APP_VERSION = "0.10.0.9"',"app version")
s=replace_once(s,'APP_UPDATE_VERSION = "0.10.0.8"','APP_UPDATE_VERSION = "0.10.0.9"',"update version")

old_bypass='''                # V0.10.0.2: official GitHub Release packages bypass NDM.
                # Some Windows/NDM combinations report a socket error on GitHub
                # redirects even though the built-in HTTPS downloader succeeds.
                if mode == "ndm" and "github.com/" in url.lower() and "/releases/download/" in url.lower():
                    mode = "builtin"
                    self.progress_changed.emit(
                        0,
                        "GitHub 更新包自动使用小美丽内置下载器，跳过 NDM 套接字兼容问题…",
                    )
'''
new_bypass='''                # V0.10.0.9: NDM is the preferred downloader for every update URL,
                # including GitHub Release assets. We first perform a real local
                # WebSocket handshake with NDM and submit the task only when the
                # bridge is reachable. Built-in HTTPS remains a fallback only.
'''
s=replace_once(s,old_bypass,new_bypass,"remove GitHub NDM bypass")

old_note='''        note = QLabel(
            "提示：上方 GPU/显存仍显示整机占用。V0.10.0.8 会先记录你点击测试时的真实状态，"
            "再隔离白板、画面识别、语音输入、云端大脑与云端TTS；当前画面识别本身已经共享一个 ScreenGrabber。"
        )'''
new_note='''        note = QLabel(
            "提示：上方 GPU/显存仍显示整机占用。V0.10.0.9 会先等待并记录一整局真实 VALORANT 对局，"
            "再自动隔离测试白板、语音输入、云端大脑与云端TTS；识别链继续共享一个 ScreenGrabber。"
        )'''
s=replace_once(s,old_note,new_note,"resource note")

old_desc='''        diag_desc = QLabel(
            "完全无人值守：当前真实状态 → 隔离基线 → 白板动画 → 全部现有画面识别 → "
            "FSMN-VAD + Fun-ASR-Nano-2512 → 云端 Qwen3-8B → 云端复刻TTS → 综合压力 → 冷却。"
            "250ms采样并记录进程树/显存/识别耗时，结束后桌面自动生成脱敏ZIP。"
            "最好保持无畏契约已打开；无需你说话或操作游戏。云端链路阶段会产生极少量真实测试用量。"
        )'''
new_desc='''        diag_desc = QLabel(
            "实战采集模式：点击一次后切回 VALORANT，正常打一局即可。检测到真实对局 HUD 后自动开始，"
            "整局记录显存/CPU/RAM、进程、屏幕采集与识别事件；检测到赛后结算后，自动继续测试 "
            "FSMN-VAD + Fun-ASR-Nano-2512、云端 Qwen3-8B、云端复刻TTS、白板与赛后综合压力。"
            "你不需要故意掉血、击杀或死亡；本局没发生的识别事件会明确标记为“未观察到”。"
        )'''
s=replace_once(s,old_desc,new_desc,"diagnostic description")

s=replace_once(
    s,
    'self.v01005_diag_status.setText("正在准备全模块深度资源诊断，请不要关闭小美丽…")',
    'self.v01005_diag_status.setText("诊断已启动：请切回 VALORANT 正常打一局；检测到真实 HUD 后会自动采集…")',
    "diagnostic start status",
)

# Bump schema marker without discarding any unknown/user fields.
s=s.replace('cfg["config_version"] = max(28, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(29, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 28','cfg["config_version"] = 29')

write(main,s)
(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9\n",encoding="ascii")

for p in (main,diag_dst):
    py_compile.compile(str(p),doraise=True)

main_text=read(main)
diag_text=read(diag_dst)
checks=[
    ('APP_VERSION = "0.10.0.9"',main_text),
    ("resource_diagnostic_v01009",main_text),
    ("NDM is the preferred downloader for every update URL",main_text),
    ("GitHub 更新包自动使用小美丽内置下载器",main_text,False),
    ("waiting_real_match",diag_text),
    ("real_match_coverage.csv",diag_text),
    ("vram_jump_events.csv",diag_text),
    ("windows-gpu-counter",diag_text),
    ("不保存用户聊天",diag_text),
]
for item in checks:
    needle=item[0]; hay=item[1]; expected=(item[2] if len(item)>2 else True)
    present=needle in hay
    if present != expected:
        raise RuntimeError(f"verification failed: {needle} expected={expected} present={present}")

print("V0.10.0.9 patch PASS")
