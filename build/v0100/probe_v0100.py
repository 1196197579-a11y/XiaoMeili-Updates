# -*- coding: utf-8 -*-
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: probe_v0100.py <source_root>")
main=Path(sys.argv[1])/"app/src/main.py"
s=main.read_text(encoding="utf-8")
terms=[
    "class PetWindow(QWidget):",
    "class SettingsDialog(QDialog):",
    "class AppController(QObject):",
    "def contextMenuEvent(self, event):",
    "def mousePressEvent(self, event):",
    "def mouseMoveEvent(self, event):",
    "def play_state(self, state",
    "def __init__(self, cfg",
    "self.pet=PetWindow",
    "self.pet = PetWindow",
    "def open_settings",
    "self.hotkeys.register(cfg); self.pet.show()",
    "def _on_speech",
    "def _begin_speech_session",
]
for term in terms:
    print("\n===== TERM",term,"=====")
    pos=0
    count=0
    while count<5:
        i=s.find(term,pos)
        if i<0: break
        a=max(0,i-1800); b=min(len(s),i+7000)
        print(s[a:b])
        pos=i+len(term); count+=1
