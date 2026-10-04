# -*- coding: utf-8 -*-
import ast, io, os, sys, tempfile, time, wave
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    main_p = root/'app'/'src'/'main.py'
    diag_p = root/'app'/'src'/'resource_diagnostic_v0100932.py'
    speech_p = root/'app'/'src'/'speech_input.py'
    texts = {}
    for k,p in [('main',main_p),('diag',diag_p),('speech',speech_p)]:
        s=p.read_text(encoding='utf-8-sig'); ast.parse(s, filename=str(p)); texts[k]=s
    combined='\n'.join(texts.values())
    required=[
        'APP_VERSION = "0.10.0.9.3.2"','resource_diagnostic_v0100932',
        'wave.open(str(path), "wb")','wave.open(str(path), "rb")','FileExistsError',
        'wav_probe_pass','diagnostic_input.wav','XiaoMeiliGpuSamplerV0100932',
        'def _event(self, event_name, **payload)','CREATE_NO_WINDOW','nvidia-smi-hidden',
        'self._proc_handles','_preflight_self_test','SAMPLE_INTERVAL_SECONDS - elapsed',
        '测试中止，已生成故障报告','CHAT_ROUNDS = 30','FINAL_COOLDOWN_SECONDS = 90'
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError('contract missing: '+token)
    if 'wave.open(str(path), "xb")' in texts['diag']:
        raise RuntimeError('unsupported xb wave mode still present')
    if texts['diag'].index('wav_path = self._make_test_wav') > texts['diag'].index('self._set_stage("baseline"'):
        raise RuntimeError('WAV preflight still happens after baseline')
    for bad in ('shutil.rmtree','os.remove','unlink(','Path.unlink','shutil.move','Remove-Item','robocopy'):
        if bad in texts['diag']:
            raise RuntimeError('unsafe diagnostic token: '+bad)

    sys.path.insert(0, str(root/'app'/'src'))
    try:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
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
        qtcore=types.ModuleType('PySide6.QtCore')
        qtcore.QObject=_DummyQObject; qtcore.Signal=lambda *a,**k:_DummySignal()
        pyside=types.ModuleType('PySide6'); pyside.QtCore=qtcore
        sys.modules['PySide6']=pyside; sys.modules['PySide6.QtCore']=qtcore

    from resource_diagnostic_v0100932 import ResourceDiagnosticRunnerV2

    class _Sig:
        def connect(self,*a,**k): pass
        def disconnect(self,*a,**k): pass
    class _Brain:
        generation_finished=_Sig()
    class _Voice:
        playback_started=_Sig(); playback_finished=_Sig()
    class _FakeProc:
        def __init__(self):
            self.pid=os.getpid(); self.stdout=io.StringIO('XMEVENT|{"event":"diag_ready"}\n'); self._done=False
        def poll(self): return 0 if self._done else None
        def terminate(self): self._done=True
        def wait(self,timeout=None): self._done=True; return 0
    class _Speech:
        def __init__(self): self.called=[]
        def diagnostic_process_v01005(self,wav_path,repeat=3,hold_seconds=25):
            self.called.append((str(wav_path),int(repeat),int(hold_seconds)))
            return _FakeProc()
        def current_state(self): return ('standby','')
    speech=_Speech()
    runner=ResourceDiagnosticRunnerV2({},_Brain(),_Voice(),speech,None,None,root,root,'0.10.0.9.3.2')
    runner._started=time.monotonic(); runner._stage='contract'

    tmp=Path(tempfile.mkdtemp(prefix='xm0932_wav_'))
    wav=tmp/'probe.wav'
    out=runner._make_test_wav(wav)
    if Path(out)!=wav or not wav.is_file(): raise RuntimeError('WAV file not created')
    with wave.open(str(wav),'rb') as wf:
        if wf.getnchannels()!=1: raise RuntimeError('WAV channels mismatch')
        if wf.getsampwidth()!=2: raise RuntimeError('WAV sample width mismatch')
        if wf.getframerate()!=16000: raise RuntimeError('WAV rate mismatch')
        if wf.getnframes()<80000: raise RuntimeError('WAV frame count too small')
    try:
        runner._make_test_wav(wav)
    except FileExistsError:
        pass
    else:
        raise RuntimeError('WAV no-overwrite guard failed')

    proc=runner._start_asr_diagnostic(wav,repeat=1,hold_seconds=1)
    if proc is None or not speech.called:
        raise RuntimeError('ASR diagnostic entry smoke failed')
    runner._terminate_proc(proc)

    runner._event('round_start',kind='whiteboard',index=1)
    rec=runner._round_start('whiteboard',1)
    if rec.get('kind')!='whiteboard': raise RuntimeError('round event contract failed')
    runner._disconnect_service_signals()
    print('V0100932_WAV_ASR_CONTRACT_PASS')

if __name__=='__main__':
    main()