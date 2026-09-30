# -*- coding: utf-8 -*-
from pathlib import Path
import sys
p=Path(sys.argv[1])/"app/src/main.py"
s=p.read_text(encoding="utf-8")
terms=[
    'if __name__ == "__main__"',
    'def main(',
    'QApplication(',
    'AppController(',
    '.exec()',
    'def desktop_dir',
    'class AppController',
    'class SettingsDialog',
    'def install_latest_async',
]
for term in terms:
    print("\n===== TERM",term,"=====")
    pos=0;n=0
    while True:
        i=s.find(term,pos)
        if i<0 or n>=10: break
        print("\n---",i,"---")
        print(s[max(0,i-3500):i+8000])
        pos=i+len(term);n+=1
