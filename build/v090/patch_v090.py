# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.9.0 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.9.0 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.9.2"' not in s:
        raise RuntimeError("V0.9.0 expected APP_VERSION 0.8.9.2 base")
    s = s.replace('APP_VERSION = "0.8.9.2"', 'APP_VERSION = "0.9.0"', 1)
    s = s.replace("V0.8.9.2｜", "V0.9.0｜", 1)

    # ---------------------------------------------------------------
    # Vision constants: 2560x1440 is the user's native runtime target.
    # Keep proportional coordinates so uploaded 1280x720 samples map cleanly.
    # Enemy portrait centers were calibrated from the supplied 5-alive / 3-alive
    # negative samples. Empty red-bar slots have far lower texture energy.
    # ---------------------------------------------------------------
    const_anchor = "ROI_KILL_PROBE"
    idx = s.find(const_anchor)
    if idx < 0:
        raise RuntimeError("V0.9.0 vision ROI anchor missing")
    line_start = s.rfind("\n", 0, idx) + 1
    constants = '''# V0.9.0 round-highlight tracker ROIs (normalized viewport coordinates)
ROI_ENEMY_TEAM = (0.588, 0.006, 0.785, 0.082)
V090_ENEMY_CENTERS = (0.615, 0.648, 0.681, 0.714, 0.747)

'''
    s = s[:line_start] + constants + s[line_start:]

    # VisionWorker state.
    init_anchor = '        self.phase = "OUT_OF_MATCH"\n'
    if init_anchor not in s:
        raise RuntimeError("V0.9.0 VisionWorker phase anchor missing")
    init_extra = '''        # V0.9.0: single-round event memory for highlight CTA.
        self.round_self_kills = 0
        self.enemy_alive = 5
        self.enemy_alive_scores = [0.0] * 5
        self.enemy_alive_confident = False
        self.self_final_kill_candidate = False
        self.self_final_kill_confirmed = False
        self.highlight_triggered = False
        self.highlight_event_id = 0
        self.highlight_last_reason = "等待回合"
        self.highlight_candidate = False
        self.hl_round_finalized = False
        self.visible_own_kill_rows = 0
        self.next_enemy_alive = 0.0
        self.last_enemy_alive_scan = 0.0
'''
    s = s.replace(init_anchor, init_anchor + init_extra, 1)

    # Add helpers before kill scan.
    kill_anchor = "    def _scan_kill_probe(self, grabber, viewport, now):\n"
    if kill_anchor not in s:
        raise RuntimeError("V0.9.0 kill scan anchor missing")
    helpers = r'''    def _reset_round_highlight(self, reason=""):
        self.round_self_kills = 0
        self.enemy_alive = 5
        self.enemy_alive_scores = [0.0] * 5
        self.enemy_alive_confident = False
        self.self_final_kill_candidate = False
        self.self_final_kill_confirmed = False
        self.highlight_triggered = False
        self.highlight_candidate = False
        self.visible_own_kill_rows = 0
        self.hl_round_finalized = False
        self.highlight_last_reason = f"新回合：{reason or 'HUD returned'}"
        LOGGER.info("[ROUND] reset | %s", reason or "new live HUD")

    def _scan_enemy_alive_v090(self, grabber, viewport, now):
        """Cheap top-HUD portrait-slot counter.

        We do not identify enemy agents. Each of the five fixed portrait slots is
        reduced to a tiny grayscale patch and judged by Laplacian texture energy.
        Living portraits are highly textured; an empty red team bar is nearly
        flat. The supplied 5-alive and 3-alive samples separate cleanly.
        """
        try:
            vx, vy, vw, vh = viewport
            scores = []
            alive = 0
            for cx in V090_ENEMY_CENTERS:
                box = (cx - 0.0105, 0.010, cx + 0.0105, 0.067)
                patch = _grab_relative_roi(grabber, viewport, box, (40, 64))
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                score = float(cv2.Laplacian(gray, cv2.CV_32F).var())
                scores.append(score)
                if score >= 1850.0:
                    alive += 1
            self.enemy_alive_scores = scores
            # Require at least one clearly high/low slot to avoid treating a
            # transient full-screen effect as authoritative.
            separated = any(x >= 2400.0 for x in scores) or all(x < 1500.0 for x in scores)
            self.enemy_alive_confident = bool(separated)
            if separated:
                self.enemy_alive = int(max(0, min(5, alive)))
            self.last_enemy_alive_scan = now
            return self.enemy_alive
        except Exception:
            LOGGER.exception("[ROUND] enemy alive scan failed")
            return self.enemy_alive

    def _ocr_own_kill_rows_v090(self, kill_roi):
        nickname = str(self.cfg.get("vision", {}).get("player_nickname", "")).strip()
        if not nickname:
            return 0, "未绑定游戏昵称"
        t0 = time.perf_counter()
        engine = self._get_report_ocr_engine()
        try:
            if engine is None:
                return 0, "OCR引擎不可用"
            self.ocr_trigger_count += 1
            roi2 = cv2.resize(kill_roi, None, fx=1.25, fy=1.25, interpolation=cv2.INTER_LINEAR)
            result = engine(roi2)
            boxes = getattr(result, "boxes", None)
            txts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            if txts is None or boxes is None:
                return 0, "未识别到昵称"
            target = self._norm_name(nickname)
            rw = max(1.0, float(roi2.shape[1]))
            hits = 0
            debug = []
            for i, txt in enumerate(list(txts)):
                conf = float(scores[i]) if scores is not None and i < len(scores) else 1.0
                if conf < 0.40:
                    continue
                box = np.array(boxes[i], dtype=np.float32)
                cx = float(box[:, 0].mean()) / rw
                sim = self._name_similarity(target, txt)
                debug.append(f"{txt}@{cx:.2f}/{sim:.2f}")
                if cx < 0.67 and sim >= 0.66:
                    hits += 1
            self.last_ocr_texts = debug[:12]
            return int(hits), (f"{nickname} 可见击杀行={hits}" if hits else "未发现本人击杀行")
        except Exception as exc:
            LOGGER.exception("[ROUND] own-kill OCR failed")
            return 0, f"OCR错误:{type(exc).__name__}"
        finally:
            self._ema_timing("ocr", (time.perf_counter() - t0) * 1000)

'''
    s = s.replace(kill_anchor, helpers + kill_anchor, 1)

    new_kill = r'''    def _scan_kill_probe(self, grabber, viewport, now):
        if not self.match_context or self.death_latched or self.round_end:
            self.last_kill_signature=(0,())
            self.last_kill_count=0
            self.visible_own_kill_rows=0
            return

        t0=time.perf_counter()
        probe=_grab_relative_roi(grabber,viewport,ROI_KILL_PROBE,(320,108))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter()
        sig,strength=_killfeed_green_signature(probe)
        self._ema_timing("kill",(time.perf_counter()-q)*1000)
        self.perf_scans+=1

        changed=sig!=self.last_kill_signature
        self.last_kill_probe_strength=strength
        self.last_kill_signature=sig
        if not changed:
            return

        # Any kill-feed edge is a useful moment to refresh the enemy count.
        before = int(self.enemy_alive)
        self._scan_enemy_alive_v090(grabber, viewport, now)

        if sig[0] <= 0:
            self.visible_own_kill_rows=0
            return
        if now-self.last_kill_event_time < 0.16:
            return
        self.last_kill_event_time=now

        # Character-agnostic identity: nickname is the source of truth. This
        # works when the user changes from Sage to Harbor or any other agent.
        t0=time.perf_counter()
        kill_roi=_grab_relative_roi(grabber,viewport,ROI_KILL_OCR,(640,189))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        visible, match = self._ocr_own_kill_rows_v090(kill_roi)
        delta=max(0, int(visible)-int(self.visible_own_kill_rows))
        self.visible_own_kill_rows=int(visible)
        self.last_nickname_match=match
        self.last_kill_count=delta

        if delta <= 0:
            LOGGER.info("[KILL] teammate/other kill ignored | %s | enemy=%s", match, self.enemy_alive)
            return

        self.round_self_kills += int(delta)
        self.highlight_candidate = self.round_self_kills >= int(
            self.cfg.get("highlight_cta",{}).get("min_kills",2)
        )
        after=int(self.enemy_alive)
        if before == 1:
            self.self_final_kill_candidate = True
            if after == 0 or not self.enemy_alive_confident:
                # If the result overlay races the top bar, the later victory is
                # the second half of the confirmation chain.
                self.self_final_kill_confirmed = (after == 0)
            LOGGER.info("[KILL] final-enemy candidate by self | before=%s after=%s", before, after)

        LOGGER.info(
            "[KILL] self +%s | round=%s enemy=%s->%s candidate=%s final=%s",
            delta, self.round_self_kills, before, after,
            self.highlight_candidate, self.self_final_kill_confirmed,
        )
        if self.alive_state is True:
            self._request_state("kill",f"event-driven own kill nick={match} +{delta}")
            self.transient_until=now+int(self.cfg.get("vision",{}).get("kill_show_ms",1400))/1000.0

'''
    s = replace_method(s, "_scan_kill_probe", "_scan_result", new_kill, "nickname-driven round kills")

    new_result = r'''    def _scan_result(self, grabber, viewport, now):
        # Do not run result matching continuously for highlight purposes. The
        # existing result scanner remains low-frequency; highlight eligibility
        # is only evaluated when a stable win event is actually confirmed.
        if not self.match_context and now>self.match_recent_until:
            return
        t0=time.perf_counter()
        img=_grab_relative_roi(grabber,viewport,ROI_RESULT,(480,243))
        self._ema_timing("capture",(time.perf_counter()-t0)*1000)
        q=time.perf_counter()
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        bw=(gray>220).astype(np.uint8)*255
        win_score=self._fixed_match(bw,self.win_t)
        loss_score=self._fixed_match(bw,self.loss_t)
        self._ema_timing("result",(time.perf_counter()-q)*1000)
        self.perf_scans+=1
        self.last_win_score=win_score
        self.last_loss_score=loss_score

        thr=float(self.cfg.get("vision",{}).get("result_threshold",0.75))
        win_raw=win_score>=thr
        loss_raw=loss_score>=thr
        win_event=win_raw and not self.win_latched
        loss_event=loss_raw and not self.loss_latched
        if win_raw:self.win_latched=True
        elif win_score<thr-0.12:self.win_latched=False
        if loss_raw:self.loss_latched=True
        elif loss_score<thr-0.12:self.loss_latched=False

        result_state="victory" if win_event else "defeat" if loss_event else None
        if not result_state:
            return

        self.round_end=True
        self.phase="ROUND_END"
        self.hl_round_finalized=True

        if result_state == "victory":
            # A win after "before=1 + own kill" also confirms the last enemy
            # when the top portrait strip disappeared too quickly to read 0.
            if self.self_final_kill_candidate:
                self.self_final_kill_confirmed = True

            hcfg=self.cfg.get("highlight_cta",{}) if isinstance(self.cfg.get("highlight_cta"),dict) else {}
            min_kills=max(1,int(hcfg.get("min_kills",2)))
            enabled=bool(hcfg.get("enabled",True))
            alive_ok=not bool(self.death_latched)
            qualifies=(
                enabled
                and self.round_self_kills>=min_kills
                and bool(self.self_final_kill_confirmed)
                and alive_ok
                and not self.highlight_triggered
            )
            if qualifies:
                self.highlight_triggered=True
                self.highlight_event_id+=1
                self.highlight_last_reason=(
                    f"{self.round_self_kills}杀 · 最后一杀本人 · 存活 · 获胜"
                )
                LOGGER.info(
                    "[HIGHLIGHT] TRIGGER id=%s kills=%s final=%s alive=%s win=%.3f",
                    self.highlight_event_id,self.round_self_kills,
                    self.self_final_kill_confirmed,alive_ok,win_score,
                )
            else:
                reasons=[]
                if not enabled: reasons.append("功能关闭")
                if self.round_self_kills<min_kills: reasons.append(f"击杀不足 {self.round_self_kills}/{min_kills}")
                if not self.self_final_kill_confirmed: reasons.append("最后一杀非本人/未确认")
                if not alive_ok: reasons.append("主人已死亡")
                if self.highlight_triggered: reasons.append("本回合已触发")
                self.highlight_last_reason="未触发："+"；".join(reasons or ["条件不满足"])
                LOGGER.info("[HIGHLIGHT] NO TRIGGER | %s",self.highlight_last_reason)
        else:
            self.highlight_last_reason="未触发：本回合失败"
            LOGGER.info("[HIGHLIGHT] defeat | no trigger")

        if self.current_display_state=="kill" and now<self.transient_until:
            self.pending_result=(result_state,self.transient_until+0.06)
        else:
            self._request_state(result_state,f"round result win={win_score:.3f} loss={loss_score:.3f}")
            self.transient_until=now+int(self.cfg.get("vision",{}).get("result_show_ms",2800))/1000.0
            self.pending_result=None

'''
    s = replace_method(s, "_scan_result", "_settle_state", new_result, "highlight result gate")

    # New round reset when live HUD reappears after a finalized round.
    ctx_anchor = '        if not self.match_context and self.context_hits>=2:\n            self.match_context=True; self.phase="IN_MATCH_UNKNOWN"; LOGGER.info("MATCH_CONTEXT TRUE votes=%s L=%.3f C=%.3f R=%.3f",votes,ls,cs,rs)\n'
    if ctx_anchor not in s:
        raise RuntimeError("V0.9.0 context re-entry anchor missing")
    ctx_new = '''        if not self.match_context and self.context_hits>=2:
            if self.hl_round_finalized:
                self._reset_round_highlight("新一回合 live HUD")
            self.match_context=True; self.phase="IN_MATCH_UNKNOWN"; LOGGER.info("MATCH_CONTEXT TRUE votes=%s L=%.3f C=%.3f R=%.3f",votes,ls,cs,rs)
'''
    s = s.replace(ctx_anchor, ctx_new, 1)

    # Scan enemy strip at low frequency using the existing shared ScreenGrabber.
    run_anchor = '                        if now>=self.next_death: self._scan_death_confirmation(grabber,viewport,now); self.next_death=now+death_i\n'
    if run_anchor not in s:
        raise RuntimeError("V0.9.0 run-loop enemy scan anchor missing")
    s = s.replace(
        run_anchor,
        run_anchor +
        '                        if now>=self.next_enemy_alive:\n'
        '                            self._scan_enemy_alive_v090(grabber,viewport,now)\n'
        '                            self.next_enemy_alive=now+0.70\n',
        1,
    )
    due_anchor = '                    due.extend([self.next_alive,self.next_hp,self.next_kill,self.next_death])\n'
    if due_anchor in s:
        s = s.replace(due_anchor,'                    due.extend([self.next_alive,self.next_hp,self.next_kill,self.next_death,self.next_enemy_alive])\n',1)

    # Snapshot fields for UI + controller. Event ID is monotonic, so the
    # controller cannot double-fire even if several snapshots carry the same ID.
    snap_anchor = '            "queue_length":0,"skipped_cycles":self.skipped_cycles,\n'
    if snap_anchor not in s:
        raise RuntimeError("V0.9.0 snapshot anchor missing")
    snap_extra = '''            "round_self_kills":self.round_self_kills,
            "enemy_alive":self.enemy_alive,
            "enemy_alive_scores":[round(float(x),1) for x in self.enemy_alive_scores],
            "enemy_alive_confident":self.enemy_alive_confident,
            "self_final_kill_candidate":self.self_final_kill_candidate,
            "self_final_kill_confirmed":self.self_final_kill_confirmed,
            "highlight_candidate":self.highlight_candidate,
            "highlight_triggered":self.highlight_triggered,
            "highlight_event_id":self.highlight_event_id,
            "highlight_reason":self.highlight_last_reason,
'''
    s = s.replace(snap_anchor, snap_anchor + snap_extra, 1)

    # ---------------------------------------------------------------
    # Settings UI: add editable highlight package to the existing Game
    # Recognition tab. The temporary test uses the current universal whiteboard
    # animation until the user imports the dedicated final clip.
    # ---------------------------------------------------------------
    ui_anchor = '        vv.addWidget(box)\n'
    if ui_anchor not in s:
        raise RuntimeError("V0.9.0 vision UI anchor missing")
    ui_block = r'''        vv.addWidget(box)

        hcfg=cfg.setdefault("highlight_cta",{})
        hbox=QGroupBox("高光回合 · P100 最高优先级")
        hf=QFormLayout(hbox)
        self.highlight_enabled=QCheckBox("启用高光关注事件")
        self.highlight_enabled.setChecked(bool(hcfg.get("enabled",True)))
        hf.addRow(self.highlight_enabled)

        identity=QLabel(str(cfg.get("vision",{}).get("player_nickname","")).strip() or "未绑定")
        identity.setStyleSheet("font-weight:700;")
        hf.addRow("绑定玩家（来自上方昵称）",identity)

        self.highlight_min_kills=QSpinBox()
        self.highlight_min_kills.setRange(1,5)
        self.highlight_min_kills.setValue(int(hcfg.get("min_kills",2)))
        hf.addRow("最低本人击杀",self.highlight_min_kills)

        conditions=QLabel("✓ 本回合本人击杀达到阈值   ✓ 本人完成敌方最后一杀   ✓ 本人存活   ✓ 本回合获胜")
        conditions.setWordWrap(True)
        hf.addRow("触发条件",conditions)

        self.highlight_board_text=QLineEdit(str(hcfg.get("board_text") or "愣着干嘛，点点关注呀！"))
        hf.addRow("白板文字",self.highlight_board_text)

        self.highlight_phrases=QTextEdit()
        self.highlight_phrases.setMinimumHeight(108)
        _phrases=hcfg.get("phrases") or [
            "愣着干嘛，点点关注呀！",
            "这波还不值得一个关注？",
            "看完还想白嫖呀？",
        ]
        self.highlight_phrases.setPlainText("\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        self.highlight_status=QLabel("当前回合：等待识别")
        self.highlight_status.setWordWrap(True)
        hf.addRow("实时状态",self.highlight_status)

        hnote=QLabel("V0.9.0 测试版暂时复用当前通用白板动画。高光触发会抢占普通TTS/普通白板；播报使用小美丽当前固定声音。")
        hnote.setWordWrap(True)
        hf.addRow(hnote)
        vv.addWidget(hbox)
'''
    s = s.replace(ui_anchor, ui_block, 1)

    # Persist highlight settings with normal Settings Apply.
    save_anchor = '        self.cfg["vision"]["nickname_ocr_fallback"]=self.nickname_ocr_cb.isChecked()\n'
    if save_anchor not in s:
        raise RuntimeError("V0.9.0 settings save anchor missing")
    save_extra = '''        hcfg=self.cfg.setdefault("highlight_cta",{})
        hcfg["enabled"]=bool(self.highlight_enabled.isChecked()) if hasattr(self,"highlight_enabled") else True
        hcfg["min_kills"]=int(self.highlight_min_kills.value()) if hasattr(self,"highlight_min_kills") else 2
        hcfg["board_text"]=self.highlight_board_text.text().strip() if hasattr(self,"highlight_board_text") else "愣着干嘛，点点关注呀！"
        if hasattr(self,"highlight_phrases"):
            hcfg["phrases"]=[x.strip() for x in self.highlight_phrases.toPlainText().splitlines() if x.strip()]
'''
    s = s.replace(save_anchor, save_anchor + save_extra, 1)

    # Update Settings live diagnostics.
    status_anchor = '        self.vision_status.setText(text)\n'
    if status_anchor not in s:
        raise RuntimeError("V0.9.0 vision diagnostics anchor missing")
    status_extra = '''        if hasattr(self,"highlight_status"):
            self.highlight_status.setText(
                f"本人击杀：{data.get('round_self_kills',0)}  |  敌方存活：{data.get('enemy_alive','?')}/5  |  "
                f"主人：{'已死亡' if data.get('death_latched') else '存活/未确认'}\\n"
                f"最后一杀：{'✓ 本人' if data.get('self_final_kill_confirmed') else '等待/非本人'}  |  "
                f"高光资格：{'已满足击杀' if data.get('highlight_candidate') else '未满足'}\\n"
                f"最近判定：{data.get('highlight_reason','等待')}"
            )
'''
    s = s.replace(status_anchor, status_anchor + status_extra, 1)

    # ---------------------------------------------------------------
    # Controller: P100 high-priority CTA package.
    # ---------------------------------------------------------------
    init_ctrl_anchor = '        self.brain_service.generation_finished.connect(self._on_voice_brain_finished)\n'
    if init_ctrl_anchor not in s:
        raise RuntimeError("V0.9.0 controller signal anchor missing")
    ctrl_init = '''        self._highlight_seen_event_id=0
        self._highlight_active=False
        self._highlight_last_phrase=""
        QTimer.singleShot(2600,self._warm_highlight_cta_cache)
'''
    s = s.replace(init_ctrl_anchor, init_ctrl_anchor + ctrl_init, 1)

    methods = r'''    def _highlight_cfg(self):
        cfg=self.cfg.get("highlight_cta",{})
        return cfg if isinstance(cfg,dict) else {}

    def _highlight_phrases_list(self):
        values=self._highlight_cfg().get("phrases") or ["愣着干嘛，点点关注呀！"]
        values=[str(x or "").strip() for x in values if str(x or "").strip()]
        return values or ["愣着干嘛，点点关注呀！"]

    def _warm_highlight_cta_cache(self):
        try:
            voice=self._speech_voice_cfg()
            vid=str(voice.get("voice_id") or "")
            if not vid or not self.voice_service.ready():
                return
            phrases=self._highlight_phrases_list()
            styles={p:self._speech_phrase_instruct(p) for p in phrases}
            self.voice_service.warm_phrase_cache(
                phrases,vid,float(voice.get("speed",1.0) or 1.0),styles
            )
            LOGGER.info("[HIGHLIGHT] TTS phrase cache warm requested: %s",len(phrases))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] warm cache failed")

    def _pick_highlight_phrase(self):
        values=self._highlight_phrases_list()
        pool=[x for x in values if x!=self._highlight_last_phrase] or values
        choice=ASSET_RNG.choice(pool)
        self._highlight_last_phrase=choice
        return choice

    def _trigger_highlight_cta(self, data):
        if self._highlight_active:
            return
        self._highlight_active=True
        LOGGER.info("[HIGHLIGHT] P100 takeover | %s",data.get("highlight_reason",""))

        # Stop/retire lower-priority dialogue. New P100 playback must not wait.
        try:
            if self._speech_session_active:
                self._end_speech_session(resume=False)
        except Exception:
            pass
        for method_name in ("stop_playback","stop_audio","cancel_playback"):
            try:
                method=getattr(self.voice_service,method_name,None)
                if callable(method):
                    method()
                    break
            except Exception:
                pass
        try:
            if getattr(self.pet,"dialogue_board_active",False):
                self.pet._end_dialogue_board()
        except Exception:
            pass

        phrase=self._pick_highlight_phrase()
        voice=self._speech_voice_cfg()
        vid=str(voice.get("voice_id") or "")
        if not vid or not self.voice_service.ready():
            LOGGER.warning("[HIGHLIGHT] voice unavailable, showing board only")
            text=str(self._highlight_cfg().get("board_text") or "愣着干嘛，点点关注呀！")
            self.pet.preview_dialogue(text,4200)
            QTimer.singleShot(4400,lambda:setattr(self,"_highlight_active",False))
            return

        self.voice_service.speak(
            phrase,vid,float(voice.get("speed",1.0) or 1.0),
            str(voice.get("output_device","default") or "default"),
            tag="highlight_cta",
            extra_instruct=self._speech_phrase_instruct(phrase),
        )

'''
    speech_method_anchor = "    def _on_voice_playback_started(self, text, duration_ms, tag):\n"
    if speech_method_anchor not in s:
        raise RuntimeError("V0.9.0 voice playback anchor missing")
    s = s.replace(speech_method_anchor, methods + speech_method_anchor, 1)

    new_started = r'''    def _on_voice_playback_started(self, text, duration_ms, tag):
        tag=str(tag or "")
        if tag=="highlight_cta":
            self._highlight_active=True
            board=str(self._highlight_cfg().get("board_text") or "愣着干嘛，点点关注呀！")
            try:
                if getattr(self.pet,"dialogue_board_active",False):
                    self.pet._end_dialogue_board()
            except Exception:
                pass
            self.pet.start_dialogue_board(board,int(duration_ms))
            return
        if not self._speech_session_active:return
        self._speech_state("speaking","小美丽正在说话")
        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.start_dialogue_board(str(text),int(duration_ms))

'''
    s = replace_method(s, "_on_voice_playback_started", "_on_voice_playback_finished", new_started, "highlight playback start")

    new_finished = r'''    def _on_voice_playback_finished(self, ok, message, tag):
        tag=str(tag or "")
        if tag=="highlight_cta":
            try:
                self.pet.finish_dialogue_board(900)
            except Exception:
                pass
            self._highlight_active=False
            if bool(self._speech_cfg().get("enabled",True)) and self.speech_service.ready():
                QTimer.singleShot(1100,self.refresh_speech_interaction)
            return

        if not self._speech_session_active:return
        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))
        if not ok:
            LOGGER.warning("语音播报失败: %s",message); self._end_speech_session(resume=True); return
        if tag=="wake_ack":
            if self._speech_pending_question:
                question=self._speech_pending_question; self._speech_pending_question=""; self._ask_voice_question(question)
            else:
                self._arm_speech_followup()
        elif tag=="dialogue_answer":
            self._arm_speech_followup()

'''
    s = replace_method(s, "_on_voice_playback_finished", "_arm_speech_followup", new_finished, "highlight playback finish")

    new_snapshot = r'''    def on_vision_snapshot(self,data):
        if self.settings:
            self.settings.update_vision_snapshot(data)
        try:
            event_id=int(data.get("highlight_event_id",0) or 0)
            if event_id>0 and event_id!=int(self._highlight_seen_event_id):
                self._highlight_seen_event_id=event_id
                self._trigger_highlight_cta(data)
        except Exception:
            LOGGER.exception("[HIGHLIGHT] controller snapshot handling failed")

'''
    s = replace_method(s, "on_vision_snapshot", "open_settings", new_snapshot, "highlight controller trigger")

    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s=path.read_text(encoding="utf-8")
    s=s.replace("小美丽 V0.8.9.2 语音诊断日志","小美丽 V0.9.0 语音诊断日志")
    path.write_text(s,encoding="utf-8")
    py_compile.compile(str(path),doraise=True)


def patch(source_root: Path):
    root=Path(source_root).resolve()
    main=root/"app"/"src"/"main.py"
    speech=root/"app"/"src"/"speech_input.py"
    if not main.exists(): raise FileNotFoundError(main)
    if not speech.exists(): raise FileNotFoundError(speech)
    patch_main(main)
    patch_speech(speech)

    m=main.read_text(encoding="utf-8")
    checks=[
        'APP_VERSION = "0.9.0"',
        'ROI_ENEMY_TEAM',
        'def _scan_enemy_alive_v090',
        'def _ocr_own_kill_rows_v090',
        'self.round_self_kills',
        'self.self_final_kill_confirmed',
        'self.highlight_event_id',
        '高光回合 · P100 最高优先级',
        '愣着干嘛，点点关注呀！',
        'def _trigger_highlight_cta',
        'tag="highlight_cta"',
    ]
    for token in checks:
        if token not in m:
            raise RuntimeError("V0.9.0 verification failed: "+token)

    print("Patched XiaoMeili source to V0.9.0 round highlight CTA")


if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: patch_v090.py <source_root>")
    patch(Path(sys.argv[1]))
