# -*- coding: utf-8 -*-
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: test_v0100_contract.py <source_root>")

root=Path(sys.argv[1]).resolve()
main=root/"app/src/main.py"
s=main.read_text(encoding="utf-8")

required=[
    'APP_VERSION = "0.10.0"',
    'class AbilitySidebarWindow(QWidget):',
    'class AbilityFormOverlay(QWidget):',
    'class AbilityNodeButton(QPushButton):',
    '("ability_lock", "01", "美丽锁定")',
    '("ability_insight", "02", "美丽洞察")',
    '("ability_power2", "03", "二成功力")',
    '("ability_power5", "04", "五成功力")',
    '("ability_god", "05", "美丽之神")',
    'self._anim.setDuration(260)',
    'self._anim.setDuration(210)',
    'anim.setDuration(165)',
    'def toggle_ability_sidebar(self):',
    'def refresh_ability_sidebar_config(self):',
    'self.v0100_ability_cb = QCheckBox("开启")',
    'QFontDatabase.addApplicationFont(resource("assets/MaokenAbilitySubset.otf"))',
    'QPixmap(resource("assets/ability_form.png"))',
    'static connector: no moving light, no pulse',
]
for token in required:
    if token not in s:
        raise AssertionError("V0.10.0 contract missing: "+token)

for asset,min_size in [
    ("ability_form.png",10_000),
    ("MaokenAbilitySubset.otf",4_000),
]:
    p=root/"app/assets"/asset
    if not p.is_file() or p.stat().st_size<min_size:
        raise AssertionError(f"V0.10.0 asset invalid: {p} size={p.stat().st_size if p.exists() else -1}")

a=s.index("# V0.10.0 美丽能力侧栏")
b=s.index("class PetWindow(QWidget):",a)
block=s[a:b]
for forbidden in (
    "ReadProcessMemory","WriteProcessMemory","OpenProcess","CreateRemoteThread",
    "SendInput","mouse_event","keybd_event","pynput","subprocess.","requests.",
    "os.remove(","unlink(","rmtree(","shutil.rmtree"
):
    if forbidden in block:
        raise AssertionError("Ability sidebar is not UI-only: "+forbidden)

# Existing protected runtime/update invariants must remain in place.
for token in (
    'from native_updater import install_update_package',
    'def ensure_desktop_launcher():',
    'target.open("xb")',
    'cfg[k] = v',
):
    if token not in s:
        raise AssertionError("Existing FullSafe/config invariant regressed: "+token)

print("V0.10.0 ability-sidebar contract PASS")
