# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7.3 patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    voice_path = source_root / "app" / "src" / "voice_qwen.py"
    voice_src = repo_root / "build" / "v073" / "voice_qwen_v073.py"
    if not all(p.exists() for p in (main_path, brain_path, voice_src)):
        raise FileNotFoundError("v0.7.3 source inputs missing")
    shutil.copy2(voice_src, voice_path)

    # ---------------- main.py ----------------
    s = main_path.read_text(encoding="utf-8")
    s = must(
        s,
        'APP_NAME = "小美丽 V0.7.2｜NDM Progress Fix + Local Brain + Qwen3-TTS"\nAPP_VERSION = "0.7.2"',
        'APP_NAME = "小美丽 V0.7.3｜Result Screen 2026 + Clean Chat + Girl Voices"\nAPP_VERSION = "0.7.3"',
        "version",
    )
    s = must(s, '"config_version": 20,', '"config_version": 21,', "config version")

    mig = '    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})\n\n'
    mig_new = '''    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})
    if "你的回答最终必须是一个JSON对象" in str(cfg["brain"].get("persona", "")):
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

        self.voice_design_btn = QPushButton("安装小女孩声线扩展（可选，约 4.5 GB）")
        self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
        self.voice_design_btn.clicked.connect(self._prepare_voice_design)
        vf2.addRow(self.voice_design_btn)

        self.voice_combo'''
    s = must(s, voice_prepare_anchor, voice_prepare_new, "voice design button")

    old_voice_note = '''            "说明：Qwen3-TTS 运行环境和模型只会保存在本机 XiaoMeiliData 中。选定后，后续语音对话版本直接复用这个固定声线，"
            "你不需要再打开任何 TTS 软件。"'''
    new_voice_note = '''            "说明：CustomVoice 官方原生中文女声身份只有 Vivian 和 Serena；原有多个名称主要是同一声音的不同说话风格。"
            "V0.7.3 新增可选 VoiceDesign 小女孩声线扩展，会生成真正不同的虚拟小女孩声线。所有模型只保存在本机。"'''
    if old_voice_note in s:
        s = s.replace(old_voice_note, new_voice_note, 1)

    handler_anchor = '    def _prepare_voice_components(self):\n'
    design_handler = '''    def _prepare_voice_design(self):
        if not self.voice_service.ready():
            QMessageBox.information(self, "小女孩声线扩展", "请先准备基础 Qwen3-TTS 语音组件。")
            return
        self.voice_design_btn.setEnabled(False)
        self.voice_status.setText("正在准备小女孩声线扩展。首次约 4.5 GB，完成后以后可离线使用。")
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

    old_chat = '''        self.brain_chat.addItem(f"小美丽：{spoken}")
        self.brain_chat.addItem(f"〔白板草稿｜{emotion}〕{board.replace(chr(10),' / ')}")
        self.brain_chat.scrollToBottom()
'''
    new_chat = '''        self.brain_chat.addItem(f"小美丽：{spoken}")
        self.brain_chat.scrollToBottom()
'''
    s = must(s, old_chat, new_chat, "clean chat display")

    s = s.replace('"小美丽人格卡"', '"小美丽性格卡（只影响她怎么说话）"', 1)
    persona_note_old = '''            "现在的👍/👎不是重新训练模型，而是在本地记录“主人喜欢/纠正的答案”，之后相似问题会作为示例喂给小美丽。"
            "等积累到足够多的高质量样本后，再考虑 LoRA 微调。所有聊天样本都只保存在本机 XiaoMeiliData/brain。"'''
    persona_note_new = '''            "性格卡可以直接修改，她下一次回答就会按新的性格说话，不需要训练。程序内部的 JSON 输出协议已经隐藏并锁定，不需要你维护。"
            "👍/👎会继续积累本地养成样本；等样本足够多后再考虑 LoRA 微调。"'''
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
    new_persona = '''DEFAULT_PERSONA = """你叫“小美丽”，是一只住在电脑桌面上的可爱小女孩虚拟伙伴。
你和主人关系很熟，会自然聊天、会吐槽、会嘴硬，也会在该关心的时候关心。
你熟悉《无畏契约 / VALORANT》，尤其知道贤者（Sage）的常见玩法和直播语境。
说中文时必须像中国小女孩的自然口语，不要客服腔，不要写作文，不要自称AI。
普通闲聊默认只回答1句话，尽量控制在10到28个汉字；除非主人明确要求详细解释。
可以俏皮、清冷、得意或吐槽，但不要无缘无故攻击主人。
不知道的现实事实就直接说不知道，不编造。
如果主人只是随便聊天，就像桌面伙伴一样回应，简单、直接、有性格。"""

OUTPUT_CONTRACT = """
程序内部格式要求：最终必须返回一个JSON对象，不要输出JSON之外的任何文字。
JSON只允许三个字段：
spoken_text：真正说出口的中文回答。绝不能包含 spoken_text、board_text、emotion 这些字段名；
board_text：最多两行的中文短句，供以后白板使用；
emotion：只能是 neutral、happy、teasing、proud、annoyed、concerned 之一。
普通闲聊的 spoken_text 默认一句话，短、自然、中文优先。
"""
'''
    b = b[:start] + new_persona + b[end:]

    old_norm_start = b.index('def _normalize_answer(raw: str):')
    old_norm_end = b.index('\n\n\nclass BrainService', old_norm_start)
    new_norm = r'''def _clean_field_value(value: str):
    value = str(value or "").strip()
    value = value.strip("`").strip().strip('"').strip("'")
    for marker in ("board_text", "emotion", "spoken_text"):
        m = re.search(rf"(?im)^\s*{re.escape(marker)}\s*[:：=]", value)
        if m and m.start() > 0:
            value = value[:m.start()].strip()
    value = re.sub(r"(?i)^\s*(spoken_text|spoken text|回答|小美丽)\s*[:：=]\s*", "", value).strip()
    return value


def _loose_field(text: str, key: str):
    pattern = rf"(?ims)(?:^|[\n{{,])\s*[\"']?{re.escape(key)}[\"']?\s*[:：=]\s*[\"']?(.*?)(?=\n\s*[\"']?(?:spoken_text|board_text|emotion)[\"']?\s*[:：=]|\s*[,}}]\s*[\"']?(?:spoken_text|board_text|emotion)[\"']?\s*[:：=]|\Z)"
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
                if re.match(r"(?i)^\s*(spoken_text|board_text|emotion)\s*[:：=]", line):
                    continue
                natural.append(line)
            spoken = _clean_field_value(natural[0] if natural else clean)

    if not spoken:
        spoken = "我刚刚脑袋短路了一下，再问我一次。"
    spoken = re.sub(r"(?i)\b(spoken_text|board_text|emotion)\b\s*[:：=]?", "", spoken).strip()
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
        '                system = str(persona or DEFAULTPERSONA).strip()\n',
        '                system = str(persona or DEFAULTPERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n',
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
                LOGGER.info("已清理 NDM 小美丽残留：%s (%.1f MB)", p, size/1024/1024)
            except Exception:
                LOGGGER.warning("清理出e�� NDM 段留失败：%s", p, exc_info=True)
        if removed:
            LOGGER.info("NDM残留自动清理完成：%d 个文件，释放 %.1f MB", removed, reclaimed/1024/1024)
        return {"removed": removed, "bytes": reclaimed}

'''
    if shutdown_anchor not in b:
        raise RuntimeError("brain shutdown anchor missing")
    b = b.replace(shutdown_anchor, cleanup_method + shutdown_anchor, 1)

    brain_path.write_text(b, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    py_compile.compile(str(voice_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.3")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v073.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
