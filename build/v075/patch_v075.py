# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.5 patch anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    if not main_path.exists() or not brain_path.exists():
        raise FileNotFoundError("v0.7.5 source inputs missing")

    # ---------------- main.py ----------------
    s = main_path.read_text(encoding="utf-8")
    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.4"',
        'APP_NAME = "小美丽 V0.7.5｜Semantic Gate + Learning Library"\nAPP_VERSION = "0.7.5"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Add a visible learning library under the correction controls.
    feedback_anchor = '''        bf.addRow("养成", feedback_row)
        bv.addWidget(bbox)

        pbox = QGroupBox("小美丽性格卡（只影响她怎么说话）")'''
    feedback_new = '''        bf.addRow("养成", feedback_row)

        rules_box = QGroupBox("养成库｜语义规则与固定台词")
        rules_v = QVBoxLayout(rules_box)
        self.brain_rules_list = QListWidget()
        self.brain_rules_list.setMinimumHeight(125)
        rules_v.addWidget(self.brain_rules_list)
        rules_btns = QHBoxLayout()
        self.brain_rules_refresh_btn = QPushButton("刷新")
        self.brain_rules_edit_btn = QPushButton("编辑")
        self.brain_rules_toggle_btn = QPushButton("启用 / 暂停")
        self.brain_rules_delete_btn = QPushButton("删除")
        self.brain_rules_refresh_btn.clicked.connect(self._refresh_brain_rules)
        self.brain_rules_edit_btn.clicked.connect(self._brain_edit_rule)
        self.brain_rules_toggle_btn.clicked.connect(self._brain_toggle_rule)
        self.brain_rules_delete_btn.clicked.connect(self._brain_delete_rule)
        rules_btns.addWidget(self.brain_rules_refresh_btn)
        rules_btns.addWidget(self.brain_rules_edit_btn)
        rules_btns.addWidget(self.brain_rules_toggle_btn)
        rules_btns.addWidget(self.brain_rules_delete_btn)
        rules_btns.addStretch(1)
        rules_v.addLayout(rules_btns)
        bf.addRow(rules_box)
        bv.addWidget(bbox)

        pbox = QGroupBox("小美丽性格卡（只影响她怎么说话）")'''
    s = replace_once(s, feedback_anchor, feedback_new, "learning library UI")

    # New description: semantic learning now has confirmation + semantic gate.
    old_note = '''        bnote = QLabel(
            "V0.7.4 纠正支持两种养成方式：\\n"
            "「学这个意思」会记住核心立场和语气，之后允许小美丽自己换句式表达；"
            "「固定这句话」才会在同样问题下逐字使用你指定的答案。"
            "👍 继续用于积累小美丽喜欢的整体说话风格。所有样本只保存在本机 XiaoMeiliData/brain。"
        )
'''
    new_note = '''        bnote = QLabel(
            "V0.7.5「学这个意思」会先让小美丽提炼场景、核心立场、必须体现、禁止偏离和语气，"
            "再让你确认她到底学到了什么。聊天时命中规则后，回答先经过语义守门检查，"
            "不合格会自动重写，连续失败才回退到你的参考答案。"
            "「固定这句话」仍然逐字命中。养成库可以编辑、暂停或删除规则。"
        )
'''
    s = replace_once(s, old_note, new_note, "v075 learning note")

    # Initialize pending semantic proposal and load the library.
    connect_anchor = '''        self.brain_service.generation_started.connect(self._brain_generation_started)
        self.brain_service.generation_finished.connect(self._brain_generation_finished)
'''
    connect_new = '''        self.brain_service.generation_started.connect(self._brain_generation_started)
        self.brain_service.generation_finished.connect(self._brain_generation_finished)
        self.brain_service.rule_proposed.connect(self._brain_rule_proposed)
        self._pending_semantic_lesson = None
        self._refresh_brain_rules()
'''
    s = replace_once(s, connect_anchor, connect_new, "rule proposal signal")

    # Replace V0.7.4 correction UI with proposal-confirmation flow.
    dislike_start = s.index('    def _brain_dislike(self):\n')
    dislike_end = s.index('    def _brain_clear_history(self):\n', dislike_start)
    new_dislike = '''    @staticmethod
    def _semantic_rule_text(rule):
        return (
            f"场景：{str(rule.get('scene') or '').strip()}\\n"
            f"核心意思：{str(rule.get('intent') or '').strip()}\\n"
            f"必须体现：{str(rule.get('must') or '').strip()}\\n"
            f"禁止偏离：{str(rule.get('forbid') or '').strip()}\\n"
            f"语气：{str(rule.get('tone') or '').strip()}"
        )

    @staticmethod
    def _parse_semantic_rule_text(text, fallback=None):
        fallback = dict(fallback or {})
        mapping = {
            "场景": "scene",
            "核心意思": "intent",
            "必须体现": "must",
            "禁止偏离": "forbid",
            "语气": "tone",
        }
        out = dict(fallback)
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            field = mapping.get(key.strip())
            if field:
                out[field] = value.strip()
        return out

    def _brain_dislike(self):
        ex = self.brain_service.last_exchange()
        if not ex:
            return

        desired, ok = QInputDialog.getMultiLineText(
            self,
            "纠正小美丽",
            "写下你希望小美丽表达的答案 / 核心意思：\\n"
            "例如：叫爸爸我就告诉你。\\n\\n"
            "下一步选择“学这个意思”或“固定这句话”。",
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
            "学这个意思：先提炼成语义规则给你确认，之后允许自由换句式，但不能改变核心意思。\\n"
            "固定这句话：同样的问题直接逐字回答你写的这一句。"
        )
        semantic_btn = mode_box.addButton("🧠 学这个意思（推荐）", QMessageBox.ButtonRole.AcceptRole)
        fixed_btn = mode_box.addButton("📌 固定这句话", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = mode_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        mode_box.exec()
        clicked = mode_box.clickedButton()
        if clicked is cancel_btn or clicked is None:
            return

        if clicked is fixed_btn:
            self.brain_service.save_feedback(
                "down",
                ex.get("user_text", ""),
                ex.get("assistant_text", ""),
                desired,
                "fixed",
            )
            self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
            self.brain_chat.addItem(f"你教她（固定这句话）：{desired}")
            self.brain_status.setText("已固定：同样的问题会直接回答你指定的原句。")
            self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
            self._refresh_brain_rules()
            return

        self._pending_semantic_lesson = {
            "user_text": str(ex.get("user_text") or ""),
            "assistant_text": str(ex.get("assistant_text") or ""),
            "desired": desired,
        }
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_status.setText("小美丽正在理解你教的意思…")
        self.brain_service.propose_semantic_rule(
            self._pending_semantic_lesson["user_text"],
            desired,
        )

    def _brain_rule_proposed(self, ok, rule, message):
        pending = self._pending_semantic_lesson
        if not pending:
            return
        if not ok:
            self.brain_status.setText(str(message))
            self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
            self._pending_semantic_lesson = None
            return

        initial = self._semantic_rule_text(rule)
        edited, accepted = QInputDialog.getMultiLineText(
            self,
            "确认小美丽学到的意思",
            "请检查下面这 5 项。理解不对可以直接修改；确认后才会真正写入养成库：",
            initial,
        )
        if not accepted:
            self.brain_status.setText("这次语义养成已取消，没有写入。")
            self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
            self._pending_semantic_lesson = None
            return

        final_rule = self._parse_semantic_rule_text(edited, rule)
        self.brain_service.save_feedback(
            "down",
            pending["user_text"],
            pending["assistant_text"],
            pending["desired"],
            "semantic",
            final_rule,
        )
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        self.brain_chat.addItem(f"你教她（学这个意思）：{pending['desired']}")
        self.brain_chat.scrollToBottom()
        self.brain_status.setText("语义规则已确认并写入养成库。以后命中时先生成，再经过守门检查。")
        self._pending_semantic_lesson = None
        self._refresh_brain_rules()

    def _refresh_brain_rules(self):
        if not hasattr(self, "brain_rules_list"):
            return
        self.brain_rules_list.clear()
        try:
            rules = self.brain_service.list_rules()
        except Exception:
            LOGGER.exception("刷新养成库失败")
            rules = []
        for rule in rules:
            mode = "语义" if rule.get("mode") == "semantic" else "固定"
            state = "启用" if rule.get("enabled", True) else "暂停"
            hits = int(rule.get("hit_count") or 0)
            title = str(rule.get("scene") or rule.get("user_text") or rule.get("reference_answer") or "").strip()
            if len(title) > 34:
                title = title[:34] + "…"
            item = QListWidgetItem(f"#{rule.get('id')}  [{mode}｜{state}]  命中 {hits} 次｜{title}")
            item.setData(Qt.ItemDataRole.UserRole, str(rule.get("id") or ""))
            self.brain_rules_list.addItem(item)

    def _selected_brain_rule_id(self):
        item = self.brain_rules_list.currentItem() if hasattr(self, "brain_rules_list") else None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _brain_edit_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return

        if rule.get("mode") == "fixed":
            value, ok = QInputDialog.getMultiLineText(
                self, "编辑固定台词", "同样问题命中时要逐字回答：",
                str(rule.get("reference_answer") or ""),
            )
            if ok and str(value or "").strip():
                self.brain_service.update_rule(rule_id, {"reference_answer": str(value).strip()})
                self.brain_status.setText(f"已更新固定规则 #{rule_id}")
        else:
            value, ok = QInputDialog.getMultiLineText(
                self, "编辑语义规则",
                "可以修改场景、核心意思、必须体现、禁止偏离和语气：",
                self._semantic_rule_text(rule),
            )
            if ok:
                changes = self._parse_semantic_rule_text(value, rule)
                self.brain_service.update_rule(rule_id, changes)
                self.brain_status.setText(f"已更新语义规则 #{rule_id}")
        self._refresh_brain_rules()

    def _brain_toggle_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            return
        enabled = not bool(rule.get("enabled", True))
        self.brain_service.update_rule(rule_id, {"enabled": enabled})
        self.brain_status.setText(f"规则 #{rule_id} 已{'启用' if enabled else '暂停'}")
        self._refresh_brain_rules()

    def _brain_delete_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        answer = QMessageBox.question(
            self, "删除养成规则",
            f"确定删除规则 #{rule_id} 吗？\\n删除后不会再用于回答。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.brain_service.delete_rule(rule_id)
            self.brain_status.setText(f"规则 #{rule_id} 已删除")
            self._refresh_brain_rules()

'''
    s = s[:dislike_start] + new_dislike + s[dislike_end:]
    main_path.write_text(s, encoding="utf-8")

    # ---------------- brain_qwen.py ----------------
    b = brain_path.read_text(encoding="utf-8")

    # Persistent rule library.
    const_anchor = 'FEEDBACK_FILE = BRAIN_ROOT / "feedback.jsonl"\n'
    const_new = '''FEEDBACK_FILE = BRAIN_ROOT / "feedback.jsonl"
RULES_FILE = BRAIN_ROOT / "learning_rules.json"
'''
    b = replace_once(b, const_anchor, const_new, "RULES_FILE")

    # Add the rule proposal signal and migrate old corrections at startup.
    signal_anchor = '''    generation_started = Signal()
    generation_finished = Signal(bool, dict, str)
    status_changed = Signal(str)
'''
    signal_new = '''    generation_started = Signal()
    generation_finished = Signal(bool, dict, str)
    status_changed = Signal(str)
    rule_proposed = Signal(bool, dict, str)
'''
    b = replace_once(b, signal_anchor, signal_new, "rule proposal signal")

    init_anchor = '''        self._lock = threading.RLock()
        self._last_exchange = None
'''
    init_new = '''        self._lock = threading.RLock()
        self._last_exchange = None
        self._sync_rules_from_feedback()
'''
    b = replace_once(b, init_anchor, init_new, "rule migration init")

    # Replace V0.7.4 correction helpers with a real rule library + matcher.
    helper_start = b.index('    def _latest_correction_rows(self, limit=500):\n')
    helper_end = b.index('    def _feedback_examples(self, limit=10):\n', helper_start)
    new_helpers = '''    def _load_rules(self):
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
        return []

    def _save_rules(self, rules):
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = RULES_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(list(rules), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(RULES_FILE)

    @staticmethod
    def _next_rule_id(rules):
        nums = []
        for row in rules:
            raw = str(row.get("id") or "")
            m = re.search(r"(\\d+)$", raw)
            if m:
                nums.append(int(m.group(1)))
        return f"R{(max(nums) + 1 if nums else 1):03d}"

    def _sync_rules_from_feedback(self):
        rules = self._load_rules()
        known = {
            (str(r.get("mode") or ""), self._feedback_key(r.get("user_text")))
            for r in rules
        }
        changed = False
        latest = {}
        for row in self._feedback_rows():
            if str(row.get("rating") or "") != "down":
                continue
            user = str(row.get("user_text") or "").strip()
            correction = str(row.get("correction") or "").strip()
            if not user or not correction:
                continue
            key = self._feedback_key(user)
            latest[key] = row
        for key, row in latest.items():
            mode = str(row.get("mode") or "fixed").strip().lower()
            if mode not in {"fixed", "semantic"}:
                mode = "fixed"
            if (mode, key) in known:
                continue
            correction = str(row.get("correction") or "").strip()
            user = str(row.get("user_text") or "").strip()
            rules.append({
                "id": self._next_rule_id(rules),
                "mode": mode,
                "enabled": True,
                "user_text": user,
                "reference_answer": correction,
                "scene": user,
                "intent": correction,
                "must": correction if mode == "semantic" else "",
                "forbid": "",
                "tone": "保持主人纠正时的口吻" if mode == "semantic" else "",
                "hit_count": 0,
                "created_at": str(row.get("time") or datetime.now().isoformat(timespec="seconds")),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "migrated": True,
            })
            known.add((mode, key))
            changed = True
        if changed:
            self._save_rules(rules)

    def list_rules(self):
        self._sync_rules_from_feedback()
        return list(reversed(self._load_rules()))

    def get_rule(self, rule_id):
        for rule in self._load_rules():
            if str(rule.get("id")) == str(rule_id):
                return dict(rule)
        return None

    def update_rule(self, rule_id, changes):
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id")) != str(rule_id):
                continue
            for key in ("scene", "intent", "must", "forbid", "tone", "reference_answer", "enabled"):
                if key in changes:
                    rule[key] = changes[key]
            rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_rules(rules)
            return dict(rule)
        return None

    def delete_rule(self, rule_id):
        rules = self._load_rules()
        new_rules = [r for r in rules if str(r.get("id")) != str(rule_id)]
        if len(new_rules) != len(rules):
            self._save_rules(new_rules)
            return True
        return False

    def _upsert_rule(self, mode, user_text, reference_answer, structured=None):
        rules = self._load_rules()
        key = self._feedback_key(user_text)
        structured = dict(structured or {})
        target = None
        # Newest lesson for the same normalized question replaces the old active lesson,
        # regardless of whether the user switched between fixed and semantic mode.
        for rule in reversed(rules):
            if self._feedback_key(rule.get("user_text")) == key:
                target = rule
                break
        if target is None:
            target = {
                "id": self._next_rule_id(rules),
                "hit_count": 0,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            rules.append(target)

        target.update({
            "mode": str(mode),
            "enabled": True,
            "user_text": str(user_text or "").strip(),
            "reference_answer": str(reference_answer or "").strip(),
            "scene": str(structured.get("scene") or user_text or "").strip(),
            "intent": str(structured.get("intent") or reference_answer or "").strip(),
            "must": str(structured.get("must") or reference_answer or "").strip() if mode == "semantic" else "",
            "forbid": str(structured.get("forbid") or "").strip(),
            "tone": str(structured.get("tone") or "保持主人纠正时的口吻").strip() if mode == "semantic" else "",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._save_rules(rules)
        return dict(target)

    def _increment_rule_hit(self, rule_id):
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id")) == str(rule_id):
                rule["hit_count"] = int(rule.get("hit_count") or 0) + 1
                rule["last_hit_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_rules(rules)
                return

    def _exact_rule(self, user_text):
        key = self._feedback_key(user_text)
        if not key:
            return None
        for rule in reversed(self._load_rules()):
            if not rule.get("enabled", True):
                continue
            if self._feedback_key(rule.get("user_text")) == key:
                return dict(rule)
        return None

    def _active_semantic_rules(self, limit=40):
        rows = [
            dict(r) for r in reversed(self._load_rules())
            if r.get("enabled", True) and str(r.get("mode") or "") == "semantic"
        ]
        return rows[:max(1, int(limit))]

    @staticmethod
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

    def _match_semantic_rule(self, user_text):
        exact = self._exact_rule(user_text)
        if exact:
            return exact

        candidates = self._active_semantic_rules(32)
        if not candidates:
            return None

        compact = []
        for rule in candidates:
            compact.append({
                "id": str(rule.get("id") or ""),
                "scene": str(rule.get("scene") or ""),
                "intent": str(rule.get("intent") or ""),
                "example_question": str(rule.get("user_text") or ""),
            })
        system = (
            "你是小美丽程序的语义规则匹配器，不负责聊天。"
            "判断当前用户问题是否与某一条养成规则属于同一个意图/场景。"
            "只有明显同义、改写、近义表达才匹配；仅仅共享一两个词不能匹配。"
            "返回JSON：{\\"rule_id\\":\\"R001或空字符串\\",\\"confidence\\":0到1,\\"reason\\":\\"简短原因\\"}。"
            "不要输出JSON之外的文字。"
        )
        user = (
            f"当前问题：{user_text}\\n\\n"
            f"候选规则：{json.dumps(compact, ensure_ascii=False)}"
        )
        payload = {
            "model": "Qwen3-8B-Q4_K_M",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\\n/no_think"},
            ],
            "temperature": 0.0,
            "top_p": 0.2,
            "max_tokens": 100,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        result = self._post_json("/v1/chat/completions", payload, timeout=120)
        raw = str(result["choices"][0]["message"]["content"])
        obj = _extract_json_object(raw) or {}
        rid = str(obj.get("rule_id") or "").strip()
        try:
            confidence = float(obj.get("confidence") or 0)
        except Exception:
            confidence = 0.0
        if not rid or confidence < 0.72:
            return None
        for rule in candidates:
            if str(rule.get("id")) == rid:
                out = dict(rule)
                out["_match_confidence"] = confidence
                return out
        return None

    def _guard_semantic_answer(self, rule, user_text, answer_text):
        system = (
            "你是小美丽程序的语义守门员。你不负责写答案，只检查候选回答是否严格遵守主人教的规则。"
            "重点检查：核心立场有没有反转；必须体现的行为/条件有没有出现；禁止偏离的内容有没有发生；"
            "允许换句式，不要求逐字复述。"
            "返回JSON：{\\"pass\\":true或false,\\"reason\\":\\"不超过40字\\"}，不要输出其他文字。"
        )
        user = (
            f"用户问题：{user_text}\\n\\n"
            f"养成规则：\\n{self._rule_prompt(rule)}\\n\\n"
            f"候选回答：{answer_text}"
        )
        payload = {
            "model": "Qwen3-8B-Q4_K_M",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\\n/no_think"},
            ],
            "temperature": 0.0,
            "top_p": 0.2,
            "max_tokens": 90,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        result = self._post_json("/v1/chat/completions", payload, timeout=120)
        raw = str(result["choices"][0]["message"]["content"])
        obj = _extract_json_object(raw) or {}
        passed = obj.get("pass")
        if isinstance(passed, str):
            passed = passed.strip().lower() in {"true", "1", "yes", "pass"}
        return bool(passed), str(obj.get("reason") or "未通过语义守门").strip()

    def _fallback_rule(self, user_text, desired):
        return {
            "scene": str(user_text or "").strip(),
            "intent": str(desired or "").strip(),
            "must": str(desired or "").strip(),
            "forbid": "不要偏离或反转主人给出的核心意思",
            "tone": "保持主人纠正时的自然口吻",
        }

    def propose_semantic_rule(self, user_text, desired):
        user_text = str(user_text or "").strip()
        desired = str(desired or "").strip()
        if not user_text or not desired:
            self.rule_proposed.emit(False, {}, "缺少问题或纠正内容。")
            return
        if self._generate_busy:
            self.rule_proposed.emit(False, {}, "小美丽还在回答上一句话，请稍等。")
            return

        def job():
            try:
                self._start_server()
                system = (
                    "你是小美丽的养成规则提炼器。根据主人原问题和主人希望的回答，"
                    "提炼真正要记住的语义，不要把参考答案机械抄成所有字段。"
                    "返回JSON且只返回JSON，字段："
                    "scene=什么场景/问题应触发；"
                    "intent=核心立场或行为策略；"
                    "must=回答必须体现的关键条件；"
                    "forbid=最重要的禁止偏离方向；"
                    "tone=语气。"
                    "每个字段用简洁中文。"
                )
                user = f"原问题：{user_text}\\n主人希望表达：{desired}"
                payload = {
                    "model": "Qwen3-8B-Q4_K_M",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user + "\\n/no_think"},
                    ],
                    "temperature": 0.15,
                    "top_p": 0.4,
                    "max_tokens": 220,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                result = self._post_json("/v1/chat/completions", payload, timeout=150)
                raw = str(result["choices"][0]["message"]["content"])
                obj = _extract_json_object(raw)
                if not isinstance(obj, dict):
                    obj = self._fallback_rule(user_text, desired)
                rule = self._fallback_rule(user_text, desired)
                for key in ("scene", "intent", "must", "forbid", "tone"):
                    value = str(obj.get(key) or "").strip()
                    if value:
                        rule[key] = value
                self.rule_proposed.emit(True, rule, "已完成语义提炼，请确认。")
            except Exception as exc:
                LOGGER.exception("语义规则提炼失败")
                # Do not lose the user's correction just because the analyzer failed.
                rule = self._fallback_rule(user_text, desired)
                self.rule_proposed.emit(True, rule, f"自动提炼失败，已使用保守规则：{type(exc).__name__}")
        threading.Thread(target=job, name="XiaoMeiliRuleProposal", daemon=True).start()

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

    # Semantic rules live in the rule library now. Style/fixed feedback remains useful as examples.
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

    # Save both the raw teaching sample and the confirmed structured rule.
    save_start = b.index('    def save_feedback(')
    save_end = b.index('    def feedback_count', save_start)
    new_save = '''    def save_feedback(self, rating: str, user_text: str, assistant_text: str, correction: str = "", mode: str = "style", rule=None):
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
            f.write(json.dumps(row, ensure_ascii=False) + "\\n")

        if str(rating) == "down" and str(correction or "").strip():
            if mode in {"fixed", "semantic"}:
                self._upsert_rule(mode, user_text, correction, rule)
            if mode == "fixed":
                self._rewrite_history_with_correction(user_text, str(correction).strip())
            elif mode == "semantic":
                self._remove_history_for_question(user_text)

'''
    b = b[:save_start] + new_save + b[save_end:]

    # Replace V0.7.4 ask() with rule-match -> generate -> guard -> retry -> fallback.
    ask_start = b.index('    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6):\n')
    ask_end = b.index('    def last_exchange(self):\n', ask_start)
    new_ask = '''    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6):
        user_text = str(user_text or "").strip()
        if not user_text:
            self.generation_finished.emit(False, {}, "请输入一句话。")
            return
        if not self.ready():
            self.generation_finished.emit(False, {}, "请先点击“准备小美丽大脑”。")
            return
        if self._generate_busy:
            self.generation_finished.emit(False, {}, "小美丽还在想上一句话，稍等一下。")
            return

        self._generate_busy = True
        self.generation_started.emit()

        exact_rule = self._exact_rule(user_text)
        if exact_rule and str(exact_rule.get("mode") or "") == "fixed":
            try:
                forced = str(exact_rule.get("reference_answer") or "").strip()
                if not forced:
                    raise RuntimeError("固定规则没有参考答案")
                answer = {"spoken_text": forced[:180], "board_text": forced[:24], "emotion": "neutral"}
                history = self._load_history()
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)
                self._increment_rule_hit(exact_rule.get("id"))
                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }
                self.generation_finished.emit(
                    True, answer,
                    f"命中养成规则 #{exact_rule.get('id')}｜固定台词"
                )
            except Exception as exc:
                LOGGER.exception("固定规则回答失败")
                self.generation_finished.emit(False, {}, f"固定规则失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False
            return

        def job():
            try:
                self._start_server()
                matched_rule = exact_rule if exact_rule and exact_rule.get("enabled", True) else self._match_semantic_rule(user_text)
                if matched_rule and str(matched_rule.get("mode") or "") != "semantic":
                    matched_rule = None

                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()
                if matched_rule:
                    system += (
                        "\\n\\n【主人养成规则｜必须遵守】\\n"
                        + self._rule_prompt(matched_rule)
                        + "\\n这不是固定台词。请自然改写，但核心立场、必须体现和禁止偏离都必须满足。"
                    )

                examples = self._feedback_examples(10)
                if examples:
                    system += "\\n\\n以下是主人认可或固定过的说话方式，用于学习整体口吻："
                    for u, a in examples:
                        system += f"\\n主人：{u}\\n小美丽：{a}"

                history = self._load_history()
                max_msgs = max(2, int(context_turns) * 2)
                history = history[-max_msgs:]

                base_messages = [{"role": "system", "content": system}]
                base_messages.extend(history)

                payload_base = {
                    "model": "Qwen3-8B-Q4_K_M",
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "max_tokens": int(max_tokens),
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }

                started = time.time()
                accepted = None
                rewrite_count = 0
                last_reason = ""

                max_attempts = 3 if matched_rule else 1
                for attempt in range(max_attempts):
                    messages = list(base_messages)
                    extra = ""
                    if attempt > 0 and matched_rule:
                        extra = (
                            f"\\n上一条候选回答被语义守门拒绝，原因：{last_reason}。"
                            "\\n请重新回答，必须满足养成规则，但不要机械复述参考答案。"
                        )
                    messages.append({"role": "user", "content": user_text + "\\n/no_think" + extra})
                    payload = dict(payload_base)
                    payload["messages"] = messages
                    if attempt > 0:
                        payload["temperature"] = max(0.78, min(1.0, float(temperature) + 0.06 * attempt))

                    response = self._post_json("/v1/chat/completions", payload, timeout=180)
                    raw = str(response["choices"][0]["message"]["content"])
                    candidate = _normalize_answer(raw)

                    if not matched_rule:
                        accepted = candidate
                        break

                    passed, reason = self._guard_semantic_answer(
                        matched_rule, user_text, candidate.get("spoken_text", "")
                    )
                    if passed:
                        accepted = candidate
                        break
                    last_reason = reason or "未满足主人教的核心意思"
                    rewrite_count += 1

                if accepted is None and matched_rule:
                    fallback = str(matched_rule.get("reference_answer") or "").strip()
                    if not fallback:
                        fallback = str(matched_rule.get("intent") or "").strip()
                    accepted = {
                        "spoken_text": fallback[:180] or "我知道你的意思了，再问我一次。",
                        "board_text": (fallback[:24] or "按主人教的意思回答"),
                        "emotion": "neutral",
                    }

                answer = accepted
                elapsed = time.time() - started

                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)

                if matched_rule:
                    self._increment_rule_hit(matched_rule.get("id"))

                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }

                if matched_rule:
                    if rewrite_count == 0:
                        status = f"命中养成规则 #{matched_rule.get('id')}｜守门通过 · {elapsed:.1f}s"
                    elif rewrite_count < max_attempts:
                        status = (
                            f"命中养成规则 #{matched_rule.get('id')}｜"
                            f"自动重写 {rewrite_count} 次后通过 · {elapsed:.1f}s"
                        )
                    else:
                        status = (
                            f"命中养成规则 #{matched_rule.get('id')}｜"
                            f"守门连续拒绝，已回退主人参考答案 · {elapsed:.1f}s"
                        )
                else:
                    status = f"回答完成 · {elapsed:.1f}s"

                self.generation_finished.emit(True, answer, status)
            except Exception as exc:
                LOGGER.exception("小美丽大脑回答失败")
                self.generation_finished.emit(False, {}, f"回答失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False

        threading.Thread(target=job, name="XiaoMeiliBrainAsk", daemon=True).start()

'''
    b = b[:ask_start] + new_ask + b[ask_end:]

    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.5 semantic gate + learning library")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v075.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
