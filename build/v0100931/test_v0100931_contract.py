# -*- coding: utf-8 -*-
import ast, os, sys, time
from pathlib import Path


def main():
    root=Path(sys.argv[1]).resolve()
    main_p=root/'app'/'src'/'main.py'
    diag_p=root/'app'/'src'/'resource_diagnostic_v0100931.py'
    speech_p=root/'app'/'src'/'speech_input.py'
    req_p=root/'app'/'requirements.txt'
    texts={}
    for k,p in [('main',main_p),('diag',diag_p),('speech',speech_p)]:
        s=p.read_text(encoding='utf-8-sig'); ast.parse(s,filename=str(p)); texts[k]=s
    req=req_p.read_text(encoding='utf-8-sig')
    combined='\n'.join(texts.values())+'\n'+req
    required=[
        'APP_VERSION = "0.10.0.9.3.1"',
        'resource_diagnostic_v0100931',
        'def _event(self, event_name, **payload)',
        'CHAT_ROUNDS = 30','BASELINE_SECONDS = 60','FINAL_COOLDOWN_SECONDS = 90',
        'pynvml','self._gpu_source = "unavailable"','XiaoMeiliGpuSamplerV0100931',
        '_hidden_subprocess_kwargs','CREATE_NO_WINDOW','nvidia-smi-hidden',
        'self._proc_handles','_preflight_self_test','SAMPLE_INTERVAL_SECONDS - elapsed',
        '测试中止，已生成故障报告','nvidia-ml-py>=12,<14',
        'timeline_250ms.csv','round_ledger.csv','stage_summary.csv','vram_jump_events.csv','process_tree.csv',
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError('contract missing: '+token)
    if 'def _event(self, kind, **payload)' in texts['diag']:
        raise RuntimeError('duplicate-kind event signature still present')
    if 'next_t += SAMPLE_INTERVAL_SECONDS' in texts['diag']:
        raise RuntimeError('catch-up sampler still present')
    # Every diagnostic nvidia-smi call must go through the hidden helper.
    if texts['diag'].count('subprocess.check_output([') != 2:
        raise RuntimeError('unexpected subprocess GPU query count')
    if texts['diag'].count('**self._hidden_subprocess_kwargs()') != 2:
        raise RuntimeError('GPU fallback is not fully hidden')
    # ASR diagnostic worker already had CREATE_NO_WINDOW; preserve it.
    if 'diagnostic_process_v01005' not in texts['speech'] or 'creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)' not in texts['speech']:
        raise RuntimeError('ASR diagnostic worker hidden-window guard missing')
    # New diagnostic itself must never delete/move user files.
    for bad in ('shutil.rmtree','os.remove','unlink(','Path.unlink','shutil.move','Remove-Item','robocopy'):
        if bad in texts['diag']:
            raise RuntimeError('unsafe diagnostic token: '+bad)

    # Runtime mini check: the exact API that failed in V0.10.0.9.3 must work.
    sys.path.insert(0,str(root/'app'/'src'))
    try:
        from PySide6.QtCore import QCoreApplication
        app=QCoreApplication.instance() or QCoreApplication([])
    except Exception:
        import types
        class _DummySignal:
            def __init__(self,*a,**k): self._slots=[]
            def connect(self,fn): self._slots.append(fn)
            def disconnect(self,fn=None): self._slots.clear()
            def emit(self,*a,**k):
                for fn in list(self._slots):
                    try: fn(*a,**k)
                    except Exception: pass
        class _DummyQObject:
            def __init__(self,*a,**k): pass
        qtcore=types.ModuleType("PySide6.QtCore")
        qtcore.QObject=_DummyQObject; qtcore.Signal=lambda *a,**k:_DummySignal()
        pyside=types.ModuleType("PySide6"); pyside.QtCore=qtcore
        sys.modules["PySide6"]=pyside; sys.modules["PySide6.QtCore"]=qtcore
    from resource_diagnostic_v0100931 import ResourceDiagnosticRunnerV2
    runner=ResourceDiagnosticRunnerV2({},None,None,None,None,None,root,root,'0.10.0.9.3.1')
    runner._started=time.monotonic(); runner._stage='contract'
    runner._event('round_start',kind='whiteboard',index=1)
    rec=runner._round_start('whiteboard',1)
    if rec.get('kind')!='whiteboard':
        raise RuntimeError('round event runtime contract failed')
    runner._rounds.clear()
    # CPU sampler should reuse handles and become non-zero under real work.
    runner._process_rows(); time.sleep(0.15)
    end=time.monotonic()+0.25
    x=0
    while time.monotonic()<end:
        x=(x*33+7)%10000019
    rows=runner._process_rows()
    root_rows=[r for r in rows if int(r.get('pid') or 0)==os.getpid()]
    if not root_rows:
        raise RuntimeError('CPU sampler did not include current process')
    if float(root_rows[0].get('cpu_percent') or 0.0)<=0.0:
        raise RuntimeError('CPU sampler still reports zero after warmup/workload')
    if os.name=='nt' and int(runner._hidden_subprocess_kwargs().get('creationflags',0) or 0)==0:
        raise RuntimeError('Windows hidden subprocess creation flag missing')
    runner._disconnect_service_signals()
    print('V0100931_RUNTIME_CONTRACT_PASS')

if __name__=='__main__':
    main()