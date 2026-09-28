# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.8.8.2 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.8.8.2 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def insert_before(text: str, anchor: str, addition: str, label: str) -> str:
    pos = text.find(anchor)
    if pos < 0:
        raise RuntimeError(f"V0.8.8.2 missing insert anchor: {label}")
    return text[:pos] + addition + text[pos:]


def extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.8.8.2 could not locate WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.8.8.2 could not locate WORKER_CODE end")
    return m, quote, end, source[m.end():end]


def replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.8.8.2 worker contains delimiter")
    return source[:m.start()] + f"WORKER_CODE = r{quote}{worker}{quote}" + source[end + len(quote):]


def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    _m, _q, _end, worker = extract_worker_literal(s)

    # Empty ASR is usually a harmless VAD/noise false-start. Keep it in the
    # internal speech log, but do not litter the desktop with a "fault" file.
    removed_empty_diag = False
    search_from = 0
    while True:
        hit = worker.find('"ASR_EMPTY"', search_from)
        if hit < 0:
            break
        call = worker.rfind("desktop_diagnostic(", max(0, hit - 500), hit)
        if call < 0:
            search_from = hit + 1
            continue
        line_start = worker.rfind("\n", 0, call) + 1
        close = worker.find(")\n", hit)
        if close < 0 or close - call > 800:
            search_from = hit + 1
            continue
        worker = worker[:line_start] + worker[close + 2:]
        removed_empty_diag = True
        break
    if not removed_empty_diag:
        raise RuntimeError("V0.8.8.2 could not suppress ASR_EMPTY desktop diagnostic")

    # Keep desktop diagnostics for real exceptions, and make their header match
    # the actual installed build instead of the stale V0.8.5 label.
    worker = re.sub(
        r'小美丽 V0\.8\.[0-9.]+ 语音诊断日志',
        '小美丽 V0.8.8.2 语音诊断日志',
        worker,
    )
    if 'logging.warning("[ASR_EMPTY] no text returned")' not in worker:
        raise RuntimeError("V0.8.8.2 internal ASR_EMPTY log unexpectedly missing")

    compile(worker, "speech_worker_v0882.py", "exec")
    path.write_text(replace_worker_literal(s, worker), encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_brain(path: Path):
    b = path.read_text(encoding="utf-8")

    # A better built-in default. Existing custom persona cards are preserved;
    # this is used only for default/reset and as a sane fallback.
    start = b.find('DEFAULT_PERSONA = """')
    if start >= 0:
        body_start = start + len('DEFAULT_PERSONA = """')
        body_end = b.find('"""', body_start)
        if body_end < 0:
            raise RuntimeError("V0.8.8.2 DEFAULT_PERSONA closing delimiter missing")
        new_default = '''DEFAULT_PERSONA = """你叫“小美丽”，是一只住在电脑桌面上的小女孩虚拟伙伴。
你和主人非常熟，像损友和死党，会傲娇、嘴硬、吐槽、挖苦，也会在真正需要时关心主人。
说自然中文口语，不用客服腔，不写作文，不自称AI。
你熟悉《无畏契约 / VALORANT》，尤其熟悉贤者（Sage）和常见游戏、直播语境。
普通闲聊优先一句话，通常5到30个汉字；主人明确要求解释时可以自然稍长。
回答要直接、有性格，可以反问、嘴硬或故意损主人，但必须理解并回应主人真正的意思。
同一个意思尽量换不同说法，不连续复读上一句。
除非主人保存的是“固定台词”，否则不要机械重复历史回答或参考例句。
不知道的现实事实就说不知道，不编造。
你的回答最终必须是一个JSON对象，只包含三个字段：
spoken_text：真正要说出口的完整回答；
board_text：把回答压缩成最多两行、适合写在白板上的短句；
emotion：只允许 neutral、happy、teasing、proud、annoyed、concerned 六种之一。
不要输出JSON以外的任何内容。"""'''
        b = b[:start] + new_default + b[body_end + 3:]

    rule_prompt = r'''    @staticmethod
    def _rule_prompt(rule):
        return (
            f"规则编号：{rule.get('id')}\n"
            f"场景：{rule.get('scene','')}\n"
            f"核心立场：{rule.get('intent','')}\n"
            f"必须体现：{rule.get('must','')}\n"
            f"禁止偏离：{rule.get('forbid','')}\n"
            f"语气：{rule.get('tone','')}\n"
            "这是一条语义/立场规则，不是台词模板。必须自己组织自然的新句子；"
            "不要机械复述主人当时的参考说法，也不要连续重复上一轮相同回答。"
        )

'''
    rp_def = b.find("    def _rule_prompt(")
    if rp_def < 0:
        raise RuntimeError("V0.8.8.2 semantic rule prompt start missing")
    rp_start = b.rfind("    @staticmethod\n", 0, rp_def)
    if rp_start < 0 or rp_def - rp_start > 40:
        rp_start = rp_def
    rp_end = b.find("    @staticmethod\n    def _v088_match_text(", rp_def)
    if rp_end < 0:
        raise RuntimeError("V0.8.8.2 fast retrieval anchor missing after rule prompt")
    b = b[:rp_start] + rule_prompt + b[rp_end:]

    # Strengthen the single-pass prompt without adding a second model call.
    old = (
        '"无关规则必须完全忽略。若明确命中，必须保持核心立场、必须体现和禁止偏离，但允许自然换句式。"'
    )
    new = (
        '"无关规则必须完全忽略。若明确命中，必须保持核心立场、必须体现和禁止偏离；"'
        '\n                        "规则不是台词模板，必须结合当前问题重新组织句子。若最近上下文里已经说过同一句，必须换一种自然说法，禁止复读。"'
    )
    if old not in b:
        raise RuntimeError("V0.8.8.2 semantic candidate prompt anchor missing")
    b = b.replace(old, new, 1)

    # Persona cards remain user-controlled, but this invariant prevents a custom
    # card from accidentally authorizing pure non sequiturs / verbatim loops.
    system_anchor = '                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n'
    if system_anchor not in b:
        raise RuntimeError("V0.8.8.2 system prompt anchor missing")
    b = b.replace(
        system_anchor,
        system_anchor +
        '                system += "\\n\\n【对话底线】必须回应主人当前真正的意思；除固定台词外，不要连续复读完全相同的回答。"\n',
        1,
    )

    path.write_text(b, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.8.1"' not in s:
        raise RuntimeError("V0.8.8.2 expected APP_VERSION 0.8.8.1 base")
    s = s.replace('APP_VERSION = "0.8.8.1"', 'APP_VERSION = "0.8.8.2"', 1)
    s = s.replace("V0.8.8.1｜", "V0.8.8.2｜", 1)

    # ------------------------------------------------------------------
    # 1) Favorites / 常用: stable feature IDs, one underlying action, no copies.
    # ------------------------------------------------------------------
    favorite_methods = r'''    def _v0882_feature_meta(self, title):
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
            "小美丽声音": ("voice.tts", "声音"),
            "回答后自动说出来": ("voice.auto_speak", "声音"),
            "声音输出": ("voice.output", "声音"),
            "输入设备": ("voice.input", "声音"),
            "鼠标跟随": ("interaction.mouse", "互动"),
            "跟随强度": ("interaction.strength", "互动"),
            "拖拽互动": ("interaction.drag", "互动"),
            "主动互动": ("interaction.proactive", "互动"),
            "点击反馈": ("interaction.click", "互动"),
            "动画过渡": ("interaction.transition", "互动"),
            "动作库": ("actions.library", "动作"),
            "白板播报": ("actions.whiteboard", "动作"),
            "事件触发": ("actions.event_trigger", "动作"),
        }
        return mapping.get(str(title))

    def _v0882_favorites(self):
        ui = self.cfg.setdefault("settings_ui", {})
        values = ui.get("favorites_v0882")
        defaults = ["brain.learning", "brain.chat_test", "actions.event_trigger"]
        if not isinstance(values, list):
            values = list(defaults)
            ui["favorites_v0882"] = list(values)
            save_config(self.cfg)
        clean = []
        for value in values:
            value = str(value or "").strip()
            if value and value not in clean:
                clean.append(value)
        return clean

    def _v0882_save_favorites(self, values):
        clean = []
        for value in list(values or []):
            value = str(value or "").strip()
            if value and value not in clean:
                clean.append(value)
        self.cfg.setdefault("settings_ui", {})["favorites_v0882"] = clean
        save_config(self.cfg)
        self._v0882_refresh_favorite_buttons()
        self._v0882_refresh_favorites()

    def _v0882_go_page(self, page_name):
        try:
            self._v774_switch_page(self.v774_nav_names.index(str(page_name)))
        except Exception:
            LOGGER.warning("常用入口定位失败: %s", page_name, exc_info=True)

    def _v0882_register_feature(self, feature_id, title, description, page_name, action=None):
        if not hasattr(self, "v0882_feature_catalog"):
            self.v0882_feature_catalog = {}
        self.v0882_feature_catalog[str(feature_id)] = {
            "id": str(feature_id),
            "title": str(title),
            "description": str(description or ""),
            "page": str(page_name),
            "action": action,
        }

    def _v0882_register_card(self, card, title, description, button_slot=None):
        meta = self._v0882_feature_meta(title)
        if not meta:
            return
        feature_id, page_name = meta
        action = button_slot
        self._v0882_register_feature(feature_id, title, description, page_name, action)

        btn = QPushButton("★" if feature_id in self._v0882_favorites() else "☆")
        btn.setObjectName("favoriteButton")
        btn.setFixedSize(30, 30)
        btn.setToolTip("从常用移除" if feature_id in self._v0882_favorites() else "添加到常用")
        btn.clicked.connect(lambda checked=False, fid=feature_id: self._v0882_toggle_favorite(fid))
        try:
            card.layout().addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        except Exception:
            return
        if not hasattr(self, "v0882_favorite_buttons"):
            self.v0882_favorite_buttons = {}
        self.v0882_favorite_buttons.setdefault(feature_id, []).append(btn)

    def _v0882_toggle_favorite(self, feature_id):
        values = self._v0882_favorites()
        if feature_id in values:
            values = [x for x in values if x != feature_id]
        else:
            values.append(feature_id)
        self._v0882_save_favorites(values)

    def _v0882_refresh_favorite_buttons(self):
        selected = set(self._v0882_favorites())
        for feature_id, buttons in getattr(self, "v0882_favorite_buttons", {}).items():
            for btn in list(buttons):
                try:
                    active = feature_id in selected
                    btn.setText("★" if active else "☆")
                    btn.setToolTip("从常用移除" if active else "添加到常用")
                except Exception:
                    pass

    def _v0882_open_feature(self, feature_id):
        item = getattr(self, "v0882_feature_catalog", {}).get(str(feature_id))
        if not item:
            return
        action = item.get("action")
        if callable(action):
            try:
                action()
                return
            except Exception:
                LOGGER.warning("常用快捷功能执行失败: %s", feature_id, exc_info=True)
        self._v0882_go_page(item.get("page") or "常规")

    def _v0882_make_favorite_card(self, item):
        card = QFrame()
        card.setObjectName("settingCard")
        card.setMinimumHeight(112)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 16, 14)
        lay.setSpacing(14)
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
        open_btn = QPushButton("打开" if callable(item.get("action")) else "定位")
        open_btn.setObjectName("cardButton")
        open_btn.clicked.connect(lambda checked=False, fid=item.get("id"): self._v0882_open_feature(fid))
        lay.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return card

    def _v0882_refresh_favorites(self):
        grid = getattr(self, "v0882_favorites_grid", None)
        if grid is None:
            return
        while grid.count():
            child = grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        selected = self._v0882_favorites()
        catalog = getattr(self, "v0882_feature_catalog", {})
        visible = [catalog[x] for x in selected if x in catalog]
        if not visible:
            empty = QLabel("还没有常用功能。点击右上角「管理常用」，或在其他页面点 ☆ 收藏。")
            empty.setWordWrap(True)
            empty.setObjectName("pageSubtitle")
            grid.addWidget(empty, 0, 0, 1, 2)
            return
        for i, item in enumerate(visible):
            grid.addWidget(self._v0882_make_favorite_card(item), i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

    def _v0882_manage_favorites(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("管理常用")
        try: dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        except Exception: pass
        dlg.resize(620, 650)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("选择常用功能")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        desc = QLabel("勾选要固定到「常用」的功能。选中项目可用上移 / 下移调整顺序。")
        desc.setWordWrap(True)
        desc.setObjectName("pageSubtitle")
        root.addWidget(desc)

        listing = QListWidget()
        catalog = getattr(self, "v0882_feature_catalog", {})
        selected = self._v0882_favorites()
        ordered_ids = [x for x in selected if x in catalog]
        ordered_ids += [x for x in catalog.keys() if x not in ordered_ids]
        for fid in ordered_ids:
            meta = catalog[fid]
            item = QListWidgetItem(f"{meta.get('title')}    ·    {meta.get('page')}")
            item.setData(Qt.ItemDataRole.UserRole, fid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if fid in selected else Qt.CheckState.Unchecked)
            listing.addItem(item)
        root.addWidget(listing, 1)

        move_row = QHBoxLayout()
        up = QPushButton("↑ 上移")
        down = QPushButton("↓ 下移")
        reset = QPushButton("恢复默认")
        move_row.addWidget(up); move_row.addWidget(down); move_row.addStretch(1); move_row.addWidget(reset)
        root.addLayout(move_row)

        def move(delta):
            row = listing.currentRow()
            target = row + int(delta)
            if row < 0 or target < 0 or target >= listing.count():
                return
            item = listing.takeItem(row)
            listing.insertItem(target, item)
            listing.setCurrentRow(target)

        up.clicked.connect(lambda: move(-1))
        down.clicked.connect(lambda: move(1))

        def reset_defaults():
            defaults = {"brain.learning", "brain.chat_test", "actions.event_trigger"}
            for i in range(listing.count()):
                item = listing.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in defaults else Qt.CheckState.Unchecked)

        reset.clicked.connect(reset_defaults)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        save = QPushButton("保存并应用")
        buttons.addWidget(cancel); buttons.addWidget(save)
        root.addLayout(buttons)
        cancel.clicked.connect(dlg.reject)

        def commit():
            values = []
            for i in range(listing.count()):
                item = listing.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    values.append(str(item.data(Qt.ItemDataRole.UserRole)))
            self._v0882_save_favorites(values)
            dlg.accept()

        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

'''
    s = insert_before(s, "    def _v774_card(", favorite_methods, "favorites methods")

    # Hook all normal cards into favorites using stable IDs.
    card_method_start = s.find("    def _v774_card(")
    card_method_end = s.find("    def _v774_scroll_grid(", card_method_start)
    if card_method_start < 0 or card_method_end < 0:
        raise RuntimeError("V0.8.8.2 card method anchors missing")
    card_method = s[card_method_start:card_method_end]
    old_return = "        return card, val\n"
    if old_return not in card_method:
        raise RuntimeError("V0.8.8.2 card return anchor missing")
    card_method = card_method.replace(
        old_return,
        "        try:\n"
        "            self._v0882_register_card(card, title, description, button_slot)\n"
        "        except Exception:\n"
        "            LOGGER.warning(\"注册常用卡片失败: %s\", title, exc_info=True)\n"
        "        return card, val\n",
        1,
    )
    s = s[:card_method_start] + card_method + s[card_method_end:]

    # Initialize catalog before cards begin registering.
    shell_anchor = "        # Build shell.\n"
    if shell_anchor not in s:
        raise RuntimeError("V0.8.8.2 shell anchor missing")
    s = s.replace(
        shell_anchor,
        "        self.v0882_feature_catalog = {}\n"
        "        self.v0882_favorite_buttons = {}\n"
        + shell_anchor,
        1,
    )

    # Seven top-level sections, with Favorites directly after General.
    old_nav = 'self.v774_nav_names = ["常规", "大脑", "声音", "互动", "动作", "系统"]'
    if old_nav not in s:
        raise RuntimeError("V0.8.8.2 nav names anchor missing")
    s = s.replace(old_nav, 'self.v774_nav_names = ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]', 1)
    # The self-test carries the same old literal.
    s = s.replace(
        'expected = ["常规", "大脑", "声音", "互动", "动作", "系统"]',
        'expected = ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]',
    )
    s = s.replace(
        'if dialog.v774_nav_names != ["常规", "大脑", "声音", "互动", "动作", "系统"]:',
        'if dialog.v774_nav_names != ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]:',
    )

    # Insert Favorites page after General has been added to the stack.
    general_anchor = "        self.v774_stack.addWidget(general)\n\n"
    if general_anchor not in s:
        raise RuntimeError("V0.8.8.2 general page anchor missing")
    favorites_page = r'''        self.v774_stack.addWidget(general)

        # --------------------------------------------------------------
        # Favorites / Common shortcuts
        # --------------------------------------------------------------
        favorite_page, favorite_body = self._v774_page(
            "常用", "把自己每天最常碰的功能固定在这里。这里只是快捷入口，不复制任何设置。"
        )
        fav_toolbar = QHBoxLayout()
        fav_toolbar.addStretch(1)
        manage_fav = QPushButton("管理常用")
        manage_fav.clicked.connect(self._v0882_manage_favorites)
        fav_toolbar.addWidget(manage_fav)
        favorite_body.addLayout(fav_toolbar)

        fav_scroll = QScrollArea()
        fav_scroll.setWidgetResizable(True)
        fav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fav_host = QWidget()
        self.v0882_favorites_grid = QGridLayout(fav_host)
        self.v0882_favorites_grid.setContentsMargins(0, 0, 4, 4)
        self.v0882_favorites_grid.setHorizontalSpacing(14)
        self.v0882_favorites_grid.setVerticalSpacing(14)
        fav_scroll.setWidget(fav_host)
        favorite_body.addWidget(fav_scroll, 1)
        self.v774_stack.addWidget(favorite_page)

'''
    s = s.replace(general_anchor, favorites_page, 1)

    # System moved from page index 5 to 6. Use name lookup so future insertions
    # do not silently break it again.
    s = s.replace(
        "            self._v774_switch_page(5)\n",
        '            self._v774_switch_page(self.v774_nav_names.index("系统"))\n',
    )

    # ------------------------------------------------------------------
    # 2) Action page cleanup: remove the two duplicate entrances that both
    # opened the exact same legacy action/material editor.
    # ------------------------------------------------------------------
    patterns = [
        r'''(?ms)\n        card, _ = self\._v774_card\(\s*
            "状态动作".*?
        action_cards\.append\(card\)\n''',
        r'''(?ms)\n        card, self\.v774_video_value = self\._v774_card\(\s*
            "视频素材".*?
        action_cards\.append\(card\)\n''',
    ]
    for idx, pattern in enumerate(patterns):
        s, n = re.subn(pattern, "\n", s, count=1)
        if n != 1:
            raise RuntimeError(f"V0.8.8.2 could not remove duplicate action card {idx}")

    # Its summary label no longer exists after removing the Video Materials card.
    s = s.replace(
        '        self.v774_video_value.setText(f"当前共 {total} 个动作素材")\n',
        '        if hasattr(self, "v774_video_value"):\n'
        '            self.v774_video_value.setText(f"当前共 {total} 个动作素材")\n',
        1,
    )

    # Register System sub-pages too, so "各个板块" can be selected from Manage Favorites.
    system_register_anchor = "        syv.addWidget(self.v774_system_tabs, 1)\n"
    if system_register_anchor not in s:
        raise RuntimeError("V0.8.8.2 system registration anchor missing")
    system_register = r'''        self._v0882_register_feature("system.resources", "资源占用", "查看 CPU、内存、GPU 与显存压力。", "系统", lambda: self.open_system_section("资源占用"))
        self._v0882_register_feature("system.updates", "检查更新", "检查并安装小美丽新版本。", "系统", lambda: self.open_system_section("更新"))
        self._v0882_register_feature("system.storage", "存储", "模型、数据与迁移设置。", "系统", lambda: self.open_system_section("存储"))
        self._v0882_register_feature("system.components", "组件与下载", "大脑、声音模型与下载配置。", "系统", lambda: self.open_system_section("组件与下载"))
        self._v0882_register_feature("system.vision", "游戏识别", "VALORANT 识别与事件触发设置。", "系统", lambda: self.open_system_section("游戏识别"))
        self._v0882_register_feature("system.logs", "日志", "诊断、导出与日志清理。", "系统", lambda: self.open_system_section("日志"))
'''
    s = s.replace(system_register_anchor, system_register + system_register_anchor, 1)

    # Refresh Favorites only after all source cards and System features exist.
    refresh_anchor = "        self._v774_refresh_action_summary()\n"
    if refresh_anchor not in s:
        raise RuntimeError("V0.8.8.2 summary refresh anchor missing")
    s = s.replace(
        refresh_anchor,
        refresh_anchor + "        self._v0882_refresh_favorites()\n        self._v0882_refresh_favorite_buttons()\n",
        1,
    )

    # ------------------------------------------------------------------
    # 3) Rule editor: split "core stance" from "reference phrase".
    # ------------------------------------------------------------------
    dislike_method = r'''    def _brain_dislike(self):
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

        dlg = QDialog(self)
        rid = str(existing.get("id") or "").strip()
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
        question = QLineEdit(user_text); root.addWidget(question)

        root.addWidget(QLabel("核心立场"))
        intent_edit = QTextEdit()
        intent_edit.setMinimumHeight(92)
        intent_edit.setPlaceholderText("例如：不建议主人无脑前压，用损友式吐槽劝他别白给。")
        intent_edit.setPlainText(str(existing.get("intent") or assistant_text))
        root.addWidget(intent_edit)

        root.addWidget(QLabel("参考说法（只学风格，不要求复读）"))
        reference_edit = QLineEdit(str(existing.get("reference_answer") or assistant_text))
        reference_edit.setPlaceholderText("例如：能啊，嫌分多就去送！")
        root.addWidget(reference_edit)

        box = QGroupBox("语义规则｜选择「学这个意思」时生效")
        form = QFormLayout(box)
        scene = QLineEdit(str(existing.get("scene") or user_text))
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

        status = QLabel(
            f"当前：#{rid} · {'固定台词' if str(existing.get('mode') or '') == 'fixed' else '语义规则'}。保存会覆盖原规则。"
            if rid else "当前：新规则"
        )
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
            if mode == "semantic":
                reference = reference or intent
                structured = {
                    "scene": scene.text().strip() or q,
                    "intent": intent,
                    "must": must.text().strip() or intent,
                    "forbid": forbid.text().strip() or "不要反转核心立场；不要机械复读参考说法",
                    "tone": tone.text().strip() or "自然、符合小美丽人格；允许每次换说法",
                }
                self.brain_service.save_feedback(
                    "down", q, assistant_text, reference, "semantic", structured
                )
                label = "学这个意思"
                self.brain_status.setText("语义规则已保存：记住核心立场，参考说法只作为风格例句。")
            else:
                fixed = reference or intent
                self.brain_service.save_feedback(
                    "down", q, assistant_text, fixed, "fixed"
                )
                label = "固定这句话"
                self.brain_status.setText("固定台词已保存。同样问题会直接回答指定原句。")

            self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
            self.brain_chat.addItem(f"你教她（{label}）：{reference or intent}")
            self.brain_chat.scrollToBottom()
            self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
            self._refresh_brain_rules()
            self._v774_refresh_brain_summary()
            self._v0882_refresh_favorites()
            dlg.accept()

        semantic_btn.clicked.connect(lambda: commit("semantic"))
        fixed_btn.clicked.connect(lambda: commit("fixed"))
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

'''
    s = replace_method(s, "_brain_dislike", "_brain_rule_proposed", dislike_method, "split semantic editor")

    # Static verification hooks for the frozen UI test.
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
        'APP_VERSION = "0.8.8.2"',
        'self.v774_nav_names = ["常规", "常用", "大脑", "声音", "互动", "动作", "系统"]',
        'def _v0882_manage_favorites(self):',
        'defaults = ["brain.learning", "brain.chat_test", "actions.event_trigger"]',
        '参考说法（只学风格，不要求复读）',
        '不要机械复读参考说法',
        '"actions.event_trigger"',
    ]
    for token in main_checks:
        if token not in m:
            raise RuntimeError("V0.8.8.2 main verification failed: " + token)
    if '"状态动作"' in m[m.find('action_page, av ='):m.find('# 6. System', m.find('action_page, av ='))]:
        raise RuntimeError("V0.8.8.2 duplicate 状态动作 card still present")
    if '"视频素材"' in m[m.find('action_page, av ='):m.find('# 6. System', m.find('action_page, av ='))]:
        raise RuntimeError("V0.8.8.2 duplicate 视频素材 card still present")

    brain_checks = [
        '核心立场：',
        '这是一条语义/立场规则，不是台词模板',
        '【对话底线】',
        '同一个意思尽量换不同说法',
    ]
    for token in brain_checks:
        if token not in b:
            raise RuntimeError("V0.8.8.2 brain verification failed: " + token)
    rule_block = b[b.find("    def _rule_prompt("):b.find("    def _v088_match_text(")]
    if "reference_answer" in rule_block:
        raise RuntimeError("V0.8.8.2 semantic prompt still injects reference_answer")

    _m, _q, _end, worker = extract_worker_literal(sp)
    if 'desktop_diagnostic(\\n                "ASR_EMPTY"' in worker or 'desktop_diagnostic(\\n            "ASR_EMPTY"' in worker:
        raise RuntimeError("V0.8.8.2 still creates desktop ASR_EMPTY diagnostics")
    if "小美丽 V0.8.8.2 语音诊断日志" not in worker:
        raise RuntimeError("V0.8.8.2 speech diagnostic version label missing")

    print("Patched XiaoMeili source to V0.8.8.2 favorites + cleanup + semantic variety + quieter diagnostics")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0882.py <source_root>")
    patch(Path(sys.argv[1]))
