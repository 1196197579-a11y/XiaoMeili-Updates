# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.7 anchor: {label}")
    return text.replace(old, new, 1)


def replace_method(text: str, start_sig: str, next_sig: str, body: str, label: str) -> str:
    start = text.find(start_sig)
    if start < 0:
        raise RuntimeError(f"missing v0.7.7.7 method start: {label}")
    end = text.find(next_sig, start + len(start_sig))
    if end < 0:
        raise RuntimeError(f"missing v0.7.7.7 method end: {label}")
    return text[:start] + body + text[end:]


def patch_brain(brain_path: Path):
    b = brain_path.read_text(encoding="utf-8")

    b = must(
        b,
        'RULES_FILE = BRAIN_ROOT / "learning_rules.json"\n',
        'RULES_FILE = BRAIN_ROOT / "learning_rules.json"\n'
        'MEMORY_FILE = BRAIN_ROOT / "long_term_memory.json"\n'
        'MEMORY_MAX_ITEMS = 300\n',
        "memory constants",
    )

    insert_anchor = "    def _load_history(self):\n"
    if insert_anchor not in b:
        raise RuntimeError("brain history anchor missing")

    memory_methods = r'''    # ------------------------------------------------------------------
    # V0.7.7.7 lightweight local long-term memory.
    # Stores only concise user facts/preferences/plans, never model weights.
    # ------------------------------------------------------------------
    @staticmethod
    def _memory_key(text):
        text = str(text or "").strip().lower()
        return re.sub(r"[\s，。！？!?、；;：:,.…~～“”\"'（）()【】\[\]<>]+", "", text)

    @staticmethod
    def _memory_tokens(text):
        text = str(text or "").lower()
        tokens = set()
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_+\-]{2,}", text):
            if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                if len(chunk) <= 2:
                    tokens.add(chunk)
                else:
                    for i in range(len(chunk) - 1):
                        tokens.add(chunk[i:i + 2])
            else:
                tokens.add(chunk)
        return tokens

    def _load_memories(self):
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            out = []
            now = time.time()
            for row in data:
                if not isinstance(row, dict):
                    continue
                expires = float(row.get("expires_at") or 0)
                if expires > 0 and expires < now:
                    continue
                if str(row.get("text") or "").strip():
                    out.append(row)
            return out[-MEMORY_MAX_ITEMS:]
        except Exception:
            return []

    def _save_memories(self, memories):
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        rows = [x for x in list(memories) if isinstance(x, dict) and str(x.get("text") or "").strip()]
        rows = rows[-MEMORY_MAX_ITEMS:]
        temp = MEMORY_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(MEMORY_FILE)

    @staticmethod
    def _next_memory_id(memories):
        nums = []
        for row in memories:
            m = re.search(r"(\d+)$", str(row.get("id") or ""))
            if m:
                nums.append(int(m.group(1)))
        return f"M{(max(nums) + 1 if nums else 1):04d}"

    def list_memories(self):
        with self._lock:
            rows = self._load_memories()
        return sorted(
            [dict(x) for x in rows],
            key=lambda x: float(x.get("updated_at") or x.get("created_at") or 0),
            reverse=True,
        )

    def memory_count(self):
        return len(self.list_memories())

    def memory_storage_bytes(self):
        try:
            return int(MEMORY_FILE.stat().st_size) if MEMORY_FILE.exists() else 0
        except Exception:
            return 0

    def add_memory(self, text, category="manual", source="manual", expires_at=0):
        text = re.sub(r"\s+", " ", str(text or "").strip())
        if not text:
            return ""
        text = text[:180]
        key = self._memory_key(text)
        now = time.time()
        with self._lock:
            rows = self._load_memories()
            matched = None
            for row in rows:
                if self._memory_key(row.get("text")) == key:
                    matched = row
                    break
            if matched is not None:
                matched["text"] = text
                matched["category"] = str(category or matched.get("category") or "fact")
                matched["source"] = str(source or matched.get("source") or "auto")
                matched["updated_at"] = now
                if expires_at:
                    matched["expires_at"] = float(expires_at)
                rows.remove(matched)
                rows.append(matched)
                mid = str(matched.get("id") or "")
            else:
                mid = self._next_memory_id(rows)
                rows.append({
                    "id": mid,
                    "text": text,
                    "category": str(category or "fact"),
                    "source": str(source or "auto"),
                    "created_at": now,
                    "updated_at": now,
                    "expires_at": float(expires_at or 0),
                    "enabled": True,
                })
            self._save_memories(rows)
        return mid

    def update_memory(self, memory_id, text):
        memory_id = str(memory_id or "")
        text = re.sub(r"\s+", " ", str(text or "").strip())[:180]
        if not memory_id or not text:
            return False
        with self._lock:
            rows = self._load_memories()
            for row in rows:
                if str(row.get("id") or "") == memory_id:
                    row["text"] = text
                    row["updated_at"] = time.time()
                    self._save_memories(rows)
                    return True
        return False

    def delete_memory(self, memory_id):
        memory_id = str(memory_id or "")
        with self._lock:
            rows = self._load_memories()
            kept = [x for x in rows if str(x.get("id") or "") != memory_id]
            changed = len(kept) != len(rows)
            if changed:
                self._save_memories(kept)
            return changed

    def clear_memories(self):
        with self._lock:
            try:
                MEMORY_FILE.unlink(missing_ok=True)
            except Exception:
                self._save_memories([])

    def _memory_candidate(self, user_text):
        text = re.sub(r"\s+", " ", str(user_text or "").strip())
        if len(text) < 4 or len(text) > 180:
            return None
        explicit = bool(re.search(r"(记住|你要记得|别忘了|以后记得)", text))
        if ("?" in text or "？" in text) and not explicit:
            return None
        if any(x in text for x in ("刚才", "刚刚", "这局", "这一把", "今天这把")) and not explicit:
            return None

        category = ""
        expires_at = 0.0
        if explicit:
            category = "important"
        elif re.search(r"(我最喜欢|我喜欢|我偏好|我不喜欢|我讨厌|我爱用|我常用)", text):
            category = "preference"
        elif re.search(r"(我叫|我的名字|你可以叫我|我是.+(?:主播|创作者|玩家|学生|老师|工程师|设计师))", text):
            category = "identity"
        elif re.search(r"(我一般|我通常|我习惯|我经常|我每天|我每周|我主玩|我主要玩)", text):
            category = "habit"
        elif re.search(r"(我准备|我打算|我计划|我接下来|我最近在)", text):
            category = "plan"
            expires_at = time.time() + 60 * 24 * 3600
        elif re.search(r"(我的.+是|我有一|我有个|我有一个)", text):
            category = "fact"
        else:
            return None

        # Keep the original sentence because it preserves nuance better than an
        # aggressive hand-written summarizer; the prompt later tells the model
        # to use it only when relevant.
        return {
            "text": text,
            "category": category,
            "expires_at": expires_at,
        }

    def auto_remember(self, user_text):
        candidate = self._memory_candidate(user_text)
        if not candidate:
            return ""
        try:
            return self.add_memory(
                candidate["text"],
                candidate["category"],
                "auto",
                candidate.get("expires_at", 0),
            )
        except Exception:
            LOGGER.warning("自动长期记忆保存失败", exc_info=True)
            return ""

    def recall_memories(self, user_text, limit=8):
        limit = max(1, min(12, int(limit or 8)))
        query = str(user_text or "").strip()
        qtokens = self._memory_tokens(query)
        query_pref = bool(re.search(r"(喜欢|偏好|推荐|习惯|常用|想要|适合我)", query))
        query_identity = bool(re.search(r"(我是谁|我叫|名字|职业|做什么)", query))
        query_recall = bool(re.search(r"(记得|记不记得|之前|以前|曾经|我说过)", query))

        rows = self.list_memories()
        scored = []
        now = time.time()
        for index, row in enumerate(rows):
            if not bool(row.get("enabled", True)):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            mtokens = self._memory_tokens(text)
            overlap = len(qtokens & mtokens)
            score = float(overlap) * 2.2
            if query and (query in text or text in query):
                score += 5.0

            category = str(row.get("category") or "fact")
            if category == "preference":
                score += 1.3 + (2.5 if query_pref else 0.0)
            elif category == "identity":
                score += 1.1 + (2.5 if query_identity else 0.0)
            elif category == "important":
                score += 1.8
            elif category == "habit":
                score += 0.8 + (1.4 if query_pref else 0.0)
            elif category == "plan":
                score += 0.4

            if query_recall:
                score += 1.5
            updated = float(row.get("updated_at") or row.get("created_at") or now)
            age_days = max(0.0, (now - updated) / 86400.0)
            score += max(0.0, 0.8 - min(0.8, age_days / 180.0))
            # Small recency tie-breaker.
            score += max(0.0, 0.15 - index * 0.003)
            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = []
        for score, row in scored:
            if score < 0.9 and selected:
                continue
            selected.append(row)
            if len(selected) >= limit:
                break

        # A small stable-personality baseline helps generic questions such as
        # "推荐一把枪" recall a saved weapon preference even without shared words.
        if len(selected) < limit:
            have = {str(x.get("id") or "") for x in selected}
            for row in rows:
                if str(row.get("id") or "") in have:
                    continue
                if str(row.get("category") or "") not in {"preference", "identity", "important"}:
                    continue
                selected.append(row)
                have.add(str(row.get("id") or ""))
                if len(selected) >= min(limit, 5):
                    break

        return [str(x.get("text") or "").strip() for x in selected if str(x.get("text") or "").strip()]

'''
    b = b.replace(insert_anchor, memory_methods + insert_anchor, 1)

    old_sig = "    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6):\n"
    new_sig = "    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6, long_term_memory=True):\n"
    b = must(b, old_sig, new_sig, "ask memory signature")

    b = must(
        b,
        "        self._generate_busy = True\n        self.generation_started.emit()\n\n        exact_rule = self._exact_rule(user_text)\n",
        "        self._generate_busy = True\n        self.generation_started.emit()\n\n"
        "        if bool(long_term_memory):\n"
        "            self.auto_remember(user_text)\n\n"
        "        exact_rule = self._exact_rule(user_text)\n",
        "auto remember before rules",
    )

    b = must(
        b,
        '                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n'
        '                if matched_rule:\n',
        '                system = str(persona or DEFAULT_PERSONA).strip() + "\\n\\n" + OUTPUT_CONTRACT.strip()\n'
        '                if bool(long_term_memory):\n'
        '                    recalled = self.recall_memories(user_text, 8)\n'
        '                    if recalled:\n'
        '                        system += (\\n'
        '                            "\\n\\n【小美丽的长期记忆｜仅在相关时自然使用】\\n"\\n'
        '                            "这些是主人过去明确表达过、并保存在本机的长期信息。只在与当前话题有关时使用，"\\n'
        '                            "不要每次主动复述，也不要根据它们编造新的事实。\\n"\\n'
        '                            + "\\n".join(f"• {item}" for item in recalled)\\n'
        '                        )\n'
        '                if matched_rule:\n',
        "inject recalled memories",
    )

    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(brain_path), doraise=True)

    final = brain_path.read_text(encoding="utf-8")
    checks = [
        'MEMORY_FILE = BRAIN_ROOT / "long_term_memory.json"',
        "MEMORY_MAX_ITEMS = 300",
        "def auto_remember(self, user_text):",
        "def recall_memories(self, user_text, limit=8):",
        "def memory_storage_bytes(self):",
        "long_term_memory=True",
        "【小美丽的长期记忆｜仅在相关时自然使用】",
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.7 brain verification failed: {token}")


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.6"',
        'APP_NAME = "小美丽 V0.7.7.7｜Long Memory + Game-Safe Lock"\nAPP_VERSION = "0.7.7.7"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ------------------------------------------------------------------
    # A. Theme button: move it into every page header instead of floating over
    # the content stack. This guarantees normal hit-testing/click delivery.
    # ------------------------------------------------------------------
    page_start = s.find("    def _v774_page(self, title, subtitle):\n")
    page_end = s.find("    def _v774_card(", page_start)
    if page_start < 0 or page_end < 0:
        raise RuntimeError("page header method anchors missing")
    new_page = r'''    def _v774_page(self, title, subtitle):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)

        heading = QWidget()
        hv = QVBoxLayout(heading)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(5)
        title_label = QLabel(str(title))
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(str(subtitle))
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        hv.addWidget(title_label)
        hv.addWidget(subtitle_label)

        hl.addWidget(heading, 1)
        theme_btn = QPushButton("☾")
        theme_btn.setObjectName("themeButton")
        theme_btn.setFixedSize(34, 34)
        theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        theme_btn.setToolTip("切换到夜间模式")
        theme_btn.clicked.connect(self._v0775_toggle_theme)
        hl.addWidget(theme_btn, 0, Qt.AlignmentFlag.AlignTop)
        if not hasattr(self, "v0777_theme_buttons"):
            self.v0777_theme_buttons = []
        self.v0777_theme_buttons.append(theme_btn)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(12)
        outer.addWidget(body, 1)
        return page, body_layout

'''
    s = s[:page_start] + new_page + s[page_end:]

    theme_start = s.find("    def _v0775_apply_theme(self, mode, persist=True):\n")
    theme_end = s.find("    def _v0775_toggle_theme(self):\n", theme_start)
    if theme_start < 0 or theme_end < 0:
        raise RuntimeError("theme apply anchors missing")
    new_theme_apply = r'''    def _v0775_apply_theme(self, mode, persist=True):
        mode = "dark" if str(mode).lower() == "dark" else "light"
        self._v0775_theme_mode = mode
        dark = mode == "dark"
        self.setStyleSheet(self._v0775_stylesheet(dark))

        for btn in list(getattr(self, "v0777_theme_buttons", [])):
            try:
                btn.setText("☀" if dark else "☾")
                btn.setToolTip("切换到白天模式" if dark else "切换到夜间模式")
                btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                btn.setEnabled(True)
                btn.raise_()
            except Exception:
                pass

        self._v0775_mark_help_widgets()
        self._v0775_apply_native_titlebar(self, dark)
        for dlg_name in ("brain_persona_dialog", "brain_rules_dialog"):
            dlg = getattr(self, dlg_name, None)
            if dlg is not None:
                try:
                    self._v0775_apply_native_titlebar(dlg, dark)
                except Exception:
                    pass

        # Force immediate repaint so the mode switch is visually obvious.
        try:
            for widget in self.findChildren(QWidget):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
            self.update()
            QApplication.processEvents()
        except Exception:
            pass

        if persist:
            ui = self.cfg.setdefault("settings_ui", {})
            ui["theme"] = mode
            save_config(self.cfg)

'''
    s = s[:theme_start] + new_theme_apply + s[theme_end:]

    install_start = s.find("    def _install_v0775_theme_layer(self):\n")
    install_end = s.find("    def _toggle_brain_advanced(self, checked):\n", install_start)
    if install_start < 0 or install_end < 0:
        raise RuntimeError("theme install anchors missing")
    new_install = r'''    def _install_v0775_theme_layer(self):
        ui = self.cfg.setdefault("settings_ui", {})
        self._v0775_theme_mode = "dark" if str(ui.get("theme", "light")).lower() == "dark" else "light"
        # V0.7.7.7 uses real in-layout buttons created by _v774_page. The old
        # absolute-position overlay button is intentionally retired.
        self._v0775_apply_theme(self._v0775_theme_mode, False)

'''
    s = s[:install_start] + new_install + s[install_end:]

    # ------------------------------------------------------------------
    # B. Game-safe lock: locked means true native click-through + no activation.
    # A global right-button poll remains available for unlocking because a
    # truly transparent window cannot receive its own context-menu event.
    # ------------------------------------------------------------------
    old_init = '''        # V0.7.7.6 migration: retire click-through + hover lock bubble.
        # Keep a hidden LockBubble object only for old shutdown code compatibility.
        if bool(self.cfg.get("click_through", False)) or int(self.cfg.get("opacity", 100)) != 100:
            self.cfg["click_through"] = False
            self.cfg["opacity"] = 100
            save_config(self.cfg)
        else:
            self.cfg["click_through"] = False
            self.cfg["opacity"] = 100
        self.lock_bubble = LockBubble()
        self.lock_bubble.hide()
        self._hover_last_seen = 0.0
'''
    new_init = '''        # V0.7.7.7: lock is a real game-safe input passthrough state.
        # The old floating bubble remains hidden for shutdown compatibility.
        locked_boot = bool(self.cfg.get("lock_position", False))
        changed_boot = (
            bool(self.cfg.get("click_through", False)) != locked_boot
            or int(self.cfg.get("opacity", 100)) != 100
        )
        self.cfg["click_through"] = locked_boot
        self.cfg["opacity"] = 100
        if changed_boot:
            save_config(self.cfg)
        self.lock_bubble = LockBubble()
        self.lock_bubble.hide()
        self._hover_last_seen = 0.0
        self._v0777_right_was_down = False
'''
    s = must(s, old_init, new_init, "lock init migration")

    click_start = s.find("    def apply_clickthrough_native(self):\n", s.find("class PetWindow(QWidget):"))
    click_end = s.find("    def resize_pet(self):\n", click_start)
    if click_start < 0 or click_end < 0:
        raise RuntimeError("native clickthrough anchors missing")
    new_clickthrough = r'''    def apply_clickthrough_native(self):
        locked = bool(self.cfg.get("lock_position", False) or self.cfg.get("click_through", False))
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        except Exception:
            pass
        if sys.platform != "win32" or not self.winId():
            return
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if locked:
                style |= (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style &= ~WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            LOGGER.info("游戏防误触锁定=%s | 原生点击穿透=%s", locked, locked)
        except Exception:
            LOGGER.exception("切换游戏防误触锁定失败")

'''
    s = s[:click_start] + new_clickthrough + s[click_end:]

    lock_methods_start = s.find("    def _position_lock_bubble(self):\n", s.find("class PetWindow(QWidget):"))
    lock_methods_end = s.find("    def toggle_show_hide(self):\n", lock_methods_start)
    if lock_methods_start < 0 or lock_methods_end < 0:
        raise RuntimeError("lock method anchors missing")
    new_lock_methods = r'''    def _position_lock_bubble(self):
        try:
            self.lock_bubble.hide()
        except Exception:
            pass

    def poll_hover_lock_button(self):
        # While locked, the pet is a true WS_EX_TRANSPARENT + NOACTIVATE window,
        # so Qt cannot receive a right click. Poll the physical right button at
        # low frequency and unlock only when its DOWN edge happens over the
        # visible pet silhouette.
        try:
            if self.lock_bubble.isVisible():
                self.lock_bubble.hide()
        except Exception:
            pass

        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down
            if down and not was_down:
                pos = QCursor.pos()
                if self._cursor_hits_pet_shape(pos):
                    LOGGER.info("锁定状态检测到小美丽区域右键：解除游戏防误触锁定")
                    self.set_interaction_lock(False)
        except Exception:
            LOGGER.warning("锁定状态右键解锁检测失败", exc_info=True)

    def set_interaction_lock(self, locked):
        locked = bool(locked)
        self.cfg["lock_position"] = locked
        self.cfg["click_through"] = locked
        self.cfg["opacity"] = 100
        if locked:
            self.drag_offset = None
            self.drag_press_global = None
            self.drag_last_global = None
            try:
                self.releaseMouse()
            except Exception:
                pass
            try:
                if self.drag_visual_active:
                    self._cancel_drag_interaction()
            except Exception:
                pass
        save_config(self.cfg)
        self.apply_clickthrough_native()
        try:
            self.lock_bubble.hide()
        except Exception:
            pass
        self.config_changed.emit()

    def toggle_interaction_lock(self):
        self.set_interaction_lock(not bool(self.cfg.get("lock_position", False)))

'''
    s = s[:lock_methods_start] + new_lock_methods + s[lock_methods_end:]

    menu_start = s.find("    def contextMenuEvent(self, event):\n", s.find("class PetWindow(QWidget):"))
    menu_end = s.find("    def mouseDoubleClickEvent(self, event):\n", menu_start)
    if menu_start < 0 or menu_end < 0:
        raise RuntimeError("context menu anchors missing")
    new_menu = r'''    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        if locked:
            # Normally unreachable because the native window is click-through.
            self.set_interaction_lock(False)
            event.accept()
            return
        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

'''
    s = s[:menu_start] + new_menu + s[menu_end:]

    dbl_start = s.find("    def mouseDoubleClickEvent(self, event):\n", s.find("class PetWindow(QWidget):"))
    dbl_end = s.find("\n\n# ------------------------------", dbl_start)
    if dbl_start < 0 or dbl_end < 0:
        raise RuntimeError("double click anchors missing")
    new_dbl = r'''    def mouseDoubleClickEvent(self, event):
        if bool(self.cfg.get("lock_position", False) or self.cfg.get("click_through", False)):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.request_settings.emit()

'''
    s = s[:dbl_start] + new_dbl + s[dbl_end:]

    # Persist click-through exactly with the lock card rather than forcing False.
    old_apply_lock = '''        # V0.7.7.6: click-through UI is retired. Keep the pet right-clickable.
        self.cfg["click_through"] = False
        self.cfg["opacity"] = 100
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
'''
    new_apply_lock = '''        # V0.7.7.7: one lock state controls position lock + real click-through.
        self.cfg["opacity"] = 100
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
        self.cfg["click_through"] = bool(self.cfg.get("lock_position", False))
'''
    s = must(s, old_apply_lock, new_apply_lock, "apply lock persistence")

    s = must(
        s,
        'card, _ = self._v774_card("锁定位置", "禁止拖动桌宠位置", control=self.v774_lockpos_cb)\n',
        'card, _ = self._v774_card("游戏防误触锁定", "锁定后左键、双击和拖拽完全穿透；右键小美丽可解除", control=self.v774_lockpos_cb)\n',
        "lock card wording",
    )

    # ------------------------------------------------------------------
    # C. One-window rule editor. No nested OK -> choose mode -> semantic
    # confirmation dialog chain, so typed text cannot be reset between steps.
    # ------------------------------------------------------------------
    edit_start = s.find("    def _brain_edit_rule(self):\n")
    edit_end = s.find("    def _brain_toggle_rule(self):\n", edit_start)
    if edit_start < 0 or edit_end < 0:
        raise RuntimeError("rule editor anchors missing")
    integrated_editor = r'''    def _brain_edit_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return

        current_mode = str(rule.get("mode") or "fixed")
        user_text = str(rule.get("user_text") or "").strip()
        answer = str(rule.get("reference_answer") or rule.get("intent") or "").strip()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑养成规则 · {rule_id}")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(680, 620)
        dlg.setMinimumSize(620, 560)
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(18, 18, 18, 16)
        dv.setSpacing(12)

        title = QLabel("修改同类问题命中时，小美丽应该表达什么")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        dv.addWidget(title)

        trigger_label = QLabel("触发问题 / 原始场景")
        trigger_label.setObjectName("cardTitle")
        dv.addWidget(trigger_label)
        trigger = QLineEdit(user_text)
        trigger.setReadOnly(True)
        dv.addWidget(trigger)

        answer_label = QLabel("回答 / 核心意思")
        answer_label.setObjectName("cardTitle")
        dv.addWidget(answer_label)
        answer_edit = QTextEdit()
        answer_edit.setMinimumHeight(120)
        answer_edit.setPlainText(answer)
        answer_edit.setPlaceholderText("写下你希望小美丽以后表达的答案或核心意思。")
        dv.addWidget(answer_edit)

        semantic_box = QGroupBox("确定语义规则｜选择「学这个意思」时生效")
        sf = QFormLayout(semantic_box)
        sf.setContentsMargins(14, 16, 14, 14)
        sf.setSpacing(9)

        scene_edit = QLineEdit(str(rule.get("scene") or user_text))
        must_edit = QLineEdit(str(rule.get("must") or answer))
        forbid_edit = QLineEdit(str(rule.get("forbid") or ""))
        tone_edit = QLineEdit(str(rule.get("tone") or "保持主人纠正时的口吻"))
        scene_edit.setPlaceholderText("例如：被他人挑衅、主人询问游戏选择")
        must_edit.setPlaceholderText("回答必须体现的意思")
        forbid_edit.setPlaceholderText("不希望小美丽偏离到哪里，可留空")
        tone_edit.setPlaceholderText("例如：嘴硬、自然、简短")
        sf.addRow("场景", scene_edit)
        sf.addRow("必须体现", must_edit)
        sf.addRow("禁止偏离", forbid_edit)
        sf.addRow("语气", tone_edit)
        dv.addWidget(semantic_box)

        inline_status = QLabel(
            "当前：" + ("语义规则" if current_mode == "semantic" else "固定台词")
            + "。本窗口内修改不会因为选择养成方式而重置。"
        )
        inline_status.setWordWrap(True)
        inline_status.setObjectName("pageSubtitle")
        dv.addWidget(inline_status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        semantic_btn = QPushButton("学这个意思（推荐）")
        semantic_btn.setObjectName("cardButton")
        semantic_btn.setMinimumWidth(170)
        fixed_btn = QPushButton("固定这句话")
        fixed_btn.setMinimumWidth(130)
        actions.addWidget(semantic_btn)
        actions.addWidget(fixed_btn)
        dv.addLayout(actions)

        def save_as(mode):
            desired = str(answer_edit.toPlainText() or "").strip()
            if not desired:
                inline_status.setText("请先填写「回答 / 核心意思」，关闭窗口不会保存。")
                return
            if mode == "fixed":
                self.brain_service.update_rule(
                    rule_id,
                    {
                        "mode": "fixed",
                        "reference_answer": desired,
                        "intent": "",
                        "must": "",
                        "forbid": "",
                        "tone": "",
                    },
                )
                self.brain_status.setText(f"规则 #{rule_id} 已保存为固定台词")
            else:
                scene = str(scene_edit.text() or "").strip() or user_text
                must_text = str(must_edit.text() or "").strip() or desired
                self.brain_service.update_rule(
                    rule_id,
                    {
                        "mode": "semantic",
                        "reference_answer": desired,
                        "scene": scene,
                        "intent": desired,
                        "must": must_text,
                        "forbid": str(forbid_edit.text() or "").strip(),
                        "tone": str(tone_edit.text() or "").strip() or "保持主人纠正时的口吻",
                    },
                )
                self.brain_status.setText(f"规则 #{rule_id} 已保存为语义规则")
            self._refresh_brain_rules()
            dlg.accept()

        semantic_btn.clicked.connect(lambda: save_as("semantic"))
        fixed_btn.clicked.connect(lambda: save_as("fixed"))
        try:
            self._v0775_apply_native_titlebar(dlg, getattr(self, "_v0775_theme_mode", "light") == "dark")
        except Exception:
            pass
        dlg.exec()

'''
    s = s[:edit_start] + integrated_editor + s[edit_end:]

    # ------------------------------------------------------------------
    # D. Memory manager: recent context + persistent long-term memory.
    # ------------------------------------------------------------------
    mem_start = s.find("    def _v774_edit_memory(self):\n")
    mem_end = s.find("    def _v774_clear_context(self):\n", mem_start)
    if mem_start < 0 or mem_end < 0:
        raise RuntimeError("memory manager anchors missing")
    memory_ui = r'''    def _v0777_memory_category_label(self, category):
        return {
            "preference": "偏好",
            "identity": "身份",
            "habit": "习惯",
            "plan": "计划",
            "important": "重要",
            "manual": "手动",
            "fact": "信息",
        }.get(str(category or ""), "记忆")

    def _v774_edit_memory(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("小美丽记忆管理")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(780, 610)
        dlg.setMinimumSize(700, 540)
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(18, 18, 18, 16)
        dv.setSpacing(12)

        heading = QLabel("记忆")
        heading.setObjectName("pageTitle")
        heading.setStyleSheet("font-size:20px;font-weight:750;")
        dv.addWidget(heading)
        hint = QLabel(
            "最近对话负责“刚刚聊了什么”；长期记忆负责跨很多轮、跨重启保留稳定的偏好、身份、习惯和明确计划。"
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        dv.addWidget(hint)

        short_box = QGroupBox("最近对话")
        sh = QHBoxLayout(short_box)
        sh.setContentsMargins(14, 14, 14, 12)
        sh.addWidget(QLabel("每次回答带上最近"))
        short_spin = QSpinBox()
        short_spin.setRange(2, 12)
        short_spin.setValue(int(self.brain_context.value()))
        short_spin.setSuffix(" 轮")
        sh.addWidget(short_spin)
        sh.addStretch(1)
        clear_short = QPushButton("清空最近对话")
        sh.addWidget(clear_short)
        dv.addWidget(short_box)

        long_box = QGroupBox("长期记忆")
        lv = QVBoxLayout(long_box)
        lv.setContentsMargins(14, 14, 14, 12)
        lv.setSpacing(9)
        long_top = QHBoxLayout()
        long_enabled = QCheckBox("启用长期记忆")
        long_enabled.setChecked(bool(self.cfg.get("brain", {}).get("long_term_memory", True)))
        self.v0777_memory_stats = QLabel("")
        self.v0777_memory_stats.setObjectName("pageSubtitle")
        long_top.addWidget(long_enabled)
        long_top.addStretch(1)
        long_top.addWidget(self.v0777_memory_stats)
        lv.addLayout(long_top)

        explain = QLabel(
            "小美丽会自动保存像“我喜欢…… / 我主玩…… / 我叫…… / 我习惯……”这类稳定信息；"
            "普通闲聊不会整段保存。临时计划默认约 60 天后自动过期。所有记忆都只保存在本机。"
        )
        explain.setWordWrap(True)
        explain.setObjectName("cardDesc")
        lv.addWidget(explain)

        self.v0777_memory_list = QListWidget()
        self.v0777_memory_list.setMinimumHeight(245)
        lv.addWidget(self.v0777_memory_list, 1)

        add_row = QHBoxLayout()
        add_edit = QLineEdit()
        add_edit.setPlaceholderText("手动告诉小美丽一条长期记忆，例如：我最喜欢用大狙")
        add_btn = QPushButton("添加")
        add_btn.setObjectName("cardButton")
        add_row.addWidget(add_edit, 1)
        add_row.addWidget(add_btn)
        lv.addLayout(add_row)

        manage_row = QHBoxLayout()
        edit_btn = QPushButton("编辑选中")
        delete_btn = QPushButton("删除选中")
        clear_all_btn = QPushButton("清空长期记忆")
        manage_row.addWidget(edit_btn)
        manage_row.addWidget(delete_btn)
        manage_row.addWidget(clear_all_btn)
        manage_row.addStretch(1)
        lv.addLayout(manage_row)
        dv.addWidget(long_box, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryCloseButton")
        bottom.addWidget(close_btn)
        dv.addLayout(bottom)

        def refresh():
            self.v0777_memory_list.clear()
            rows = self.brain_service.list_memories()
            for row in rows:
                label = self._v0777_memory_category_label(row.get("category"))
                text = str(row.get("text") or "").strip()
                self.v0777_memory_list.addItem(f"[{label}]  {text}")
                item = self.v0777_memory_list.item(self.v0777_memory_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, str(row.get("id") or ""))
                item.setToolTip(text)
            size = int(self.brain_service.memory_storage_bytes())
            if size < 1024:
                size_text = f"{size} B"
            else:
                size_text = f"{size / 1024:.1f} KB"
            self.v0777_memory_stats.setText(f"{len(rows)} 条 · {size_text}")

        def selected_id():
            item = self.v0777_memory_list.currentItem()
            return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

        def save_short(value):
            self.brain_context.setValue(int(value))
            self._brain_save_settings()
            self._v774_refresh_brain_summary()

        def toggle_long(checked):
            self.cfg.setdefault("brain", {})["long_term_memory"] = bool(checked)
            save_config(self.cfg)
            self._v774_refresh_brain_summary()

        def add_manual():
            text = str(add_edit.text() or "").strip()
            if not text:
                return
            self.brain_service.add_memory(text, "manual", "manual")
            add_edit.clear()
            refresh()
            self._v774_refresh_brain_summary()

        def edit_selected():
            mid = selected_id()
            item = self.v0777_memory_list.currentItem()
            if not mid or item is None:
                return
            shown = str(item.text() or "")
            old = shown.split("]  ", 1)[-1] if "]  " in shown else shown
            value, ok = QInputDialog.getMultiLineText(dlg, "编辑长期记忆", "修改这条记忆：", old)
            if ok and str(value or "").strip():
                self.brain_service.update_memory(mid, str(value).strip())
                refresh()
                self._v774_refresh_brain_summary()

        def delete_selected():
            mid = selected_id()
            if not mid:
                return
            self.brain_service.delete_memory(mid)
            refresh()
            self._v774_refresh_brain_summary()

        def clear_all():
            answer = QMessageBox.question(
                dlg,
                "清空长期记忆",
                "确定删除所有长期记忆吗？\n养成库和性格卡不会受影响。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.brain_service.clear_memories()
                refresh()
                self._v774_refresh_brain_summary()

        short_spin.valueChanged.connect(save_short)
        clear_short.clicked.connect(self._v774_clear_context)
        long_enabled.toggled.connect(toggle_long)
        add_btn.clicked.connect(add_manual)
        add_edit.returnPressed.connect(add_manual)
        edit_btn.clicked.connect(edit_selected)
        delete_btn.clicked.connect(delete_selected)
        clear_all_btn.clicked.connect(clear_all)
        close_btn.clicked.connect(dlg.accept)
        refresh()

        try:
            self._v0775_apply_native_titlebar(dlg, getattr(self, "_v0775_theme_mode", "light") == "dark")
        except Exception:
            pass
        dlg.exec()

'''
    s = s[:mem_start] + memory_ui + s[mem_end:]

    s = must(
        s,
        '        self.v774_memory_value.setText(f"最近 {turns} 轮 · 长期记忆尚未启用")\n',
        '        memory_on = bool(self.cfg.get("brain", {}).get("long_term_memory", True))\n'
        '        memory_count = int(self.brain_service.memory_count())\n'
        '        self.v774_memory_value.setText(f"最近 {turns} 轮 · 长期记忆{\'已开启\' if memory_on else \'已关闭\'} · {memory_count} 条")\n',
        "memory card summary",
    )

    s = must(
        s,
        '            "记忆", "", "长期记忆尚未启用；当前先管理最近对话。", "管理", self._v774_edit_memory\n',
        '            "记忆", "", "最近对话 + 本地长期记忆。", "管理", self._v774_edit_memory\n',
        "memory card description",
    )

    s = must(
        s,
        '            self.cfg["brain"].get("context_turns",6),\n        )\n',
        '            self.cfg["brain"].get("context_turns",6),\n'
        '            self.cfg["brain"].get("long_term_memory", True),\n'
        '        )\n',
        "brain ask long memory flag",
    )

    # Theme button self-test + lock state contract + memory service availability.
    smoke_anchor = '''        if not isinstance(getattr(dialog, "v0776_avatar", None), EditableAvatar):
            raise RuntimeError("editable avatar widget missing")

        return True
'''
    smoke_new = '''        if not isinstance(getattr(dialog, "v0776_avatar", None), EditableAvatar):
            raise RuntimeError("editable avatar widget missing")

        theme_buttons = list(getattr(dialog, "v0777_theme_buttons", []))
        if len(theme_buttons) != 6:
            raise RuntimeError(f"expected 6 in-layout theme buttons, got {len(theme_buttons)}")
        before_mode = dialog._v0775_theme_mode
        theme_buttons[0].click()
        app.processEvents()
        if dialog._v0775_theme_mode == before_mode:
            raise RuntimeError("theme button click did not switch mode")
        theme_buttons[0].click()
        app.processEvents()

        pet.set_interaction_lock(True)
        app.processEvents()
        if not bool(cfg.get("lock_position", False)) or not bool(cfg.get("click_through", False)):
            raise RuntimeError("game-safe lock did not enable click-through")
        if not pet.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            raise RuntimeError("locked pet is still accepting Qt mouse events")
        pet.set_interaction_lock(False)
        app.processEvents()
        if bool(cfg.get("lock_position", False)) or bool(cfg.get("click_through", False)):
            raise RuntimeError("unlock did not restore interactive state")

        # Long-term memory is file-light and does not require the model to be loaded.
        marker = f"CI memory {time.time_ns()}"
        mid = brain.add_memory(marker, "manual", "selftest")
        if not mid or marker not in [x.get("text") for x in brain.list_memories()]:
            raise RuntimeError("long-term memory add/list failed")
        brain.delete_memory(mid)

        return True
'''
    s = must(s, smoke_anchor, smoke_new, "v0777 smoke checks")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.7"',
        'theme_btn.clicked.connect(self._v0775_toggle_theme)',
        'def _v0777_memory_category_label',
        '长期记忆{"已开启" if memory_on else "已关闭"}',
        'self.cfg["brain"].get("long_term_memory", True)',
        'WS_EX_NOACTIVATE = 0x08000000',
        'GetAsyncKeyState(VK_RBUTTON)',
        'self.cfg["click_through"] = locked',
        '游戏防误触锁定',
        '确定语义规则｜选择「学这个意思」时生效',
        'semantic_btn = QPushButton("学这个意思（推荐）")',
        'fixed_btn = QPushButton("固定这句话")',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.7 main verification failed: {token}")

    if '长期记忆尚未启用' in final:
        raise RuntimeError("stale 'long-term memory disabled' text remains in V0.7.7.7")

    print("Patched XiaoMeili source to V0.7.7.7 long-term memory + unified rule editor + game-safe lock")


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    patch_brain(brain_path)
    patch_main(main_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0777.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
