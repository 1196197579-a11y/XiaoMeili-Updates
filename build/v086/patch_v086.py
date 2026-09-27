# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def once(text, old, new, label):
    n=text.count(old)
    if n != 1:
        raise RuntimeError(f"V0.8.6 expected one {label}, found {n}")
    return text.replace(old,new,1)


def patch(source_root: Path):
    root=Path(source_root).resolve()
    main=root/"app"/"src"/"main.py"
    voice=root/"app"/"src"/"voice_qwen.py"
    if not main.exists() or not voice.exists():
        raise FileNotFoundError("V0.8.6 expected V0.8.5 source")
    m=main.read_text(encoding="utf-8")
    v=voice.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.5"' not in m:
        raise RuntimeError("V0.8.6 expected APP_VERSION 0.8.5 base")
    m=m.replace('APP_VERSION = "0.8.5"','APP_VERSION = "0.8.6"',1)
    m=m.replace("V0.8.5","V0.8.6")
    v=v.replace("V0.8.5","V0.8.6")

    # ---- 1) Live whiteboard: never freeze the speaking animation.
    old='''    def finish_dialogue_board(self, hold_ms=None):
        if not self.dialogue_board_active:
            return
        self.dialogue_overlay.complete()
        try:
            movie = self.movies[self.current_slot]
            if self.current_state == "dialogue" and movie is not None:
                movie.setPaused(True)
        except Exception:
            pass
        self.dialogue_visual_generation += 1
        generation = self.dialogue_visual_generation
        if hold_ms is None:
            hold_ms = int(self.cfg.get("whiteboard", {}).get("hold_ms", 3000))
        QTimer.singleShot(max(300, int(hold_ms)), lambda g=generation: self._end_dialogue_board(g))
'''
    new='''    def finish_dialogue_board(self, hold_ms=None):
        if not self.dialogue_board_active:
            return
        # V0.8.6: the supplied board clip is a talking animation. Never pause it
        # on the last frame. Keep motion alive until the board is removed.
        self.dialogue_overlay.complete()
        self.dialogue_visual_generation += 1
        generation = self.dialogue_visual_generation
        if hold_ms is None:
            hold_ms = 120
        QTimer.singleShot(max(60, int(hold_ms)), lambda g=generation: self._end_dialogue_board(g))
'''
    m=once(m,old,new,"dynamic dialogue-board finish")

    # Update the internal comment to reflect dynamic looping.
    m=m.replace(
        '''            # The source clip is 15 seconds. Long answers simply restart the
            # talking loop; after TTS finishes finish_dialogue_board() freezes
            # the current frame for the viewer's 3-second reading hold.''',
        '''            # The source clip is 15 seconds. Long answers restart the talking
            # loop. V0.8.6 never freezes the final frame; the clip stays animated
            # until TTS ends and the board is removed.''')

    # Live dialogue no longer uses the old 3-second frozen reading hold.
    old='''        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))
'''
    new='''        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(120)
'''
    m=once(m,old,new,"live board dynamic tail")

    # ---- 2) Continuous conversation: rolling inactivity timeout, never end after one answer.
    helper_anchor='''    def _speech_listen_timeout(self, token):
        if int(token)!=int(self._speech_session_token) or not self._speech_session_active or not self._speech_waiting_question:return
        self._end_speech_session(resume=True)
'''
    helper_new='''    def _arm_speech_followup(self):
        """Resume listening for another turn and start a rolling inactivity timer."""
        if not self._speech_session_active:
            return
        self._speech_waiting_question=True
        self._speech_waiting_brain=False
        self._speech_state("listening","正在听你继续说")
        self.speech_service.resume()
        token=self._speech_session_token
        timeout=max(5000,int(self._speech_cfg().get("listen_timeout_ms",15000)))
        QTimer.singleShot(timeout,lambda t=token:self._speech_listen_timeout(t))

    def _speech_listen_timeout(self, token):
        if int(token)!=int(self._speech_session_token) or not self._speech_session_active or not self._speech_waiting_question:return
        self._end_speech_session(resume=True)
'''
    m=once(m,helper_anchor,helper_new,"rolling follow-up helper")

    old='''            else:
                self._speech_waiting_question=True; self._speech_state("listening","正在听你说话") ; self.speech_service.resume()
                token=self._speech_session_token; timeout=max(5000,int(self._speech_cfg().get("listen_timeout_ms",15000)))
                QTimer.singleShot(timeout,lambda t=token:self._speech_listen_timeout(t))
'''
    new='''            else:
                self._arm_speech_followup()
'''
    m=once(m,old,new,"wake follow-up arm")

    old='''        elif tag=="dialogue_answer":
            hold=max(300,int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))
            self._speech_state("holding",f"白板保留 {hold/1000:.1f} 秒给观众看")
            token=self._speech_session_token
            QTimer.singleShot(hold+80,lambda t=token:self._speech_finish_if_token(t))
'''
    new='''        elif tag=="dialogue_answer":
            # V0.8.6: one wake opens a rolling multi-turn conversation. The
            # session ends only after the configured period of user inactivity.
            self._arm_speech_followup()
'''
    m=once(m,old,new,"multi-turn dialogue answer")

    # Make settings copy match the new semantics. Whiteboard hold remains only
    # for manual preview; live speech removes the board immediately after audio.
    m=m.replace("form.addRow('说完后停留',self.hold)","form.addRow('预览停留',self.hold)")
    m=m.replace(
        "文字会在 TTS 播报时逐步出现，播报结束后默认完整保留 3 秒。",
        "文字会跟随 TTS 播报逐步出现；实时语音结束后白板立即收起，不冻结画面。15 秒素材不足时会自动循环。")
    m=m.replace("唤醒后等待问题","连续对话静默退出")

    # ---- 3) Generic phrase-specific voice style overrides.
    old='''            "wake_replies": ["干嘛？", "咋滴了？", "有事你就说！"],
            "listen_timeout_ms": 15000,
'''
    new='''            "wake_replies": ["干嘛？", "咋滴了？", "有事你就说！"],
            "phrase_voice_overrides": {
                "干嘛": "这两个字必须保持明显的小女孩年龄感，音色清亮偏高、短促、轻快，带一点傲娇和疑问感。不要压低声线，不要成熟成年女性感，不要御姐腔。",
            },
            "listen_timeout_ms": 15000,
'''
    m=once(m,old,new,"default phrase voice override")

    anchor='''    def _pick_wake_reply(self):
        values=self._speech_fixed_replies()
        pool=[x for x in values if x!=self._speech_last_wake_reply] or values
        choice=ASSET_RNG.choice(pool); self._speech_last_wake_reply=choice; return choice
'''
    addition=anchor+'''
    def _speech_phrase_instruct(self, text):
        rules=self._speech_cfg().get("phrase_voice_overrides") or {}
        if not isinstance(rules,dict):
            return ""
        raw=str(text or "").strip()
        normalized=re.sub(r"[\\s，,。.!！？?、:：]+","",raw)
        for key,value in rules.items():
            k=re.sub(r"[\\s，,。.!！？?、:：]+","",str(key or "").strip())
            if k and k==normalized:
                return str(value or "").strip()
        return ""
'''
    m=once(m,anchor,addition,"phrase instruction helper")

    # Wake cache must be generated with the phrase override or the old adult-sounding
    # cached clip would keep winning.
    old='''        self.voice_service.warm_phrase_cache(self._speech_fixed_replies(),vid,float(voice.get("speed",1.0) or 1.0))
'''
    new='''        _replies=self._speech_fixed_replies()
        _styles={p:self._speech_phrase_instruct(p) for p in _replies}
        self.voice_service.warm_phrase_cache(_replies,vid,float(voice.get("speed",1.0) or 1.0),_styles)
'''
    m=once(m,old,new,"styled wake cache")

    old='''        self.voice_service.speak(reply,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="wake_ack")
'''
    new='''        self.voice_service.speak(reply,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="wake_ack",extra_instruct=self._speech_phrase_instruct(reply))
'''
    m=once(m,old,new,"styled wake playback")

    old='''        self.voice_service.speak(spoken,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="dialogue_answer")
'''
    new='''        self.voice_service.speak(spoken,str(voice.get("voice_id") or ""),float(voice.get("speed",1.0) or 1.0),str(voice.get("output_device","default") or "default"),tag="dialogue_answer",extra_instruct=self._speech_phrase_instruct(spoken))
'''
    m=once(m,old,new,"styled dialogue playback")

    # ---- VoiceService optional extra instruction, cache-safe.
    old='''    def _speech_cache_path(self, text, voice_id, speed):
        preset = PRESETS.get(str(voice_id or ""), {})
        payload = json.dumps({
            "text": str(text or "").strip(),
            "voice_id": str(voice_id or ""),
            "speed": round(float(speed or 1.0), 3),
            "instruct": str(preset.get("instruct") or ""),
'''
    new='''    def _speech_cache_path(self, text, voice_id, speed, extra_instruct=""):
        preset = PRESETS.get(str(voice_id or ""), {})
        payload = json.dumps({
            "text": str(text or "").strip(),
            "voice_id": str(voice_id or ""),
            "speed": round(float(speed or 1.0), 3),
            "instruct": str(preset.get("instruct") or ""),
            "extra_instruct": str(extra_instruct or "").strip(),
'''
    v=once(v,old,new,"voice cache key extra instruction")

    v=once(v,
           '''    def _synthesize_to(self, text, voice_id, speed, out):
''',
           '''    def _synthesize_to(self, text, voice_id, speed, out, extra_instruct=""):
''',
           "synthesize signature")

    old='''            "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed),
'''
    new='''            "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed) + (" " + str(extra_instruct).strip() if str(extra_instruct or "").strip() else ""),
'''
    if old not in v:
        raise RuntimeError("V0.8.6 synthesize instruction token missing")
    v=v.replace(old,new,1)

    v=once(v,
           '''    def warm_phrase_cache(self, phrases, voice_id, speed=1.0):
''',
           '''    def warm_phrase_cache(self, phrases, voice_id, speed=1.0, phrase_styles=None):
''',
           "warm cache signature")
    old='''                for phrase in phrases:
                    out = self._speech_cache_path(phrase, voice_id, speed)
                    if not out.exists() or out.stat().st_size < 256:
                        self._synthesize_to(phrase, voice_id, speed, out)
'''
    new='''                styles = phrase_styles if isinstance(phrase_styles, dict) else {}
                for phrase in phrases:
                    extra = str(styles.get(phrase) or "").strip()
                    out = self._speech_cache_path(phrase, voice_id, speed, extra)
                    if not out.exists() or out.stat().st_size < 256:
                        self._synthesize_to(phrase, voice_id, speed, out, extra)
'''
    v=once(v,old,new,"warm styled phrases")

    v=once(v,
           '''    def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue"):
''',
           '''    def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue", extra_instruct=""):
''',
           "speak signature")
    old='''                out = self._speech_cache_path(text, voice_id, speed)
                if not out.exists() or out.stat().st_size < 256:
                    self._synthesize_to(text, voice_id, speed, out)
'''
    new='''                extra_instruct = str(extra_instruct or "").strip()
                out = self._speech_cache_path(text, voice_id, speed, extra_instruct)
                if not out.exists() or out.stat().st_size < 256:
                    self._synthesize_to(text, voice_id, speed, out, extra_instruct)
'''
    v=once(v,old,new,"speak styled cache")

    main.write_text(m,encoding="utf-8")
    voice.write_text(v,encoding="utf-8")
    py_compile.compile(str(main),doraise=True)
    py_compile.compile(str(voice),doraise=True)

    mm=main.read_text(encoding="utf-8")
    vv=voice.read_text(encoding="utf-8")
    checks=[
        'APP_VERSION = "0.8.6"',
        'def _arm_speech_followup(self):',
        'self._arm_speech_followup()',
        'self.pet.finish_dialogue_board(120)',
        'phrase_voice_overrides',
        'extra_instruct=self._speech_phrase_instruct(reply)',
    ]
    for token in checks:
        if token not in mm: raise RuntimeError("V0.8.6 main check failed: "+token)
    for token in [
        'def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue", extra_instruct=""):',
        'def warm_phrase_cache(self, phrases, voice_id, speed=1.0, phrase_styles=None):',
        '"extra_instruct": str(extra_instruct or "").strip()',
    ]:
        if token not in vv: raise RuntimeError("V0.8.6 voice check failed: "+token)
    if "movie.setPaused(True)" in mm[mm.find("def finish_dialogue_board"):mm.find("def _end_dialogue_board")]:
        raise RuntimeError("V0.8.6 dialogue finish still freezes movie")
    print("Patched XiaoMeili source to V0.8.6 continuous conversation + dynamic board + phrase voice styles")


if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: patch_v086.py <source_root>")
    patch(Path(sys.argv[1]))
