# -*- coding: utf-8 -*-
import ast, json, os, sys, tempfile, time, zipfile
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    src = root/'app'/'src'
    main_p = src/'main.py'
    diag_p = src/'resource_diagnostic_v0100933.py'
    speech_p = src/'speech_input.py'
    texts = {}
    for k,p in [('main',main_p),('diag',diag_p),('speech',speech_p)]:
        s=p.read_text(encoding='utf-8-sig'); ast.parse(s, filename=str(p)); texts[k]=s
    combined='\n'.join(texts.values())
    required=[
        'APP_VERSION = "0.10.0.9.3.3"','resource_diagnostic_v0100933',
        'recover_interrupted_resource_diagnostics','live_timeline.jsonl','live_events.jsonl',
        'live_rounds.jsonl','live_status.jsonl','finalized.flag',
        'self._open_live_journals()','self._journal_write(self._live_timeline_fp, row)',
        'Riskier child-process/native cleanup happens only after report generation',
        'CREATE_NO_WINDOW','nvidia-smi-hidden','wave.open(str(path), "wb")','wave.open(str(path), "rb")',
        'CHAT_ROUNDS = 30','FINAL_COOLDOWN_SECONDS = 90'
    ]
    for token in required:
        if token not in combined:
            raise RuntimeError('contract missing: '+token)
    if 'pynvml.nvmlShutdown()' in texts['diag']:
        raise RuntimeError('diagnostic still shuts down NVML before/after report')
    for bad in ('shutil.rmtree','os.remove','unlink(','Path.unlink','shutil.move','Remove-Item','robocopy'):
        if bad in texts['diag']:
            raise RuntimeError('unsafe diagnostic token: '+bad)

    sys.path.insert(0, str(src))
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    import resource_diagnostic_v0100933 as mod
    Runner = mod.ResourceDiagnosticRunnerV2

    class Sig:
        def __init__(self): self.slots=[]
        def connect(self,fn): self.slots.append(fn)
        def disconnect(self,fn=None): self.slots=[]
        def emit(self,*a,**k):
            for fn in list(self.slots): fn(*a,**k)
    class Brain:
        def __init__(self): self.generation_finished=Sig(); self._generate_busy=False
    class Voice:
        def __init__(self): self.playback_started=Sig(); self.playback_finished=Sig(); self._cloud_ctx={}
        def cloud_stream_in_progress(self): return False
    class Speech:
        def current_state(self): return ('idle','')
    class Vision:
        last_snapshot={}
    class Pet:
        dialogue_board_active=False; movies=[]; current_state='idle'

    tmp=Path(tempfile.mkdtemp(prefix='xm0933-contract-'))
    data=tmp/'data'; desk=tmp/'desktop'; data.mkdir(); desk.mkdir()
    r=Runner({},Brain(),Voice(),Speech(),Vision(),Pet(),data,desk,'0.10.0.9.3.3')
    r._started=time.monotonic()
    r.session_dir=data/'diagnostics'/'resource'/'v0100933_ci'; r.session_dir.mkdir(parents=True)
    r._open_live_journals()
    r._event('ci_event',ok=True)
    rec=r._round_start('whiteboard',1); r._round_end(rec,True,0)
    r._samples.append({'t':0.0,'stage':'ci','system_cpu_percent':0,'system_ram_percent':0,'app_cpu_percent':0,'app_rss_bytes':1234,'gpu_util_percent':0,'vram_used_mb':0,'vram_total_mb':0,'gpu_temp_c':0,'threads':1,'speech_state':'','brain_busy':False,'tts_active':False,'tts_queue':0,'whiteboard_active':False,'qmovie_slots':0,'pet_state':'idle','vision_phase':'','vision_scan_fps':0,'processes':[],'gpu_processes':[]})
    r._journal_write(r._live_timeline_fp, r._samples[-1])
    r._journal_status('reporting','report')
    r._close_live_journals()
    z=r._write_reports()
    if not Path(z).is_file(): raise RuntimeError('final ZIP not created')
    with zipfile.ZipFile(z,'r') as zf:
        names=set(zf.namelist())
        for req in ('live_timeline.jsonl','live_events.jsonl','live_rounds.jsonl','live_status.jsonl','summary.json'):
            if req not in names: raise RuntimeError('final ZIP missing '+req)
    for req in ('live_timeline.jsonl','live_events.jsonl','live_rounds.jsonl','live_status.jsonl'):
        if not (r.session_dir/req).is_file(): raise RuntimeError('source journal removed: '+req)

    orphan=data/'diagnostics'/'resource'/'v0100933_orphan'; orphan.mkdir()
    (orphan/'live_status.jsonl').write_text(json.dumps({'state':'running','stage':'combined'})+'\n',encoding='utf-8')
    (orphan/'live_events.jsonl').write_text(json.dumps({'event':'stage','stage':'combined'})+'\n',encoding='utf-8')
    (orphan/'speech_diagnostic_worker.log').write_text('safe diagnostic log',encoding='utf-8')
    recovered=mod.recover_interrupted_resource_diagnostics(data,desk,'0.10.0.9.3.3')
    if not recovered: raise RuntimeError('orphan diagnostic was not recovered')
    if not (orphan/'live_events.jsonl').is_file(): raise RuntimeError('recovery moved/deleted source evidence')
    if not (orphan/'recovered.flag').is_file(): raise RuntimeError('recovery marker missing')

    legacy=data/'diagnostics'/'resource'/'v0100932_legacy'; legacy.mkdir()
    (legacy/'speech_diagnostic_worker.log').write_text('legacy safe log',encoding='utf-8')
    recovered2=mod.recover_interrupted_resource_diagnostics(data,desk,'0.10.0.9.3.3')
    if not any('自动恢复' in Path(x).name for x in recovered2):
        raise RuntimeError('legacy orphan recovery failed')
    if not (legacy/'speech_diagnostic_worker.log').is_file(): raise RuntimeError('legacy source log deleted')

    print('V0100933_CRASH_SAFE_CONTRACT_PASS')

if __name__=='__main__':
    main()
