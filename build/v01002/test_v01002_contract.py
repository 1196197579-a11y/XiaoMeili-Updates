from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'app/src/main.py').read_text(encoding='utf-8')
SIDEBAR = (ROOT / 'app/src/ability_sidebar.py').read_text(encoding='utf-8')
NDM = (ROOT / 'app/src/ndm_bridge.py').read_text(encoding='utf-8')
BRAIN = (ROOT / 'app/src/brain_qwen.py').read_text(encoding='utf-8')
NATIVE = (ROOT / 'app/src/native_updater.py').read_text(encoding='utf-8')

assert 'APP_VERSION = "0.10.0.2"' in MAIN
assert 'APP_UPDATE_VERSION = "0.10.0.2"' in MAIN
assert (ROOT / 'app/assets/VERSION.txt').read_text(encoding='ascii').strip() == '0.10.0.2'

# Vector panel only: no screenshot panel background in runtime sidebar.
for num, name in (("01","美丽锁定"),("02","美丽洞察"),("03","二成功力"),("04","五成功力"),("05","美丽之神")):
    assert f'"{num}", "{name}"' in SIDEBAR
for forbidden in ('ability_panel_reference_v0100.png', '_panel_pixmap', 'BEAUTY LINK', '"LOCK"', '"INSIGHT"', '"MAX"'):
    assert forbidden not in SIDEBAR, forbidden
assert 'QLinearGradient' in SIDEBAR
assert 'addRoundedRect' in SIDEBAR
assert 'self._paint_sweep_dot(p, panel_path, self._sweep_phase)' in SIDEBAR
assert 'self._paint_sweep_dot(p, panel_path, (self._sweep_phase + 0.5) % 1.0)' in SIDEBAR
assert 'self._sweep_timer.setInterval(33)' in SIDEBAR
assert 'self._sweep_timer.start()' in SIDEBAR
assert 'self._sweep_timer.stop()' in SIDEBAR
assert 'hover_entered = Signal()' in SIDEBAR and 'hover_left = Signal()' in SIDEBAR

# Uploaded ability video is bundled as an animated transparent WebP, not a static PNG.
form = ROOT / 'app/assets/xiaomeili_ability_form_v01002.webp'
assert form.is_file() and form.stat().st_size > 1_000_000
head = form.read_bytes()[:32]
assert head[:4] == b'RIFF' and head[8:12] == b'WEBP'
data = form.read_bytes()
assert b'ANIM' in data and b'ANMF' in data
assert 'xiaomeili_ability_form_v01002.webp' in MAIN
assert 'xiaomeili_ability_form_v0100.png' not in MAIN
assert '_ability_form_movie = QMovie' in MAIN
assert '_ability_form_movie.setCacheMode(QMovie.CacheMode.CacheNone)' in MAIN
assert 'movie.start()' in MAIN and 'movie.stop()' in MAIN

# Moving mouse away from pet/node/sidebar schedules an automatic close and return.
for token in (
    'self.ability_sidebar.hover_entered.connect(self._on_sidebar_ability_hover_enter)',
    'self.ability_sidebar.hover_left.connect(self._on_sidebar_ability_hover_leave)',
    'def _schedule_close_ability_ui(self, delay_ms=520):',
    'self.ability_sidebar.hide_animated()',
):
    assert token in MAIN, token

# Ability video remains the unique cosmetic visual while the sidebar is open.
assert 'if getattr(self, "_ability_form_requested", False):' in MAIN
assert 'While the ability sidebar is open, dragging moves the whole pet/sidebar' in MAIN

# Five independent ON/OFF interfaces remain available.
for sig in (
    'ability_lock_on','ability_lock_off','ability_insight_on','ability_insight_off',
    'ability_power2_on','ability_power2_off','ability_power5_on','ability_power5_off',
    'ability_god_on','ability_god_off'):
    assert sig in SIDEBAR, sig

# Ability code contains no file deletion/move operations.
for forbidden in ('unlink(', 'rmtree(', 'os.remove(', 'shutil.move(', 'Remove-Item', 'Path.unlink'):
    assert forbidden not in SIDEBAR, forbidden

# Startup auto cleanup remains disabled; NDM adoption remains exact/copy-only.
startup_tail = MAIN[MAIN.index('class AppController'):]
assert 'QTimer.singleShot(9000, lambda: self.brain_service.cleanup_ndm_leftovers' not in startup_tail
m = re.search(r'def cleanup_ndm_leftovers\(self, download_root\):(.*?)(?=\n    def shutdown)', BRAIN, re.S)
assert m
for bad in ('rglob(', '.unlink(', 'shutil.rmtree', 'os.remove(', 'Remove-Item'):
    assert bad not in m.group(1), bad
assert 'root.rglob(' not in NDM
assert 'shutil.move(' not in NDM
assert 'src.unlink(' not in NDM
assert 'shutil.copy2' in NDM

# Native updater remains the no-delete, separate-version installer.
for token in ('never mirrors, purges, removes, unlinks, or recursively deletes files', 'versions', 'active.json'):
    assert token in NATIVE, token

print('V01002_CONTRACT_PASS')

# Official GitHub update packages bypass the NDM socket-error path.
assert 'GitHub 更新包自动使用小美丽内置下载器' in MAIN
assert '"/releases/download/" in url.lower()' in MAIN
