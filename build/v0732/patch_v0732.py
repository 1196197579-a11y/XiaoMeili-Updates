# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.3.2 patch anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"

    s = main_path.read_text(encoding="utf-8")
    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.3\.1"',
        'APP_NAME = "小美丽 V0.7.3.2｜Deterministic Correction Memory"\nAPP_VERSION = "0.7.3.2"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Make the UI promise match the new deterministic behavior.
    s = s.replace(
        '这句话你希望小美丽怎么回答？\n我会把它保存成养成样本，后面相似问题会优先模仿：',
        '这句话你希望小美丽怎么回答？\n同样的问题下次会直接使用你纠正的答案；相似问题会优先参考：',
        1,
    )
    s = s.replace(
        '纠正已记住。下次相似语境会优先参考。',
        '纠正已记住。同样的问题下次会直接回答这句；相似问题会优先参考。',
        1,
    )

    main_path.write_text(s, encoding="utf-8")

    b = brain_path.read_text(encoding="utf-8")

    # Add deterministic correction helpers before feedback example collection.
    anchor = '    def _feedback_examples(self, limit=10):\n'
    helpers = r'''    @staticmethod
    def _feedback_key(text):
        text = str(text or "").strip().lower()
        # Same wording with different spaces/punctuation should count as the same question.
        text = re.sub(r"[\s，。！？!?、；;：:,.…~～“”\"'（）()【】\[\]]+", "", text)
        return text

    def _feedback_rows(self):
        if not FEEDBACK_FILE.exists():
            return []
        rows = []
        try:
            for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except Exception:
                    continue
        except Exception:
            return []
        return rows

    def _forced_correction(self, user_text):
        key = self._feedback_key(user_text)
        if not key:
            return ""
        # Latest correction wins. A thumbs-up is a style sample, not a hard rule.
        for row in reversed(self._feedback_rows()[-500:]):
            if str(row.get("rating") or "") != "down":
                continue
            correction = str(row.get("correction") or "").strip()
            if not correction:
                continue
            if self._feedback_key(row.get("user_text")) == key:
                return correction
        return ""

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
    if anchor not in b:
        raise RuntimeError("feedback examples anchor missing")
    b = b.replace(anchor, helpers + anchor, 1)

    # Avoid reading/parsing the feedback file twice.
    old_rows = '''        if not FEEDBACK_FILE.exists():
            return []
        rows = []
        try:
            for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except Exception:
                    continue
        except Exception:
            return []
        examples = []
'''
    new_rows = '''        rows = self._feedback_rows()
        examples = []
'''
    b = replace_once(b, old_rows, new_rows, "feedback rows refactor")

    # Replace save_feedback as a whole. This is more robust than matching escaped newline literals.
    sf_start = b.index('    def save_feedback(')
    sf_end = b.index('    def feedback_count', sf_start)
    save_method = '''    def save_feedback(self, rating: str, user_text: str, assistant_text: str, correction: str = ""):
        row = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "rating": str(rating),
            "user_text": str(user_text or "").strip(),
            "assistant_text": str(assistant_text or "").strip(),
            "correction": str(correction or "").strip(),
        }
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\\n")
        if str(rating) == "down" and str(correction or "").strip():
            self._rewrite_history_with_correction(user_text, str(correction).strip())
'''
    b = b[:sf_start] + save_method + b[sf_end:]

    # Exact corrected questions must bypass model randomness entirely.
    ask_anchor = '''        self._generate_busy = True
        self.generation_started.emit()

        def job():
'''
    ask_new = '''        self._generate_busy = True
        self.generation_started.emit()

        forced = self._forced_correction(user_text)
        if forced:
            try:
                answer = {
                    "spoken_text": forced[:180],
                    "board_text": forced[:24],
                    "emotion": "neutral",
                }
                history = self._load_history()
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)
                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }
                self.generation_finished.emit(True, answer, "已使用主人纠正的固定回答")
            finally:
                self._generate_busy = False
            return

        def job():
'''
    b = replace_once(b, ask_anchor, ask_new, "deterministic correction bypass")

    # Make soft examples stronger for similar, but not exact, questions.
    b = b.replace(
        '以下是主人亲自认可或纠正过的说话方式。遇到相似语境时优先模仿这种风格：',
        '以下是主人亲自认可或纠正过的说话方式。纠正样本代表主人的明确偏好；相似语境必须优先参考这些回答的口吻和内容：',
        1,
    )

    brain_path.write_text(b, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.3.2")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0732.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
