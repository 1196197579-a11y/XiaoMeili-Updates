# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "src" / "main.py").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "app" / "src" / "ability_sidebar.py").read_text(encoding="utf-8")

assert 'APP_VERSION = "0.10.0.3"' in MAIN
assert 'APP_UPDATE_VERSION = "0.10.0.3"' in MAIN
assert '"config_version": 25' in MAIN

# Names are user editable but hard-limited to four characters.
assert 'setMaxLength(4)' in MAIN
assert 'display_names' in MAIN
assert 'value[:4]' in SIDEBAR

# User-controlled relative layout.
for token in ('sidebar_scale','form_scale','gap_px','sidebar_y','form_x','form_y'):
    assert token in MAIN
    assert token in SIDEBAR or token in ('form_scale','form_x','form_y')
assert '恢复参考图默认布局' in MAIN
assert '实时预览' in MAIN
assert 'ability_editor_active = Signal(bool)' in MAIN
assert 'def _set_ability_editor_active' in MAIN

# User-supplied Maoken font is privately loaded, never installed system-wide.
assert 'MaokenAssortedSans-Lite(1).otf' in MAIN
assert 'QFontDatabase.addApplicationFont' in SIDEBAR
assert 'font_path' in SIDEBAR
assert 'AddFontResource' not in MAIN + SIDEBAR

# Old character aura must never become visible from ability switches.
assert 'ability_aura.hide()' in MAIN
assert 'self.ability_aura.set_states' not in MAIN

# Five editable phrases + immediate normal VoiceService path + prewarm cache.
for key in ('beauty_lock','beauty_insight','power_20','power_50','beauty_god'):
    assert key in MAIN
assert 'warm_phrase_cache' in MAIN
assert 'tag="ability_feedback"' in MAIN
assert '启用能力语音反馈' in MAIN

# 60fps-ish sweep, only while the sidebar is visible.
assert 'self._sweep_timer.setInterval(16)' in SIDEBAR
assert 'self._sweep_timer.stop()' in SIDEBAR
assert '_paint_sweep_dot' in SIDEBAR
assert '(self._sweep_phase + 0.5)' in SIDEBAR

# Reference polish: brighter outer glow, ON glow and connector node.
assert 'QColor(225, 255, 255, 248)' in SIDEBAR
assert 'QColor(240, 255, 255, 255)' in SIDEBAR
assert 'row_right = panel.right() - 30.0' in SIDEBAR

# Ability sidebar must not contain destructive file operations.
for bad in ('unlink(', 'rmtree(', 'os.remove(', 'shutil.move(', 'Remove-Item'):
    assert bad not in SIDEBAR

print("V01003_CONTRACT_PASS")

# Ability character geometry must not be owned by QStackedLayout.
assert 'self.stack.addWidget(self.ability_form_label)' not in MAIN
assert 'def refresh_ability_form_layout' in MAIN
