# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import re
import sys
from pathlib import Path

def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    voice_path = source_root / "app" / "src" / "voice_qwen.py"
    req_path = source_root / "app" / "requirements.txt"
    if not main_path.exists() or not voice_path.exists():
        raise FileNotFoundError("v0.6.2 base source not prepared")

    s = main_path.read_text(encoding="utf-8")

    # Version and every visible version label must derive from APP_VERSION.
    s = re.sub(r'APP_NAME = "小美丽 V0\.6\.2\.1｜[^"]*"\nAPP_VERSION = "0\.6\.2\.1"',
               'APP_NAME = "小美丽 V0.6.2.2｜Qwen3-TTS Voice Mouth + Output Routing"\nAPP_VERSION = "0.6.2.2"',
               s, count=1)
    if 'APP_VERSION = "0.6.2.2"' not in s:
        raise RuntimeError("version patch failed")
    s = replace_once(s, 'self.setWindowTitle("小美丽 V0.6.1 设置")',
                     'self.setWindowTitle(f"小美丽 V{APP_VERSION} 设置")', "settings dynamic title")
    s = replace_once(s, 'self.tabs.addTab(sp,"声音 V0.6.1")',
                     'self.tabs.addTab(sp, f"声音 V{APP_VERSION}")', "voice tab dynamic title")

    # Default playback routing config.
    s = replace_once(s,
        '"test_text": "美丽美丽，我在呢。今天又想让我陪你干嘛？",\n        },',
        '"test_text": "美丽美丽，我在呢。今天又想让我陪你干嘛？",\n            "output_device": "default",\n        },',
        "voice output config")

    # Make voice intro version dynamic.
    s = s.replace(
        '"V0.6.2 已更换为阿里 Qwen3-TTS 1.7B 中文语音：优先普通话自然度和中文咬字，试听后选定一个固定声线。"',
        'f"V{APP_VERSION} 使用阿里 Qwen3-TTS 1.7B 中文语音：优先普通话自然度和中文咬字，试听后选定一个固定声线。"',
        1,
    )

    # Playback device UI, persisted alongside the fixed voice.
    speed_anchor = 'vf2.addRow("语速", self.voice_speed)\n\n        self.voice_fixed_label'
    speed_insert = '''vf2.addRow("语速", self.voice_speed)

        output_row = QWidget(); output_l = QHBoxLayout(output_row); output_l.setContentsMargins(0,0,0,0)
        self.voice_output_combo = QComboBox(); self.voice_output_combo.setMinimumContentsLength(28)
        self.voice_output_refresh_btn = QPushButton("刷新")
        self.voice_output_refresh_btn.setToolTip("刷新 Windows 当前可用的播放设备")
        self.voice_output_refresh_btn.clicked.connect(self._populate_voice_outputs)
        output_l.addWidget(self.voice_output_combo, 1); output_l.addWidget(self.voice_output_refresh_btn)
        vf2.addRow("播放设备", output_row)
        self._populate_voice_outputs()

        self.voice_fixed_label'''
    s = replace_once(s, speed_anchor, speed_insert, "voice output UI")

    # Preview through selected output device.
    s = replace_once(s,
        'self.voice_service.preview(text, str(vid), self.voice_speed.value())',
        'self.voice_service.preview(text, str(vid), self.voice_speed.value(), self.voice_output_combo.currentData() or "default")',
        "preview output device")

    # Add output device helper before the existing preparation handler.
    handler_anchor = '    def _prepare_voice_components(self):\n'
    handler_code = '''    def _populate_voice_outputs(self):
        current = str(self.cfg.get("voice", {}).get("output_device", "default") or "default")
        if hasattr(self, "voice_output_combo"):
            selected = self.voice_output_combo.currentData()
            if selected:
                current = str(selected)
            self.voice_output_combo.blockSignals(True)
            self.voice_output_combo.clear()
            try:
                items = self.voice_service.output_devices()
            except Exception as e:
                LOGGER.exception("枚举播放设备失败")
                items = [("default", "系统默认播放设备")]
            for key, label in items:
                self.voice_output_combo.addItem(str(label), str(key))
            idx = self.voice_output_combo.findData(current)
            if idx < 0:
                idx = self.voice_output_combo.findData("default")
            if idx >= 0:
                self.voice_output_combo.setCurrentIndex(idx)
            self.voice_output_combo.blockSignals(False)

'''
    if handler_anchor not in s:
        raise RuntimeError("voice handler anchor missing")
    s = s.replace(handler_anchor, handler_code + handler_anchor, 1)

    # Persist output device when fixing voice and when applying settings.
    s = replace_once(s,
        'self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()\n        save_config(self.cfg)\n        self.voice_fixed_label',
        'self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()\n        self.cfg["voice"]["output_device"] = str(self.voice_output_combo.currentData() or "default")\n        save_config(self.cfg)\n        self.voice_fixed_label',
        "fix voice output persistence")
    s = replace_once(s,
        '(self.voice_test_text, "textChanged"), (self.voice_speed, "valueChanged"),',
        '(self.voice_test_text, "textChanged"), (self.voice_speed, "valueChanged"), (self.voice_output_combo, "currentIndexChanged"),',
        "dirty tracking output")
    s = replace_once(s,
        'self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()\n        self.cfg["vision"]["enabled"]',
        'self.cfg["voice"]["test_text"] = self.voice_test_text.text().strip()\n        self.cfg["voice"]["output_device"] = str(self.voice_output_combo.currentData() or "default")\n        self.cfg["vision"]["enabled"]',
        "apply output persistence")

    # Known-safe storage cleanup. It runs after the new app has been alive for 5s,
    # so the external updater has time to finish and release its files.
    settings_anchor = 'class SettingsDialog(QDialog):\n'
    cleanup_code = '''def _path_size_bytes(path: Path):
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except Exception:
        return 0


def cleanup_obsolete_storage():
    reclaimed = 0
    removed = []
    try:
        # Completed update packages and partial downloads are never needed after a successful launch.
        if UPDATE_DIR.exists():
            for p in list(UPDATE_DIR.iterdir()):
                try:
                    if p.is_file() and (
                        p.name.startswith("XiaoMeili_") and (p.suffix.lower() in {".zip", ".part", ".tmp"})
                        or p.name.startswith("update_helper_runtime")
                    ):
                        reclaimed += _path_size_bytes(p)
                        p.unlink(missing_ok=True)
                        removed.append(str(p))
                except Exception:
                    LOGGER.warning("清理更新缓存失败：%s", p, exc_info=True)

        # Kokoro has been fully retired since V0.6.2. Qwen3-TTS is the only active voice backend.
        legacy_kokoro = USER / "voice" / "kokoro_v1_1_zh"
        if legacy_kokoro.exists():
            reclaimed += _path_size_bytes(legacy_kokoro)
            shutil.rmtree(legacy_kokoro, ignore_errors=False)
            removed.append(str(legacy_kokoro))

        old_preview = VOICE_CACHE_DIR / "xiaomeili_voice_preview.wav"
        if old_preview.exists():
            reclaimed += _path_size_bytes(old_preview)
            old_preview.unlink(missing_ok=True)
            removed.append(str(old_preview))

        LOGGER.info("自动存储清理完成：释放 %.1f MB；移除 %d 项", reclaimed / 1024 / 1024, len(removed))
    except Exception:
        LOGGER.warning("自动存储清理遇到非致命错误", exc_info=True)


'''
    if settings_anchor not in s:
        raise RuntimeError("settings class anchor missing")
    s = s.replace(settings_anchor, cleanup_code + settings_anchor, 1)

    # Tell the user cleanup is automatic in the update page.
    s = s.replace(
        '"个人配置、声音模型、动作素材和日志都保存在 XiaoMeiliData，不会因程序升级被覆盖。"',
        '"个人配置、当前语音模型、动作素材和日志都保存在 XiaoMeiliData，不会因程序升级被覆盖。更新成功后会自动清理旧更新包、临时文件和已淘汰的 Kokoro 组件。"',
        1,
    )

    # Schedule cleanup after startup, not while the updater may still be finishing.
    s = replace_once(s,
        'self.hotkeys.register(cfg); self.pet.show(); self.vision.start()',
        'self.hotkeys.register(cfg); self.pet.show(); self.vision.start(); QTimer.singleShot(5000, cleanup_obsolete_storage)',
        "startup cleanup schedule")

    main_path.write_text(s, encoding="utf-8")

    # Qwen voice backend: enumerate Windows outputs and play through the selected one.
    v = voice_path.read_text(encoding="utf-8")
    preview_sig = '    def preview(self, text, voice_id, speed=1.0):\n'
    methods = '''    def output_devices(self):
        items = [("default", "系统默认播放设备")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            seen = set()
            for idx, dev in enumerate(devices):
                try:
                    if int(dev.get("max_output_channels", 0)) <= 0:
                        continue
                    name = str(dev.get("name", f"设备 {idx}"))
                    host_idx = int(dev.get("hostapi", -1))
                    host_name = str(hostapis[host_idx].get("name", "")) if 0 <= host_idx < len(hostapis) else ""
                    key = f"{idx}|{host_idx}|{name}"
                    label = f"{name} · {host_name}" if host_name else name
                    if label in seen:
                        label = f"{label} · #{idx}"
                    seen.add(label)
                    items.append((key, label))
                except Exception:
                    continue
        except Exception:
            LOGGER.exception("读取 Windows 播放设备失败")
        return items

    @staticmethod
    def _device_index(device_key):
        key = str(device_key or "default")
        if key == "default":
            return None
        try:
            return int(key.split("|", 1)[0])
        except Exception:
            return None

    @staticmethod
    def _play_wav(path, device_key="default"):
        import soundfile as sf
        import sounddevice as sd
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
        sd.stop()
        sd.play(data, int(sample_rate), device=VoiceService._device_index(device_key), blocking=False)

'''
    if preview_sig not in v:
        raise RuntimeError("voice preview signature anchor missing")
    v = v.replace(preview_sig, methods + '    def preview(self, text, voice_id, speed=1.0, output_device="default"):\n', 1)

    old_play = '''                if sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(str(out), winsound.SND_FILENAME | winsound.SND_ASYNC)
                ok = True'''
    new_play = '''                self._play_wav(out, output_device)
                ok = True'''
    if old_play not in v:
        raise RuntimeError("voice playback anchor missing")
    v = v.replace(old_play, new_play, 1)
    voice_path.write_text(v, encoding="utf-8")

    # Main app needs a tiny PortAudio wrapper for selectable output routing.
    req = req_path.read_text(encoding="utf-8")
    if "sounddevice" not in req.lower():
        req = req.rstrip() + "\nsounddevice>=0.5,<1\n"
        req_path.write_text(req, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(voice_path), doraise=True)
    print("Patched XiaoMeili source to V0.6.2.2")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0622.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
