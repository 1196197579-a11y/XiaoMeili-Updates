"""Packaged app acceptance; never treats partial or simulated service runs as pass."""
import argparse,atexit,csv,hashlib,json,os,subprocess,time,uuid,zipfile
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('exe'); p.add_argument('--mode',choices=['normal','crash'],default='normal')
args=p.parse_args()
exe=Path(args.exe).resolve()
root=Path('acceptance942').resolve(); root.mkdir(exist_ok=True)
run=root/(args.mode+'_'+uuid.uuid4().hex)
env=dict(os.environ)
if args.mode=='crash': env['XM_RESOURCE_E2E_CRASH']='1'
else: env.pop('XM_RESOURCE_E2E_CRASH',None)
print('Starting packaged '+args.mode+' acceptance in '+str(run),flush=True)
host=subprocess.Popen([str(exe),'--resource-e2e',str(run)],env=env,
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
def cleanup_test_host():
    if host.poll() is None:
        host.terminate(); host.wait(timeout=10)
atexit.register(cleanup_test_host)
endpoint=run/'XiaoMeiliData'/('post_completion.json' if args.mode=='normal' else 'crash_host.json')
deadline=time.monotonic()+390
while time.monotonic()<deadline and host.poll() is None and not endpoint.exists():
    time.sleep(0.2)
assert endpoint.exists() and host.poll() is None,('Host died or timed out before acceptance endpoint',host.poll())
code=None
if args.mode=='normal':
    health=json.loads(endpoint.read_text(encoding='utf-8'))
    assert health['ui_value']==100 and health['button_enabled'] and not health['tts_active'],health
    assert health['monitor_exit_code']==0,health
    result_path=run/'XiaoMeiliData/e2e_result.json'
    if not result_path.exists():
        print('FAIL: no result, host exit='+str(code),flush=True); raise SystemExit(31)
    result=json.loads(result_path.read_text(encoding='utf-8'))
    assert result['ok'],result.get('message')
    values=[x['ui_value'] for x in result['progress']]
    assert 1 in values and 2 in values,values
    session=Path(result['session'])
    trace=[x['state'] for x in result['startup_trace']]
    for step in ('runner_created','runner_started','session_created','monitor_path_found','monitor_process_started','monitor_ready','waiting_for_ui_progress','ui_progress_visible','test_started'):
        assert step in trace,(step,trace)
    events=json.loads((session/'events.json').read_text(encoding='utf-8'))
    stages={e.get('stage') for e in events if e.get('event')=='stage'}
    # Stage is also persisted in the status journal; this checks actual execution.
    statuses=[json.loads(l) for l in (session/'live_status.jsonl').read_text(encoding='utf-8').splitlines()]
    stages|={x.get('stage') for x in statuses}
    assert {'preflight','baseline','animation','whiteboard','asr','brain','tts'}<=stages,stages
    assert any(e.get('event')=='asr_diagnostic_ready' and e.get('ready') for e in events)
    assert any(e.get('event')=='brain_result' and e.get('ok') for e in events)
    assert any(e.get('event')=='tts_result' and e.get('ok') for e in events)
    summary=json.loads((session/'external_monitor_summary.json').read_text(encoding='utf-8'))
    assert summary['samples']>10 and summary['host_crashed'] is False
    report=Path(result['report'])
    with zipfile.ZipFile(report) as z:
        assert z.testzip() is None
        assert 'external_timeline_250ms.csv' in z.namelist()
        assert 'summary.json' in z.namelist()
    validation={'pass':True,'mode':args.mode,'host_alive_10_seconds_after_test':True,'cleanup':'external harness terminates its own isolated host after validation','exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                'report':str(report),'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),
                'stages':sorted(stages),'samples':summary['samples'],'trace':trace,'ui_progress':values}
else:
    crash_record=run/'XiaoMeiliData/crash_host.json'
    crash=json.loads(crash_record.read_text(encoding='utf-8'))
    assert crash['ready'] and crash['pid']==host.pid,crash
    host.kill(); code=host.wait(timeout=10)
    assert code!=0,code
    session=Path(crash['session'])
    deadline=time.monotonic()+60
    report_pointer=session/'external_report_path.txt'
    while time.monotonic()<deadline and not report_pointer.exists(): time.sleep(0.2)
    assert report_pointer.exists(),'External monitor did not produce crash ZIP'
    report=Path(report_pointer.read_text(encoding='utf-8').strip())
    with zipfile.ZipFile(report) as z:
        assert z.testzip() is None
        summary=json.loads(z.read('external_monitor_summary.json'))
        assert summary['host_crashed'] and summary['samples']>0,summary
    validation={'pass':True,'mode':'crash','host_exit':code,'host_pid':crash['pid'],
                'monitor_pid':summary['monitor_pid'],'report':str(report),
                'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
with (run/'validated.json').open('x',encoding='utf-8') as f:json.dump(validation,f,indent=2,ensure_ascii=False)
print(json.dumps(validation,ensure_ascii=True),flush=True)
