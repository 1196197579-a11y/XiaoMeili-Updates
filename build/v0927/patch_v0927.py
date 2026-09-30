# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0927.py <source_root>")

root=Path(sys.argv[1]).resolve()
main=root/"app/src/main.py"
speech=root/"app/src/speech_input.py"
version_file=root/"app/assets/VERSION.txt"
s=main.read_text(encoding="utf-8")

if 'APP_VERSION = "0.9.2.6"' not in s:
    raise RuntimeError("V0.9.2.7 expected V0.9.2.6 base")

s=s.replace('APP_VERSION = "0.9.2.6"','APP_VERSION = "0.9.2.7"',1)
s=s.replace('APP_NAME = "小美丽 V0.9.2.6｜Voice Interaction"','APP_NAME = "小美丽 V0.9.2.7｜Voice Interaction"',1)
s=s.replace("自动存储清理已禁用：V0.9.2.6 不会自动删除任何文件。","自动存储清理已禁用：V0.9.2.7 不会自动删除任何文件。",1)
s=s.replace('"config_version": 22,','"config_version": 23,',1)

# ------------------------------------------------------------------
# 1) Fix V0.9.2.6 exact-asset Test crash.
# QListWidget is already single-selection by default. The explicit line used
# QAbstractItemView without importing it, which caused the runtime NameError.
# Removing the redundant call avoids a new dependency and keeps behavior intact.
# ------------------------------------------------------------------
bad='        lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)\n'
if bad not in s:
    raise RuntimeError("V0.9.2.7 expected QAbstractItemView crash line missing")
s=s.replace(bad,'',1)

# ------------------------------------------------------------------
# 2) Forward-compatible user-config carry-through.
# Previous load_config only copied top-level keys that already existed in
# default_config(). Extension blocks added by later versions, especially
# highlight_cta and settings_ui, were silently dropped at the next process
# start/update. Preserve every non-special top-level user key verbatim; the
# schema-aware sections below still receive their existing migration logic.
# ------------------------------------------------------------------
old_general='''    # General fields.
    for k, v in old_data.items():
        if k in ("hotkeys", "assets", "vision", "mouse_interaction", "voice", "speech", "whiteboard", "brain", "updates"):
            continue
        if k in cfg:
            cfg[k] = v
'''
new_general='''    # General fields + forward-compatible extension blocks.
    # User-created feature state must survive EXE/version replacement even when
    # a later feature was not yet added to default_config() in the old base.
    _schema_sections = {
        "hotkeys", "assets", "vision", "mouse_interaction",
        "voice", "speech", "whiteboard", "brain", "updates",
    }
    for k, v in old_data.items():
        if k in _schema_sections:
            continue
        cfg[k] = v
'''
if old_general not in s:
    raise RuntimeError("V0.9.2.7 load_config general-field anchor missing")
s=s.replace(old_general,new_general,1)

old_return='''    cfg.setdefault("updates", {})["manifest_url"] = "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest_safe.json"

    return cfg
'''
new_return='''    cfg.setdefault("updates", {})["manifest_url"] = "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest_safe.json"
    # Mark the migrated file as the current schema only after all old values
    # have been carried through. This does not remove any unknown user fields.
    try:
        cfg["config_version"] = max(23, int(cfg.get("config_version", 0) or 0))
    except Exception:
        cfg["config_version"] = 23

    return cfg
'''
if old_return not in s:
    raise RuntimeError("V0.9.2.7 load_config return anchor missing")
s=s.replace(old_return,new_return,1)

# ------------------------------------------------------------------
# 3) High-glow user text now saves itself immediately.
# In V0.9.2.6, imported videos were saved explicitly, but editing the CTA text
# pool only changed the widget until another unrelated setting happened to
# trigger Settings.apply(). Debounce-save only this block so future updates,
# restarts and crashes do not revert the user's lines.
# ------------------------------------------------------------------
method_anchor='''    def _v0926_choose_and_test_asset(self,state):
'''
if method_anchor not in s:
    raise RuntimeError("V0.9.2.7 highlight save method anchor missing")

save_methods=r'''    def _v0927_save_highlight_ui_now(self):
        try:
            hcfg=self.cfg.setdefault("highlight_cta",{})
            if hasattr(self,"highlight_enabled"):
                hcfg["enabled"]=bool(self.highlight_enabled.isChecked())
            if hasattr(self,"highlight_min_kills"):
                hcfg["min_kills"]=int(self.highlight_min_kills.value())
            if hasattr(self,"highlight_board_text"):
                hcfg["board_text"]=str(self.highlight_board_text.text() or "").strip()
            if hasattr(self,"highlight_phrases"):
                values=[
                    x.strip() for x in self.highlight_phrases.toPlainText().splitlines()
                    if x.strip()
                ]
                hcfg["phrases"]=values
            save_config(self.cfg)
            try:
                self.config_changed.emit()
            except Exception:
                pass
        except Exception:
            LOGGER.exception("V0.9.2.7 保存高光设置失败")

    def _v0927_schedule_highlight_save(self,*_):
        timer=getattr(self,"_v0927_highlight_save_timer",None)
        if timer is not None:
            timer.start(260)

'''
s=s.replace(method_anchor,save_methods+method_anchor,1)

timer_anchor='''        self._v774_apply_timer = QTimer(self)
        self._v774_apply_timer.setSingleShot(True)
        self._v774_apply_timer.timeout.connect(self._v774_apply_now)

        for editor in self.hk_editors.values():
'''
timer_new='''        self._v774_apply_timer = QTimer(self)
        self._v774_apply_timer.setSingleShot(True)
        self._v774_apply_timer.timeout.connect(self._v774_apply_now)

        # Dedicated high-glow persistence. These controls were introduced after
        # the original auto-save list, so they need their own debounce timer.
        self._v0927_highlight_save_timer = QTimer(self)
        self._v0927_highlight_save_timer.setSingleShot(True)
        self._v0927_highlight_save_timer.timeout.connect(self._v0927_save_highlight_ui_now)
        for _w,_sig in (
            (getattr(self,"highlight_enabled",None),"toggled"),
            (getattr(self,"highlight_min_kills",None),"valueChanged"),
            (getattr(self,"highlight_board_text",None),"textChanged"),
            (getattr(self,"highlight_phrases",None),"textChanged"),
        ):
            if _w is not None:
                try:
                    getattr(_w,_sig).connect(self._v0927_schedule_highlight_save)
                except Exception:
                    LOGGER.warning("连接高光自动保存信号失败: %s",_sig,exc_info=True)

        for editor in self.hk_editors.values():
'''
if timer_anchor not in s:
    raise RuntimeError("V0.9.2.7 auto-save timer anchor missing")
s=s.replace(timer_anchor,timer_new,1)

# ------------------------------------------------------------------
# 4) Safety invariants.
# ------------------------------------------------------------------
checks=[
    'APP_VERSION = "0.9.2.7"',
    '"config_version": 23,',
    'cfg[k] = v',
    'def _v0927_save_highlight_ui_now',
    'self._v0927_highlight_save_timer',
    'hcfg["phrases"]=values',
    'from native_updater import install_update_package',
    'install_update_package(',
]
for token in checks:
    if token not in s:
        raise RuntimeError("V0.9.2.7 verification missing: "+token)

if 'QAbstractItemView.SelectionMode.SingleSelection' in s:
    raise RuntimeError("V0.9.2.7 QAbstractItemView crash path still present")

# The native updater must remain versioned/no-delete and must not regress to the
# legacy PowerShell/robocopy update handoff.
method_start=s.find("    def install_latest_async(self):")
method_end=s.find("\n\ndef _path_size_bytes",method_start)
if method_start<0 or method_end<0:
    raise RuntimeError("V0.9.2.7 updater method missing")
update_method=s[method_start:method_end]
for forbidden in ('powershell.exe','update_helper.ps1','robocopy','/MIR','/PURGE'):
    if forbidden in update_method:
        raise RuntimeError("V0.9.2.7 updater regression: "+forbidden)

# Removing a high-glow video from the UI must continue to be list-only. No file
# unlink/rmtree is allowed in that user action.
a=s.find("    def _v0911_remove_highlight_video(self):")
b=s.find("\n    def _v0911_save_highlight_editor_state",a)
if a<0 or b<0:
    raise RuntimeError("V0.9.2.7 highlight remove method missing")
remove_block=s[a:b]
for forbidden in ("unlink(","rmtree(","os.remove(","Path.remove("):
    if forbidden in remove_block:
        raise RuntimeError("V0.9.2.7 highlight removal would delete a file: "+forbidden)

main.write_text(s,encoding="utf-8")
py_compile.compile(str(main),doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.6 语音诊断日志","小美丽 V0.9.2.7 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech),doraise=True)

version_file.write_text("0.9.2.7\n",encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.7 crash fix + durable user config")
