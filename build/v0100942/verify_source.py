from pathlib import Path
import sys,json,hashlib
source,expected=map(Path,sys.argv[1:])
for name,digest in json.loads(expected.read_text()).items():
    normalized=(source/name).read_text(encoding='utf-8-sig').encode('utf-8')
    assert hashlib.sha256(normalized).hexdigest()==digest,name
print('EXACT_NORMALIZED_SOURCE_PASS')
