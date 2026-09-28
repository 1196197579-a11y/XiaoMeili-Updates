# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.8.9.1 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.8.9.1 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.9"' not in s:
        raise RuntimeError("V0.8.9.1 expected APP_VERSION 0.8.9 base")
    s = s.replace('APP_VERSION = "0.8.9"', 'APP_VERSION = "0.8.9.1"', 1)
    s = s.replace("V0.8.9｜", "V0.8.9.1｜", 1)

    # Favorites were originally stored inside the monolithic config dictionary.
    # Legacy settings saves/updater restarts can write an older snapshot of that
    # dictionary and silently drop settings_ui.favorites_v0882. V0.8.9.1 makes
    # Favorites its own persistent UI-state file under XiaoMeiliData. The normal
    # config field remains only as a compatibility mirror.
    favorites = r'''    def _v0891_favorites_file(self):
        root = Path(xiaomeili_logical_data_root()) / "ui_state"
        root.mkdir(parents=True, exist_ok=True)
        return root / "favorites_v2.json"

    @staticmethod
    def _v0891_clean_favorite_ids(values):
        clean = []
        if not isinstance(values, list):
            return clean
        for value in values:
            value = str(value or "").strip()
            if value and value not in clean:
                clean.append(value)
        return clean

    def _v0891_read_favorites_file(self):
        path = self._v0891_favorites_file()
        backup = path.with_suffix(".bak")
        for candidate in (path, backup):
            try:
                if not candidate.exists():
                    continue
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                values = payload.get("favorites") if isinstance(payload, dict) else payload
                if isinstance(values, list):
                    return self._v0891_clean_favorite_ids(values)
            except Exception:
                LOGGER.warning("读取常用独立状态失败: %s", candidate, exc_info=True)
        return None

    def _v0891_write_favorites_file(self, values):
        clean = self._v0891_clean_favorite_ids(values)
        path = self._v0891_favorites_file()
        temp = path.with_suffix(".tmp")
        backup = path.with_suffix(".bak")
        payload = {"schema": 2, "favorites": clean}
        try:
            if path.exists():
                try:
                    backup.write_bytes(path.read_bytes())
                except Exception:
                    LOGGER.warning("备份常用状态失败", exc_info=True)
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(path)
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass
        return clean

    def _v0882_favorites(self):
        # Dedicated UI-state file is authoritative from V0.8.9.1 onward.
        file_values = self._v0891_read_favorites_file()
        ui = self.cfg.setdefault("settings_ui", {})
        if file_values is not None:
            ui["favorites_v0882"] = list(file_values)
            return list(file_values)

        # One-time migration from the old config field. An empty/missing old
        # value on the buggy builds is treated as lost state and repaired to the
        # original three defaults. After the new file exists, an intentionally
        # empty Favorites page remains empty across restarts.
        defaults = ["brain.learning", "brain.chat_test", "actions.event_trigger"]
        legacy = ui.get("favorites_v0882")
        values = self._v0891_clean_favorite_ids(legacy)
        if not values:
            values = list(defaults)

        self._v0891_write_favorites_file(values)
        ui["favorites_v0882"] = list(values)
        try:
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("迁移常用状态到主配置镜像失败，但独立状态文件已保存", exc_info=True)
        return list(values)

    def _v0882_save_favorites(self, values):
        clean = self._v0891_write_favorites_file(values)

        # Mirror into the main config for backward compatibility, but Favorites
        # no longer depends on that monolithic file surviving every legacy save.
        self.cfg.setdefault("settings_ui", {})["favorites_v0882"] = list(clean)
        try:
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("保存常用到主配置镜像失败，独立状态文件仍然有效", exc_info=True)

        self._v0882_refresh_favorite_buttons()
        self._v0882_refresh_favorites()

'''
    s = replace_method(s, "_v0882_favorites", "_v0882_go_page", favorites, "durable favorites persistence")

    # Always redraw Favorites when the user enters the page. This is a second
    # guard against startup/catalog timing leaving the page visually blank even
    # though the saved IDs still exist.
    switch_anchor = '''        self.v774_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.v774_nav_buttons):
'''
    switch_new = '''        self.v774_stack.setCurrentIndex(index)
        try:
            if self.v774_nav_names[index] == "常用":
                self._v0882_refresh_favorites()
                self._v0882_refresh_favorite_buttons()
        except Exception:
            LOGGER.warning("进入常用页时刷新失败", exc_info=True)
        for i, btn in enumerate(self.v774_nav_buttons):
'''
    if switch_anchor not in s:
        raise RuntimeError("V0.8.9.1 page switch refresh anchor missing")
    s = s.replace(switch_anchor, switch_new, 1)

    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    if "小美丽 V0.8.9 语音诊断日志" in s:
        s = s.replace("小美丽 V0.8.9 语音诊断日志", "小美丽 V0.8.9.1 语音诊断日志")
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    speech = root / "app" / "src" / "speech_input.py"
    for p in (main, speech):
        if not p.exists():
            raise FileNotFoundError(p)

    patch_main(main)
    patch_speech(speech)

    m = main.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")

    checks = [
        'APP_VERSION = "0.8.9.1"',
        'def _v0891_favorites_file(self):',
        'return root / "favorites_v2.json"',
        'def _v0891_write_favorites_file(self, values):',
        '"schema": 2, "favorites": clean',
        'Dedicated UI-state file is authoritative from V0.8.9.1 onward.',
        'if self.v774_nav_names[index] == "常用":',
    ]
    for token in checks:
        if token not in m:
            raise RuntimeError("V0.8.9.1 main verification failed: " + token)

    fav_block = m[m.find("    def _v0882_favorites("):m.find("    def _v0882_go_page(")]
    if '_v0891_read_favorites_file' not in fav_block or '_v0891_write_favorites_file' not in fav_block:
        raise RuntimeError("V0.8.9.1 Favorites is not using durable storage")
    if "小美丽 V0.8.9.1 语音诊断日志" not in sp:
        raise RuntimeError("V0.8.9.1 speech diagnostic version label missing")

    print("Patched XiaoMeili source to V0.8.9.1 durable Favorites persistence + page refresh repair")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0891.py <source_root>")
    patch(Path(sys.argv[1]))
