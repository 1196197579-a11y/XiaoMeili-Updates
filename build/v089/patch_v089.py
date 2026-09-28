# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.8.9 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.8.9 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.8.3"' not in s:
        raise RuntimeError("V0.8.9 expected APP_VERSION 0.8.8.3 base")
    s = s.replace('APP_VERSION = "0.8.8.3"', 'APP_VERSION = "0.8.9"', 1)
    s = s.replace("V0.8.8.3｜", "V0.8.9｜", 1)

    # ------------------------------------------------------------------
    # 1) Favorites dark-theme white-gap bug.
    # QScrollArea owns a viewport and a separate content host. V0.8.8.3 only
    # styled the cards, so the uncovered viewport/host area could stay white.
    # ------------------------------------------------------------------
    fav_anchor = '''        fav_scroll = QScrollArea()
        fav_scroll.setWidgetResizable(True)
        fav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fav_host = QWidget()
'''
    fav_new = '''        fav_scroll = QScrollArea()
        fav_scroll.setWidgetResizable(True)
        fav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fav_scroll.setAutoFillBackground(False)
        fav_scroll.viewport().setAutoFillBackground(False)
        fav_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea QWidget{background:transparent;}")
        fav_scroll.viewport().setStyleSheet("background:transparent;")
        fav_host = QWidget()
        fav_host.setObjectName("favoritesHost")
        fav_host.setAutoFillBackground(False)
        fav_host.setStyleSheet("QWidget#favoritesHost{background:transparent;}")
'''
    if fav_anchor not in s:
        raise RuntimeError("V0.8.9 favorites scroll anchor missing")
    s = s.replace(fav_anchor, fav_new, 1)

    # ------------------------------------------------------------------
    # 2) Unified V0.8.9 rule editor:
    #    top-center segmented mode switch: 模仿 / 固定
    #    模仿 -> behavior rule editor
    #    固定 -> multi-sentence zero-inference random reply pool
    # ------------------------------------------------------------------
    editor = r'''    def _v0883_open_rule_editor(self, existing=None, user_text="", assistant_text="", from_chat=False):
        existing = dict(existing or {})
        rid = str(existing.get("id") or "").strip()
        original_user = str(existing.get("user_text") or user_text or "").strip()
        assistant_text = str(assistant_text or "").strip()
        original_reference = str(existing.get("reference_answer") or assistant_text).strip()
        original_intent = str(existing.get("intent") or original_reference or assistant_text).strip()
        original_mode = "fixed" if str(existing.get("mode") or "").strip().lower() == "fixed" else "semantic"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑养成规则 · {rid}" if rid else "纠正 / 养成")
        try: dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        except Exception: pass
        dlg.resize(740, 760)
        root = QVBoxLayout(dlg); root.setContentsMargins(18,16,18,16); root.setSpacing(10)

        title = QLabel("修改同类问题命中时，小美丽应该怎么想、怎么说")
        title.setObjectName("pageTitle"); root.addWidget(title)
        sub = QLabel("「模仿」让小美丽记住行为和立场后自己组织新回答；「固定」不调用大模型，直接从你的回复池中随机挑一句。")
        sub.setWordWrap(True); sub.setObjectName("pageSubtitle"); root.addWidget(sub)

        root.addWidget(QLabel("触发问题 / 示例"))
        question = QLineEdit(original_user)
        question.setPlaceholderText("例如：小美丽你在干嘛？")
        root.addWidget(question)

        # Prominent segmented switch.
        mode_row = QHBoxLayout()
        mode_row.addStretch(1)
        mimic_btn = QPushButton("模仿")
        fixed_btn = QPushButton("固定")
        for btn in (mimic_btn, fixed_btn):
            btn.setObjectName("learningModeSwitch")
            btn.setCheckable(True)
            btn.setFixedSize(176, 46)
            btn.setStyleSheet(
                "QPushButton#learningModeSwitch{"
                "border:1px solid #4FCFB0;border-radius:11px;padding:7px 22px;"
                "font-size:16px;font-weight:700;background:transparent;color:palette(text);"
                "}"
                "QPushButton#learningModeSwitch:hover{background:rgba(79,207,176,0.12);}"
                "QPushButton#learningModeSwitch:checked{background:#4FCFB0;color:#08352D;border-color:#4FCFB0;}"
            )
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        mode_hint = QLabel("")
        mode_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_hint.setObjectName("pageSubtitle")
        mode_hint.setWordWrap(True)
        root.addWidget(mode_hint)

        pages = QStackedWidget()
        root.addWidget(pages, 1)

        # ---------------- 模仿 ----------------
        mimic_page = QWidget()
        mv = QVBoxLayout(mimic_page)
        mv.setContentsMargins(0, 4, 0, 0)
        mv.setSpacing(9)

        mv.addWidget(QLabel("核心立场"))
        intent_edit = QTextEdit()
        intent_edit.setMinimumHeight(105)
        intent_edit.setPlaceholderText("写小美丽真正要坚持的态度/行为，不要只写一句台词。")
        intent_edit.setPlainText(original_intent)
        mv.addWidget(intent_edit)

        mv.addWidget(QLabel("参考说法（只学风格，不要求复读）"))
        reference_edit = QLineEdit(original_reference)
        reference_edit.setPlaceholderText("例如：要你管！  这里只是示例，不会作为必须复读的答案。")
        mv.addWidget(reference_edit)

        mimic_box = QGroupBox("语义规则｜命中后只执行这一条行为规则")
        mimic_form = QFormLayout(mimic_box)
        scene = QLineEdit(str(existing.get("scene") or original_user))
        scene.setPlaceholderText("描述哪类问题 / 哪种场景应触发，不要写回答内容")
        must = QLineEdit(str(existing.get("must") or ""))
        must.setPlaceholderText("回答中必须体现的立场或动作")
        forbid = QLineEdit(str(existing.get("forbid") or "不要反转核心立场；不要机械复读参考说法"))
        tone = QLineEdit(str(existing.get("tone") or "自然、傲娇、损友式、短促；允许每次换说法"))
        mimic_form.addRow("场景", scene)
        mimic_form.addRow("必须体现", must)
        mimic_form.addRow("禁止偏离", forbid)
        mimic_form.addRow("语气", tone)
        mv.addWidget(mimic_box)
        mv.addStretch(1)
        pages.addWidget(mimic_page)

        # ---------------- 固定 ----------------
        fixed_page = QWidget()
        fv = QVBoxLayout(fixed_page)
        fv.setContentsMargins(0, 4, 0, 0)
        fv.setSpacing(9)

        speed_badge = QLabel("⚡ 0 次模型思考 · 命中后直接随机回复")
        speed_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_badge.setStyleSheet(
            "padding:8px 12px;border:1px solid rgba(79,207,176,0.45);"
            "border-radius:9px;font-weight:700;background:rgba(79,207,176,0.08);"
        )
        fv.addWidget(speed_badge)

        fixed_desc = QLabel("把你认可的台词放进回复池。相同/相近触发问题命中后，小美丽直接随机挑一句；有两句以上时会尽量避免连续重复。")
        fixed_desc.setWordWrap(True)
        fixed_desc.setObjectName("pageSubtitle")
        fv.addWidget(fixed_desc)

        fixed_list = QListWidget()
        fixed_list.setMinimumHeight(260)
        fixed_list.setAlternatingRowColors(False)
        initial_pool = existing.get("fixed_replies") or []
        if not isinstance(initial_pool, list):
            initial_pool = []
        initial_pool = [str(x or "").strip() for x in initial_pool if str(x or "").strip()]
        if not initial_pool and original_reference:
            initial_pool = [original_reference]
        for line in initial_pool:
            fixed_list.addItem(line)
        fv.addWidget(fixed_list, 1)

        add_row = QHBoxLayout()
        fixed_input = QLineEdit()
        fixed_input.setPlaceholderText("输入一条固定回复，例如：查岗啊？不告诉你。")
        add_btn = QPushButton("＋ 添加")
        add_row.addWidget(fixed_input, 1)
        add_row.addWidget(add_btn)
        fv.addLayout(add_row)

        edit_row = QHBoxLayout()
        edit_fixed_btn = QPushButton("编辑选中")
        remove_fixed_btn = QPushButton("删除选中")
        clear_fixed_btn = QPushButton("清空")
        edit_row.addWidget(edit_fixed_btn)
        edit_row.addWidget(remove_fixed_btn)
        edit_row.addWidget(clear_fixed_btn)
        edit_row.addStretch(1)
        count_label = QLabel("0 句")
        count_label.setObjectName("pageSubtitle")
        edit_row.addWidget(count_label)
        fv.addLayout(edit_row)
        pages.addWidget(fixed_page)

        def refresh_count():
            count_label.setText(f"{fixed_list.count()} 句")

        def add_fixed():
            text_value = fixed_input.text().strip()
            if not text_value:
                return
            for i in range(fixed_list.count()):
                if fixed_list.item(i).text().strip() == text_value:
                    fixed_input.clear()
                    return
            fixed_list.addItem(text_value)
            fixed_input.clear()
            fixed_list.setCurrentRow(fixed_list.count() - 1)
            refresh_count()

        def edit_fixed():
            item = fixed_list.currentItem()
            if item is None:
                return
            value, ok = QInputDialog.getText(dlg, "编辑固定回复", "回复内容：", text=item.text())
            if ok and str(value or "").strip():
                item.setText(str(value).strip())
                refresh_count()

        def remove_fixed():
            row = fixed_list.currentRow()
            if row >= 0:
                fixed_list.takeItem(row)
                refresh_count()

        add_btn.clicked.connect(add_fixed)
        fixed_input.returnPressed.connect(add_fixed)
        edit_fixed_btn.clicked.connect(edit_fixed)
        remove_fixed_btn.clicked.connect(remove_fixed)
        clear_fixed_btn.clicked.connect(lambda: (fixed_list.clear(), refresh_count()))
        fixed_list.itemDoubleClicked.connect(lambda _item: edit_fixed())
        refresh_count()

        active_mode = {"value": original_mode}

        def apply_mode(mode):
            mode = "fixed" if mode == "fixed" else "semantic"
            active_mode["value"] = mode
            is_fixed = mode == "fixed"
            mimic_btn.blockSignals(True); fixed_btn.blockSignals(True)
            mimic_btn.setChecked(not is_fixed)
            fixed_btn.setChecked(is_fixed)
            mimic_btn.blockSignals(False); fixed_btn.blockSignals(False)
            pages.setCurrentIndex(1 if is_fixed else 0)
            mode_hint.setText(
                "固定：追求最快响应。命中后不启动 Qwen 推理，直接从回复池随机挑一句。"
                if is_fixed else
                "模仿：记住触发范围、核心立场和语气，由小美丽现场组织新句子；正常只进行 1 次主推理。"
            )

        mimic_btn.clicked.connect(lambda checked=False: apply_mode("semantic"))
        fixed_btn.clicked.connect(lambda checked=False: apply_mode("fixed"))
        apply_mode(original_mode)

        if rid:
            current_name = "固定" if original_mode == "fixed" else "模仿"
            status = QLabel(f"当前：#{rid} · {current_name}。保存会直接覆盖这一条，并保留规则编号、分组和命中次数。")
        else:
            status = QLabel("当前：新规则。")
        status.setWordWrap(True)
        root.addWidget(status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("保存并应用")
        save_btn.setMinimumWidth(132)
        cancel_btn = QPushButton("取消")
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        cancel_btn.clicked.connect(dlg.reject)

        def commit():
            q = question.text().strip()
            if not q:
                QMessageBox.warning(dlg, "无法保存", "触发问题 / 示例不能为空。")
                return

            mode = active_mode["value"]
            if mode == "semantic":
                intent = intent_edit.toPlainText().strip()
                if not intent:
                    QMessageBox.warning(dlg, "无法保存", "模仿模式下「核心立场」不能为空。")
                    return
                reference = reference_edit.text().strip() or intent
                scene_text = scene.text().strip() or q
                must_text = must.text().strip() or intent
                forbid_text = forbid.text().strip() or "不要反转核心立场；不要机械复读参考说法"
                tone_text = tone.text().strip() or "自然、符合小美丽人格；允许每次换说法"
                changes = {
                    "mode": "semantic",
                    "user_text": q,
                    "scene": scene_text,
                    "intent": intent,
                    "must": must_text,
                    "forbid": forbid_text,
                    "tone": tone_text,
                    "reference_answer": reference,
                    "fixed_replies": [],
                }
                if rid:
                    saved = self.brain_service.update_rule(rid, changes)
                    if not saved:
                        QMessageBox.warning(dlg, "保存失败", "没有找到原规则，已取消本次修改。")
                        return
                else:
                    self.brain_service.save_feedback(
                        "down", q, assistant_text, reference, "semantic",
                        {
                            "scene": scene_text,
                            "intent": intent,
                            "must": must_text,
                            "forbid": forbid_text,
                            "tone": tone_text,
                        },
                    )
                label = "模仿"
                self.brain_status.setText("模仿规则已保存：只记住行为与立场，参考说法不参与规则匹配，也不会被当成固定台词。")
            else:
                pool = []
                for i in range(fixed_list.count()):
                    value = fixed_list.item(i).text().strip()
                    if value and value not in pool:
                        pool.append(value)
                if not pool:
                    QMessageBox.warning(dlg, "无法保存", "固定模式至少需要添加 1 句回复。")
                    return
                reference = pool[0]
                changes = {
                    "mode": "fixed",
                    "user_text": q,
                    "scene": q,
                    "intent": "",
                    "must": "",
                    "forbid": "",
                    "tone": "",
                    "reference_answer": reference,
                    "fixed_replies": pool,
                }
                if rid:
                    saved = self.brain_service.update_rule(rid, changes)
                    if not saved:
                        QMessageBox.warning(dlg, "保存失败", "没有找到原规则，已取消本次修改。")
                        return
                else:
                    self.brain_service.save_feedback(
                        "down", q, assistant_text, reference, "fixed",
                        {"fixed_replies": pool},
                    )
                label = "固定"
                self.brain_status.setText(f"固定回复池已保存：{len(pool)} 句。命中后 0 次模型推理，直接随机回复。")

            if from_chat:
                try:
                    self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
                    self.brain_chat.addItem(f"你教她（{label}）：已保存")
                    self.brain_chat.scrollToBottom()
                    self.brain_like_btn.setEnabled(False)
                    self.brain_dislike_btn.setEnabled(False)
                except Exception:
                    pass

            self._refresh_brain_rules()
            self._v774_refresh_brain_summary()
            try: self._v0882_refresh_favorites()
            except Exception: pass
            dlg.accept()

        save_btn.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

'''
    s = replace_method(s, "_v0883_open_rule_editor", "_brain_dislike", editor, "V0.8.9 mimic/fixed editor")

    # Library display text: use user-facing mode names without changing the
    # persisted schema (semantic/fixed remains backward compatible).
    s = s.replace(
        'mode_text = "固定台词" if str(rule.get("mode") or "") == "fixed" else "语义规则"',
        'mode_text = "固定" if str(rule.get("mode") or "") == "fixed" else "模仿"',
    )

    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_brain(path: Path):
    b = path.read_text(encoding="utf-8")

    if "import random\n" not in b:
        if "import json\n" not in b:
            raise RuntimeError("V0.8.9 json import anchor missing")
        b = b.replace("import json\n", "import json\nimport random\n", 1)

    # Allow the rule store to persist fixed pools and per-rule recent replies.
    old_keys = '''                "mode", "user_text", "scene", "intent", "must", "forbid",
                "tone", "reference_answer", "enabled", "group_id",
'''
    new_keys = '''                "mode", "user_text", "scene", "intent", "must", "forbid",
                "tone", "reference_answer", "fixed_replies", "recent_replies",
                "enabled", "group_id",
'''
    if old_keys not in b:
        raise RuntimeError("V0.8.9 update_rule key anchor missing")
    b = b.replace(old_keys, new_keys, 1)

    # _upsert_rule: fixed pools are saved through structured metadata too.
    upsert_anchor = '''            "tone": str(structured.get("tone") or "保持主人纠正时的口吻").strip() if mode == "semantic" else "",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
'''
    upsert_new = '''            "tone": str(structured.get("tone") or "保持主人纠正时的口吻").strip() if mode == "semantic" else "",
            "fixed_replies": [
                str(x or "").strip()
                for x in (structured.get("fixed_replies") or [])
                if str(x or "").strip()
            ] if mode == "fixed" else [],
            "recent_replies": list(target.get("recent_replies") or [])[-5:],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
'''
    if upsert_anchor not in b:
        raise RuntimeError("V0.8.9 _upsert_rule anchor missing")
    b = b.replace(upsert_anchor, upsert_new, 1)

    # Trigger-only retrieval. Answer content (intent/must/reference/tone) is
    # explicitly excluded from matching to prevent "what she should say" from
    # changing "when this rule should trigger".
    start = b.find("    def _v088_rule_score(")
    end = b.find("    def _match_semantic_rule(", start)
    if start < 0 or end < 0:
        raise RuntimeError("V0.8.9 fast matcher anchors missing")

    matcher = r'''    @staticmethod
    def _v089_trigger_normalize(text):
        text = str(text or "").lower().strip()
        replacements = (
            ("在做什么", "在干嘛"),
            ("做什么", "干嘛"),
            ("干什么", "干嘛"),
            ("干啥", "干嘛"),
            ("忙什么", "干嘛"),
            ("忙啥", "干嘛"),
            ("可不可以", "能"),
            ("能不能", "能"),
            ("能否", "能"),
            ("行不行", "能"),
            ("厉不厉害", "厉害"),
            ("牛不牛", "厉害"),
            ("强不强", "厉害"),
        )
        for old, new in replacements:
            text = text.replace(old, new)
        text = re.sub(r"[\s，,。.!！？?、:：；;（）()\[\]{}<>《》‘’“”\"']", "", text)
        text = re.sub(r"[呀啊呢吧啦呗哇]+$", "", text)
        return text[:220]

    @staticmethod
    def _v089_pair_score(query, target):
        q = BrainService._v089_trigger_normalize(query)
        t = BrainService._v089_trigger_normalize(target)
        if not q or not t:
            return 0.0
        if q == t:
            return 1.0
        q2 = BrainService._v088_ngrams(q, 2)
        t2 = BrainService._v088_ngrams(t, 2)
        q3 = BrainService._v088_ngrams(q, 3)
        t3 = BrainService._v088_ngrams(t, 3)
        seq = difflib.SequenceMatcher(None, q, t).ratio()
        j2 = len(q2 & t2) / max(1, len(q2 | t2))
        j3 = len(q3 & t3) / max(1, len(q3 | t3))
        cq, ct = set(q), set(t)
        char_j = len(cq & ct) / max(1, len(cq | ct))
        score = 0.48 * seq + 0.27 * j2 + 0.12 * j3 + 0.13 * char_j
        if q in t or t in q:
            score += 0.18
        return max(0.0, min(1.0, score))

    def _v088_rule_score(self, user_text, rule):
        # Only trigger-side data may participate in matching.
        targets = [str(rule.get("user_text") or "")]
        aliases = rule.get("feedback_aliases") or []
        if isinstance(aliases, list):
            targets.extend(str(x or "") for x in aliases if str(x or "").strip())

        scores = [self._v089_pair_score(user_text, target) for target in targets if target]
        scene = str(rule.get("scene") or "").strip()
        if scene:
            # Scene is descriptive prose, so it gets a small discount.
            scores.append(self._v089_pair_score(user_text, scene) * 0.88)
        return max(scores or [0.0])

    def _active_rules_v2(self, limit=120):
        rows = [
            dict(r) for r in reversed(self._load_rules())
            if r.get("enabled", True) and str(r.get("mode") or "") in {"semantic", "fixed"}
        ]
        return rows[:max(1, int(limit))]

    def _fast_rule_candidates(self, user_text, limit=6):
        exact = self._exact_rule(user_text)
        if exact:
            exact["_match_confidence"] = 1.0
            exact["_exact_match"] = True
            return [exact]

        scored = []
        for index, rule in enumerate(self._active_rules_v2(120)):
            score = self._v088_rule_score(user_text, rule)
            if score < 0.16:
                continue
            row = dict(rule)
            row["_match_confidence"] = float(score)
            row["_exact_match"] = False
            # Very small recency tiebreaker only; never enough to make an
            # unrelated rule win.
            scored.append((score + max(0.0, 0.004 - index * 0.00005), row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _score, row in scored[:max(1, int(limit))]]

    def _v089_best_rule(self, user_text):
        rows = self._fast_rule_candidates(user_text, 3)
        if not rows:
            return None
        top = dict(rows[0])
        score = float(top.get("_match_confidence") or 0.0)
        if top.get("_exact_match"):
            top["_ambiguous"] = False
            return top
        second = float(rows[1].get("_match_confidence") or 0.0) if len(rows) > 1 else 0.0
        top["_ambiguous"] = bool(second and score < 0.82 and (score - second) < 0.06)
        return top

    @staticmethod
    def _v089_reply_similarity(a, b):
        a = re.sub(r"[\s，,。.!！？?、:：；;（）()]+", "", str(a or "").lower())
        b = re.sub(r"[\s，,。.!！？?、:：；;（）()]+", "", str(b or "").lower())
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio()

    def _v089_rule_recent(self, rule):
        values = rule.get("recent_replies") or []
        if not isinstance(values, list):
            return []
        return [str(x or "").strip() for x in values if str(x or "").strip()][-5:]

    def _v089_remember_rule_reply(self, rule_id, reply):
        if not rule_id or not str(reply or "").strip():
            return
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id")) != str(rule_id):
                continue
            recent = self._v089_rule_recent(rule)
            reply = str(reply).strip()
            recent = [x for x in recent if x != reply]
            recent.append(reply)
            rule["recent_replies"] = recent[-5:]
            rule["last_hit_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_rules(rules)
            return

    def _v089_fixed_reply(self, rule):
        pool = rule.get("fixed_replies") or []
        if not isinstance(pool, list):
            pool = []
        pool = [str(x or "").strip() for x in pool if str(x or "").strip()]
        fallback = str(rule.get("reference_answer") or "").strip()
        if not pool and fallback:
            pool = [fallback]
        if not pool:
            return ""
        recent = self._v089_rule_recent(rule)
        last = recent[-1] if recent else ""
        choices = [x for x in pool if x != last] if len(pool) > 1 else list(pool)
        if not choices:
            choices = list(pool)
        return random.choice(choices)

'''
    b = b[:start] + matcher + b[end:]

    semantic_compat = r'''    def _match_semantic_rule(self, user_text):
        rule = self._v089_best_rule(user_text)
        if not rule or str(rule.get("mode") or "") != "semantic":
            return None
        score = float(rule.get("_match_confidence") or 0.0)
        if rule.get("_exact_match") or (score >= 0.58 and not rule.get("_ambiguous")):
            return rule
        return None

'''
    b = replace_method(b, "_match_semantic_rule", "_guard_semantic_answer", semantic_compat, "semantic compatibility matcher")

    # Behavior prompt: no reference phrase, and no answer-side fields affect
    # retrieval. It describes an executable behavior, not a sentence template.
    prompt = r'''    @staticmethod
    def _rule_prompt(rule):
        return (
            f"规则编号：{rule.get('id')}\n"
            f"触发范围：{rule.get('scene','') or rule.get('user_text','')}\n"
            f"核心立场：{rule.get('intent','')}\n"
            f"必须体现：{rule.get('must','')}\n"
            f"禁止偏离：{rule.get('forbid','')}\n"
            f"语气：{rule.get('tone','')}\n"
            "这是行为策略，不是台词模板。只要当前问题属于触发范围，就按这个立场回应；"
            "必须针对主人这一次的具体问法现场组织一句新的自然回答。"
        )

'''
    b = replace_method(b, "_rule_prompt", "_v088_match_text", prompt, "V0.8.9 behavior prompt")

    ask = r'''    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6, long_term_memory=True):
        user_text = str(user_text or "").strip()
        if not user_text:
            self.generation_finished.emit(False, {}, "请输入一句话。")
            return
        if self._generate_busy:
            self.generation_finished.emit(False, {}, "小美丽还在想上一句话，稍等一下。")
            return

        # Rule lookup is local and cheap. Do it before checking/loading Qwen so
        # fixed pools can answer even when the LLM is not resident.
        retrieval_started = time.time()
        exact_rule = self._exact_rule(user_text)
        best_rule = dict(exact_rule or self._v089_best_rule(user_text) or {})
        retrieval_ms = int((time.time() - retrieval_started) * 1000)

        # Fixed mode is the latency-first lane: exact or high-confidence,
        # non-ambiguous trigger -> 0 model calls.
        if best_rule and str(best_rule.get("mode") or "") == "fixed":
            confidence = float(best_rule.get("_match_confidence") or (1.0 if exact_rule else 0.0))
            safe_fixed = bool(exact_rule) or (
                confidence >= 0.72 and not bool(best_rule.get("_ambiguous"))
            )
            if safe_fixed:
                self._generate_busy = True
                self.generation_started.emit()
                try:
                    forced = self._v089_fixed_reply(best_rule)
                    if not forced:
                        raise RuntimeError("固定回复池为空")
                    answer = {
                        "spoken_text": forced[:180],
                        "board_text": forced[:24],
                        "emotion": "neutral",
                    }
                    history = self._load_history()
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": answer["spoken_text"]})
                    self._save_history(history)
                    self._increment_rule_hit(best_rule.get("id"))
                    self._v089_remember_rule_reply(best_rule.get("id"), answer["spoken_text"])
                    self._last_exchange = {
                        "user_text": user_text,
                        "assistant_text": answer["spoken_text"],
                        "answer": answer,
                    }
                    self.generation_finished.emit(
                        True, answer,
                        f"命中固定规则 #{best_rule.get('id')}｜回复池随机 · 0 次模型推理 · 检索 {retrieval_ms}ms",
                    )
                except Exception as exc:
                    LOGGER.exception("固定回复池回答失败")
                    self.generation_finished.emit(False, {}, f"固定回复失败：{type(exc).__name__}: {exc}")
                finally:
                    self._generate_busy = False
                return

        if not self.ready():
            self.generation_finished.emit(False, {}, "请先点击“准备小美丽大脑”。")
            return

        self._generate_busy = True
        self.generation_started.emit()
        if bool(long_term_memory):
            self.auto_remember(user_text)

        # Only one possible mimic rule is ever handed to Qwen. A low-confidence
        # candidate may be shown as "possible", letting the same single
        # generation decide relevance; we never run a separate LLM classifier.
        mimic_rule = None
        if best_rule and str(best_rule.get("mode") or "") == "semantic":
            score = float(best_rule.get("_match_confidence") or (1.0 if exact_rule else 0.0))
            if bool(exact_rule) or (score >= 0.28 and not bool(best_rule.get("_ambiguous"))):
                mimic_rule = dict(best_rule)

        def job():
            total_started = time.time()
            try:
                self._start_server()

                system = str(persona or DEFAULT_PERSONA).strip() + "\n\n" + OUTPUT_CONTRACT.strip()
                system += (
                    "\n\n【对话底线】必须回应主人当前真正的意思。"
                    "「模仿」规则只约束行为与立场，不是参考台词；除固定模式外禁止机械复读历史回答。"
                )

                if bool(long_term_memory):
                    recalled = self.recall_memories(user_text, 8)
                    if recalled:
                        system += (
                            "\n\n【小美丽的长期记忆｜仅在相关时自然使用】\n"
                            "只在与当前话题真正有关时使用，不要主动复述，也不要编造。\n"
                            + "\n".join(f"• {item}" for item in recalled)
                        )

                recent_rule_replies = []
                rule_score = 0.0
                if mimic_rule:
                    rule_score = float(mimic_rule.get("_match_confidence") or (1.0 if exact_rule else 0.0))
                    system += (
                        "\n\n【唯一可能相关的模仿规则】\n"
                        + self._rule_prompt(mimic_rule)
                        + "\n先判断主人这一次的问题是否真的属于上面的触发范围。"
                        "如果属于，就严格保持核心立场；如果不属于，就完全忽略这条规则，正常回答。"
                    )
                    recent_rule_replies = self._v089_rule_recent(mimic_rule)
                    if recent_rule_replies:
                        system += (
                            "\n\n【这条规则最近已经说过的话｜本轮禁止复读或近似复述】\n"
                            + "\n".join(f"- {x}" for x in recent_rule_replies)
                        )

                examples = self._feedback_examples(8)
                if examples:
                    system += "\n\n以下只用于学习整体说话口吻，不是当前问题的答案："
                    for u, a in examples:
                        system += f"\n主人：{u}\n小美丽：{a}"

                history = self._load_history()
                max_msgs = max(2, int(context_turns) * 2)
                history = history[-max_msgs:]
                messages = [{"role": "system", "content": system}]
                messages.extend(history)
                messages.append({"role": "user", "content": user_text + "\n/no_think"})

                payload = {
                    "model": "Qwen3-8B-Q4_K_M",
                    "messages": messages,
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "max_tokens": int(max_tokens),
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }

                generation_started = time.time()
                response = self._post_json("/v1/chat/completions", payload, timeout=180)
                answer = _normalize_answer(str(response["choices"][0]["message"]["content"]))
                rewrite_count = 0

                # Program-level anti-repeat. Normal path remains one inference.
                # Only an actual near-duplicate triggers one fast rewrite.
                if mimic_rule and recent_rule_replies:
                    duplicate = any(
                        self._v089_reply_similarity(answer.get("spoken_text"), old) >= 0.84
                        for old in recent_rule_replies
                    )
                    if duplicate:
                        retry_messages = list(messages)
                        retry_messages[-1] = {
                            "role": "user",
                            "content": (
                                user_text
                                + "\n/no_think\n"
                                + "你刚才准备的回答与这条规则最近的说法太像。"
                                  "核心立场不变，但必须换一个明显不同的措辞和句式，仍然保持自然短句。"
                            ),
                        }
                        retry_payload = dict(payload)
                        retry_payload["messages"] = retry_messages
                        retry_payload["temperature"] = max(0.92, float(temperature))
                        retry = self._post_json("/v1/chat/completions", retry_payload, timeout=180)
                        answer = _normalize_answer(str(retry["choices"][0]["message"]["content"]))
                        rewrite_count = 1

                generation_ms = int((time.time() - generation_started) * 1000)

                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)

                strong_rule = None
                if mimic_rule and (bool(exact_rule) or (rule_score >= 0.58 and not mimic_rule.get("_ambiguous"))):
                    strong_rule = mimic_rule
                    self._increment_rule_hit(strong_rule.get("id"))
                    self._v089_remember_rule_reply(strong_rule.get("id"), answer["spoken_text"])

                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }

                total_ms = int((time.time() - total_started) * 1000)
                if strong_rule:
                    prefix = f"命中模仿规则 #{strong_rule.get('id')}｜"
                elif mimic_rule:
                    prefix = "参考 1 条可能相关规则｜"
                else:
                    prefix = ""
                retry_text = " · 防复读重写1次" if rewrite_count else ""
                status = (
                    f"{prefix}规则检索 {retrieval_ms}ms · 生成 {generation_ms/1000:.1f}s"
                    f"{retry_text} · 总计 {total_ms/1000:.1f}s"
                )
                LOGGER.info(
                    "[BRAIN_LATENCY] retrieval_ms=%s generation_ms=%s total_ms=%s rule=%s rewrite=%s",
                    retrieval_ms, generation_ms, total_ms,
                    str((mimic_rule or {}).get("id") or ""), rewrite_count,
                )
                self.generation_finished.emit(True, answer, status)
            except Exception as exc:
                LOGGER.exception("小美丽大脑回答失败")
                self.generation_finished.emit(False, {}, f"回答失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False

        threading.Thread(target=job, name="XiaoMeiliBrainAsk", daemon=True).start()

'''
    b = replace_method(b, "ask", "last_exchange", ask, "V0.8.9 latency-first rule execution")

    path.write_text(b, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    s = re.sub(
        r"小美丽 V0\.8\.[0-9.]+ 语音诊断日志",
        "小美丽 V0.8.9 语音诊断日志",
        s,
    )
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    brain = root / "app" / "src" / "brain_qwen.py"
    speech = root / "app" / "src" / "speech_input.py"
    for p in (main, brain, speech):
        if not p.exists():
            raise FileNotFoundError(p)

    patch_main(main)
    patch_brain(brain)
    patch_speech(speech)

    m = main.read_text(encoding="utf-8")
    b = brain.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")

    main_checks = [
        'APP_VERSION = "0.8.9"',
        'QPushButton("模仿")',
        'QPushButton("固定")',
        '⚡ 0 次模型思考 · 命中后直接随机回复',
        'fixed_replies',
        '保存并应用',
        'fav_scroll.viewport().setStyleSheet("background:transparent;")',
    ]
    for token in main_checks:
        if token not in m:
            raise RuntimeError("V0.8.9 main verification failed: " + token)

    brain_checks = [
        'def _v089_trigger_normalize(text):',
        'def _v089_best_rule(self, user_text):',
        'def _v089_fixed_reply(self, rule):',
        '固定回复池回答失败',
        '0 次模型推理',
        '唯一可能相关的模仿规则',
        '防复读重写1次',
    ]
    for token in brain_checks:
        if token not in b:
            raise RuntimeError("V0.8.9 brain verification failed: " + token)

    score_block = b[b.find("    def _v088_rule_score("):b.find("    def _active_rules_v2(")]
    for forbidden in ("intent", "must", "forbid", "reference_answer", "tone"):
        if f'rule.get("{forbidden}")' in score_block or f"rule.get('{forbidden}')" in score_block:
            raise RuntimeError("V0.8.9 trigger matcher still reads answer-side field: " + forbidden)

    ask_block = b[b.find("    def ask("):b.find("    def last_exchange(")]
    if ask_block.count('_post_json("/v1/chat/completions"') > 2:
        raise RuntimeError("V0.8.9 ask unexpectedly contains more than main + rare anti-repeat retry")
    if "candidates = self._fast_rule_candidates(user_text, 6)" in ask_block:
        raise RuntimeError("V0.8.9 still injects six candidate rules")

    if "小美丽 V0.8.9 语音诊断日志" not in sp:
        raise RuntimeError("V0.8.9 speech diagnostic version label missing")

    print("Patched XiaoMeili source to V0.8.9: favorites dark fix + mimic/fixed rule V2 + zero-inference reply pools")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v089.py <source_root>")
    patch(Path(sys.argv[1]))
