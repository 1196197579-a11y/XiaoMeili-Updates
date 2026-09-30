# -*- coding: utf-8 -*-
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit("usage: test_v0927_contract.py <source_root>")
root=Path(sys.argv[1]).resolve()
main=(root/"app/src/main.py").read_text(encoding="utf-8")

required=[
    'APP_VERSION = "0.9.2.7"',
    '"config_version": 23,',
    'def _v0927_save_highlight_ui_now',
    'self._v0927_highlight_save_timer',
    'hcfg["phrases"]=values',
    'from native_updater import install_update_package',
]
for token in required:
    if token not in main:
        raise RuntimeError("missing V0.9.2.7 contract token: "+token)

if 'QAbstractItemView.SelectionMode.SingleSelection' in main:
    raise RuntimeError("V0.9.2.6 QAbstractItemView crash path remains")

# Verify the top-level config carry-through is no longer gated by "if k in cfg".
start=main.index("def load_config():")
end=main.index("\ndef save_config",start)
load=main[start:end]
if 'cfg[k] = v' not in load:
    raise RuntimeError("forward-compatible top-level carry-through missing")
if 'if k in cfg:\n            cfg[k] = v' in load:
    raise RuntimeError("old drop-unknown config gate remains")
for token in ('"highlight_cta"','"settings_ui"'):
    # These are intentionally extension blocks, not required in default_config.
    # The generic carry-through is what keeps them durable.
    pass

# Verify the exact Test dialog has no filesystem mutation.
a=main.index("    def _v0926_choose_and_test_asset")
b=main.index("\n    def manage_assets",a)
block=main[a:b]
for forbidden in ("unlink(","rmtree(","os.remove(","shutil.move(","shutil.rmtree("):
    if forbidden in block:
        raise RuntimeError("Test dialog unexpectedly mutates files: "+forbidden)

# Verify the highlight list removal remains non-destructive.
a=main.index("    def _v0911_remove_highlight_video")
b=main.index("\n    def _v0911_save_highlight_editor_state",a)
block=main[a:b]
for forbidden in ("unlink(","rmtree(","os.remove("):
    if forbidden in block:
        raise RuntimeError("Highlight list removal deletes files: "+forbidden)

print("V0.9.2.7 persistence/crash/no-delete contract PASS")
