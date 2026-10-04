# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root=Path(sys.argv[1]).resolve()
src=root/"app"/"src"
main=src/"main.py"

def rd(p): return p.read_text(encoding="utf-8-sig")
def wr(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def rep(s,a,b,name,count=1):
    if a not in s:
        raise RuntimeError("missing patch anchor: "+name)
    return s.replace(a,b,count)

s=rd(main)
if 'APP_VERSION = "0.10.0.9.3.4"' not in s:
    raise RuntimeError("V0.10.0.9.3.4 baseline required")

s=rep(s,
      'APP_NAME = "小美丽 V0.10.0.9.3.4｜Crash-Safe Diagnostic 3.0"',
      'APP_NAME = "小美丽 V0.10.0.9.3.5｜Crash-Safe Diagnostic 3.0 Preflight Fix"',
      'app name')
s=rep(s,'APP_VERSION = "0.10.0.9.3.4"','APP_VERSION = "0.10.0.9.3.5"','app version')
s=rep(s,'APP_UPDATE_VERSION = "0.10.0.9.3.4"','APP_UPDATE_VERSION = "0.10.0.9.3.5"','update version')
s=s.replace('cfg["config_version"] = max(36, int(cfg.get("config_version", 0) or 0))',
            'cfg["config_version"] = max(37, int(cfg.get("config_version", 0) or 0))')
s=s.replace('cfg["config_version"] = 36','cfg["config_version"] = 37')

old='''            elif action=="hard_silence":
                self._hard_silence_now(str(payload.get("phrase") or "闭嘴"))
'''
new='''            elif action=="hard_silence":
                # This settings/controller object does not own _hard_silence_now.
                # Re-inject the recognized phrase through SpeechInputService on
                # the Qt main thread. AppController receives the real
                # utterance_ready signal and executes the production P0 path.
                phrase=str(payload.get("phrase") or "闭嘴")
                self.speech_service.utterance_ready.emit(phrase)
'''
s=rep(s,old,new,'hard silence main-thread routing')

# Keep a concise, non-sensitive error hint in the diagnostic event path by
# preserving the existing main_action_error event and ensuring this route no
# longer references an object method that is not owned by the settings UI.
if 'self._hard_silence_now(str(payload.get("phrase")' in s:
    raise RuntimeError("invalid hard-silence owner call remains")

wr(main,s)
(root/"app"/"assets"/"VERSION.txt").write_text("0.10.0.9.3.5\n",encoding="ascii")
(root/"V0100935_CHANGELOG.txt").write_text("""XiaoMeili V0.10.0.9.3.5

- 修复 V0.10.0.9.3.4 高风险预检在 hard_silence 主线程动作中调用错误对象方法，导致预检立即失败的问题。
- “闭嘴”测试现在从 Qt 主线程通过 SpeechInputService.utterance_ready 注入识别结果，走真实 AppController P0 硬打断链路。
- 保留 Crash-Safe Diagnostic 3.0：Qt 主线程串行化、10秒高风险预检、独立隐藏 Watchdog、实时追加日志、崩溃自动报告。
- 继续保留 NDM 与 FullSafe：不删除、不移动、不覆盖、不递归清理用户文件或任何旧版本。
""",encoding="utf-8")
py_compile.compile(str(main),doraise=True)

combined=rd(main)
for token in [
    'APP_VERSION = "0.10.0.9.3.5"',
    'self.speech_service.utterance_ready.emit(phrase)',
    'Qt.ConnectionType.QueuedConnection',
    '_v0100934_diagnostic_main_action'
]:
    if token not in combined:
        raise RuntimeError("contract missing: "+token)
if 'self._hard_silence_now(str(payload.get("phrase")' in combined:
    raise RuntimeError("broken hard-silence route remains")
print("PATCH_0100935_PASS")
