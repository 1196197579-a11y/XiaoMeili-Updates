import argparse, hashlib, re
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--target', required=True)
p.add_argument('--patch', required=True)
p.add_argument('--expected-sha256', required=True)
a=p.parse_args()

target=Path(a.target)
patch=Path(a.patch)
src=target.read_text(encoding='utf-8').splitlines(keepends=True)
pl=patch.read_text(encoding='utf-8').splitlines(keepends=True)

hunk_re=re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
i=0
while i < len(pl) and not pl[i].startswith('@@ '): i += 1
out=[]; src_pos=0; hunk_no=0
while i < len(pl):
    m=hunk_re.match(pl[i])
    if not m: raise SystemExit(f'bad hunk header: {pl[i]!r}')
    old_start=int(m.group(1)); old_count=int(m.group(2) or '1')
    new_count=int(m.group(4) or '1')
    expected_pos=old_start-1
    if expected_pos < src_pos: raise SystemExit('overlapping hunks')
    out.extend(src[src_pos:expected_pos]); src_pos=expected_pos
    i += 1; seen_old=0; seen_new=0; hunk_no += 1
    while i < len(pl) and not pl[i].startswith('@@ '):
        line=pl[i]
        if line.startswith('\\ No newline at end of file'):
            i += 1; continue
        if not line: raise SystemExit('empty patch record')
        kind=line[0]; body=line[1:]
        if kind in (' ', '-'):
            if src_pos >= len(src) or src[src_pos] != body:
                got = '<EOF>' if src_pos >= len(src) else src[src_pos]
                raise SystemExit(f'hunk {hunk_no} mismatch at source line {src_pos+1}: expected {body!r}, got {got!r}')
            seen_old += 1
            if kind == ' ': out.append(src[src_pos]); seen_new += 1
            src_pos += 1
        elif kind == '+':
            out.append(body); seen_new += 1
        else:
            raise SystemExit(f'unsupported patch record: {line!r}')
        i += 1
    if seen_old != old_count or seen_new != new_count:
        raise SystemExit(f'hunk {hunk_no} count mismatch old={seen_old}/{old_count} new={seen_new}/{new_count}')
out.extend(src[src_pos:])
raw=''.join(out).encode('utf-8')
digest=hashlib.sha256(raw).hexdigest()
if digest.lower() != a.expected_sha256.lower():
    raise SystemExit(f'patched main sha mismatch: {digest}')
target.write_bytes(raw)
print(f'V01101_MAIN_DELTA_OK {digest}')
