# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch anchor missing: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    req_path = source_root / "app" / "requirements.txt"
    voice_src = repo_root / "build" / "v062" / "voice_qwen.py"
    voice_dst = source_root / "app" / "src" / "voice_qwen.py"
    if not main_path.exists():
        raise FileNotFoundError(main_path)
    if not voice_src.exists():
        raise FileNotFoundError(voice_src)
    shutil.copy2(voice_src, voice_dst)

    s = main_path.read_text(encoding="utf-8")
    s = must_replace(s,
        'APP_NAME = "小美丽 V0.6.1.1｜Voice Mouth + Continuous Puppet V2"\nAPP_VERSION = "0.6.1.1"',
        'APP_NAME = "小美丽 V0.6.2｜Qwen3-TTS Voice Mouth + Continuous Puppet V2"\nAPP_VERSION = "0.6.2"',
        "version")
    s = must_replace(s,
        '"manifest_url": "",\n            "auto_check": True,',
        '"manifest_url": "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest.json",\n            "auto_check": True,',
        "default update manifest")
    s = must_replace(s,
        'cfg["voice"].update({k: v for k, v in old_voice.items() if k in cfg["voice"]})\n\n    old_updates =',
        'cfg["voice"].update({k: v for k, v in old_voice.items() if k in cfg["voice"]})\n    if str(cfg["voice"].get("voice_id", "")).startswith("zf_"):\n        cfg["voice"]["voice_id"] = ""\n\n    old_updates =',
        "Kokoro voice migration")

    start = s.index("# V0.6 local voice subsystem")
    start = s.rfind("# ----------------------------", 0, start)
    end_anchor = "# V0.6.1.1 self-update subsystem"
    end_mid = s.index(end_anchor, start)
    replacement = """# ----------------------------
# V0.6.2 local voice subsystem
# ----------------------------
# Heavy Qwen3-TTS dependencies live in a separate first-use runtime so the
# desktop pet EXE stays small and future app updates do not redownload models.

# V0.6.2: native-Chinese Qwen3-TTS backend. The old Kokoro backend is intentionally not used.
from voice_qwen import VoiceService

# ----------------------------
# V0.6.2 self-update subsystem
# ----------------------------
"""
    hdr_end = s.index("def _version_tuple", end_mid)
    s = s[:start] + replacement + s[hdr_end:]

    replacements = [
        ('"V0.6 第一阶段只给小美丽装上“嘴”：先从 Kokoro 中文女声库里试听并选定一个固定声音。"',
         '"V0.6.2 已更换为阿里 Qwen3-TTS 1.7B 中文语音：优先普通话自然度和中文咬字，试听后选定一个固定声线。"',
         "voice intro"),
        ('QPushButton("准备语音组件（首次约 380 MB）")',
         'QPushButton("准备 Qwen3-TTS（首次约 7–9 GB）")',
         "prepare button"),
        ('"说明：模型和声音库只会保存在本机 XiaoMeiliData/voice 中。选定后，后续语音对话版本直接复用这个 voice ID，"',
         '"说明：Qwen3-TTS 运行环境和模型只会保存在本机 XiaoMeiliData 中。选定后，后续语音对话版本直接复用这个固定声线，"',
         "voice note"),
        ('"从 V0.6.1 起，小美丽内置自更新器。以后只要更新源已经绑定，修复 Bug 或增加功能都可以直接在这里检查并更新，不再重新下载整包。"',
         '"从 V0.6.1 起，小美丽内置自更新器。V0.6.2 已固定官方 GitHub 更新源，后续修复或功能增加都在这里直接更新。"',
         "update intro"),
        ('voices = [str(v) for v in (voices or []) if str(v).startswith("zf_")]',
         'voices = [str(v) for v in (voices or [])]',
         "voice filter"),
        ('for idx, vid in enumerate(voices, start=1):\n            suffix = vid.split("_",1)[-1]\n            self.voice_combo.addItem(f"女声 {suffix}  ·  {vid}", vid)',
         'for idx, vid in enumerate(voices, start=1):\n            try:\n                display = self.voice_service.display_name(vid)\n            except Exception:\n                display = str(vid)\n            self.voice_combo.addItem(display, vid)',
         "voice display"),
        ('self.voice_status.setText(f"声音库已就绪：{self.voice_combo.count()} 个中文女声可试听。")',
         'self.voice_status.setText(f"Qwen3-TTS 已就绪：{self.voice_combo.count()} 个小美丽候选声线可试听。")',
         "ready status"),
        ('self.voice_status.setText("语音组件已下载，但没有读取到中文女声。请查看日志。")',
         'self.voice_status.setText("Qwen3-TTS 已准备，但没有读取到候选声线。请查看桌面错误日志。")',
         "empty status"),
        ('self.voice_fixed_label.setText(f"当前固定：{vid}")\n        self.voice_status.setText(f"已固定为 {vid}。后续小美丽所有语音都默认使用这个声音。")',
         'self.voice_fixed_label.setText(f"当前固定：{self.voice_service.display_name(vid) if hasattr(self.voice_service, \'display_name\') else vid}")\n        self.voice_status.setText(f"已固定为 {self.voice_service.display_name(vid) if hasattr(self.voice_service, \'display_name\') else vid}。后续小美丽所有语音都默认使用这个声线。")',
         "fixed label"),
        ('self.pet.lock_bubble.hide(); self.hotkeys.unregister_all(); self.vision.stop(); self.vision.wait(1800)\n            LOGGER.info("正常退出")',
         'self.pet.lock_bubble.hide(); self.hotkeys.unregister_all(); self.vision.stop(); self.vision.wait(1800)\n            try: self.voice_service.shutdown()\n            except Exception: pass\n            LOGGER.info("正常退出")',
         "voice shutdown"),
    ]
    for old, new, label in replacements:
        s = must_replace(s, old, new, label)

    old_test = """def runtime_self_test():
    import espeakng_loader
    lib = Path(espeakng_loader.get_library_path())
    data = Path(espeakng_loader.get_data_path())
    if not lib.exists():
        raise FileNotFoundError(f"espeak library missing: {lib}")
    if not data.exists():
        raise FileNotFoundError(f"espeak data missing: {data}")
    from kokoro_onnx import Kokoro, EspeakConfig
    from misaki import zh
    _ = EspeakConfig(lib_path=str(lib), data_path=str(data))
    _ = zh.ZHG2P(version=None)
    return True
"""
    new_test = """def runtime_self_test():
    # Qwen3-TTS is installed into an isolated external runtime on first use.
    # The frozen desktop app only verifies the lightweight bridge module.
    from voice_qwen import VoiceService
    _ = VoiceService
    return True
"""
    s = must_replace(s, old_test, new_test, "runtime self test")
    main_path.write_text(s, encoding="utf-8")

    req_lines = req_path.read_text(encoding="utf-8").splitlines()
    banned = ("kokoro-onnx", "espeakng-loader", "misaki[")
    req_lines = [ln for ln in req_lines if not ln.strip().lower().startswith(banned)]
    req_path.write_text("\n".join(req_lines).rstrip() + "\n", encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(voice_dst), doraise=True)
    print(f"Patched XiaoMeili source to V0.6.2: {source_root}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v062.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
