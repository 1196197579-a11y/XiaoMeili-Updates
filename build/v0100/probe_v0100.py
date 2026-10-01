# -*- coding: utf-8 -*-
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: probe_v0100.py <source_root> <repo_root>")
source=Path(sys.argv[1])
repo=Path(sys.argv[2])
s=(source/"app/src/main.py").read_text(encoding="utf-8")
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
out=[]
for term in terms:
    out.append("\n===== TERM "+term+" =====\n")
    pos=0
    count=0
    while count<6:
        i=s.find(term,pos)
        if i<0: break
        a=max(0,i-2000); b=min(len(s),i+9000)
        out.append(s[a:b])
        out.append("\n---\n")
        pos=i+len(term); count+=1
(repo/"build/v0100/probe_output.txt").write_text("".join(out),encoding="utf-8")
print("wrote probe_output.txt", len("".join(out)))
