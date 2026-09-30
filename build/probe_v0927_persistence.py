# -*- coding: utf-8 -*-
from pathlib import Path
import sys,re
p=Path(sys.argv[1])/"app/src/main.py"
s=p.read_text(encoding="utf-8")
terms=[
    "CONFIG_FILE =",
    "def load_config",
    "def save_config",
    "def default_config",
    "DEFAULT_CONFIG",
    "def xiaomeili_logical_data_root",
    "highlight_cta",
    "DATA_DIR =",
    "XiaoMeiliData",
]
for term in terms:
    print("\n===== TERM",term,"=====")
    pos=0
    shown=0
    while True:
        i=s.find(term,pos)
        if i<0 or shown>=12: break
        print("\n---",i,"---")
        print(s[max(0,i-2500):i+6500])
        pos=i+len(term)
        shown+=1
