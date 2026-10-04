import subprocess,uuid,json,hashlib,sys
from pathlib import Path
exe=Path(sys.argv[1] if len(sys.argv)>1 else 'candidate-package942/XiaoMeili.exe').resolve()
base=Path('acceptance942').resolve()
results=[]
for flag in ('--runtime-self-test','--settings-ui-self-test'):
    run=base/('selftest_'+uuid.uuid4().hex)
    proc=subprocess.Popen([str(exe),'--resource-e2e',str(run),flag],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try: code=proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(); raise RuntimeError(flag+' exceeded 90 seconds')
    result={'test':flag,'exit_code':code,'pass':code==0,'run_directory':str(run)}
    results.append(result)
    print(json.dumps(result),flush=True)
    assert code==0,result
with (base/'selftests.json').open('x') as f:json.dump({'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'results':results},f,indent=2)
