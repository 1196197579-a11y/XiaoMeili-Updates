from pathlib import Path
import subprocess, sys
if len(sys.argv) != 4: raise SystemExit(2)
delta=Path(sys.argv[1]); main=Path(sys.argv[2]); native=Path(sys.argv[3])
for p in (main,native):
    p.write_bytes(p.read_bytes().decode('utf-8').replace('\r\n','\n').encode('utf-8'))
subprocess.check_call([sys.executable,str(delta),str(main),str(native)])
print('V011032_NORMALIZED_DELTA_OK')
