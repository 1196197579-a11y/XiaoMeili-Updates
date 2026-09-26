# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.9 anchor: {label}")
    return text.replace(old, new, 1)


def replace_method(text: str, start_sig: str, next_sig: str, body: str, label: str) -> str:
    start = text.find(start_sig)
    if start < 0:
        raise RuntimeError(f"missing v0.7.7.9 method start: {label}")
    end = text.find(next_sig, start + len(start_sig))
    if end < 0:
        raise RuntimeError(f"missing v0.7.7.9 method end: {label}")
    return text[:start] + body + text[end:]


def patch_brain(brain_path: Path):
    b = brain_path.read_text(encoding="utf-8")

    b = must(
        b,
        'RULES_FILE = BRAIN_ROOT / "learning_rules.json"\nMEMORY_FILE = BRAIN_ROOT / "long_term_memory.json"\n',
        'RULES_FILE = BRAIN_ROOT / "learning_rules.json"\n'
        'RULE_GROUPS_FILE = BRAIN_ROOT / "learning_rule_groups.json"\n'
        'MEMORY_FILE = BRAIN_ROOT / "long_term_memory.json"\n',
        "rule groups constant",
    )

    sync_body = r'''    def _sync_rules_from_feedback(self):
        rules = self._load_rules()

        # One normalized question owns one current lesson. Deleted rows are kept
        # as tombstones, so an old feedback.jsonl entry can never silently
        # resurrect a rule that the user deliberately removed.
        known_keys = {
            self._feedback_key(r.get("user_text"))
            for r in rules
            if self._feedback_key(r.get("user_text"))
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
            if key:
                latest[key] = row

        for key, row in latest.items():
            if key in known_keys:
                continue
            mode = str(row.get("mode") or "fixed").strip().lower()
            if mode not in {"fixed", "semantic"}:
                mode = "fixed"
            correction = str(row.get("correction") or "").strip()
            user = str(row.get("user_text") or "").strip()
            rules.append({
                "id": self._next_rule_id(rules),
                "mode": mode,
                "enabled": True,
                "deleted": False,
                "group_id": "",
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
            known_keys.add(key)
            changed = True

        if changed:
            self._save_rules(rules)

'''
    b = replace_method(
        b,
        "    def _sync_rules_from_feedback(self):\n",
        "    def list_rules(self):\n",
        sync_body,
        "feedback sync tombstones",
    )

    library_body = r'''    def list_rules(self):
        self._sync_rules_from_feedback()
        return [
            dict(r) for r in reversed(self._load_rules())
            if not bool(r.get("deleted", False))
        ]

    def get_rule(self, rule_id):
        for rule in self._load_rules():
            if str(rule.get("id")) == str(rule_id):
                if bool(rule.get("deleted", False)):
                    return None
                out = dict(rule)
                out.setdefault("group_id", "")
                return out
        return None

    def update_rule(self, rule_id, changes):
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id")) != str(rule_id) or bool(rule.get("deleted", False)):
                continue
            for key in (
                "mode", "user_text", "scene", "intent", "must", "forbid",
                "tone", "reference_answer", "enabled", "group_id",
            ):
                if key in changes:
                    rule[key] = changes[key]
            rule.setdefault("group_id", "")
            rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_rules(rules)
            return dict(rule)
        return None

    def delete_rule(self, rule_id):
        # Soft-delete is intentional. feedback.jsonl is an append-only training
        # history; physically removing only learning_rules.json caused
        # _sync_rules_from_feedback() to recreate the lesson immediately.
        # A tombstone means "this lesson was explicitly deleted" forever, unless
        # the user teaches the same question again later.
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id")) != str(rule_id) or bool(rule.get("deleted", False)):
                continue
            rule["deleted"] = True
            rule["enabled"] = False
            rule["deleted_at"] = datetime.now().isoformat(timespec="seconds")
            rule["updated_at"] = rule["deleted_at"]
            self._save_rules(rules)
            return True
        return False

    # ------------------------------------------------------------------
    # V0.7.7.9 learning-library groups.
    # Groups are organization metadata only. They never alter rule matching.
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_rule_group_name(name):
        return re.sub(r"\s+", " ", str(name or "").strip())[:24]

    def _load_rule_groups(self):
        try:
            data = json.loads(RULE_GROUPS_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            out = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                gid = str(row.get("id") or "").strip()
                name = self._normalize_rule_group_name(row.get("name"))
                if gid and name:
                    out.append({
                        "id": gid,
                        "name": name,
                        "created_at": str(row.get("created_at") or ""),
                        "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
                    })
            return out
        except Exception:
            return []

    def _save_rule_groups(self, groups):
        RULE_GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        seen = set()
        for row in list(groups):
            if not isinstance(row, dict):
                continue
            gid = str(row.get("id") or "").strip()
            name = self._normalize_rule_group_name(row.get("name"))
            folded = name.casefold()
            if not gid or not name or folded in seen:
                continue
            seen.add(folded)
            rows.append({
                "id": gid,
                "name": name,
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            })
        temp = RULE_GROUPS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(RULE_GROUPS_FILE)

    @staticmethod
    def _next_rule_group_id(groups):
        nums = []
        for row in groups:
            m = re.search(r"(\d+)$", str(row.get("id") or ""))
            if m:
                nums.append(int(m.group(1)))
        return f"G{(max(nums) + 1 if nums else 1):03d}"

    def list_rule_groups(self):
        return [dict(x) for x in self._load_rule_groups()]

    def create_rule_group(self, name):
        name = self._normalize_rule_group_name(name)
        if not name:
            return None, "分组名称不能为空"
        if name in {"全部规则", "未分组"}:
            return None, "这个名称是养成库保留名称，请换一个"
        groups = self._load_rule_groups()
        if any(str(x.get("name") or "").casefold() == name.casefold() for x in groups):
            return None, "已经存在同名分组"
        now = datetime.now().isoformat(timespec="seconds")
        row = {
            "id": self._next_rule_group_id(groups),
            "name": name,
            "created_at": now,
            "updated_at": now,
        }
        groups.append(row)
        self._save_rule_groups(groups)
        return dict(row), ""

    def rename_rule_group(self, group_id, name):
        group_id = str(group_id or "").strip()
        name = self._normalize_rule_group_name(name)
        if not group_id:
            return False, "未分组不能重命名"
        if not name:
            return False, "分组名称不能为空"
        if name in {"全部规则", "未分组"}:
            return False, "这个名称是养成库保留名称，请换一个"
        groups = self._load_rule_groups()
        for row in groups:
            if str(row.get("id") or "") == group_id:
                if any(
                    str(x.get("id") or "") != group_id
                    and str(x.get("name") or "").casefold() == name.casefold()
                    for x in groups
                ):
                    return False, "已经存在同名分组"
                row["name"] = name
                row["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_rule_groups(groups)
                return True, ""
        return False, "分组不存在"

    def delete_rule_group(self, group_id):
        group_id = str(group_id or "").strip()
        if not group_id:
            return False
        groups = self._load_rule_groups()
        kept = [g for g in groups if str(g.get("id") or "") != group_id]
        if len(kept) == len(groups):
            return False

        # Deleting a folder must never delete the lessons inside it.
        # Move all contained rules back to "未分组", including tombstones.
        rules = self._load_rules()
        changed_rules = False
        for rule in rules:
            if str(rule.get("group_id") or "") == group_id:
                rule["group_id"] = ""
                rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
                changed_rules = True
        if changed_rules:
            self._save_rules(rules)
        self._save_rule_groups(kept)
        return True

    def move_rule_to_group(self, rule_id, group_id):
        rule_id = str(rule_id or "").strip()
        group_id = str(group_id or "").strip()
        if group_id:
            valid = {str(x.get("id") or "") for x in self._load_rule_groups()}
            if group_id not in valid:
                return False
        rules = self._load_rules()
        for rule in rules:
            if str(rule.get("id") or "") == rule_id and not bool(rule.get("deleted", False)):
                rule["group_id"] = group_id
                rule["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_rules(rules)
                return True
        return False

'''
    b = replace_method(
        b,
        "    def list_rules(self):\n",
        "    def _upsert_rule(self, mode, user_text, reference_answer, structured=None):\n",
        library_body,
        "rule library + groups",
    )

    upsert_body = r'''    def _upsert_rule(self, mode, user_text, reference_answer, structured=None):
        rules = self._load_rules()
        key = self._feedback_key(user_text)
        structured = dict(structured or {})
        target = None

        # Only update an active lesson. If the previous lesson was explicitly
        # deleted, teaching the same question again is treated as a fresh lesson
        # with a new rule ID instead of reviving hidden metadata.
        for rule in reversed(rules):
            if bool(rule.get("deleted", False)):
                continue
            if self._feedback_key(rule.get("user_text")) == key:
                target = rule
                break

        if target is None:
            target = {
                "id": self._next_rule_id(rules),
                "hit_count": 0,
                "group_id": "",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            rules.append(target)

        target.update({
            "mode": str(mode),
            "enabled": True,
            "deleted": False,
            "user_text": str(user_text or "").strip(),
            "reference_answer": str(reference_answer or "").strip(),
            "scene": str(structured.get("scene") or user_text or "").strip(),
            "intent": str(structured.get("intent") or reference_answer or "").strip(),
            "must": str(structured.get("must") or reference_answer or "").strip() if mode == "semantic" else "",
            "forbid": str(structured.get("forbid") or "").strip(),
            "tone": str(structured.get("tone") or "保持主人纠正时的口吻").strip() if mode == "semantic" else "",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        target.setdefault("group_id", "")
        target.pop("deleted_at", None)
        self._save_rules(rules)
        return dict(target)

'''
    b = replace_method(
        b,
        "    def _upsert_rule(self, mode, user_text, reference_answer, structured=None):\n",
        "    def _increment_rule_hit(self, rule_id):\n",
        upsert_body,
        "upsert deleted-rule behavior",
    )

    exact_body = r'''    def _exact_rule(self, user_text):
        key = self._feedback_key(user_text)
        if not key:
            return None
        for rule in reversed(self._load_rules()):
            if bool(rule.get("deleted", False)) or not rule.get("enabled", True):
                continue
            if self._feedback_key(rule.get("user_text")) == key:
                return dict(rule)
        return None

'''
    b = replace_method(
        b,
        "    def _exact_rule(self, user_text):\n",
        "    def _active_semantic_rules(self, limit=40):\n",
        exact_body,
        "exact rule tombstone guard",
    )

    semantic_body = r'''    def _active_semantic_rules(self, limit=40):
        rows = [
            dict(r) for r in reversed(self._load_rules())
            if (
                not bool(r.get("deleted", False))
                and r.get("enabled", True)
                and str(r.get("mode") or "") == "semantic"
            )
        ]
        return rows[:max(1, int(limit))]

'''
    b = replace_method(
        b,
        "    def _active_semantic_rules(self, limit=40):\n",
        "    @staticmethod\n    def _rule_prompt(rule):\n",
        semantic_body,
        "semantic tombstone guard",
    )

    examples_body = r'''    def _feedback_examples(self, limit=10):
        rows = self._feedback_rows()
        rules = self._load_rules()
        active_keys = {
            self._feedback_key(r.get("user_text"))
            for r in rules
            if not bool(r.get("deleted", False)) and self._feedback_key(r.get("user_text"))
        }
        deleted_keys = {
            self._feedback_key(r.get("user_text"))
            for r in rules
            if bool(r.get("deleted", False)) and self._feedback_key(r.get("user_text"))
        } - active_keys

        examples = []
        seen_down = set()
        for row in reversed(rows[-200:]):
            rating = str(row.get("rating") or "")
            user = str(row.get("user_text") or "").strip()
            if rating == "down":
                key = self._feedback_key(user)
                if not key or key in seen_down or key in deleted_keys:
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
    b = replace_method(
        b,
        "    def _feedback_examples(self, limit=10):\n",
        "    def save_feedback(",
        examples_body,
        "deleted fixed rule feedback guard",
    )

    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(brain_path), doraise=True)

    final = brain_path.read_text(encoding="utf-8")
    checks = [
        'RULE_GROUPS_FILE = BRAIN_ROOT / "learning_rule_groups.json"',
        'def create_rule_group(self, name):',
        'def rename_rule_group(self, group_id, name):',
        'def delete_rule_group(self, group_id):',
        'def move_rule_to_group(self, rule_id, group_id):',
        'rule["deleted"] = True',
        'if key in known_keys:',
        'if bool(rule.get("deleted", False)) or not rule.get("enabled", True):',
        'and r.get("enabled", True)',
        'key in deleted_keys',
        '"group_id": ""',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.9 brain verification failed: {token}")


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.8"',
        'APP_NAME = "小美丽 V0.7.7.9｜Learning Library Groups + Delete Fix"\nAPP_VERSION = "0.7.7.9"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ------------------------------------------------------------------
    # Rebuild the learning-library dialog as a small two-pane organizer.
    # Existing rules stay compatible and appear under "未分组".
    # ------------------------------------------------------------------
    dialog_start = s.find("        self.brain_rules_dialog = QDialog(self)\n")
    dialog_end = s.find("        self.brain_persona_dialog = QDialog(self)\n", dialog_start)
    if dialog_start < 0 or dialog_end < 0:
        raise RuntimeError("learning dialog anchors missing")

    dialog_block = r'''        self.brain_rules_dialog = QDialog(self)
        self.brain_rules_dialog.setWindowTitle("养成库 / 语义规则编辑")
        self.brain_rules_dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        rules_dv = QVBoxLayout(self.brain_rules_dialog)
        rules_dv.setContentsMargins(12, 12, 12, 12)
        rules_dv.setSpacing(8)

        rules_hint = QLabel(
            "按分组管理固定台词和语义规则。分组只用于整理与查找，不会改变小美丽的匹配逻辑。"
        )
        rules_hint.setWordWrap(True)
        rules_hint.setStyleSheet("color:#657185;")
        rules_dv.addWidget(rules_hint)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索"))
        self.brain_rules_search = QLineEdit()
        self.brain_rules_search.setPlaceholderText("搜索规则、场景、核心意思、参考回答…")
        self.brain_rules_search.setClearButtonEnabled(True)
        self.brain_rules_search.textChanged.connect(self._refresh_brain_rules)
        search_row.addWidget(self.brain_rules_search, 1)
        rules_dv.addLayout(search_row)

        organizer = QHBoxLayout()
        organizer.setSpacing(10)

        groups_box = QGroupBox("分组")
        groups_v = QVBoxLayout(groups_box)
        groups_v.setContentsMargins(9, 12, 9, 9)
        groups_v.setSpacing(7)
        self.brain_rule_groups_list = QListWidget()
        self.brain_rule_groups_list.setMinimumWidth(180)
        self.brain_rule_groups_list.setMaximumWidth(220)
        self.brain_rule_groups_list.setToolTip("选择分组后，右侧只显示该分组里的规则")
        self.brain_rule_groups_list.itemSelectionChanged.connect(self._refresh_brain_rules)
        groups_v.addWidget(self.brain_rule_groups_list, 1)

        group_buttons = QHBoxLayout()
        self.brain_group_new_btn = QPushButton("新建")
        self.brain_group_rename_btn = QPushButton("重命名")
        self.brain_group_delete_btn = QPushButton("删除")
        self.brain_group_new_btn.clicked.connect(self._brain_create_rule_group)
        self.brain_group_rename_btn.clicked.connect(self._brain_rename_rule_group)
        self.brain_group_delete_btn.clicked.connect(self._brain_delete_rule_group)
        group_buttons.addWidget(self.brain_group_new_btn)
        group_buttons.addWidget(self.brain_group_rename_btn)
        group_buttons.addWidget(self.brain_group_delete_btn)
        groups_v.addLayout(group_buttons)
        organizer.addWidget(groups_box, 0)

        rules_panel = QWidget()
        rules_v = QVBoxLayout(rules_panel)
        rules_v.setContentsMargins(0, 0, 0, 0)
        rules_v.setSpacing(7)
        self.brain_rules_list = QListWidget()
        self.brain_rules_list.setMinimumHeight(360)
        self.brain_rules_list.setToolTip("双击任意规则即可编辑")
        self.brain_rules_list.itemDoubleClicked.connect(lambda item: self._brain_edit_rule())
        rules_v.addWidget(self.brain_rules_list, 1)

        move_row = QHBoxLayout()
        move_row.addWidget(QLabel("移动选中规则到"))
        self.brain_rule_move_combo = QComboBox()
        self.brain_rule_move_combo.setMinimumWidth(170)
        move_row.addWidget(self.brain_rule_move_combo)
        self.brain_rule_move_btn = QPushButton("移动")
        self.brain_rule_move_btn.clicked.connect(self._brain_move_rule_to_group)
        move_row.addWidget(self.brain_rule_move_btn)
        move_row.addStretch(1)
        rules_v.addLayout(move_row)

        organizer.addWidget(rules_panel, 1)
        rules_dv.addLayout(organizer, 1)

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
        rules_close = QPushButton("关闭")
        rules_close.clicked.connect(self.brain_rules_dialog.accept)
        rules_btns.addWidget(rules_close)
        rules_dv.addLayout(rules_btns)

'''
    s = s[:dialog_start] + dialog_block + s[dialog_end:]

    open_body = r'''    def _open_brain_rules_editor(self):
        self._refresh_rule_groups()
        self._refresh_brain_rules()
        self.brain_rules_dialog.resize(940, 610)
        self.brain_rules_dialog.setMinimumSize(820, 540)
        try:
            self._v0775_apply_native_titlebar(
                self.brain_rules_dialog,
                getattr(self, "_v0775_theme_mode", "light") == "dark",
            )
        except Exception:
            pass
        self.brain_rules_dialog.exec()

'''
    s = replace_method(
        s,
        "    def _open_brain_rules_editor(self):\n",
        "    def _prepare_brain(self):\n",
        open_body,
        "open learning editor",
    )

    # Group manager + grouped/searchable refresh. Place these immediately before
    # the existing selected-rule helper.
    refresh_start = s.find("    def _refresh_brain_rules(self):\n")
    selected_start = s.find("    def _selected_brain_rule_id(self):\n", refresh_start)
    if refresh_start < 0 or selected_start < 0:
        raise RuntimeError("rule refresh anchors missing")

    manager_methods = r'''    def _selected_brain_group_id(self):
        if not hasattr(self, "brain_rule_groups_list"):
            return "__all__"
        item = self.brain_rule_groups_list.currentItem()
        if item is None:
            return "__all__"
        value = item.data(Qt.ItemDataRole.UserRole)
        return "__all__" if value is None else str(value)

    def _refresh_rule_groups(self):
        if not hasattr(self, "brain_rule_groups_list"):
            return

        wanted = self._selected_brain_group_id()
        if wanted == "__all__" and self.brain_rule_groups_list.count() == 0:
            wanted = "__all__"

        try:
            groups = self.brain_service.list_rule_groups()
            rules = self.brain_service.list_rules()
        except Exception:
            LOGGER.exception("刷新养成库分组失败")
            groups, rules = [], []

        counts = {"": 0}
        for rule in rules:
            gid = str(rule.get("group_id") or "")
            counts[gid] = counts.get(gid, 0) + 1

        self.brain_rule_groups_list.blockSignals(True)
        self.brain_rule_groups_list.clear()

        all_item = QListWidgetItem(f"全部规则  ({len(rules)})")
        all_item.setData(Qt.ItemDataRole.UserRole, "__all__")
        self.brain_rule_groups_list.addItem(all_item)

        ungrouped = QListWidgetItem(f"未分组  ({counts.get('', 0)})")
        ungrouped.setData(Qt.ItemDataRole.UserRole, "")
        self.brain_rule_groups_list.addItem(ungrouped)

        for group in groups:
            gid = str(group.get("id") or "")
            name = str(group.get("name") or "未命名")
            item = QListWidgetItem(f"{name}  ({counts.get(gid, 0)})")
            item.setData(Qt.ItemDataRole.UserRole, gid)
            item.setToolTip(name)
            self.brain_rule_groups_list.addItem(item)

        found = False
        for i in range(self.brain_rule_groups_list.count()):
            item = self.brain_rule_groups_list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == wanted:
                self.brain_rule_groups_list.setCurrentRow(i)
                found = True
                break
        if not found:
            self.brain_rule_groups_list.setCurrentRow(0)
        self.brain_rule_groups_list.blockSignals(False)

        if hasattr(self, "brain_rule_move_combo"):
            current_move = str(self.brain_rule_move_combo.currentData() or "")
            self.brain_rule_move_combo.blockSignals(True)
            self.brain_rule_move_combo.clear()
            self.brain_rule_move_combo.addItem("未分组", "")
            for group in groups:
                self.brain_rule_move_combo.addItem(
                    str(group.get("name") or "未命名"),
                    str(group.get("id") or ""),
                )
            for i in range(self.brain_rule_move_combo.count()):
                if str(self.brain_rule_move_combo.itemData(i) or "") == current_move:
                    self.brain_rule_move_combo.setCurrentIndex(i)
                    break
            self.brain_rule_move_combo.blockSignals(False)

        selected_gid = self._selected_brain_group_id()
        editable_group = selected_gid not in {"__all__", ""}
        if hasattr(self, "brain_group_rename_btn"):
            self.brain_group_rename_btn.setEnabled(editable_group)
        if hasattr(self, "brain_group_delete_btn"):
            self.brain_group_delete_btn.setEnabled(editable_group)

    def _refresh_brain_rules(self):
        if not hasattr(self, "brain_rules_list"):
            return

        self._refresh_rule_groups()
        selected_group = self._selected_brain_group_id()
        query = ""
        if hasattr(self, "brain_rules_search"):
            query = str(self.brain_rules_search.text() or "").strip().casefold()

        self.brain_rules_list.clear()
        try:
            rules = self.brain_service.list_rules()
            groups = self.brain_service.list_rule_groups()
        except Exception:
            LOGGER.exception("刷新养成库失败")
            rules, groups = [], []

        group_names = {str(x.get("id") or ""): str(x.get("name") or "") for x in groups}

        for rule in rules:
            gid = str(rule.get("group_id") or "")
            if selected_group != "__all__" and gid != selected_group:
                continue

            haystack = " ".join(
                str(rule.get(k) or "")
                for k in (
                    "id", "user_text", "scene", "intent", "must", "forbid",
                    "tone", "reference_answer",
                )
            ).casefold()
            if query and query not in haystack:
                continue

            mode = "语义" if rule.get("mode") == "semantic" else "固定"
            state = "启用" if rule.get("enabled", True) else "暂停"
            hits = int(rule.get("hit_count") or 0)
            title = str(
                rule.get("scene")
                or rule.get("user_text")
                or rule.get("reference_answer")
                or ""
            ).strip()
            if len(title) > 34:
                title = title[:34] + "…"

            group_name = group_names.get(gid, "未分组") if gid else "未分组"
            prefix = f"〔{group_name}〕 " if selected_group == "__all__" else ""
            item = QListWidgetItem(
                f"#{rule.get('id')}  {prefix}[{mode}｜{state}]  命中 {hits} 次｜{title}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(rule.get("id") or ""))
            item.setToolTip(
                f"分组：{group_name}\n"
                f"触发：{str(rule.get('user_text') or rule.get('scene') or '')}\n"
                f"回答/核心意思：{str(rule.get('reference_answer') or rule.get('intent') or '')}"
            )
            self.brain_rules_list.addItem(item)

    def _brain_create_rule_group(self):
        value, ok = QInputDialog.getText(
            self.brain_rules_dialog,
            "新建分组",
            "分组名称：",
        )
        if not ok:
            return
        row, error = self.brain_service.create_rule_group(value)
        if row is None:
            QMessageBox.information(self.brain_rules_dialog, "无法创建分组", str(error))
            return
        self._refresh_rule_groups()
        gid = str(row.get("id") or "")
        for i in range(self.brain_rule_groups_list.count()):
            item = self.brain_rule_groups_list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == gid:
                self.brain_rule_groups_list.setCurrentRow(i)
                break
        self._refresh_brain_rules()

    def _brain_rename_rule_group(self):
        gid = self._selected_brain_group_id()
        if gid in {"__all__", ""}:
            QMessageBox.information(self.brain_rules_dialog, "重命名分组", "请选择一个自定义分组。")
            return
        groups = self.brain_service.list_rule_groups()
        group = next((g for g in groups if str(g.get("id") or "") == gid), None)
        if not group:
            self._refresh_rule_groups()
            return
        value, ok = QInputDialog.getText(
            self.brain_rules_dialog,
            "重命名分组",
            "新的分组名称：",
            text=str(group.get("name") or ""),
        )
        if not ok:
            return
        changed, error = self.brain_service.rename_rule_group(gid, value)
        if not changed:
            QMessageBox.information(self.brain_rules_dialog, "无法重命名", str(error))
            return
        self._refresh_brain_rules()

    def _brain_delete_rule_group(self):
        gid = self._selected_brain_group_id()
        if gid in {"__all__", ""}:
            QMessageBox.information(self.brain_rules_dialog, "删除分组", "请选择一个自定义分组。")
            return
        groups = self.brain_service.list_rule_groups()
        group = next((g for g in groups if str(g.get("id") or "") == gid), None)
        name = str(group.get("name") or "这个分组") if group else "这个分组"
        answer = QMessageBox.question(
            self.brain_rules_dialog,
            "删除分组",
            f"确定删除分组「{name}」吗？\n\n分组里的规则不会被删除，会自动移动到「未分组」。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.brain_service.delete_rule_group(gid):
            QMessageBox.warning(self.brain_rules_dialog, "删除失败", "分组不存在或保存失败。")
            return
        self._refresh_brain_rules()

    def _brain_move_rule_to_group(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self.brain_rules_dialog, "移动规则", "请先选中一条规则。")
            return
        gid = str(self.brain_rule_move_combo.currentData() or "")
        if not self.brain_service.move_rule_to_group(rule_id, gid):
            QMessageBox.warning(self.brain_rules_dialog, "移动失败", "没有找到规则或目标分组。")
            return
        self.brain_status.setText(f"规则 #{rule_id} 已移动")
        self._refresh_brain_rules()

'''
    s = s[:refresh_start] + manager_methods + s[selected_start:]

    # Make deletion truthful: report a failure if persistence failed and then
    # refresh both groups and rules. The service tombstone prevents feedback
    # migration from bringing the rule back.
    delete_start = s.find("    def _brain_delete_rule(self):\n")
    delete_end = s.find("    def _brain_clear_history(self):\n", delete_start)
    if delete_start < 0 or delete_end < 0:
        raise RuntimeError("delete rule anchors missing")
    delete_body = r'''    def _brain_delete_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return

        title = str(rule.get("scene") or rule.get("user_text") or rule_id).strip()
        if len(title) > 42:
            title = title[:42] + "…"
        answer = QMessageBox.question(
            self.brain_rules_dialog,
            "删除养成规则",
            f"确定删除规则 #{rule_id} 吗？\n\n{title}\n\n"
            "删除后它不会再参与固定命中、语义匹配或回答风格示例。"
            "以后重新教同一问题时，会作为一条新规则重新建立。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not self.brain_service.delete_rule(rule_id):
            QMessageBox.warning(self.brain_rules_dialog, "删除失败", "规则没有成功写入删除状态，请重试。")
            return

        self.brain_status.setText(f"规则 #{rule_id} 已删除")
        self._refresh_brain_rules()

'''
    s = s[:delete_start] + delete_body + s[delete_end:]

    # Extend the existing settings UI smoke test with the actual regression:
    # feedback -> rule -> delete -> list_rules() must NOT resurrect it.
    smoke_anchor = '''        dark_css = dialog._v0775_stylesheet(True)
        if "settingsScrollViewport" not in dark_css or "#1C3028" not in dark_css:
            raise RuntimeError("dark theme scroll/card palette regression")

        return True
'''
    smoke_new = '''        dark_css = dialog._v0775_stylesheet(True)
        if "settingsScrollViewport" not in dark_css or "#1C3028" not in dark_css:
            raise RuntimeError("dark theme scroll/card palette regression")

        # V0.7.7.9 deletion regression + group lifecycle.
        probe_q = "__V0779_DELETE_RESURRECTION_PROBE__"
        brain.save_feedback("down", probe_q, "old", "new", "fixed")
        probe = next(
            (r for r in brain.list_rules() if str(r.get("user_text") or "") == probe_q),
            None,
        )
        if not probe:
            raise RuntimeError("v0779 probe rule was not created")
        probe_id = str(probe.get("id") or "")

        group, err = brain.create_rule_group("__V0779_TEST_GROUP__")
        if group is None:
            # A previous interrupted local smoke run may have left the group.
            group = next(
                (g for g in brain.list_rule_groups() if str(g.get("name") or "") == "__V0779_TEST_GROUP__"),
                None,
            )
        if group is None:
            raise RuntimeError(f"v0779 group create failed: {err}")
        gid = str(group.get("id") or "")
        if not brain.move_rule_to_group(probe_id, gid):
            raise RuntimeError("v0779 group move failed")
        moved = brain.get_rule(probe_id)
        if not moved or str(moved.get("group_id") or "") != gid:
            raise RuntimeError("v0779 group assignment did not persist")
        ok, err = brain.rename_rule_group(gid, "__V0779_TEST_GROUP_RENAMED__")
        if not ok:
            raise RuntimeError(f"v0779 group rename failed: {err}")
        if not brain.delete_rule_group(gid):
            raise RuntimeError("v0779 group delete failed")
        moved = brain.get_rule(probe_id)
        if not moved or str(moved.get("group_id") or "") != "":
            raise RuntimeError("v0779 group delete did not return rules to ungrouped")

        if not brain.delete_rule(probe_id):
            raise RuntimeError("v0779 rule delete failed")
        # Critical call: list_rules invokes feedback sync. The deleted lesson
        # must remain absent instead of being rebuilt from feedback.jsonl.
        if any(str(r.get("id") or "") == probe_id for r in brain.list_rules()):
            raise RuntimeError("v0779 deleted rule resurrected after feedback sync")
        if brain.get_rule(probe_id) is not None:
            raise RuntimeError("v0779 deleted rule is still addressable")

        return True
'''
    s = must(s, smoke_anchor, smoke_new, "v0779 regression smoke test")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.9"',
        'self.brain_rule_groups_list = QListWidget()',
        'self.brain_rules_search = QLineEdit()',
        'def _refresh_rule_groups(self):',
        'def _brain_create_rule_group(self):',
        'def _brain_rename_rule_group(self):',
        'def _brain_delete_rule_group(self):',
        'def _brain_move_rule_to_group(self):',
        '删除后它不会再参与固定命中、语义匹配或回答风格示例',
        '__V0779_DELETE_RESURRECTION_PROBE__',
        'self.brain_rules_dialog.resize(940, 610)',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.9 main verification failed: {token}")


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    if not main_path.exists() or not brain_path.exists():
        raise FileNotFoundError("v0.7.7.9 source inputs missing")

    patch_brain(brain_path)
    patch_main(main_path)
    print("Patched XiaoMeili source to V0.7.7.9 learning library groups + delete fix")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0779.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
