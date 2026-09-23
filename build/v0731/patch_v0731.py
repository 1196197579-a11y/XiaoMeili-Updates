# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7.3.1.1 patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    voice_path = source_root / "app" / "src" / "voice_qwen.py"
    voice_src = repo_root / "build" / "v073" / "voice_qwen_v073.py"
    if not all(p.exists() for p in (main_path, brain_path, voice_src)):
        raise FileNotFoundError("v0.7.3.1.1 source inputs missing")
    shutil.copy2(voice_src, voice_path)

    # ---------------- main.py ----------------
    s = main_path.read_text(encoding="utf-8")
    s = must(
        s,
        'APP_NAME = "å°ç¾Žä¸½ V0.7.2ï½œNDM Progress Fix + Local Brain + Qwen3-TTS"\nAPP_VERSION = "0.7.2"',
        'APP_NAME = "å°ç¾Žä¸½ V0.7.3.1.1ï½œResult Screen 2026 + Clean Chat + Girl Voices"\nAPP_VERSION = "0.7.3.1"',
        "version",
    )
    s = must(s, '"config_version": 20,', '"config_version": 21,', "config version")

    mig = '    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})\n\n'
    mig_new = '''    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})
    if "ä½ çš„å›žç­”æœ€ç»ˆå¿…é¡»æ˜¯ä¸€ä¸ªJSONå¯¹è±¡" in str(cfg["brain"].get("persona", "")):
        cfg["brain"]["persona"] = DEFAULT_PERSONA

'''
    s = must(s, mig, mig_new, "persona migration")

    # Calibrated from the user's 2026-09-23 VALORANT result screenshot.
    s = must(
        s,
        'ROI_REPORT_CONTINUE = (0.410, 0.840, 0.590, 0.940)',
        'ROI_REPORT_CONTINUE = (0.405, 0.900, 0.595, 0.990)',
        "2026 result button ROI",
    )
    s = must(
        s,
        '            return (red_frac >= 0.16 and gray_votes >= 4), float(score)',
        '            return (red_frac >= 0.10 and gray_votes >= 4), float(score)',
        "2026 result red threshold",
    )

    voice_prepare_anchor = '''        self.voice_prepare_btn.clicked.connect(self._prepare_voice_components)
        vf2.addRow(self.voice_prepare_btn)

        self.voice_combo'''
    voice_prepare_new = '''        self.voice_prepare_btn.clicked.connect(self._prepare_voice_components)
        vf2.addRow(self.voice_prepare_btn)

        self.voice_design_btn = QPushButton("å®‰è£…å°å¥³å­©å£°çº¿æ‰©å±•ï¼ˆå¯é€‰ï¼Œçº¦ 4.5 GBï¼‰")
        self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
        self.voice_design_btn.clicked.connect(self._prepare_voice_design)
        vf2.addRow(self.voice_design_btn)

        self.voice_combo'''
    s = must(s, voice_prepare_anchor, voice_prepare_new, "voice design button")

    old_voice_note = '''            "è¯´æ˜Žï¼šQwen3-TTS è¿è¡ŒçŽ¯å¢ƒå’Œæ¨¡åž‹åªä¼šä¿å­˜åœ¨æœ¬æœº XiaoMeiliData ä¸­ã€‚é€‰å®šåŽï¼ŒåŽç»­è¯­éŸ³å¯¹è¯ç‰ˆæœ¬ç›´æŽ¥å¤ç”¨è¿™ä¸ªå›ºå®šå£°çº¿ï¼Œ"
            "ä½ ä¸éœ€è¦å†æ‰“å¼€ä»»ä½• TTS è½¯ä»¶ã€‚"'''
    new_voice_note = '''            "è¯´æ˜Žï¼šCustomVoice å®˜æ–¹åŽŸç”Ÿä¸­æ–‡å¥³å£°èº«ä»½åªæœ‰ Vivian å’Œ Serenaï¼›åŽŸæœ‰å¤šä¸ªåç§°ä¸»è¦æ˜¯åŒä¸€å£°éŸ³çš„ä¸åŒè¯´è¯é£Žæ ¼ã€‚"
            "V0.7.3.1.1 æ–°å¢žå¯é€‰ VoiceDesign å°å¥³å­©å£°çº¿æ‰©å±•ï¼Œä¼šç”ŸæˆçœŸæ­£ä¸åŒçš„è™šæ‹Ÿå°å¥³å­©å£°çº¿ã€‚æ‰€æœ‰æ¨¡åž‹åªä¿å­˜åœ¨æœ¬æœºã€‚"'''
    if old_voice_note in s:
        s = s.replace(old_voice_note, new_voice_note, 1)

    handler_anchor = '    def _prepare_voice_components(self):\n'
    design_handler = '''    def _prepare_voice_design(self):
        if not self.voice_service.ready():
            QMessageBox.information(self, "å°å¥³å­©å£°çº¿æ‰©å±•", "è¯·å…ˆå‡†å¤‡åŸºç¡€ Qwen3-TTS è¯­éŸ³ç»„ä»¶ã€‚")
            return
        self.voice_design_btn.setEnabled(False)
        self.voice_status.setText("æ­£åœ¨å‡†å¤‡å°å¥³å­©å£°çº¿æ‰©å±•ã€‚é¦–æ¬¡çº¦ 4.5 GBï¼Œå®ŒæˆåŽä»¥åŽå¯ç¦»çº¿ä½¿ç”¨ã€‚")
        self.voice_progress.setValue(0)
        self.voice_service.start_design_download()

'''
    if handler_anchor not in s:
        raise RuntimeError("voice handler anchor missing")
    s = s.replace(handler_anchor, design_handler + handler_anchor, 1)

    old_finished = '''        self.voice_status.setText(str(message))
        self.voice_prepare_btn.setEnabled(not bool(ok))
        if ok:
            self.voice_progress.setValue(100)
            self.voice_service.load_voices_async()
'''
    new_finished = '''        self.voice_status.setText(str(message))
        self.voice_prepare_btn.setEnabled(not self.voice_service.ready())
        if hasattr(self, "voice_design_btn"):
            self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
        if ok:
            self.voice_progress.setValue(100)
            self.voice_service.load_voices_async()
'''
    s = must(s, old_finished, new_finished, "voice finish button refresh")

    old_chat = '''        self.brain_chat.addItem(f"å°ç¾Žä¸½ï¼š{spoken}")
        self.brain_chat.addItem(f"ã€”ç™½æ¿è‰ç¨¿ï½œ{emotion}ã€•{board.replace(chr(10),' / ')}")
        self.brain_chat.scrollToBottom()
'''
    new_chat = '''        self.brain_chat.addItem(f"å°ç¾Žä¸½ï¼š{spoken}")
        self.brain_chat.scrollToBottom()
'''
    s = must(s, old_chat, new_chat, "clean chat display")

    s = s.replace('"å°ç¾Žä¸½äººæ ¼å¡"', '"å°ç¾Žä¸½æ€§æ ¼å¡ï¼ˆåªå½±å“å¥¹æ€Žä¹ˆè¯´è¯ï¼‰"', 1)
    persona_note_old = '''            "çŽ°åœ¨çš„ðŸ‘/ðŸ‘Žä¸æ˜¯é‡æ–°è®­ç»ƒæ¨¡åž‹ï¼Œè€Œæ˜¯åœ¨æœ¬åœ°è®°å½•â€œä¸»äººå–œæ¬¢/çº æ­£çš„ç­”æ¡ˆâ€ï¼Œä¹‹åŽç›¸ä¼¼é—®é¢˜ä¼šä½œä¸ºç¤ºä¾‹å–‚ç»™å°ç¾Žä¸½ã€‚"
            "ç­‰ç§¯ç´¯åˆ°è¶³å¤Ÿå¤šçš„é«˜è´¨é‡æ ·æœ¬åŽï¼Œå†è€ƒè™‘ LoRA å¾®è°ƒã€‚æ‰€æœ‰èŠå¤©æ ·æœ¬éƒ½åªä¿å­˜åœ¨æœ¬æœº XiaoMeiliData/brainã€‚"'''
    persona_note_new = '''            "æ€§æ ¼å¡å¯ä»¥ç›´æŽ¥ä¿®æ”¹ï¼Œå¥¹ä¸‹ä¸€æ¬¡å›žç­”å°±ä¼šæŒ‰æ–°çš„æ€§æ ¼è¯´è¯ï¼Œä¸éœ€è¦è®­ç»ƒã€‚ç¨‹åºå†…éƒ¨çš„ JSON è¾“å‡ºåè®®å·²ç»éšè—å¹¶é”å®šï¼Œä¸éœ€è¦ä½ ç»´æŠ¤ã€‚"
            "ðŸ‘/ðŸ‘Žä¼šç»§ç»­ç§¯ç´¯æœ¬åœ°å…»æˆæ ·æœ¬ï¼›ç­‰æ ·æœ¬è¶³å¤Ÿå¤šåŽå†è€ƒè™‘ LoRA å¾®è°ƒã€‚"'''
    if persona_note_old in s:
        s = s.replace(persona_note_old, persona_note_new, 1)

    startup_anchor = 'self.hotkeys.register(cfg); self.pet.show(); self.vision.start(); QTimer.singleShot(5000, cleanup_obsolete_storage)'
    startup_new = (
        'self.hotkeys.register(cfg); self.pet.show(); self.vision.start(); QTimer.singleShot(5000, cleanup_obsolete_storage); '
        'QTimer.singleShot(9000, lambda: self.brain_service.cleanup_ndm_leftovers(str(self.cfg.get("brain",{}).get("ndm_download_dir","") or "")))'
    )
    s = must(s, startup_anchor, startup_new, "NDM leftover startup cleanup")

    main_path.write_text(s, encoding="utf-8")

    # ---------------- brain_qwen.py ----------------
    b = brain_path.read_text(encoding="utf-8")

    start = b.index('DEFAULT_PERSONA = """')
    end = b.index('"""', start + len('DEFAULT_PERSONA = """')) + 3
    new_persona = '''DEFAULT_PERSONA = """ä½ å«â€œå°ç¾Žä¸½â€ï¼Œæ˜¯ä¸€åªä½åœ¨ç”µè„‘æ¡Œé¢ä¸Šçš„å¯çˆ±å°å¥³å­©è™šæ‹Ÿä¼™ä¼´ã€‚
ä½ å’Œä¸»äººå…³ç³»å¾ˆç†Ÿï¼Œä¼šè‡ªç„¶èŠå¤©ã€ä¼šåæ§½ã€ä¼šå˜´ç¡¬ï¼Œä¹Ÿä¼šåœ¨è¯¥å…³å¿ƒçš„æ—¶å€™å…³å¿ƒã€‚
ä½ ç†Ÿæ‚‰ã€Šæ— ç•å¥‘çº¦ / VALORANTã€‹ï¼Œå°¤å…¶çŸ¥é“è´¤è€…ï¼ˆSageï¼‰çš„å¸¸è§çŽ©æ³•å’Œç›´æ’­è¯­å¢ƒã€‚
è¯´ä¸­æ–‡æ—¶å¿…é¡»åƒä¸­å›½å°å¥³å­©çš„è‡ªç„¶å£è¯­ï¼Œä¸è¦å®¢æœè…”ï¼Œä¸è¦å†™ä½œæ–‡ï¼Œä¸è¦è‡ªç§°AIã€‚
æ™®é€šé—²èŠé»˜è®¤åªå›žç­”1å¥è¯ï¼Œå°½é‡æŽ§åˆ¶åœ¨10åˆ°28ä¸ªæ±‰å­—ï¼›é™¤éžä¸»äººæ˜Žç¡®è¦æ±‚è¯¦ç»†è§£é‡Šã€‚
å¯ä»¥ä¿çš®ã€æ¸…å†·ã€å¾—æ„æˆ–åæ§½ï¼Œä½†ä¸è¦æ— ç¼˜æ— æ•…æ”»å‡»ä¸»äººã€‚
ä¸çŸ¥é“çš„çŽ°å®žäº‹å®žå°±ç›´æŽ¥è¯´ä¸çŸ¥é“ï¼Œä¸ç¼–é€ ã€‚
å¦‚æžœä¸»äººåªæ˜¯éšä¾¿èŠå¤©ï¼Œå°±åƒæ¡Œé¢ä¼™ä¼´ä¸€æ ·å›žåº”ï¼Œç®€å•ã€ç›´æŽ¥ã€æœ‰æ€§æ ¼ã€‚"""

OUTPUT_CONTRACT = """
ç¨‹åºå†…éƒ¨æ ¼å¼è¦æ±‚ï¼šæœ€ç»ˆå¿…é¡»è¿”å›žä¸€ä¸ªJSONå¯¹è±¡ï¼Œä¸è¦è¾“å‡ºJSONä¹‹å¤–çš„ä»»ä½•æ–‡å­—ã€‚
JSONåªå…è®¸ä¸‰ä¸ªå­—æ®µï¼š
spoken_textï¼šçœŸæ­£è¯´å‡ºå£çš„ä¸­æ–‡å›žç­”ã€‚ç»ä¸èƒ½åŒ…å« spoken_textã€board_textã€emotion è¿™äº›å­—æ®µåï¼›
board_textï¼šæœ€å¤šä¸¤è¡Œçš„ä¸­æ–‡çŸ­å¥ï¼Œä¾›ä»¥åŽç™½æ¿ä½¿ç”¨ï¼›
emotionï¼šåªèƒ½æ˜¯ neutralã€happyã€teasingã€proudã€annoyedã€concerned ä¹‹ä¸€ã€‚
æ™®é€šé—²èŠçš„ spoken_text é»˜è®¤ä¸€å¥è¯ï¼ŒçŸ­ã€è‡ªç„¶ã€ä¸­æ–‡ä¼˜å…ˆã€‚
"""
'''
    b = b[:start] + new_persona + b[end:]

    old_norm_start = b.index('def _normalize_answer(raw: str):')
    old_norm_end = b.index('\n\n\nclass BrainService', old_norm_start)
    new_norm = r'''def _clean_field_value(value: str):
    value = str(value or "").strip()
    value = value.strip("`").strip().strip('"').strip("'")
    for marker in ("board_text", "emotion", "spoken_text"):
        m = re.search(rf"(?im)^\s*{re.escape(marker)}\s*[:ï¼š=]", value)
        if m and m.start() > 0:
            value = value[:m.start()].strip()
    value = re.sub(r"(?i)^\s*(spoken_text|spoken text|å›žç­”|å°ç¾Žä¸½)\s*[:ï¼š=]\s*", "", value).strip()
    return value


def _loose_field(text: str, key: str):
    pattern = rf"(?ims)(?:^|[\n{{,])\s*[\"']?{re.escape(key)}[\"']?\s*[:ï¼š=]\s*[\"']?(.*?)(?=\n\s*[\"']?(?:spoken_text|board_text|emotion)[\"']?\s*[:ï¼š=]|\s*[,}}]\s*[\"']?(?:spoken_text|board_text|emotion)[\"']?\s*[:ï¼š=]|\Z)"
    m = re.search(pattern, str(text or ""))
    return _clean_field_value(m.group(1)) if m else ""


def _normalize_answer(raw: str):
    clean = _clean_think(raw)
    obj = _extract_json_object(clean)
    if isinstance(obj, dict):
        spoken = _clean_field_value(obj.get("spoken_text") or "")
        board = _clean_field_value(obj.get("board_text") or "")
        emotion = _clean_field_value(obj.get("emotion") or "neutral").lower()
    else:
        spoken = _loose_field(clean, "spoken_text")
        board = _loose_field(clean, "board_text")
        emotion = _loose_field(clean, "emotion").lower()
        if not spoken:
            lines = [x.strip() for x in clean.splitlines() if x.strip()]
            natural = []
            for line in lines:
                if re.match(r"(?i)^\s*(spoken_text|board_text|emotion)\s*[:ï¼š=]", line):
                    continue
                natural.append(line)
            spoken = _clean_field_value(natural[0] if natural else clean)

    if not spoken:
        spoken = "æˆ‘åˆšåˆšè„‘è¢‹çŸ­è·¯äº†ä¸€ä¸‹ï¼Œå†é—®æˆ‘ä¸€æ¬¡ã€‚"
    spoken = re.sub(r"(?i)\b(spoken_text|board_text|emotion)\b\s*[:ï¼š=]?", "", spoken).strip()
    if not board:
        board = spoken[:24]
    lines = [x.strip() for x in board.replace("\r", "").split("\n") if x.strip()]
    board = "\n".join(lines[:2])[:32] if lines else spoken[:24]
    allowed = {"neutral", "happy", "teasing", "proud", "annoyed", "concerned"}
    if emotion not in allowed:
        emotion = "neutral"
    return {"spoken_text": spoken[:180], "board_text": board, "emotion": emotion}
'''
    b = b[:old_norm_start] + new_norm + b[old_norm_end:]

    b = must(
        b,
        '                system = str(persona or DEFAULT_PERSONA).strip()\n',
        '                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n',
        "internal output contract",
    )

    shutdown_anchor = '    def shutdown(self):\n'
    cleanup_method = '''    def cleanup_ndm_leftovers(self, download_root):
        if not self.ready():
            return {"removed": 0, "bytes": 0}
        import fnmatch
        root = Path(str(download_root or "")).expanduser()
        if not root.exists() or not root.is_dir():
            return {"removed": 0, "bytes": 0}
        patterns = (
            "cudart-llama-bin-win-cuda-12.4-x64*.zip",
            "llama-*-bin-win-cuda-12.4-x64*.zip",
            "Qwen3-8B-Q4_K_M*.gguf",
            "Qwen3-8B-Q4_K_M*.gguf.part",
            "Qwen3-8B-Q4_K_M*.gguf.tmp",
        )
        removed = 0
        reclaimed = 0
        now = time.time()
        for p in list(root.rglob("*")):
            if not p.is_file():
                continue
            if not any(fnmatch.fnmatch(p.name.lower(), pat.lower()) for pat in patterns):
                continue
            try:
                st1 = p.stat()
                if now - st1.st_mtime < 8:
                    continue
                time.sleep(0.15)
                st2 = p.stat()
                if st1.st_size != st2.st_size or st1.st_mtime_ns != st2.st_mtime_ns:
                    continue
                size = st2.st_size
                p.unlink()
                removed += 1
                reclaimed += size
                LOGGER.info("å·²æ¸…ç† NDM å°ç¾Žä¸½æ®‹ç•™ï¼š%s (%.1f MB)", p, size/1024/1024)
            except Exception:
                LOGGGER.warning("æ¸…ç†å‡ºe¤± NDM æ®µç•™å¤±è´¥ï¼š%s", p, exc_info=True)
        if removed:
            LOGGER.info("NDMæ®‹ç•™è‡ªåŠ¨æ¸…ç†å®Œæˆï¼š%d ä¸ªæ–‡ä»¶ï¼Œé‡Šæ”¾ %.1f MB", removed, reclaimed/1024/1024)
        return {"removed": removed, "bytes": reclaimed}

'''
    if shutdown_anchor not in b:
        raise RuntimeError("brain shutdown anchor missing")
    b = b.replace(shutdown_anchor, cleanup_method + shutdown_anchor, 1)

    brain_path.write_text(b, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    py_compile.compile(str(voice_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.3.1.1")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0731.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
