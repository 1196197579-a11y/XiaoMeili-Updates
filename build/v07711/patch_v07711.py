# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def patch_voice(voice_path: Path):
    v = voice_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r'    "design_xiaomeili_cool": \{\n'
        r'.*?'
        r'    \},\n'
        r'(?=    # Optional VoiceDesign presets\.)',
        re.S,
    )
    # The current V0.7.7.10 preset sits immediately before the VoiceDesign
    # preset comment. If later formatting changes, fall back to the next preset.
    if not pattern.search(v):
        pattern = re.compile(
            r'    "design_xiaomeili_cool": \{\n'
            r'.*?'
            r'    \},\n'
            r'(?=    "design_mint": \{)',
            re.S,
        )

    replacement = '''    "design_xiaomeili_cool": {
        "name": "小美丽｜战斗贤者（推荐）",
        "kind": "design",
        "seed": 61723,
        "human_pause": True,
        "recommended_speed": 0.95,
        "instruct": (
            "中国普通话、中性偏女的年轻少女声。基底必须仍然能听出是女孩，但略带一点小男孩式的干净少年感，"
            "只靠近一点，不能变成真正男声。把音高和声音重心比普通小女孩压低一些，减少头腔、尖亮和甜味，"
            "声线清澈、偏冷、薄而有韧性，听起来利落、有战斗感。不要甜、不要奶、不要软萌、不要撒娇，"
            "不要娃娃音、不要夹子音、不要尖细刺耳。说话高冷、酷、拽、自信，带一点漫不经心和轻微嫌弃，"
            "像一个年轻但身经百战的战斗贤者：冷静、警觉、反应快，不爱废话。咬字短促清楚，情绪起伏克制，"
            "语速自然略慢，短语之间保留轻微真人停顿，句尾干净利落并略微下压。不要成熟御姐感，不要低沉成年男声，"
            "不要粗糙沙哑，不要播音腔，不要明显气声，不要外国口音，也不要故意拖长尾音。"
        ),
    },
'''
    v, n = pattern.subn(replacement, v, count=1)
    if n != 1:
        raise RuntimeError("V0.7.7.11 voice preset replacement failed")

    voice_path.write_text(v, encoding="utf-8")
    py_compile.compile(str(voice_path), doraise=True)

    final = voice_path.read_text(encoding="utf-8")
    checks = [
        '"design_xiaomeili_cool"',
        '"小美丽｜战斗贤者（推荐）"',
        "略带一点小男孩式的干净少年感",
        "只靠近一点，不能变成真正男声",
        "减少头腔、尖亮和甜味",
        "像一个年轻但身经百战的战斗贤者",
        '"human_pause": True',
        '"recommended_speed": 0.95',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"V0.7.7.11 voice verification failed: {token}")


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.10"',
        'APP_NAME = "小美丽 V0.7.7.11｜Battle Sage Voice + Quiet Settings Startup"\nAPP_VERSION = "0.7.7.11"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("V0.7.7.11 version replacement failed")

    # Retire the old V0.7.7.4 onboarding popup completely. It was intended as
    # a one-time migration notice, but persistent/migrated config states could
    # make it reappear. The settings center itself remains unchanged.
    notice_pattern = re.compile(
        r'    def _v774_first_run_notice\(self\):\n'
        r'.*?'
        r'(?=\n    def _install_v0774_shell\(self, root\):)',
        re.S,
    )
    notice_replacement = '''    def _v774_first_run_notice(self):
        # V0.7.7.11: onboarding notice retired permanently.
        return
'''
    s, n = notice_pattern.subn(notice_replacement, s, count=1)
    if n != 1:
        raise RuntimeError("V0.7.7.11 settings notice method replacement failed")

    timer_line = "        QTimer.singleShot(350, self._v774_first_run_notice)\n"
    if timer_line not in s:
        raise RuntimeError("V0.7.7.11 settings notice timer anchor missing")
    s = s.replace(
        timer_line,
        "        # V0.7.7.11: no startup/onboarding message box.\n",
        1,
    )

    # Update user-facing recommendation text to the revised, less sweet voice.
    s = s.replace(
        'suffix = " 推荐先试听「小美丽｜高冷酷拽」。" if recommended >= 0 else ""',
        'suffix = " 推荐先试听「小美丽｜战斗贤者」。" if recommended >= 0 else ""',
        1,
    )

    # Frozen regression test: the startup popup text and scheduled invocation
    # must not come back, and the same voice ID should expose the new name.
    smoke_anchor = '''        if voice.display_name("design_xiaomeili_cool") != "小美丽｜高冷酷拽（推荐）":
            raise RuntimeError("cool XiaoMeili voice preset missing")
'''
    smoke_new = '''        if voice.display_name("design_xiaomeili_cool") != "小美丽｜战斗贤者（推荐）":
            raise RuntimeError("battle-sage XiaoMeili voice preset missing")
'''
    if smoke_anchor not in s:
        raise RuntimeError("V0.7.7.11 voice smoke-test anchor missing")
    s = s.replace(smoke_anchor, smoke_new, 1)

    smoke_return = '''        humanized = voice._humanize_spoken_text("你今天还行但是别得意")
        if "，但是" not in humanized:
            raise RuntimeError(f"human pause text transform failed: {humanized}")

        return True
'''
    smoke_return_new = '''        humanized = voice._humanize_spoken_text("你今天还行但是别得意")
        if "，但是" not in humanized:
            raise RuntimeError(f"human pause text transform failed: {humanized}")

        # V0.7.7.11 startup notice must be fully retired.
        source_text = Path(__file__).read_text(encoding="utf-8")
        retired_title = "设置中心" + "焕新完成"
        if retired_title in source_text:
            raise RuntimeError("retired settings-center startup popup text returned")
        retired_timer = "QTimer.singleShot(350, " + "self._v774_first_run_notice)"
        if retired_timer in source_text:
            raise RuntimeError("retired settings-center startup popup timer returned")

        return True
'''
    if smoke_return not in s:
        raise RuntimeError("V0.7.7.11 startup notice smoke-test anchor missing")
    s = s.replace(smoke_return, smoke_return_new, 1)

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.11"',
        'def _v774_first_run_notice(self):\\n        # V0.7.7.11: onboarding notice retired permanently.\\n        return',
        'V0.7.7.11: no startup/onboarding message box.',
        '推荐先试听「小美丽｜战斗贤者」',
        '小美丽｜战斗贤者（推荐）',
    ]
    for token in checks:
        if token.replace("\\n", "\n") not in final:
            raise RuntimeError(f"V0.7.7.11 main verification failed: {token}")

    if "设置中心焕新完成" in final:
        raise RuntimeError("V0.7.7.11 verification failed: startup notice text still present")
    if "QTimer.singleShot(350, self._v774_first_run_notice)" in final:
        raise RuntimeError("V0.7.7.11 verification failed: startup notice timer still present")


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    voice_path = source_root / "app" / "src" / "voice_qwen.py"
    if not main_path.exists() or not voice_path.exists():
        raise FileNotFoundError("V0.7.7.11 source inputs missing")

    patch_voice(voice_path)
    patch_main(main_path)
    print("Patched XiaoMeili source to V0.7.7.11 battle-sage voice + quiet settings startup")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v07711.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
