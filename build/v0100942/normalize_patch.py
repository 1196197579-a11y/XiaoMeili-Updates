from pathlib import Path
import sys,json
source,build=map(Path,sys.argv[1:])
for name in json.loads((build/'expected-source.json').read_text()):
    p=source/name
    if p.exists():p.write_text(p.read_text(encoding='utf-8-sig'),encoding='utf-8',newline='\n')
p=build/'changes.diff'
p.write_text(p.read_text(encoding='utf-8-sig'),encoding='utf-8',newline='\n')
