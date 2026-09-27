# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.12 anchor: {label}")
    return text.replace(old, new, 1)


def replace_method(text, start_sig, next_sig, body, label):
    start = text.find(start_sig)
    if start < 0:
        raise RuntimeError(f"missing method start: {label}")
    end = text.find(next_sig, start + len(start_sig))
    if end < 0:
        raise RuntimeError(f"missing method end: {label}")
    return text[:start] + body + text[end:]


def patch_brain(brain_path: Path):
    b = brain_path.read_text(encoding="utf-8")

    # 1) Semantic rules should expose abstractions, not the original sentence.
    old_rule_prompt = '''    @staticmethod
    def _rule_prompt(rule):
        return (
            f"规则编号：{rule.get('id')}\\n"
            f"场景：{rule.get('scene','')}\\n"
            f"核心意思：{rule.get('intent','')}\\n"
            f"必须体现：{rule.get('must','')}\\n"
            f"禁止偏离：{rule.get('forbid','')}\\n"
            f"语气：{rule.get('tone','')}\\n"
            f"主人最初的参考答案：{rule.get('reference_answer','')}"
        )

'''
    new_rule_prompt = '''    @staticmethod
    def _rule_prompt(rule):
        # Semantic generation deliberately hides the owner's original wording.
        # The correction is evidence used to learn the rule, not a sentence to copy.
        return (
            f"规则编号：{rule.get('id')}\\n"
            f"场景：{rule.get('scene','')}\\n"
            f"核心立场：{rule.get('intent','')}\\n"
            f"必须体现的语义：{rule.get('must','')}\\n"
            f"禁止偏离：{rule.get('forbid','')}\\n"
            f"语气：{rule.get('tone','')}"
        )

'''
    b = must(b, old_rule_prompt, new_rule_prompt, "semantic prompt hides reference")

    # 2) Make the semantic-rule distiller explicitly abstract away wording.
    old_system = '''                    "你是小美丽的养成规则提炼器。根据主人原问题和主人希望的回答，"
                    "提炼真正要记住的语义，不要把参考答案机械抄成所有字段。"
                    "返回JSON且只返回JSON，字段："
'''
    new_system = '''                    "你是小美丽的养成规则提炼器。根据主人原问题和主人希望的回答，"
                    "只提炼可泛化的观点、立场、行为策略和语气，绝对不要保存或复述主人原句的具体措辞。"
                    "例如主人纠正“没见过你这么丑的”，应提炼为“认为主人不好看/用毒舌方式否定其颜值”，"
                    "而不是把原句放进 intent 或 must。must 必须是抽象语义条件，不是完整台词。"
                    "返回JSON且只返回JSON，字段："
'''
    b = must(b, old_system, new_system, "semantic distiller abstraction")

    # 3) Strengthen the generation instruction against copying.
    old_gen = '''                        + "\\n这不是固定台词。请自然改写，但核心立场、必须体现和禁止偏离都必须满足。"
'''
    new_gen = '''                        + "\\n这是一条“学这个意思”的语义规则，不是固定台词。"
                          "\\n请只继承观点、立场和语气，每次重新组织语言；不要复述主人曾经教过的原句，"
                          "不要为了过守门而贴近参考措辞。相同问题连续出现时，也尽量换一种自然说法。"
'''
    b = must(b, old_gen, new_gen, "semantic generation diversity")

    # 4) Guard only meaning/stance, never similarity to wording.
    old_guard = '''            "重点检查：核心立场有没有反转；必须体现的行为/条件有没有出现；禁止偏离的内容有没有发生；"
            "允许换句式，不要求逐字复述。"
'''
    new_guard = '''            "重点只检查：核心立场有没有反转；关键语义是否表达出来；禁止偏离的方向有没有发生。"
            "不要检查措辞是否接近主人原句，也不要因为用了不同表达就判失败。只要意思一致，就应该通过。"
'''
    b = must(b, old_guard, new_guard, "semantic guard meaning-only")

    # 5) Remove the final "copy owner's reference answer" fallback.
    old_fallback = '''                if accepted is None and matched_rule:
                    fallback = str(matched_rule.get("reference_answer") or "").strip()
                    if not fallback:
                        fallback = str(matched_rule.get("intent") or "").strip()
                    accepted = {
                        "spoken_text": fallback[:180] or "我知道你的意思了，再问我一次。",
                        "board_text": (fallback[:24] or "按主人教的意思回答"),
                        "emotion": "neutral",
                    }
'''
    new_fallback = '''                if accepted is None and matched_rule:
                    # Never fall back to the owner's original correction for a
                    # semantic rule. Generate once more from abstract meaning only.
                    rescue_system = (
                        str(persona or DEFAULT_PERSONA).strip()
                        + "\\n\\n" + OUTPUT_CONTRACT.strip()
                        + "\\n\\n【只按抽象语义回答】\\n"
                        + self._rule_prompt(matched_rule)
                        + "\\n请给出一句自然、简短、全新措辞的回答。"
                          "只要立场和关键意思一致即可，不要复述任何示例原句。"
                    )
                    rescue_payload = dict(payload_base)
                    rescue_payload["temperature"] = max(0.88, float(temperature))
                    rescue_payload["top_p"] = 0.94
                    rescue_payload["messages"] = [
                        {"role": "system", "content": rescue_system},
                        {"role": "user", "content": user_text + "\\n/no_think"},
                    ]
                    rescue = self._post_json("/v1/chat/completions", rescue_payload, timeout=180)
                    accepted = _normalize_answer(str(rescue["choices"][0]["message"]["content"]))
'''
    b = must(b, old_fallback, new_fallback, "semantic no-copy rescue")

    # Update status wording so diagnostics are truthful.
    b = b.replace(
        'f"守门连续拒绝，已回退主人参考答案 · {elapsed:.1f}s"',
        'f"守门连续拒绝，已按抽象语义重新生成 · {elapsed:.1f}s"',
        1,
    )

    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(brain_path), doraise=True)

    final = brain_path.read_text(encoding="utf-8")
    for token in [
        "核心立场：",
        "绝对不要保存或复述主人原句的具体措辞",
        "这是一条“学这个意思”的语义规则，不是固定台词",
        "不要检查措辞是否接近主人原句",
        "【只按抽象语义回答】",
        "已按抽象语义重新生成",
    ]:
        if token not in final:
            raise RuntimeError(f"brain verification failed: {token}")
    if "主人最初的参考答案：" in final:
        raise RuntimeError("semantic prompt still exposes original reference wording")


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.11"',
        'APP_NAME = "小美丽 V0.7.7.12｜Semantic Learning + Resource Monitor"\nAPP_VERSION = "0.7.7.12"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Add psutil import near stdlib imports. GPU metrics intentionally use
    # nvidia-smi so no NVML Python package is required.
    if "import psutil\n" not in s:
        # pathlib is present in every current source line.
        s = must(s, "from pathlib import Path\n", "from pathlib import Path\nimport psutil\n", "psutil import")

    # Resource monitor methods before the existing system navigation helper.
    anchor = "    def open_system_section(self, name=\"更新\"):\n"
    methods = r'''    def _v07712_format_bytes(self, value):
        value = max(0.0, float(value or 0))
        units = ["B", "KB", "MB", "GB"]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit in {"B", "KB", "MB"} else f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} GB"

    def _v07712_gpu_metrics(self):
        result = {"util": None, "used_mb": None, "total_mb": None, "temp": None}
        if sys.platform != "win32":
            return result
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=1.5,
                creationflags=flags,
                stderr=subprocess.DEVNULL,
            )
            first = str(out).strip().splitlines()[0]
            parts = [x.strip() for x in first.split(",")]
            if len(parts) >= 4:
                result["util"] = float(parts[0])
                result["used_mb"] = float(parts[1])
                result["total_mb"] = float(parts[2])
                result["temp"] = float(parts[3])
        except Exception:
            pass
        return result

    def _v07712_refresh_resources(self):
        if not hasattr(self, "v07712_resource_cpu"):
            return
        try:
            vm = psutil.virtual_memory()
            cpu_total = float(psutil.cpu_percent(interval=None))
            proc = psutil.Process(os.getpid())
            proc_cpu = float(proc.cpu_percent(interval=None))
            proc_mem = float(proc.memory_info().rss)
            child_mem = 0.0
            child_cpu = 0.0
            try:
                for child in proc.children(recursive=True):
                    try:
                        child_mem += float(child.memory_info().rss)
                        child_cpu += float(child.cpu_percent(interval=None))
                    except Exception:
                        pass
            except Exception:
                pass

            app_mem = proc_mem + child_mem
            app_cpu = proc_cpu + child_cpu
            gpu = self._v07712_gpu_metrics()

            self.v07712_resource_cpu.setText(
                f"整机 {cpu_total:.0f}%   ·   小美丽约 {app_cpu:.1f}%"
            )
            self.v07712_resource_cpu_bar.setValue(max(0, min(100, int(round(cpu_total)))))

            self.v07712_resource_ram.setText(
                f"整机 {vm.percent:.0f}%   ·   小美丽约 {self._v07712_format_bytes(app_mem)}"
            )
            self.v07712_resource_ram_bar.setValue(max(0, min(100, int(round(vm.percent)))))

            if gpu["util"] is None:
                self.v07712_resource_gpu.setText("暂未读取到 NVIDIA GPU 数据")
                self.v07712_resource_gpu_bar.setValue(0)
                self.v07712_resource_vram.setText("显存：不可用")
                self.v07712_resource_vram_bar.setValue(0)
            else:
                util = float(gpu["util"])
                used = float(gpu["used_mb"] or 0)
                total = max(1.0, float(gpu["total_mb"] or 1))
                temp = float(gpu["temp"] or 0)
                self.v07712_resource_gpu.setText(
                    f"整机 {util:.0f}%   ·   {temp:.0f}°C"
                )
                self.v07712_resource_gpu_bar.setValue(max(0, min(100, int(round(util)))))
                self.v07712_resource_vram.setText(
                    f"显存 {used / 1024:.1f} / {total / 1024:.1f} GB"
                )
                self.v07712_resource_vram_bar.setValue(
                    max(0, min(100, int(round(used * 100.0 / total))))
                )

            # Simple one-glance pressure summary. GPU figures are whole-system
            # because Windows WDDM does not reliably expose per-process VRAM.
            pressure = max(
                cpu_total,
                float(vm.percent),
                float(gpu["util"] or 0),
                (float(gpu["used_mb"] or 0) * 100.0 / max(1.0, float(gpu["total_mb"] or 1))),
            )
            if pressure >= 90:
                label = "压力很高"
            elif pressure >= 75:
                label = "压力偏高"
            elif pressure >= 55:
                label = "中等"
            else:
                label = "轻松"
            self.v07712_resource_summary.setText(
                f"当前资源压力：{label}  ·  2 秒刷新"
            )
        except Exception as exc:
            LOGGER.warning("刷新资源监控失败: %s", exc)

    def _v07712_make_metric(self, title):
        box = QGroupBox(str(title))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        value = QLabel("正在读取…")
        value.setObjectName("cardValue")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        lay.addWidget(value)
        lay.addWidget(bar)
        return box, value, bar

    def _v07712_build_resource_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("资源占用")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "用来观察小美丽未来增加画面识别、动画和 AI 功能后的性能压力。"
            "CPU/内存会显示小美丽进程及其子进程估算值；GPU/显存显示整机数据。"
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.v07712_resource_summary = QLabel("正在读取资源状态…")
        self.v07712_resource_summary.setObjectName("cardValue")
        outer.addWidget(self.v07712_resource_summary)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        cpu_box, self.v07712_resource_cpu, self.v07712_resource_cpu_bar = self._v07712_make_metric("CPU")
        ram_box, self.v07712_resource_ram, self.v07712_resource_ram_bar = self._v07712_make_metric("内存")
        gpu_box, self.v07712_resource_gpu, self.v07712_resource_gpu_bar = self._v07712_make_metric("GPU")
        vram_box, self.v07712_resource_vram, self.v07712_resource_vram_bar = self._v07712_make_metric("显存")

        grid.addWidget(cpu_box, 0, 0)
        grid.addWidget(ram_box, 0, 1)
        grid.addWidget(gpu_box, 1, 0)
        grid.addWidget(vram_box, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        note = QLabel(
            "提示：GPU/显存显示整机占用，不等于全部由小美丽产生。"
            "以后增加游戏画面识别时，可以先看开启前后的变化来判断新增功能成本。"
        )
        note.setWordWrap(True)
        note.setObjectName("cardDesc")
        outer.addWidget(note)
        outer.addStretch(1)

        self.v07712_resource_timer = QTimer(self)
        self.v07712_resource_timer.setInterval(2000)
        self.v07712_resource_timer.timeout.connect(self._v07712_refresh_resources)
        self.v07712_resource_timer.start()
        QTimer.singleShot(100, self._v07712_refresh_resources)
        return page

'''
    s = must(s, anchor, methods + anchor, "resource monitor methods")

    # Insert resource page as the first System sub-tab.
    system_anchor = '''        update_page = self._v774_take_legacy_page("更新")
        storage_page = self._v774_take_legacy_page("存储")
'''
    system_new = '''        resource_page = self._v07712_build_resource_page()
        self._v774_system_index["资源占用"] = self.v774_system_tabs.addTab(resource_page, "资源占用")

        update_page = self._v774_take_legacy_page("更新")
        storage_page = self._v774_take_legacy_page("存储")
'''
    s = must(s, system_anchor, system_new, "resource system tab")

    # Update self-test expected tabs.
    old_titles = '''        for title in ("更新", "存储", "组件与下载", "游戏识别", "日志"):
'''
    new_titles = '''        for title in ("资源占用", "更新", "存储", "组件与下载", "游戏识别", "日志"):
'''
    s = must(s, old_titles, new_titles, "resource tab self test")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    for token in [
        'APP_VERSION = "0.7.7.12"',
        "import psutil",
        'def _v07712_refresh_resources(self):',
        'def _v07712_gpu_metrics(self):',
        'self._v774_system_index["资源占用"]',
        '"CPU"', '"内存"', '"GPU"', '"显存"',
        "2 秒刷新",
    ]:
        if token not in final:
            raise RuntimeError(f"main verification failed: {token}")


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    patch_brain(brain_path)
    patch_main(main_path)
    print("Patched XiaoMeili source to V0.7.7.12 semantic learning + resource monitor")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v07712.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
