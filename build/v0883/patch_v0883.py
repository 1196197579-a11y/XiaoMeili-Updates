# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.8.8.3 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.8.8.3 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.8.2"' not in s:
        raise RuntimeError("V0.8.8.3 expected APP_VERSION 0.8.8.2 base")
    s = s.replace('APP_VERSION = "0.8.8.2"', 'APP_VERSION = "0.8.8.3"', 1)
    s = s.replace("V0.8.8.2｜", "V0.8.8.3｜", 1)

    # ------------------------------------------------------------------
    # 1) Real vector five-point star. Unicode ☆/★ rendered inconsistently on
    # some Windows font/DPI combinations, which is why V0.8.8.2 could look
    # like a vertical punctuation mark instead of a star.
    # ------------------------------------------------------------------
    settings_anchor = "class SettingsDialog(QDialog):\n"
    if settings_anchor not in s:
        raise RuntimeError("V0.8.8.3 SettingsDialog anchor missing")
    star_class = r'''from PySide6.QtGui import QPainterPath


class FavoriteStarButton(QPushButton):
    """Font-independent five-point favorite button used by every settings card."""

    def __init__(self, checked=False, parent=None):
        super().__init__("", parent)
        self.setObjectName("favoriteButton")
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("收藏到常用")
        self.setStyleSheet(
            "QPushButton#favoriteButton{background:transparent;border:none;padding:0px;"
            "min-width:34px;max-width:34px;min-height:34px;max-height:34px;}"
        )

    @staticmethod
    def _star_path(rect):
        # Normalized ten-point polygon: five outer tips + five inner corners.
        pts = (
            (0.500, 0.030),
            (0.615, 0.355),
            (0.965, 0.365),
            (0.690, 0.575),
            (0.790, 0.925),
            (0.500, 0.725),
            (0.210, 0.925),
            (0.310, 0.575),
            (0.035, 0.365),
            (0.385, 0.355),
        )
        left = rect.left() + 6.0
        top = rect.top() + 5.5
        width = max(1.0, rect.width() - 12.0)
        height = max(1.0, rect.height() - 11.0)
        path = QPainterPath()
        for i, (x, y) in enumerate(pts):
            px = left + x * width
            py = top + y * height
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 200, 61, 34 if not self.isChecked() else 48))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)

        star = self._star_path(self.rect())
        if self.isChecked():
            painter.setPen(QColor("#D99A00"))
            painter.setBrush(QColor("#FFC83D"))
        else:
            painter.setPen(QColor("#9DAEA7") if not self.underMouse() else QColor("#D5A000"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(star)

        # Small highlight keeps the selected icon close to the soft yellow
        # reference image without depending on an external PNG asset.
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 92))
            painter.drawEllipse(12, 9, 5, 3)
        painter.end()


'''
    s = s.replace(settings_anchor, star_class + settings_anchor, 1)

    # Keep page context automatically. This makes the favorite system cover
    # future _v774_card tiles too, rather than maintaining a brittle whitelist.
    page_anchor = '''    def _v774_page(self, title, subtitle):
        page = QWidget()
'''
    page_new = '''    def _v774_page(self, title, subtitle):
        self._v0883_current_page = str(title or "")
        page = QWidget()
'''
    if page_anchor not in s:
        raise RuntimeError("V0.8.8.3 _v774_page anchor missing")
    s = s.replace(page_anchor, page_new, 1)

    feature_meta = r'''    def _v0882_feature_meta(self, title):
        # Stable IDs for known tiles keep V0.8.8.2 favorites compatible.
        # Any future _v774_card tile still receives a favorite button via the
        # page/title fallback instead of silently losing the control.
        mapping = {
            "昵称": ("general.name", "常规"),
            "开机启动": ("general.autostart", "常规"),
            "始终置顶": ("general.top", "常规"),
            "点击穿透": ("general.clickthrough", "常规"),
            "锁定位置": ("general.lock", "常规"),
            "透明度": ("general.opacity", "常规"),
            "桌宠大小": ("general.size", "常规"),
            "快捷键": ("general.hotkeys", "常规"),
            "桌宠位置": ("general.position", "常规"),
            "AI 大脑": ("brain.ai", "大脑"),
            "小美丽性格": ("brain.persona", "大脑"),
            "记忆": ("brain.memory", "大脑"),
            "学习与养成": ("brain.learning", "大脑"),
            "表达自由度": ("brain.expression", "大脑"),
            "对话测试": ("brain.chat_test", "大脑"),
            "唤醒词": ("voice.wake", "声音"),
            "语音识别": ("voice.asr", "声音"),
            "语音对话": ("voice.dialogue", "声音"),
            "唤醒回应": ("voice.wake_replies", "声音"),
            "小美丽声音": ("voice.tts", "声音"),
            "单句语气微调": ("voice.phrase_style", "声音"),
            "回答后自动说出来": ("voice.auto_speak", "声音"),
            "声音输出": ("voice.output", "声音"),
            "输入设备": ("voice.input", "声音"),
            "鼠标跟随": ("interaction.mouse", "互动"),
            "跟随强度": ("interaction.strength", "互动"),
            "拖拽互动": ("interaction.drag", "互动"),
            "游戏防误触锁定": ("interaction.game_lock", "互动"),
            "主动互动": ("interaction.proactive", "互动"),
            "点击反馈": ("interaction.click", "互动"),
            "动画过渡": ("interaction.transition", "互动"),
            "动作库": ("actions.library", "动作"),
            "白板播报": ("actions.whiteboard", "动作"),
            "事件触发": ("actions.event_trigger", "动作"),
        }
        title = str(title or "").strip()
        known = mapping.get(title)
        if known:
            return known
        page = str(getattr(self, "_v0883_current_page", "") or "设置").strip()
        return (f"card:{page}:{title}", page)

'''
    s = replace_method(s, "_v0882_feature_meta", "_v0882_favorites", feature_meta, "favorite metadata")

    register_card = r'''    def _v0882_register_card(self, card, title, description, button_slot=None):
        feature_id, page_name = self._v0882_feature_meta(title)
        action = button_slot if callable(button_slot) else None
        self._v0882_register_feature(feature_id, title, description, page_name, action)

        active = feature_id in self._v0882_favorites()
        btn = FavoriteStarButton(active, card)
        btn.setToolTip("从常用移除" if active else "添加到常用")
        btn.setAccessibleName(("取消收藏：" if active else "收藏：") + str(title))
        btn.clicked.connect(lambda checked=False, fid=feature_id: self._v0882_toggle_favorite(fid))
        try:
            card.layout().addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        except Exception:
            return
        if not hasattr(self, "v0882_favorite_buttons"):
            self.v0882_favorite_buttons = {}
        self.v0882_favorite_buttons.setdefault(feature_id, []).append(btn)

'''
    s = replace_method(s, "_v0882_register_card", "_v0882_toggle_favorite", register_card, "favorite card registration")

    refresh_buttons = r'''    def _v0882_refresh_favorite_buttons(self):
        selected = set(self._v0882_favorites())
        for feature_id, buttons in getattr(self, "v0882_favorite_buttons", {}).items():
            for btn in list(buttons):
                try:
                    active = feature_id in selected
                    btn.setChecked(active)
                    btn.setToolTip("从常用移除" if active else "添加到常用")
                    btn.setAccessibleName(("取消收藏：" if active else "收藏：") + str(feature_id))
                    btn.update()
                except Exception:
                    pass

'''
    s = replace_method(s, "_v0882_refresh_favorite_buttons", "_v0882_open_feature", refresh_buttons, "favorite refresh")

    favorite_card = r'''    def _v0882_make_favorite_card(self, item):
        card = QFrame()
        card.setObjectName("settingCard")
        card.setMinimumHeight(112)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 12, 14)
        lay.setSpacing(12)

        text_box = QWidget()
        tv = QVBoxLayout(text_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        title = QLabel(str(item.get("title") or "快捷功能"))
        title.setObjectName("cardTitle")
        value = QLabel(str(item.get("description") or ""))
        value.setObjectName("cardValue")
        value.setWordWrap(True)
        source = QLabel(f"来自：{item.get('page') or '设置'}")
        source.setObjectName("cardDesc")
        tv.addWidget(title)
        tv.addWidget(value)
        tv.addWidget(source)
        lay.addWidget(text_box, 1)

        action_box = QWidget()
        av = QVBoxLayout(action_box)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(6)
        star = FavoriteStarButton(True, action_box)
        star.setToolTip("从常用移除")
        star.setAccessibleName("取消收藏：" + str(item.get("title") or ""))
        star.clicked.connect(lambda checked=False, fid=item.get("id"): self._v0882_toggle_favorite(fid))
        av.addWidget(star, 0, Qt.AlignmentFlag.AlignRight)
        av.addStretch(1)

        open_btn = QPushButton("打开" if callable(item.get("action")) else "定位")
        open_btn.setObjectName("cardButton")
        open_btn.clicked.connect(lambda checked=False, fid=item.get("id"): self._v0882_open_feature(fid))
        av.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignRight)
        av.addStretch(1)
        lay.addWidget(action_box, 0)
        return card

'''
    s = replace_method(s, "_v0882_make_favorite_card", "_v0882_refresh_favorites", favorite_card, "favorite shortcut card")

    # ------------------------------------------------------------------
    # 2) One rule editor for both correction and Learning Library editing.
    # This eliminates the V0.8.8.2 split where chat correction used the new
    # editor but double-clicking a library rule still opened V0.7.7.6 dialogs.
    # ------------------------------------------------------------------
    unified_editor = r'''    def _v0883_open_rule_editor(self, existing=None, user_text="", assistant_text="", from_chat=False):
        existing = dict(existing or {})
        rid = str(existing.get("id") or "").strip()
        original_user = str(existing.get("user_text") or user_text or "").strip()
        assistant_text = str(assistant_text or "").strip()
        original_reference = str(existing.get("reference_answer") or assistant_text).strip()
        original_intent = str(existing.get("intent") or original_reference or assistant_text).strip()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑养成规则 · {rid}" if rid else "纠正 / 养成")
        try: dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        except Exception: pass
        dlg.resize(720, 720)
        root = QVBoxLayout(dlg); root.setContentsMargins(18,16,18,16); root.setSpacing(9)

        title = QLabel("修改同类问题命中时，小美丽应该怎么想、怎么说")
        title.setObjectName("pageTitle"); root.addWidget(title)
        sub = QLabel("“核心立场”决定她要表达什么；“参考说法”只是一个例句，不会再当成必须复读的台词。")
        sub.setWordWrap(True); sub.setObjectName("pageSubtitle"); root.addWidget(sub)

        root.addWidget(QLabel("触发问题 / 示例"))
        question = QLineEdit(original_user); root.addWidget(question)

        root.addWidget(QLabel("核心立场"))
        intent_edit = QTextEdit()
        intent_edit.setMinimumHeight(92)
        intent_edit.setPlaceholderText("例如：不建议主人无脑前压，用损友式吐槽劝他别白给。")
        intent_edit.setPlainText(original_intent)
        root.addWidget(intent_edit)

        root.addWidget(QLabel("参考说法（只学风格，不要求复读）"))
        reference_edit = QLineEdit(original_reference)
        reference_edit.setPlaceholderText("例如：能啊，嫌分多就去送！")
        root.addWidget(reference_edit)

        box = QGroupBox("语义规则｜选择「学这个意思」时生效")
        form = QFormLayout(box)
        scene = QLineEdit(str(existing.get("scene") or original_user))
        scene.setPlaceholderText("什么场景 / 哪类问法应触发")
        must = QLineEdit(str(existing.get("must") or ""))
        must.setPlaceholderText("必须体现的条件或立场")
        forbid = QLineEdit(str(existing.get("forbid") or "不要反转核心立场；不要机械复读参考说法"))
        tone = QLineEdit(str(existing.get("tone") or "自然、傲娇、损友式、短促；允许每次换说法"))
        form.addRow("场景", scene)
        form.addRow("必须体现", must)
        form.addRow("禁止偏离", forbid)
        form.addRow("语气", tone)
        root.addWidget(box)

        if rid:
            current_mode = "固定台词" if str(existing.get("mode") or "") == "fixed" else "语义规则"
            status = QLabel(f"当前：#{rid} · {current_mode}。保存会直接覆盖这一条，并保留分组、命中次数和规则编号。")
        else:
            status = QLabel("当前：新规则。")
        status.setWordWrap(True); root.addWidget(status)

        buttons = QHBoxLayout(); buttons.addStretch(1)
        semantic_btn = QPushButton("🧠 学这个意思（推荐）")
        fixed_btn = QPushButton("📌 固定这句话")
        cancel_btn = QPushButton("取消")
        buttons.addWidget(semantic_btn); buttons.addWidget(fixed_btn); buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        cancel_btn.clicked.connect(dlg.reject)

        def commit(mode):
            q = question.text().strip()
            intent = intent_edit.toPlainText().strip()
            reference = reference_edit.text().strip()
            if not q or not intent:
                QMessageBox.warning(dlg, "无法保存", "触发问题和核心立场不能为空。")
                return

            scene_text = scene.text().strip() or q
            must_text = must.text().strip() or intent
            forbid_text = forbid.text().strip() or "不要反转核心立场；不要机械复读参考说法"
            tone_text = tone.text().strip() or "自然、符合小美丽人格；允许每次换说法"
            reference = reference or intent

            if mode == "semantic":
                changes = {
                    "mode": "semantic",
                    "user_text": q,
                    "scene": scene_text,
                    "intent": intent,
                    "must": must_text,
                    "forbid": forbid_text,
                    "tone": tone_text,
                    "reference_answer": reference,
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
                label = "学这个意思"
                self.brain_status.setText("语义规则已保存：记住核心立场，参考说法只作为风格例句。")
            else:
                changes = {
                    "mode": "fixed",
                    "user_text": q,
                    "scene": scene_text,
                    "intent": intent,
                    "must": must_text,
                    "forbid": forbid_text,
                    "tone": tone_text,
                    "reference_answer": reference,
                }
                if rid:
                    saved = self.brain_service.update_rule(rid, changes)
                    if not saved:
                        QMessageBox.warning(dlg, "保存失败", "没有找到原规则，已取消本次修改。")
                        return
                else:
                    self.brain_service.save_feedback(
                        "down", q, assistant_text, reference, "fixed"
                    )
                label = "固定这句话"
                self.brain_status.setText("固定台词已保存。同样问题会直接回答指定原句。")

            if from_chat:
                try:
                    self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
                    self.brain_chat.addItem(f"你教她（{label}）：{reference}")
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

        semantic_btn.clicked.connect(lambda: commit("semantic"))
        fixed_btn.clicked.connect(lambda: commit("fixed"))
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _brain_dislike(self):
        ex = self._v088_selected_exchange()
        if not ex:
            return
        user_text = str(ex.get("user_text") or "").strip()
        assistant_text = str(ex.get("assistant_text") or "").strip()
        if not user_text:
            return
        try:
            existing = dict(self.brain_service.find_rule_for_question(user_text) or {})
        except Exception:
            existing = {}
        self._v0883_open_rule_editor(existing, user_text, assistant_text, True)

'''
    s = replace_method(s, "_brain_dislike", "_brain_rule_proposed", unified_editor, "unified correction editor")

    library_edit = r'''    def _brain_edit_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return
        self._v0883_open_rule_editor(
            rule,
            str(rule.get("user_text") or ""),
            str(rule.get("reference_answer") or rule.get("intent") or ""),
            False,
        )

'''
    s = replace_method(s, "_brain_edit_rule", "_brain_toggle_rule", library_edit, "learning library editor")

    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_brain(path: Path):
    b = path.read_text(encoding="utf-8")

    # If the user edits a rule's trigger question, remember the old normalized
    # key as an alias. Otherwise append-only feedback.jsonl could later recreate
    # the old question as a duplicate rule during sync.
    old_known = '''        known_keys = {
            self._feedback_key(r.get("user_text"))
            for r in rules
            if self._feedback_key(r.get("user_text"))
        }
'''
    new_known = '''        known_keys = set()
        for r in rules:
            key = self._feedback_key(r.get("user_text"))
            if key:
                known_keys.add(key)
            aliases = r.get("feedback_aliases") or []
            if isinstance(aliases, list):
                for alias in aliases:
                    alias = str(alias or "").strip()
                    if alias:
                        known_keys.add(alias)
'''
    if old_known not in b:
        raise RuntimeError("V0.8.8.3 feedback known_keys anchor missing")
    b = b.replace(old_known, new_known, 1)

    update_anchor = '''        for rule in rules:
            if str(rule.get("id")) != str(rule_id) or bool(rule.get("deleted", False)):
                continue
            for key in (
                "mode", "user_text", "scene", "intent", "must", "forbid",
                "tone", "reference_answer", "enabled", "group_id",
            ):
'''
    update_new = '''        for rule in rules:
            if str(rule.get("id")) != str(rule_id) or bool(rule.get("deleted", False)):
                continue

            if "user_text" in changes:
                old_key = self._feedback_key(rule.get("user_text"))
                new_key = self._feedback_key(changes.get("user_text"))
                if old_key and old_key != new_key:
                    aliases = rule.get("feedback_aliases") or []
                    if not isinstance(aliases, list):
                        aliases = []
                    aliases = [str(x or "").strip() for x in aliases if str(x or "").strip()]
                    if old_key not in aliases:
                        aliases.append(old_key)
                    rule["feedback_aliases"] = aliases[-30:]

            for key in (
                "mode", "user_text", "scene", "intent", "must", "forbid",
                "tone", "reference_answer", "enabled", "group_id",
            ):
'''
    if update_anchor not in b:
        raise RuntimeError("V0.8.8.3 update_rule anchor missing")
    b = b.replace(update_anchor, update_new, 1)

    path.write_text(b, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    if "小美丽 V0.8.8.2 语音诊断日志" in s:
        s = s.replace("小美丽 V0.8.8.2 语音诊断日志", "小美丽 V0.8.8.3 语音诊断日志")
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    brain = root / "app" / "src" / "brain_qwen.py"
    speech = root / "app" / "src" / "speech_input.py"
    for path in (main, brain, speech):
        if not path.exists():
            raise FileNotFoundError(path)

    patch_main(main)
    patch_brain(brain)
    patch_speech(speech)

    m = main.read_text(encoding="utf-8")
    b = brain.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")

    main_checks = [
        'APP_VERSION = "0.8.8.3"',
        'class FavoriteStarButton(QPushButton):',
        'painter.drawPath(star)',
        '"语音对话": ("voice.dialogue", "声音")',
        '"唤醒回应": ("voice.wake_replies", "声音")',
        '"单句语气微调": ("voice.phrase_style", "声音")',
        '"游戏防误触锁定": ("interaction.game_lock", "互动")',
        'return (f"card:{page}:{title}", page)',
        'def _v0883_open_rule_editor(self, existing=None, user_text="", assistant_text="", from_chat=False):',
        'self._v0883_open_rule_editor(',
        '保存会直接覆盖这一条，并保留分组、命中次数和规则编号',
    ]
    for token in main_checks:
        if token not in m:
            raise RuntimeError("V0.8.8.3 main verification failed: " + token)

    edit_block = m[m.find("    def _brain_edit_rule("):m.find("    def _brain_toggle_rule(", m.find("    def _brain_edit_rule("))]
    if "QInputDialog.getMultiLineText" in edit_block:
        raise RuntimeError("V0.8.8.3 old Learning Library editor still active")
    if "_v0883_open_rule_editor" not in edit_block:
        raise RuntimeError("V0.8.8.3 Learning Library is not using unified editor")

    if 'feedback_aliases' not in b:
        raise RuntimeError("V0.8.8.3 feedback alias protection missing")
    if "小美丽 V0.8.8.3 语音诊断日志" not in sp:
        raise RuntimeError("V0.8.8.3 speech diagnostic version label missing")

    print("Patched XiaoMeili source to V0.8.8.3 vector favorites + complete card coverage + unified rule editor")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0883.py <source_root>")
    patch(Path(sys.argv[1]))
