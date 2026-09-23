# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.4 patch anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    if not main_path.exists() or not brain_path.exists():
        raise FileNotFoundError("v0.7.4 source inputs missing")

    # ---------------- main.py ----------------
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.3\.3"',
        'APP_NAME = "小美丽 V0.7.4｜Semantic Learning"\nAPP_VERSION = "0.7.4"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Make the correction button's purpose clearer.
    s = replace_once(
        s,
        'self.brain_like_btn = QPushButton("👍 这句像小美丽"); self.brain_dislike_btn = QPushButton("👎 我来纠正")',
        'self.brain_like_btn = QPushButton("👍 这句像小美丽"); self.brain_dislike_btn = QPushButton("👎 纠正 / 养成")',
        "feedback button label",
    )

    # Explain the two learning modes directly in the UI.
    old_note = '''        bnote = QLabel(
            "现在的👍/👎不是重新训练模型，而是在本地记录“主人喜欢/纠正的答案”，之后相似问题会作为示例喂给小美丽。"
            "等积累到足够多的高质量样本后，再考虑 LoRA 微调。所有聊天样本都只保存在本机 XiaoMeiliData/brain。"
        )
'''
    new_note = '''        bnote = QLabel(
            "V0.7.4 纠正支持两种养成方式：\n"
            "「学这个意思」会记住核心立场和语气，之后允许小美丽自己换句式表达；"
            "「固定这句话」才会在同样问题下逐字使用你指定的答案。"
            "👍 继续用于积累小美丽喜欢的整体说话风格。所有样本只保存在本机 XiaoMeiliData/brain。"
        )
'''
    s = replace_once(s, old_note, new_note, "semantic learning note")

    # Replace the old single-mode correction workflow with a two-mode dialog.
    start = s.index('    def _brain_dislike(self):\n')
    end = s.index('    def _brain_clear_history(self):\n', start)
    new_dislike = '''    def _brain_dislike(self):
        ex = self.brain_service.last_exchange()
        if not ex:
            return

        desired, ok = QInputDialog.getMultiLineText(
            self,
            "纠正小美丽",
            "写下你希望小美丽表达的答案 / 核心意思：\n"
            "例如：保枪别说是我徒弟。\n\n"
            "下一步再选择是让她固定背这句话，还是只学这个意思。",
            str(ex.get("assistant_text") or ""),
        )
        if not ok:
            return
        desired = str(desired or "").strip()
        if not desired:
            return

        mode_box = QMessageBox(self)
        mode_box.setWindowTitle("选择养成方式")
        mode_box.setIcon(QMessageBox.Icon.Question)
        mode_box.setText("你希望小美丽怎么记住这次纠正？")
        mode_box.setInformativeText(
            "学这个意思（推荐）：保留核心含义、立场和语气，但允许她自然重组句子。\n"
            "固定这句话：以后遇到同样的问题，直接逐字回答你写的这一句。"
        )
        semantic_btn = mode_box.addButton("🧠 学这个意思（推荐）", QMessageBox.ButtonRole.AcceptRole)
        fixed_btn = mode_box.addButton("📌 固定这句话", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = mode_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        mode_box.exec()
        clicked = mode_box.clickedButton()
        if clicked is cancel_btn or clicked is None:
            return

        mode = "semantic" if clicked is semantic_btn else "fixed"
        self.brain_service.save_feedback(
            "down",
            ex.get("user_text", ""),
            ex.get("assistant_text", ""),
            desired,
            mode,
        )
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        label = "学这个意思" if mode == "semantic" else "固定这句话"
        self.brain_chat.addItem(f"你教她（{label}）：{desired}")
        self.brain_chat.scrollToBottom()
        if mode == "semantic":
            self.brain_status.setText("已学会这个意思：以后允许换一种说法，但核心立场不能变。")
        else:
            self.brain_status.setText("已固定这句话：同样的问题会直接回答你指定的原句。")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)

'''
    s = s[:start] + new_dislike + s[end:]

    main_path.write_text(s, encoding="utf-8")

    # ---------------- brain_qwen.py ----------------
    b = brain_path.read_text(encoding="utf-8")

    # Replace correction-memory helpers with mode-aware fixed/semantic learning.
    helper_start = b.index('    def _forced_correction(self, user_text):\n')
    helper_end = b.index('    def _feedback_examples(self, limit=10):\n', helper_start)
    new_helpers = '''    def _latest_correction_rows(self, limit=500):
        rows = self._feedback_rows()[-max(1, int(limit)):]
        latest = []
        seen = set()
        for row in reversed(rows):
            if str(row.get("rating") or "") != "down":
                continue
            key = self._feedback_key(row.get("user_text"))
            if not key or key in seen:
                continue
            seen.add(key)
            latest.append(row)
        return latest

    def _forced_correction(self, user_text):
        key = self._feedback_key(user_text)
        if not key:
            return ""
        # The newest correction for this exact question decides the mode.
        # Legacy V0.7.3.2 rows have no mode and are intentionally treated as fixed.
        for row in self._latest_correction_rows():
            if self._feedback_key(row.get("user_text")) != key:
                continue
            mode = str(row.get("mode") or "fixed").strip().lower()
            correction = str(row.get("correction") or "").strip()
            if mode == "fixed":
                return correction
            # A newer semantic correction suppresses any older fixed answer.
            return ""
        return ""

    def _semantic_rules(self, user_text, limit=10):
        current_key = self._feedback_key(user_text)
        exact = []
        recent = []
        for row in self._latest_correction_rows():
            mode = str(row.get("mode") or "fixed").strip().lower()
            if mode != "semantic":
                continue
            correction = str(row.get("correction") or "").strip()
            original = str(row.get("user_text") or "").strip()
            if not original or not correction:
                continue
            item = {
                "user_text": original,
                "meaning": correction,
                "exact": self._feedback_key(original) == current_key,
            }
            if item["exact"]:
                exact.append(item)
            else:
                recent.append(item)
        # Exact semantic rules must always survive the limit; the remaining slots are
        # the most recent semantic lessons. Qwen decides whether a non-exact rule is relevant.
        return (exact + recent)[:max(1, int(limit))]

    @staticmethod
    def _semantic_rules_prompt(rules):
        if not rules:
            return ""
        lines = [
            "以下是主人教过小美丽的“语义养成规则”。",
            "只有当当前问题和某条规则的场景含义相同或明显相近时才应用；无关规则必须忽略。",
            "应用规则时必须保持参考答案的核心立场、肯定/否定方向、人物关系和语气，不得反转意思。",
            "但这不是固定台词：优先用自然中文换一种说法，不要机械逐字复述参考句。",
        ]
        for i, row in enumerate(rules, start=1):
            hit = "【当前问题直接命中】" if row.get("exact") else ""
            lines.append(
                f"{i}. {hit}主人当时问：{row.get('user_text','')}\n"
                f"   主人要求保留的核心意思：{row.get('meaning','')}"
            )
        return "\n".join(lines)

    def _remove_history_for_question(self, user_text):
        key = self._feedback_key(user_text)
        if not key:
            return
        history = self._load_history()
        kept = []
        i = 0
        changed = False
        while i < len(history):
            item = history[i]
            if item.get("role") == "user" and self._feedback_key(item.get("content")) == key:
                changed = True
                i += 1
                if i < len(history) and history[i].get("role") == "assistant":
                    i += 1
                continue
            kept.append(item)
            i += 1
        if changed:
            self._save_history(kept)

    def _rewrite_history_with_correction(self, user_text, correction):
        key = self._feedback_key(user_text)
        if not key or not correction:
            return
        history = self._load_history()
        changed = False
        for i in range(len(history) - 1):
            try:
                if history[i].get("role") != "user":
                    continue
                if self._feedback_key(history[i].get("content")) != key:
                    continue
                if history[i + 1].get("role") == "assistant":
                    history[i + 1]["content"] = correction
                    changed = True
            except Exception:
                continue
        if changed:
            self._save_history(history)

'''
    b = b[:helper_start] + new_helpers + b[helper_end:]

    # Replace feedback examples. Semantic corrections are injected as semantic rules,
    # not as literal assistant examples, to avoid teaching verbatim repetition.
    examples_start = b.index('    def _feedback_examples(self, limit=10):\n')
    examples_end = b.index('    def save_feedback(', examples_start)
    new_examples = '''    def _feedback_examples(self, limit=10):
        rows = self._feedback_rows()
        examples = []
        seen_down = set()
        for row in reversed(rows[-200:]):
            rating = str(row.get("rating") or "")
            user = str(row.get("user_text") or "").strip()
            if rating == "down":
                key = self._feedback_key(user)
                if not key or key in seen_down:
                    continue
                seen_down.add(key)
                mode = str(row.get("mode") or "fixed").strip().lower()
                if mode == "semantic":
                    continue
                desired = str(row.get("correction") or "").strip()
            elif rating == "up":
                desired = str(row.get("assistant_text") or "").strip()
            else:
                continue
            if user and desired:
                examples.append((user, desired))
            if len(examples) >= int(limit):
                break
        examples.reverse()
        return examples

'''
    b = b[:examples_start] + new_examples + b[examples_end:]

    # Replace save_feedback with mode-aware behavior.
    save_start = b.index('    def save_feedback(')
    save_end = b.index('    def feedback_count', save_start)
    new_save = '''    def save_feedback(self, rating: str, user_text: str, assistant_text: str, correction: str = "", mode: str = "style"):
        mode = str(mode or "style").strip().lower()
        if mode not in {"style", "fixed", "semantic"}:
            mode = "style"
        row = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "rating": str(rating),
            "mode": mode,
            "user_text": str(user_text or "").strip(),
            "assistant_text": str(assistant_text or "").strip(),
            "correction": str(correction or "").strip(),
        }
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

        if str(rating) == "down" and str(correction or "").strip():
            if mode == "fixed":
                self._rewrite_history_with_correction(user_text, str(correction).strip())
            elif mode == "semantic":
                # Remove the old wrong exchange. The next answer is regenerated from the
                # semantic rule, so stale history cannot drag it back to the rejected answer.
                self._remove_history_for_question(user_text)

'''
    b = b[:save_start] + new_save + b[save_end:]

    # Add semantic lessons to the generation prompt. Fixed answers still bypass generation.
    system_anchor = '                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n'
    system_new = '''                system = str(persona or DEFAULT_PERSONA).strip() + "\n\n" + OUTPUT_CONTRACT.strip()
                semantic_rules = self._semantic_rules(user_text, 10)
                semantic_prompt = self._semantic_rules_prompt(semantic_rules)
                if semantic_prompt:
                    system += "\n\n" + semantic_prompt
'''
    b = replace_once(b, system_anchor, system_new, "semantic rules prompt")

    # If an exact semantic lesson is active and Qwen merely copies the reference sentence
    # verbatim, ask once more for a natural rephrase while preserving the same meaning.
    answer_anchor = '''                raw = str(response["choices"][0]["message"]["content"])
                answer = _normalize_answer(raw)
                elapsed = time.time() - started
'''
    answer_new = '''                raw = str(response["choices"][0]["message"]["content"])
                answer = _normalize_answer(raw)

                exact_semantic = next((r for r in semantic_rules if r.get("exact")), None)
                if exact_semantic:
                    wanted = self._feedback_key(exact_semantic.get("meaning"))
                    got = self._feedback_key(answer.get("spoken_text"))
                    if wanted and got == wanted:
                        retry_messages = list(messages)
                        retry_messages[-1] = {
                            "role": "user",
                            "content": user_text + "\n/no_think\n"
                                       "请根据主人教过的核心意思换一种自然说法回答，"
                                       "不要逐字复述参考句，但立场和含义必须保持一致。",
                        }
                        retry_payload = dict(payload)
                        retry_payload["messages"] = retry_messages
                        retry_payload["temperature"] = max(0.82, float(temperature))
                        retry = self._post_json("/v1/chat/completions", retry_payload, timeout=180)
                        retry_raw = str(retry["choices"][0]["message"]["content"])
                        retry_answer = _normalize_answer(retry_raw)
                        if str(retry_answer.get("spoken_text") or "").strip():
                            answer = retry_answer

                elapsed = time.time() - started
'''
    b = replace_once(b, answer_anchor, answer_new, "semantic paraphrase retry")

    # Surface semantic-learning use in the status text so the user can tell it is working.
    emit_anchor = '                self.generation_finished.emit(True, answer, f"回答完成 · {elapsed:.1f}s")\n'
    emit_new = '''                if any(r.get("exact") for r in semantic_rules):
                    status = f"回答完成 · {elapsed:.1f}s · 已按语义养成规则自由表达"
                else:
                    status = f"回答完成 · {elapsed:.1f}s"
                self.generation_finished.emit(True, answer, status)
'''
    b = replace_once(b, emit_anchor, emit_new, "semantic status")

    brain_path.write_text(b, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.4 semantic learning")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v074.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
