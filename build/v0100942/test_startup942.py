import sys,time,json,zipfile,threading,uuid
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication
source=Path(sys.argv[1] if len(sys.argv)>1 else 'candidate-v0100942').resolve()
sys.path.insert(0,str(source/'app/src'))
from resource_diagnostic_v0100934 import ResourceDiagnosticRunnerV2, recover_interrupted_resource_diagnostics
app=QCoreApplication([])
base=Path('startup-fault-tests_'+uuid.uuid4().hex); base.mkdir(exist_ok=False)
results=[]
for kind in ('journal_exception','monitor_blocked','ui_progress_unacknowledged'):
    service=SimpleNamespace()
    runner=ResourceDiagnosticRunnerV2({},service,service,service,None,None,base/kind,base/kind/'reports','0.10.0.9.4.2')
    got=[]
    runner.finished.connect(lambda ok,path,message:got.append((ok,path,message)))
    if kind=='journal_exception':
        def bad(): raise AttributeError("injected journal failure")
        runner._open_live_journals=bad
    elif kind=='monitor_blocked':
        runner._start_watchdog=lambda:time.sleep(14)
    else:
        runner._start_watchdog=lambda:True
    t=time.monotonic(); runner.start()
    while not got and time.monotonic()-t<12:
        app.processEvents(); time.sleep(0.01)
    assert got and not got[0][0], (kind,got)
    path=Path(got[0][1]); assert path.is_file()
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        payload=json.loads(z.read('startup_failure.json'))
        assert payload['ok'] is False
    assert time.monotonic()-t<10.5, (kind,time.monotonic()-t)
    results.append({'case':kind,'elapsed':time.monotonic()-t,'report':str(path),'failed_step':payload['failed_step']})
orphan=base/'recovery/diagnostics/resource/v0100942_orphan'; orphan.mkdir(parents=True)
(orphan/'live_status.jsonl').write_text('{"state":"running"}\n')
recovered=recover_interrupted_resource_diagnostics(base/'recovery',base/'recovered','0.10.0.9.4.2')
assert len(recovered)==1 and (orphan/'live_status.jsonl').is_file()
(base/'results.json').write_text(json.dumps(results,indent=2))
print('STARTUP_EXCEPTION_AND_10_SECOND_TIMEOUT_REPORT_PASS')
print('INTERRUPTED_RECOVERY_PATH_PASS')
