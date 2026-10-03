from pathlib import Path
import py_compile, re, shutil, sys

root = Path(sys.argv[1]).resolve()
src = root / 'app' / 'src'
main = src / 'main.py'
speech = src / 'speech_input.py'
ndm = src / 'ndm_bridge.py'
voice = src / 'voice_dual.py'


def rd(p):
    return p.read_text(encoding='utf-8-sig')

def wr(p, s):
    p.write_text(s, encoding='utf-8', newline='\n')

def rep(s, a, b, name, count=1):
    if a not in s:
        raise RuntimeError(f'missing patch anchor: {name}')
    return s.replace(a, b, count)

# ---------------- main.py ----------------
s = rd(main)
if 'APP_VERSION = "0.10.0.9.1"' not in s:
    raise RuntimeError('V0.10.0.9.1 baseline required')

s = rep(s,
    'APP_NAME = "小美丽 V0.10.0.9.1｜Long Interaction Diagnostic + NDM Preferred"',
    'APP_NAME = "小美丽 V0.10.0.9.2｜Long Chat Stability + Hard Silence + NDM Fast Fallback"',
    'app name')
s = rep(s, 'APP_VERSION = "0.10.0.9.1"', 'APP_VERSION = "0.10.0.9.2"', 'app version')
s = rep(s, 'APP_UPDATE_VERSION = \"0.10.0.9.1\"', 'APP_UPDATE_VERSION = \"0.10.0.9.2\"', 'update version')

# Updater version parsing hotfix: XiaoMeili uses five-part versions such as
# 0.10.0.9.1 -> 0.10.0.9.2. The old parser kept only four numeric
# components, so both versions collapsed to (0, 10, 0, 9) and the update
# button stayed disabled even though the new manifest was fetched correctly.
s = rep(s,
'''def _version_tuple(value):
    nums = re.findall(r"\\d+", str(value or ""))[:4]
    return tuple(int(x) for x in nums) if nums else (0,)
''',
'''def _version_tuple(value):
    nums = re.findall(r"\\d+", str(value or ""))[:8]
    return tuple(int(x) for x in nums) if nums else (0,)
''',
'five-part update version parser')

# Avoid stale GitHub Raw/CDN responses during manual update checks.
s = rep(s,
'''                req = urllib.request.Request(url, headers={"User-Agent": f"XiaoMeili/{APP_VERSION}"})
''',
'''                req = urllib.request.Request(url, headers={
                    "User-Agent": f"XiaoMeili/{APP_VERSION}",
                    "Cache-Control": "no-cache, no-store, max-age=0",
                    "Pragma": "no-cache",
                })
''',
'update no-cache headers')

# If a manifest was fetched but is older/different, do not falsely label that
# manifest as the running "current version".
s = rep(s,
'''            else:
                self.update_status.setText(f"当前已是最新版本 V{APP_VERSION}。")
                title = f"V{version or APP_VERSION}（当前版本）"
''',
'''            else:
                self.update_status.setText(f"当前已是最新版本 V{APP_VERSION}。")
                if version and _version_tuple(version) != _version_tuple(APP_UPDATE_VERSION):
                    title = f"更新源版本 V{version}"
                else:
                    title = f"V{APP_VERSION}（当前版本）"
''',
'update notes current-version label')

# Config schema bump without changing user settings.
s = s.replace('cfg["config_version"] = max(30, int(cfg.get("config_version", 0) or 0))',
              'cfg["config_version"] = max(31, int(cfg.get("config_version", 0) or 0))')
s = s.replace('cfg["config_version"] = 30', 'cfg["config_version"] = 31')

# QMovie lifecycle: CacheNone + explicit release before replacement.
old = '''    def set_asset(self, label_idx, path, state):\n        movie = QMovie(path)\n        movie.setCacheMode(QMovie.CacheMode.CacheAll)\n        movie.setScaledSize(self.size())\n        if not movie.isValid():\n            raise RuntimeError(f"动画素材无效: {path}")\n        self.movie_generation += 1\n        token = self.movie_generation\n        # Imported WebP clips are finite. When one finishes, choose another clip\n        # from the same state pool. Stale movies are ignored via generation token.\n        movie.finished.connect(lambda tok=token, st=state: self._movie_finished(tok, st))\n        self.movies[label_idx] = movie\n        self.labels[label_idx].setMovie(movie)\n        self.current_asset_path = path\n        if state == "report" and hasattr(self, "report_overlay"):\n            self.report_overlay.set_asset(path)\n        movie.start()\n'''
new = '''    def _release_movie_slot(self, label_idx):\n        """Release one QMovie immediately instead of leaving decoded frames/QObjects behind."""\n        try:\n            idx = int(label_idx)\n            movie = self.movies[idx] if 0 <= idx < len(self.movies) else None\n            if movie is None:\n                return\n            try:\n                movie.stop()\n            except Exception:\n                pass\n            try:\n                movie.finished.disconnect()\n            except Exception:\n                pass\n            try:\n                self.labels[idx].clear()\n            except Exception:\n                pass\n            self.movies[idx] = None\n            try:\n                movie.deleteLater()\n            except Exception:\n                pass\n        except Exception:\n            LOGGER.debug("释放动画槽失败", exc_info=True)\n\n    def _dispose_animation_group(self, attr_name):\n        grp = getattr(self, attr_name, None)\n        if grp is None:\n            return\n        try:\n            grp.stop()\n        except Exception:\n            pass\n        try:\n            grp.deleteLater()\n        except Exception:\n            pass\n        setattr(self, attr_name, None)\n\n    def set_asset(self, label_idx, path, state):\n        # V0.10.0.9.2: every replacement retires the previous QMovie first.\n        # CacheNone prevents each WebP/GIF from keeping a full decoded-frame cache.\n        self._release_movie_slot(label_idx)\n        movie = QMovie(path)\n        movie.setCacheMode(QMovie.CacheMode.CacheNone)\n        movie.setScaledSize(self.size())\n        if not movie.isValid():\n            try:\n                movie.deleteLater()\n            except Exception:\n                pass\n            raise RuntimeError(f"动画素材无效: {path}")\n        self.movie_generation += 1\n        token = self.movie_generation\n        # Imported WebP clips are finite. When one finishes, choose another clip\n        # from the same state pool. Stale movies are ignored via generation token.\n        movie.finished.connect(lambda tok=token, st=state: self._movie_finished(tok, st))\n        self.movies[label_idx] = movie\n        self.labels[label_idx].setMovie(movie)\n        self.current_asset_path = path\n        if state == "report" and hasattr(self, "report_overlay"):\n            self.report_overlay.set_asset(path)\n        movie.start()\n'''
s = rep(s, old, new, 'QMovie lifecycle')

# Replace transition-group handling so parented QObjects do not accumulate forever.
s = rep(s,
'''            if self._mouse_transition_group:\n                try: self._mouse_transition_group.stop()\n                except Exception: pass\n''',
'''            if self._mouse_transition_group:\n                self._dispose_animation_group("_mouse_transition_group")\n''',
'mouse transition dispose', count=2)

# First mouse transition completion.
s = rep(s,
'''            def done():\n                if self.movies[old]: self.movies[old].stop()\n            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()\n''',
'''            def done():\n                self._release_movie_slot(old)\n                if self._mouse_transition_group is grp:\n                    self._mouse_transition_group = None\n                grp.deleteLater()\n            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()\n''',
'mouse transition done 1')

# Second mouse transition completion.
s = rep(s,
'''            def done():\n                self.mouse_layer.hide(); self.current_slot = new\n                self.effects[1-new].setOpacity(0.0)\n            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()\n''',
'''            def done():\n                self.mouse_layer.hide(); self.current_slot = new\n                self.effects[1-new].setOpacity(0.0)\n                self._release_movie_slot(1-new)\n                if self._mouse_transition_group is grp:\n                    self._mouse_transition_group = None\n                grp.deleteLater()\n            grp.finished.connect(done); self._mouse_transition_group = grp; grp.start()\n''',
'mouse transition done 2')

# Main state transition lifecycle.
s = rep(s,
'''                if self.anim_group:\n                    self.anim_group.stop()\n''',
'''                if self.anim_group:\n                    self._dispose_animation_group("anim_group")\n''',
'anim group dispose')

s = rep(s,
'''                def done():\n                    if self.movies[old]:\n                        self.movies[old].stop()\n                    self.current_slot = new\n                grp.finished.connect(done)\n                self.anim_group = grp\n                grp.start()\n''',
'''                def done():\n                    self._release_movie_slot(old)\n                    self.current_slot = new\n                    if self.anim_group is grp:\n                        self.anim_group = None\n                    grp.deleteLater()\n                grp.finished.connect(done)\n                self.anim_group = grp\n                grp.start()\n''',
'anim group done')

# Immediate state swaps should free the hidden slot, not merely stop it.
s = s.replace('''                if self.movies[old]:\n                    self.movies[old].stop()\n                self.current_slot = next_slot\n''',
'''                self._release_movie_slot(old)\n                self.current_slot = next_slot\n''')

# Dialogue swap should also free the hidden slot.
s = rep(s,
'''        old = self.current_slot\n        if self.movies[old]: self.movies[old].stop()\n        self.current_slot = new; self.current_state = "dialogue"\n''',
'''        old = self.current_slot\n        self._release_movie_slot(old)\n        self.current_slot = new; self.current_state = "dialogue"\n''',
'dialogue old movie release')

# Thinking-state de-duplication: prevent state_changed -> singleShot -> state_changed feedback loop.
s = rep(s,
'''        self._speech_cache_waiting=False\n\n        self.bridge.trigger_state.connect(self.pet.play_state)\n''',
'''        self._speech_cache_waiting=False\n        self._speech_last_state_emitted=None\n        self._speech_thinking_restore_pending=False\n        self._speech_resume_guard_token=0\n\n        self.bridge.trigger_state.connect(self.pet.play_state)\n''',
'speech lifecycle fields')

s = rep(s,
'''    def _speech_state(self, code, label):\n        try: self.speech_service._emit_state(str(code), str(label))\n        except Exception: pass\n''',
'''    def _speech_state(self, code, label):\n        key=(str(code),str(label))\n        if key == getattr(self,"_speech_last_state_emitted",None):\n            return\n        self._speech_last_state_emitted=key\n        try: self.speech_service._emit_state(*key)\n        except Exception: pass\n''',
'speech state dedupe')

s = rep(s,
'''    def _on_speech_engine_state(self, code, label):\n        interaction_diag_note("speech_state",code=str(code or ""))\n        if self._speech_session_active and not self._speech_waiting_question:\n            if self._speech_waiting_brain:\n                QTimer.singleShot(0,lambda:self._speech_state("thinking","小美丽正在想"))\n            return\n''',
'''    def _on_speech_engine_state(self, code, label):\n        code=str(code or "")\n        label=str(label or "")\n        self._speech_last_state_emitted=(code,label)\n        interaction_diag_note("speech_state",code=code)\n        if self._speech_session_active and self._speech_waiting_brain and code != "thinking":\n            if not self._speech_thinking_restore_pending:\n                self._speech_thinking_restore_pending=True\n                def restore_thinking():\n                    self._speech_thinking_restore_pending=False\n                    if self._speech_session_active and self._speech_waiting_brain:\n                        self._speech_state("thinking","小美丽正在想")\n                QTimer.singleShot(0,restore_thinking)\n            return\n''',
'thinking feedback fix')

# Add hard-silence classifier and handler before existing interrupt callback.
anchor = '''    def _on_speech_interrupt(self, text):\n'''
insert = '''    @staticmethod\n    def _is_hard_silence_command(text):\n        raw=re.sub(r"[\\s，,。.!！？?、:：；;~～]+","",str(text or "")).lower()\n        if not raw:\n            return False\n        phrases=(\n            "闭嘴","给我闭嘴","你给我闭嘴","别说话","别说话了","你别说话了",\n            "先别说话","不要说话","别说了","不要说了","别讲了","别讲",\n            "不要讲话","别讲话","停止说话","停一下","安静","安静点","安静一下","住嘴",\n        )\n        if any(p in raw for p in phrases):\n            return True\n        if len(raw)>14:\n            return False\n        try:\n            from difflib import SequenceMatcher\n            return max(SequenceMatcher(None,raw,p).ratio() for p in phrases)>=0.78\n        except Exception:\n            return False\n\n    def _hard_silence_now(self, text=""):\n        interaction_diag_note("hard_silence",chars=len(str(text or "")))\n        LOGGER.info("[HARD_SILENCE] local P0 interrupt: %r", text)\n        self._speech_session_token += 1\n        self._speech_session_active = False\n        self._speech_waiting_question = False\n        self._speech_waiting_brain = False\n        self._speech_pending_question = ""\n        self._speech_thinking_restore_pending=False\n        setattr(self.brain_service, "_voice_session_request", False)\n        try:\n            self.brain_service.abort_current("hard_silence")\n        except Exception:\n            LOGGER.warning("闭嘴指令打断云端大脑失败", exc_info=True)\n        try:\n            self.voice_service.abort_playback("hard_silence")\n        except Exception:\n            LOGGER.warning("闭嘴指令打断语音播放失败", exc_info=True)\n        try:\n            if getattr(self.pet, "dialogue_board_active", False):\n                self.pet.dialogue_visual_generation += 1\n                self.pet._end_dialogue_board()\n        except Exception:\n            LOGGER.debug("闭嘴指令关闭白板失败", exc_info=True)\n        try:\n            self.pet.set_dialogue_indicator(False)\n        except Exception:\n            pass\n        # Do not answer the command. Resume wake-word standby only after a short\n        # output-tail guard so XiaoMeili cannot hear the end of its own TTS.\n        self._speech_resume_guard_token += 1\n        token=self._speech_resume_guard_token\n        self._speech_state("silenced", "已停止说话，等待“美丽美丽”")\n        def resume_after_tail():\n            if token != self._speech_resume_guard_token:\n                return\n            if bool(self._speech_cfg().get("enabled", True)) and self.speech_service.ready():\n                self.speech_service.resume()\n                self._speech_state("listening", "等待“美丽美丽”")\n            else:\n                self._speech_state("stopped", "语音监听已停止")\n        QTimer.singleShot(420,resume_after_tail)\n\n'''
if anchor not in s:
    raise RuntimeError('interrupt anchor')
s = s.replace(anchor, insert + anchor, 1)

# Route worker interrupt through one handler.
start = s.index('    def _on_speech_interrupt(self, text):\n')
end = s.index('    def _on_speech_utterance(self, text):\n', start)
s = s[:start] + '''    def _on_speech_interrupt(self, text):\n        interaction_diag_note("voice_interrupt")\n        if not (self._speech_session_active or self._speech_waiting_brain or self.voice_service.cloud_stream_in_progress()):\n            return\n        self._hard_silence_now(text)\n\n''' + s[end:]

# P0 command check on every recognized utterance, before wake/brain routing.
s = rep(s,
'''    def _on_speech_utterance(self, text):\n        text=str(text or "").strip()\n        if not text:return\n        interaction_diag_note("speech_utterance",chars=len(text))\n        if not self._speech_session_active:\n''',
'''    def _on_speech_utterance(self, text):\n        text=str(text or "").strip()\n        if not text:return\n        interaction_diag_note("speech_utterance",chars=len(text))\n        if self._is_hard_silence_command(text):\n            if self._speech_session_active or self._speech_waiting_brain or self.voice_service.cloud_stream_in_progress():\n                self._hard_silence_now(text)\n            return\n        if not self._speech_session_active:\n''',
'hard silence before brain')

# Delay normal follow-up listening slightly to avoid TTS tail self-feedback.
s = rep(s,
'''        self._speech_waiting_question=True\n        self._speech_waiting_brain=False\n        self._speech_state("listening","正在听你继续说")\n        self.speech_service.resume()\n        token=self._speech_session_token\n        timeout=max(5000,int(self._speech_cfg().get("listen_timeout_ms",15000)))\n        QTimer.singleShot(timeout,lambda t=token:self._speech_listen_timeout(t))\n''',
'''        self._speech_waiting_question=True\n        self._speech_waiting_brain=False\n        token=self._speech_session_token\n        self._speech_resume_guard_token += 1\n        guard=self._speech_resume_guard_token\n        self._speech_state("listening","正在听你继续说")\n        def resume_followup():\n            if guard != self._speech_resume_guard_token or token != self._speech_session_token or not self._speech_session_active:\n                return\n            self.speech_service.resume()\n        QTimer.singleShot(320,resume_followup)\n        timeout=max(5000,int(self._speech_cfg().get("listen_timeout_ms",15000)))\n        QTimer.singleShot(timeout,lambda t=token:self._speech_listen_timeout(t))\n''',
'post TTS echo guard')

# NDM update: fast fallback only when no file appears / no progress; active downloads can still run for hours.
s = rep(s,
'''                                progress_cb=ndm_note,\n                                timeout_seconds=6 * 3600,\n                            )\n''',
'''                                progress_cb=ndm_note,\n                                timeout_seconds=6 * 3600,\n                                appearance_timeout_seconds=25,\n                                stall_timeout_seconds=75,\n                            )\n''',
'NDM fast fallback args')

# Source export wording now truthful because the build embeds the exact source snapshot.
s = s.replace('当前 V{APP_VERSION} 完整可编辑源码快照已随程序提供',
              '当前 V{APP_VERSION} 完整可编辑源码快照已随程序内置')

wr(main, s)

# ---------------- speech_input.py ----------------
s = rd(speech)
# Broaden hotwords for the common natural commands.
s = s.replace(
    '闭嘴 别说话 别说了 不要说了 安静 停一下 停止说话 别讲了 住嘴',
    '闭嘴 给我闭嘴 你给我闭嘴 别说话 你别说话了 先别说话 别说了 不要说了 安静 安静点 停一下 停止说话 别讲了 住嘴')

s = rep(s,
'''    paused = threading.Event()\n    stopping = threading.Event()\n    interrupt_only = threading.Event()\n    q = queue.Queue(maxsize=30)\n''',
'''    paused = threading.Event()\n    stopping = threading.Event()\n    interrupt_only = threading.Event()\n    reset_capture = threading.Event()\n    q = queue.Queue(maxsize=30)\n''',
'speech reset event')

s = rep(s,
'''        phrases = ("闭嘴","别说话","别说了","不要说了","安静","停一下","停止说话","别讲了","别讲","住嘴","不要讲话","别讲话")\n''',
'''        phrases = ("闭嘴","给我闭嘴","你给我闭嘴","别说话","别说话了","你别说话了","先别说话","不要说话","别说了","不要说了","安静","安静点","安静一下","停一下","停止说话","别讲了","别讲","住嘴","不要讲话","别讲话")\n''',
'interrupt phrases')

s = s.replace('''            elif cmd == "interrupt":\n                paused.clear(); interrupt_only.set()\n                emit("state", code="interrupt", label="可说“闭嘴”立即打断")\n            elif cmd == "resume":\n                interrupt_only.clear(); paused.clear()\n                emit("state", code="listening", label="等待“美丽美丽”")\n''',
'''            elif cmd == "interrupt":\n                paused.clear(); interrupt_only.set(); reset_capture.set()\n                emit("state", code="interrupt", label="可说“闭嘴”立即打断")\n            elif cmd == "resume":\n                interrupt_only.clear(); paused.clear(); reset_capture.set()\n                emit("state", code="listening", label="等待“美丽美丽”")\n''')

# Reset queued/VAD audio when switching modes. This prevents TTS tail audio from
# surviving the interrupt-only -> normal-listening boundary.
s = rep(s,
'''        while not stopping.is_set():\n            if paused.is_set():\n''',
'''        while not stopping.is_set():\n            if reset_capture.is_set():\n                reset_capture.clear()\n                vad_cache = {}; preroll = []; speech = []; active = False\n                active_peak_rms = 0.0; silent_chunks = 0; active_started_at = 0.0\n                try:\n                    while True: q.get_nowait()\n                except Exception:\n                    pass\n            if paused.is_set():\n''',
'reset capture loop')

# Faster energy endpoint while waiting only for interrupt commands.
s = rep(s,
'''                if silent_chunks >= silence_end_chunks and len(speech) >= 5:\n''',
'''                endpoint_chunks = 2 if interrupt_only.is_set() else silence_end_chunks\n                if silent_chunks >= endpoint_chunks and len(speech) >= 5:\n''',
'fast interrupt endpoint')

wr(speech, s)

# ---------------- ndm_bridge.py ----------------
s = rd(ndm)

# Real NDM may ignore the requested filename field and save the URL basename
# instead. Accept only two exact task-owned names: the unique requested name and
# the exact URL basename, and still require creation/modification after this task
# started. This keeps the no-guess/no-recursion safety rule while making the real
# NDM bridge usable.
s = rep(s,
'''def _candidate_files(root: Path, filename: str, started_at: float | None = None):
    """Return only exact task-owned filenames in the selected NDM directory.

    V0.10.0 deliberately does NOT recurse and does NOT guess by extension. If NDM
    ignores the requested filename, XiaoMeili falls back to its built-in downloader
    rather than risking adoption of an unrelated user file.
    """
    wanted = Path(filename).name
    wanted_lower = wanted.lower()
    allowed = {wanted_lower}
    for suffix in _TEMP_SUFFIXES:
        allowed.add((wanted + suffix).lower())
''',
'''def _candidate_files(root: Path, filename: str, started_at: float | None = None, aliases=()):
    """Return only exact task-owned filenames in the selected NDM directory.

    V0.10.0.9.2 accepts the unique requested name plus the exact URL basename,
    because real NDM can ignore field 4 and keep the URL filename. It still does
    not recurse, does not guess by extension, and requires task-time ownership.
    """
    names = [Path(filename).name]
    for alias in tuple(aliases or ()):
        alias_name = Path(str(alias or "")).name
        if alias_name and alias_name.lower() not in {x.lower() for x in names}:
            names.append(alias_name)
    allowed = set()
    for wanted in names:
        allowed.add(wanted.lower())
        for suffix in _TEMP_SUFFIXES:
            allowed.add((wanted + suffix).lower())
''',
'NDM exact URL basename candidates')

s = rep(s,
'''def _snapshot(root: Path, filename: str):
    snap = {}
    for p in _candidate_files(root, filename):
''',
'''def _snapshot(root: Path, filename: str, aliases=()):
    snap = {}
    for p in _candidate_files(root, filename, aliases=aliases):
''',
'NDM snapshot aliases')

s = rep(s,
'''    # Snapshot exact task names before sending. Pre-existing files are never adopted
    # merely because their name/extension happens to match.
    baseline = _snapshot(root, filename)
''',
'''    # Snapshot exact task names before sending. Pre-existing files are never adopted
    # merely because their name/extension happens to match.
    remote_name = Path(urlparse(str(url or "")).path).name
    aliases = tuple(
        x for x in (remote_name,)
        if x and x.lower() != Path(filename).name.lower()
    )
    baseline = _snapshot(root, filename, aliases=aliases)
''',
'NDM derive URL basename alias')

s = rep(s,
'''            _candidate_files(root, filename, started_at=started),
''',
'''            _candidate_files(root, filename, started_at=started, aliases=aliases),
''',
'NDM scan URL basename alias')
s = rep(s,
'''    progress_cb=None,\n    timeout_seconds=21600,\n):\n''',
'''    progress_cb=None,\n    timeout_seconds=21600,\n    appearance_timeout_seconds=None,\n    stall_timeout_seconds=None,\n):\n''',
'NDM timeout signature')

s = rep(s,
'''    last_bytes = 0\n    last_time = time.time()\n    last_seen = None\n    while time.time() - started < timeout_seconds:\n''',
'''    last_bytes = 0\n    last_time = time.time()\n    last_seen = None\n    last_progress_at = started\n    seen_owned_file = False\n    appearance_timeout = max(0.0, float(appearance_timeout_seconds or 0.0))\n    stall_timeout = max(0.0, float(stall_timeout_seconds or 0.0))\n    while time.time() - started < timeout_seconds:\n''',
'NDM progress tracking')

s = rep(s,
'''        if candidates:\n            p = candidates[0]\n            try:\n                st = p.stat()\n                now = time.time()\n                dt = max(0.2, now - last_time)\n                speed = max(0.0, (st.st_size - last_bytes) / dt) if last_seen == str(p) else 0.0\n                last_bytes = st.st_size\n                last_time = now\n                last_seen = str(p)\n''',
'''        if candidates:\n            p = candidates[0]\n            try:\n                st = p.stat()\n                now = time.time()\n                previous_bytes = last_bytes if last_seen == str(p) else 0\n                dt = max(0.2, now - last_time)\n                speed = max(0.0, (st.st_size - previous_bytes) / dt) if last_seen == str(p) else 0.0\n                if (not seen_owned_file) or last_seen != str(p) or st.st_size > previous_bytes:\n                    last_progress_at = now\n                seen_owned_file = True\n                last_bytes = st.st_size\n                last_time = now\n                last_seen = str(p)\n''',
'NDM progress update')

s = rep(s,
'''        else:\n            _emit(progress_cb, f"NDM 已接收任务，仍在等待文件出现在：{root}", 0, expected, 0)\n\n        time.sleep(0.8)\n''',
'''                if stall_timeout > 0 and (now - last_progress_at) >= stall_timeout:\n                    raise TimeoutError(\n                        f"NDM 任务已出现但连续 {int(stall_timeout)} 秒没有写入进度：{p.name}"\n                    )\n        else:\n            waited = time.time() - started\n            _emit(progress_cb, f"NDM 已接收任务，仍在等待文件出现在：{root}", 0, expected, 0)\n            if appearance_timeout > 0 and not seen_owned_file and waited >= appearance_timeout:\n                raise TimeoutError(\n                    f"NDM 已接收任务但 {int(appearance_timeout)} 秒内没有创建本次下载文件"\n                )\n\n        time.sleep(0.8)\n''',
'NDM early fallback')

wr(ndm, s)

# ---------------- voice_dual.py ----------------
s = rd(voice)
# Make completion/abort drop heavy context references immediately after stream close.
s = rep(s,
'''        try:\n            if stream:\n                time.sleep(0.05)\n                stream.stop(ignore_errors=True)\n                stream.close(ignore_errors=True)\n        except Exception:\n            pass\n\n        usage = dict(ctx.get("usage") or {})\n''',
'''        try:\n            if stream:\n                time.sleep(0.05)\n                stream.stop(ignore_errors=True)\n                stream.close(ignore_errors=True)\n        except Exception:\n            pass\n        ctx["stream"] = None\n        ctx["tts"] = None\n        ctx["queue"] = None\n        ctx["pending"] = ""\n\n        usage = dict(ctx.get("usage") or {})\n''',
'cloud TTS ctx release')

s = rep(s,
'''        if q:\n            q.put(("abort", str(reason or "")))\n        try:\n            if stream:\n                stream.abort(ignore_errors=True)\n                stream.close(ignore_errors=True)\n        except Exception:\n            pass\n        LOGGER.warning("[CLOUD_TTS] stream aborted: %s", reason)\n''',
'''        if q:\n            q.put(("abort", str(reason or "")))\n        try:\n            if stream:\n                stream.abort(ignore_errors=True)\n                stream.close(ignore_errors=True)\n        except Exception:\n            pass\n        ctx["stream"] = None\n        ctx["tts"] = None\n        ctx["pending"] = ""\n        LOGGER.warning("[CLOUD_TTS] stream aborted: %s", reason)\n''',
'cloud TTS abort release')

wr(voice, s)

(root / 'app' / 'assets' / 'VERSION.txt').write_text('0.10.0.9.2\n', encoding='ascii')

changelog = root / 'V010092_CHANGELOG.txt'
changelog.write_text('''XiaoMeili V0.10.0.9.2\n\n1. 长聊稳定性\n- QMovie 改为 CacheNone，状态/白板动画替换前显式 stop/disconnect/clear/deleteLater。\n- 过渡 QParallelAnimationGroup 完成后 deleteLater，避免 QObject 子对象长期堆积。\n- 云端 TTS 完成/打断后释放 stream/tts/queue/pending 引用。\n- thinking 状态恢复去重，修复 state_changed -> singleShot -> state_changed 自反馈。\n\n2. “闭嘴”P0 本地硬打断\n- 所有 ASR 文本先检查“闭嘴/你给我闭嘴/你别说话了/别说了/安静点”等指令，再决定是否送入大脑。\n- 命中后立即终止大脑、TTS、白板/字幕，不生成任何回复。\n- TTS 结束后增加短暂回声保护并清空语音捕获队列，降低小美丽听到自己尾音的概率。\n\n3. NDM\n- 更新仍优先 NDM；连接后 25 秒未创建本次文件，或已创建但连续 75 秒无写入进度，立即回退内置 HTTPS。\n- 正常持续写入时仍允许长时间下载，不用固定短超时误杀慢速下载。\n- NDM 下载源文件只复制到小美丽受控 staging，不移动、不删除。\n\n4. FullSafe\n- 更新器只新建 %LOCALAPPDATA%\\XiaoMeiliApp\\versions 下的新版本并切换 active.json。\n- 不删除、不移动、不递归清理桌面、下载、文档、D盘、XiaoMeiliData 或旧版本。\n- 发布前执行 no-delete 合约与功能测试。\n\n5. 源码工程导出\n- 发布流水线先生成 XiaoMeili_V0.10.0.9.2_SourceProject.zip，再把同一份快照嵌入程序 assets 后构建 EXE。\n- “打包完整原始源码工程”按钮可直接导出当前版本源码，不覆盖同名用户文件。\n''', encoding='utf-8')

for p in (main, speech, ndm, voice):
    py_compile.compile(str(p), doraise=True)

combined = rd(main) + rd(speech) + rd(ndm) + rd(voice)
checks = [
    'APP_VERSION = "0.10.0.9.2"',
    'QMovie.CacheMode.CacheNone',
    '_release_movie_slot',
    '_speech_thinking_restore_pending',
    '_is_hard_silence_command',
    '_hard_silence_now',
    'appearance_timeout_seconds=25',
    'stall_timeout_seconds=75',
    'ctx["queue"] = None',
]
for x in checks:
    if x not in combined:
        raise RuntimeError(f'contract missing: {x}')
print('PATCH_010092_PASS')