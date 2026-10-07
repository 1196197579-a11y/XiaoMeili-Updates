from pathlib import Path
import re, sys, hashlib

if len(sys.argv) != 3:
    raise SystemExit('usage: apply_v011031_hotfix.py MAIN_PY DESKTOP_ACTIONS_PY')

main_path = Path(sys.argv[1]).resolve()
desk_path = Path(sys.argv[2]).resolve()
main = main_path.read_text(encoding='utf-8')
desk = desk_path.read_text(encoding='utf-8')

def sub_once(text, pattern, repl, label, flags=0):
    out, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    return out

# Version.
main = sub_once(main, r'APP_NAME\s*=\s*"[^"]*"', 'APP_NAME = "小美丽 V0.11.0.3.1｜桌面动作模板热修复"', 'app name')
main = sub_once(main, r'APP_VERSION\s*=\s*"0\.11\.0\.3"', 'APP_VERSION = "0.11.0.3.1"', 'app version')
main = sub_once(main, r'APP_UPDATE_VERSION\s*=\s*"0\.11\.0\.3"', 'APP_UPDATE_VERSION = "0.11.0.3.1"', 'update version')

# Only idle grows from 20 to 30.
if 'IDLE_MAX_ASSETS = 30' not in main:
    main = sub_once(
        main,
        r'MAX_ASSETS_PER_STATE\s*=\s*20\s*\n',
        'MAX_ASSETS_PER_STATE = 20\nIDLE_MAX_ASSETS = 30\n\n\ndef asset_limit(state):\n    """Per-state cap. Only idle is expanded in V0.11.0.3.1."""\n    return IDLE_MAX_ASSETS if str(state or "") == "idle" else MAX_ASSETS_PER_STATE\n\n',
        'asset limit helper',
    )

for old, new in [
    ('migrated[:MAX_ASSETS_PER_STATE]', 'migrated[:asset_limit(new_key)]'),
    ('return pool[:MAX_ASSETS_PER_STATE]', 'return pool[:asset_limit(state)]'),
    ('MAX_ASSETS_PER_STATE-len(current)', 'asset_limit(state)-len(current)'),
    ('(current+success)[:MAX_ASSETS_PER_STATE]', '(current+success)[:asset_limit(state)]'),
    ('{len(user)}/{MAX_ASSETS_PER_STATE}', '{len(user)}/{asset_limit(state)}'),
    ("{len(_asset_list(self.cfg['assets'].get(state)))}/{MAX_ASSETS_PER_STATE}", "{len(_asset_list(self.cfg['assets'].get(state)))}/{asset_limit(state)}"),
    ('{len(pool)}/{MAX_ASSETS_PER_STATE}', '{len(pool)}/{asset_limit(state)}'),
    ('{len(vals)}/{MAX_ASSETS_PER_STATE}', '{len(vals)}/{asset_limit(state)}'),
]:
    main = main.replace(old, new)

main = main.replace('每个状态最多 20 支视频', '待机最多 30 支，其余状态最多 20 支视频')
main = main.replace('每个状态最多20支', '待机最多30支，其余状态最多20支')
main = main.replace('最多20支。每次播放完重新独立抽签', '待机最多30支，其余状态最多20支。每次播放完重新独立抽签')
main = main.replace(
    'lab.setToolTip("可一次拖入多支视频；透明 WebM 直读 Alpha，普通视频自动抠绿；都会保留白边/柔光；最多20支。")',
    'limit = asset_limit(state)\n            lab.setToolTip(f"可一次拖入多支视频；透明 WebM 直读 Alpha，普通视频自动抠绿；都会保留白边/柔光；本状态最多{limit}支。")'
)
main = main.replace(
    'f"「{STATE_NAMES[state]}」已经有 20 支视频。请先点“管理”移除不需要的素材。"',
    'f"「{STATE_NAMES[state]}」已经有 {asset_limit(state)} 支视频。请先点“管理”移除不需要的素材。"'
)
main = main.replace(
    'f"\\n\\n素材池最多 20 支，本次有 {overflow} 支因容量限制未导入。"',
    'f"\\n\\n该素材池最多 {asset_limit(state)} 支，本次有 {overflow} 支因容量限制未导入。"'
)

# Disable the historical Desktop/小美丽.exe auto-generator. Never delete the
# already existing launcher; just stop creating new Desktop executables.
main = sub_once(
    main,
    r'def ensure_desktop_launcher\(\):\n.*?\n\ndef main\(\):',
    '''def ensure_desktop_launcher():
    """Desktop EXE auto-generation is permanently disabled.

    Existing Desktop files are intentionally left untouched.
    """
    LOGGER.info("桌面 EXE 自动生成已禁用；不会创建、移动、覆盖或删除桌面文件。")
    return None


def main():''',
    'disable desktop exe generator',
    flags=re.S,
)

# PySide/shiboken lifetime guard for DesktopTemplateDialog.
if 'def _qt_object_alive(' not in desk:
    marker = '\ndef section('
    pos = desk.find(marker)
    if pos < 0:
        raise SystemExit('desktop helper insertion point missing')
    helper = '''

def _qt_object_alive(obj):
    """False for a stale PySide wrapper whose C++ object was deleted."""
    if obj is None:
        return False
    try:
        from shiboken6 import isValid
        return bool(isValid(obj))
    except Exception:
        try:
            obj.objectName()
            return True
        except Exception:
            return False
'''
    desk = desk[:pos] + helper + desk[pos:]

if 'def live_panel(self):' not in desk:
    marker = '    def shutdown(self):\n'
    pos = desk.find(marker)
    if pos < 0:
        raise SystemExit('DesktopController.shutdown missing')
    helper = '''    def live_panel(self):
        """Return a live template dialog and clear stale shiboken wrappers."""
        panel = getattr(self, 'panel', None)
        if panel is not None and not _qt_object_alive(panel):
            self.panel = None
            return None
        return panel

    def clear_dead_panel(self):
        if getattr(self, 'panel', None) is not None and not _qt_object_alive(self.panel):
            self.panel = None

    def close_panel_safely(self):
        panel = self.live_panel()
        self.panel = None
        if panel is not None:
            try:
                panel.close()
            except RuntimeError:
                pass

'''
    desk = desk[:pos] + helper + desk[pos:]

desk = sub_once(
    desk,
    r'    def shutdown\(self\):\n(?:        .*\n)+?\n\nclass DesktopPreview',
    '''    def shutdown(self):
        self.random_timer.stop()
        self.stop(restore=False)
        self.close_panel_safely()


class DesktopPreview''',
    'safe controller shutdown',
)

start_marker = '    def start_test(self):\n'
pos = desk.find(start_marker, desk.find('class DesktopTemplateDialog'))
if pos < 0:
    raise SystemExit('DesktopTemplateDialog.start_test missing')
body = pos + len(start_marker)
if 'if not _qt_object_alive(self):' not in desk[body:body+300]:
    desk = desk[:body] + '        if not _qt_object_alive(self):\n            return\n        self.c.clear_dead_panel()\n' + desk[body:]

desk = desk.replace(
    '        if self.c.panel not in (None,self):\n            self.c.panel.close()\n',
    '''        other_panel = self.c.live_panel()
        if other_panel is not None and other_panel is not self:
            try:
                other_panel.close()
            except RuntimeError:
                self.c.panel = None
''',
    1,
)
desk = desk.replace(
    '        if self.c.panel is self:\n            self.c.restore_idle();self.c.panel=None\n',
    '''        panel = self.c.live_panel()
        if panel is self:
            self.c.restore_idle();self.c.panel=None
''',
    1,
)

# Replace only open_template(), leaving every V0.11.0.3 choreography feature
# above it intact. Keep the V0.11.0.3 parent_window parameter if present.
m = re.search(r'def open_template\(([^\n]*)\):\n(.*)\Z', desk, flags=re.S)
if not m:
    raise SystemExit('open_template missing')
sig = m.group(1)
parent_expr = 'parent_window' if 'parent_window' in sig else 'settings'
new_open = f'''def open_template({sig}):
    paths=settings.pet.desktop_controller.pool()
    if path and Path(path).is_file():paths=[path]+[p for p in paths if p!=path]
    if not paths:
        QMessageBox.information(settings,'桌面动作','请先导入一支桌面动作视频。');return
    controller = settings.pet.desktop_controller
    controller.clear_dead_panel()
    holder = {parent_expr} if {parent_expr} is not None else settings
    existing = getattr(settings, '_desktop_template_dialog', None)
    if existing is not None and _qt_object_alive(existing):
        try:
            existing.show(); existing.raise_(); existing.activateWindow()
            return existing
        except RuntimeError:
            pass
    dlg=DesktopTemplateDialog(settings.cfg,settings.pet,settings.pet.desktop_controller.save,paths,holder,test)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    dlg.setWindowModality(Qt.WindowModality.WindowModal if holder is not None else Qt.WindowModality.NonModal)
    settings._desktop_template_dialog = dlg
    def _clear_template_ref(*_):
        try:
            if getattr(settings, '_desktop_template_dialog', None) is dlg:
                settings._desktop_template_dialog = None
        except Exception:
            pass
        controller.clear_dead_panel()
    dlg.finished.connect(_clear_template_ref)
    dlg.destroyed.connect(_clear_template_ref)
    dlg.show(); dlg.raise_(); dlg.activateWindow()
    return dlg
'''
desk = desk[:m.start()] + new_open

if 'target.open("xb")' in main or "target.open('xb')" in main:
    raise SystemExit('Desktop EXE creation code still present')
if 'WA_DeleteOnClose, False' not in desk or 'def live_panel(self):' not in desk:
    raise SystemExit('template lifetime hardening incomplete')

main_path.write_text(main, encoding='utf-8')
desk_path.write_text(desk, encoding='utf-8')
print('V011031_HOTFIX_OK')
print('MAIN_SHA256', hashlib.sha256(main_path.read_bytes()).hexdigest())
print('DESKTOP_SHA256', hashlib.sha256(desk_path.read_bytes()).hexdigest())
