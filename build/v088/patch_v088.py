# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.8.8 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.8.8 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def insert_before(text: str, anchor: str, addition: str, label: str) -> str:
    pos = text.find(anchor)
    if pos < 0:
        raise RuntimeError(f"V0.8.8 missing insert anchor: {label}")
    return text[:pos] + addition + text[pos:]


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.7"' not in s:
        raise RuntimeError("V0.8.8 expected APP_VERSION 0.8.7 base")
    s = s.replace('APP_VERSION = "0.8.7"', 'APP_VERSION = "0.8.8"', 1)
    s = s.replace("V0.8.7", "V0.8.8")

    generation_finished = r'''    def _brain_generation_finished(self, ok, answer, message):
        self.brain_send_btn.setEnabled(True)
        self.brain_status.setText(str(message))
        if not ok:
            self.brain_chat.addItem(f"系统：{message}")
            self.brain_chat.scrollToBottom()
            return
        spoken = str(answer.get("spoken_text") or "").strip()
        board = str(answer.get("board_text") or "").strip()
        emotion = str(answer.get("emotion") or "neutral")
        ex = self.brain_service.last_exchange() or {}
        exchange = {
            "user_text": str(ex.get("user_text") or "").strip(),
            "assistant_text": spoken,
            "answer": dict(answer or {}),
        }
        reply_item = QListWidgetItem(f"小美丽：{spoken}")
        reply_item.setData(Qt.ItemDataRole.UserRole, exchange)
        self.brain_chat.addItem(reply_item)
        board_item = QListWidgetItem(f"〔白板草稿｜{emotion}〕{board.replace(chr(10),' / ')}")
        board_item.setData(Qt.ItemDataRole.UserRole, exchange)
        self.brain_chat.addItem(board_item)
        self.brain_chat.scrollToBottom()
        self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
        if self.brain_auto_speak.isChecked():
            voice = self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
            vid = str(voice.get("voice_id") or "")
            if vid:
                try:
                    self.voice_service.preview(
                        spoken, vid, float(voice.get("speed",1.0) or 1.0),
                        str(voice.get("output_device","default") or "default")
                    )
                except Exception:
                    LOGGER.exception("大脑回答自动朗读失败")

'''
    s = replace_method(s, "_brain_generation_finished", "_brain_like", generation_finished, "exchange metadata")

    selected_helper = r'''    def _v088_selected_exchange(self):
        item = self.brain_chat.currentItem() if hasattr(self, "brain_chat") else None
        if item is not None:
            try:
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and str(data.get("user_text") or "").strip() and str(data.get("assistant_text") or "").strip():
                    return dict(data)
            except Exception:
                pass
        return self.brain_service.last_exchange()

'''
    s = insert_before(s, "    def _brain_like(self):\n", selected_helper, "selected exchange helper")

    dislike_method = r'''    def _brain_dislike(self):
        ex = self._v088_selected_exchange()
        if not ex:
            return
        user_text = str(ex.get("user_text") or "").strip()
        assistant_text = str(ex.get("assistant_text") or "").strip()
        if not user_text:
            return

        existing = None
        try:
            existing = self.brain_service.find_rule_for_question(user_text)
        except Exception:
            existing = None
        existing = dict(existing or {})

        dlg = QDialog(self)
        rid = str(existing.get("id") or "").strip()
        dlg.setWindowTitle(f"编辑养成规则 · {rid}" if rid else "纠正 / 养成")
        try: dlg.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png')))
        except Exception: pass
        dlg.resize(690, 650)
        root = QVBoxLayout(dlg); root.setContentsMargins(18,16,18,16); root.setSpacing(10)

        title = QLabel("修改同类问题命中时，小美丽应该表达什么")
        title.setObjectName("pageTitle"); root.addWidget(title)
        sub = QLabel("点击纠正后直接在这里完成。已有规则会直接编辑原规则，不会重复创建。")
        sub.setWordWrap(True); sub.setObjectName("pageSubtitle"); root.addWidget(sub)

        root.addWidget(QLabel("触发问题 / 原始场景"))
        question = QLineEdit(user_text); root.addWidget(question)

        root.addWidget(QLabel("回答 / 核心意思"))
        answer_edit = QTextEdit()
        answer_edit.setMinimumHeight(135)
        answer_edit.setPlainText(str(existing.get("reference_answer") or existing.get("intent") or assistant_text))
        root.addWidget(answer_edit)

        box = QGroupBox("确定语义规则｜选择「学这个意思」时生效")
        form = QFormLayout(box)
        scene = QLineEdit(str(existing.get("scene") or user_text))
        must = QLineEdit(str(existing.get("must") or ""))
        forbid = QLineEdit(str(existing.get("forbid") or "不要反转或偏离上方核心意思"))
        tone = QLineEdit(str(existing.get("tone") or "自然、自信，符合小美丽性格"))
        form.addRow("场景", scene)
        form.addRow("必须体现", must)
        form.addRow("禁止偏离", forbid)
        form.addRow("语气", tone)
        root.addWidget(box)

        current_mode = str(existing.get("mode") or "semantic")
        current_text = "当前：新规则"
        if rid:
            current_text = f"当前：#{rid} · {'固定台词' if current_mode == 'fixed' else '语义规则'}。保存会覆盖这一条，不新增重复规则。"
        status = QLabel(current_text); status.setWordWrap(True); root.addWidget(status)

        buttons = QHBoxLayout(); buttons.addStretch(1)
        semantic_btn = QPushButton("🧠 学这个意思（推荐）")
        fixed_btn = QPushButton("📌 固定这句话")
        cancel_btn = QPushButton("取消")
        buttons.addWidget(semantic_btn); buttons.addWidget(fixed_btn); buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        cancel_btn.clicked.connect(dlg.reject)

        def commit(mode):
            q = question.text().strip()
            desired = answer_edit.toPlainText().strip()
            if not q or not desired:
                QMessageBox.warning(dlg, "无法保存", "触发问题和回答 / 核心意思不能为空。")
                return
            if mode == "semantic":
                structured = {
                    "scene": scene.text().strip() or q,
                    "intent": desired,
                    "must": must.text().strip() or desired,
                    "forbid": forbid.text().strip() or "不要反转或偏离核心意思",
                    "tone": tone.text().strip() or "自然、符合小美丽人格",
                }
                self.brain_service.save_feedback(
                    "down", q, assistant_text, desired, "semantic", structured
                )
                label = "学这个意思"
                self.brain_status.setText("语义规则已保存。以后允许自由换句式，但核心意思不能变。")
            else:
                self.brain_service.save_feedback(
                    "down", q, assistant_text, desired, "fixed"
                )
                label = "固定这句话"
                self.brain_status.setText("固定台词已保存。同样问题会直接回答你指定的原句。")
            self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
            self.brain_chat.addItem(f"你教她（{label}）：{desired}")
            self.brain_chat.scrollToBottom()
            self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
            self._refresh_brain_rules()
            dlg.accept()

        semantic_btn.clicked.connect(lambda: commit("semantic"))
        fixed_btn.clicked.connect(lambda: commit("fixed"))
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

'''
    s = replace_method(s, "_brain_dislike", "_brain_rule_proposed", dislike_method, "direct correction editor")

    controller_anchor = "        self.brain_service=BrainService()\n"
    if controller_anchor not in s:
        raise RuntimeError("V0.8.8 brain controller anchor missing")
    s = s.replace(
        controller_anchor,
        controller_anchor + "        QTimer.singleShot(1800, self.brain_service.warm_up_async)\n",
        1,
    )

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)


def patch_brain(brain_path: Path):
    b = brain_path.read_text(encoding="utf-8")
    if "import difflib\n" not in b:
        if "import json\n" not in b:
            raise RuntimeError("V0.8.8 json import anchor missing")
        b = b.replace("import json\n", "import difflib\nimport json\n", 1)

    find_rule = r'''    def find_rule_for_question(self, user_text):
        """Return the newest active rule for this exact normalized question."""
        return self._exact_rule(user_text)

'''
    b = insert_before(b, "    def _active_semantic_rules(self, limit=40):\n", find_rule, "public exact rule lookup")

    fast_match = r'''    @staticmethod
    def _v088_match_text(text):
        text = re.sub(r"[\s，,。.!！？?、:：；;（）()\[\]{}<>《》‘’“”\"']+", "", str(text or "").lower())
        return text[:240]

    @staticmethod
    def _v088_ngrams(text, n=2):
        text = str(text or "")
        if len(text) < n:
            return {text} if text else set()
        return {text[i:i+n] for i in range(len(text)-n+1)}

    def _v088_rule_score(self, user_text, rule):
        q = self._v088_match_text(user_text)
        if not q:
            return 0.0
        parts = [
            str(rule.get("user_text") or ""),
            str(rule.get("scene") or ""),
            str(rule.get("intent") or ""),
        ]
        r = self._v088_match_text(" ".join(parts))
        if not r:
            return 0.0
        q2 = self._v088_ngrams(q, 2); r2 = self._v088_ngrams(r, 2)
        q3 = self._v088_ngrams(q, 3); r3 = self._v088_ngrams(r, 3)
        j2 = len(q2 & r2) / max(1, len(q2 | r2))
        j3 = len(q3 & r3) / max(1, len(q3 | r3))
        seq = difflib.SequenceMatcher(None, q, r).ratio()
        cq, cr = set(q), set(r)
        char_j = len(cq & cr) / max(1, len(cq | cr))
        score = 0.46 * seq + 0.28 * j2 + 0.12 * j3 + 0.14 * char_j
        if q in r or r in q:
            score += 0.24
        generic = {
            "可以", "怎么", "什么", "是不是", "有没有", "这个", "那个", "现在", "今天",
            "然后", "对面", "你是", "我是", "不要", "要不", "真的", "觉得", "还是",
        }
        informative = [g for g in (q2 & r2) if g and g not in generic]
        if informative:
            score += min(0.24, 0.07 * len(informative))
        return max(0.0, min(1.0, score))

    def _fast_rule_candidates(self, user_text, limit=6):
        exact = self._exact_rule(user_text)
        if exact:
            exact["_match_confidence"] = 1.0
            return [exact]
        rows = self._active_semantic_rules(80)
        scored = []
        for index, rule in enumerate(rows):
            score = self._v088_rule_score(user_text, rule)
            score += max(0.0, 0.012 - index * 0.00025)
            if score >= 0.18:
                row = dict(rule)
                row["_match_confidence"] = min(1.0, score)
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _score, row in scored[:max(1, int(limit))]]

    def _match_semantic_rule(self, user_text):
        candidates = self._fast_rule_candidates(user_text, 1)
        if not candidates:
            return None
        top = candidates[0]
        return top if float(top.get("_match_confidence") or 0.0) >= 0.58 else None

'''
    b = replace_method(b, "_match_semantic_rule", "_guard_semantic_answer", fast_match, "fast semantic retrieval")

    warm = r'''    def warm_up_async(self):
        """Load the local brain in the background without downloading anything."""
        if not self.ready() or self._server_alive():
            return
        def job():
            try:
                started = time.time()
                self._start_server()
                LOGGER.info("[BRAIN_WARMUP] ready in %.3fs", time.time() - started)
            except Exception:
                LOGGER.warning("[BRAIN_WARMUP] background warmup failed", exc_info=True)
        threading.Thread(target=job, name="XiaoMeiliBrainWarmup", daemon=True).start()

'''
    b = insert_before(b, "    def _load_history(self):\n", warm, "brain warmup")

    ask = r'''    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6, long_term_memory=True):
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

        if bool(long_term_memory):
            self.auto_remember(user_text)

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
                self.generation_finished.emit(True, answer, f"命中养成规则 #{exact_rule.get('id')}｜固定台词 · 0 次模型推理")
            except Exception as exc:
                LOGGER.exception("固定规则回答失败")
                self.generation_finished.emit(False, {}, f"固定规则失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False
            return

        def job():
            total_started = time.time()
            try:
                self._start_server()

                retrieval_started = time.time()
                candidates = self._fast_rule_candidates(user_text, 6)
                retrieval_ms = int((time.time() - retrieval_started) * 1000)
                exact_semantic = exact_rule if exact_rule and str(exact_rule.get("mode") or "") == "semantic" else None
                if exact_semantic:
                    candidates = [dict(exact_semantic)] + [r for r in candidates if str(r.get("id")) != str(exact_semantic.get("id"))]
                    candidates[0]["_match_confidence"] = 1.0

                system = str(persona or DEFAULT_PERSONA).strip() + "\n\n" + OUTPUT_CONTRACT.strip()

                if bool(long_term_memory):
                    recalled = self.recall_memories(user_text, 8)
                    if recalled:
                        system += (
                            "\n\n【小美丽的长期记忆｜仅在相关时自然使用】\n"
                            "这些是主人过去明确表达过、并保存在本机的长期信息。只在与当前话题有关时使用，"
                            "不要每次主动复述，也不要根据它们编造新的事实。\n"
                            + "\n".join(f"• {item}" for item in recalled)
                        )

                if candidates:
                    system += (
                        "\n\n【养成规则候选｜一次推理内自行判断】\n"
                        "下面规则由本地快速检索挑出。只有当前问题与某条规则的场景/意图明显相同时才应用；"
                        "无关规则必须完全忽略。若明确命中，必须保持核心立场、必须体现和禁止偏离，但允许自然换句式。"
                    )
                    for i, rule in enumerate(candidates, start=1):
                        confidence = float(rule.get("_match_confidence") or 0.0)
                        system += f"\n候选{i}｜检索相似度 {confidence:.2f}\n{self._rule_prompt(rule)}"

                examples = self._feedback_examples(8)
                if examples:
                    system += "\n\n以下是主人认可或固定过的说话方式，只学习整体口吻，不要机械复述："
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
                generation_ms = int((time.time() - generation_started) * 1000)
                raw = str(response["choices"][0]["message"]["content"])
                answer = _normalize_answer(raw)

                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": answer["spoken_text"]})
                self._save_history(history)

                strong_rule = candidates[0] if candidates and float(candidates[0].get("_match_confidence") or 0.0) >= 0.58 else None
                if strong_rule:
                    self._increment_rule_hit(strong_rule.get("id"))

                self._last_exchange = {
                    "user_text": user_text,
                    "assistant_text": answer["spoken_text"],
                    "answer": answer,
                }

                total_ms = int((time.time() - total_started) * 1000)
                if strong_rule:
                    prefix = f"命中养成规则 #{strong_rule.get('id')}｜"
                elif candidates:
                    prefix = "已参考养成候选｜"
                else:
                    prefix = ""
                status = f"{prefix}规则检索 {retrieval_ms}ms · 生成 {generation_ms/1000:.1f}s · 总计 {total_ms/1000:.1f}s"
                LOGGER.info(
                    "[BRAIN_LATENCY] retrieval_ms=%s generation_ms=%s total_ms=%s candidates=%s",
                    retrieval_ms, generation_ms, total_ms, len(candidates),
                )
                self.generation_finished.emit(True, answer, status)
            except Exception as exc:
                LOGGER.exception("小美丽大脑回答失败")
                self.generation_finished.emit(False, {}, f"回答失败：{type(exc).__name__}: {exc}")
            finally:
                self._generate_busy = False

        threading.Thread(target=job, name="XiaoMeiliBrainAsk", daemon=True).start()

'''
    b = replace_method(b, "ask", "last_exchange", ask, "single inference ask")

    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(brain_path), doraise=True)


def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    brain = root / "app" / "src" / "brain_qwen.py"
    if not main.exists() or not brain.exists():
        raise FileNotFoundError("V0.8.8 expected V0.8.7 source")
    patch_main(main)
    patch_brain(brain)

    m = main.read_text(encoding="utf-8")
    b = brain.read_text(encoding="utf-8")
    checks_main = [
        'APP_VERSION = "0.8.8"',
        'def _v088_selected_exchange(self):',
        '修改同类问题命中时，小美丽应该表达什么',
        '已有规则会直接编辑原规则，不会重复创建',
        'QTimer.singleShot(1800, self.brain_service.warm_up_async)',
    ]
    checks_brain = [
        'def find_rule_for_question(self, user_text):',
        'def _fast_rule_candidates(self, user_text, limit=6):',
        'def warm_up_async(self):',
        '一次推理内自行判断',
        '[BRAIN_LATENCY]',
        '0 次模型推理',
    ]
    for token in checks_main:
        if token not in m:
            raise RuntimeError("V0.8.8 main verification failed: " + token)
    for token in checks_brain:
        if token not in b:
            raise RuntimeError("V0.8.8 brain verification failed: " + token)

    ask_block = b[b.find("    def ask("):b.find("    def last_exchange(")]
    if "_guard_semantic_answer(" in ask_block:
        raise RuntimeError("V0.8.8 ask still invokes semantic guard")
    if "max_attempts" in ask_block or "rewrite_count" in ask_block:
        raise RuntimeError("V0.8.8 ask still contains multi-pass rewrite loop")
    if ask_block.count('_post_json("/v1/chat/completions"') != 1:
        raise RuntimeError("V0.8.8 ask must contain exactly one chat completion call")

    print("Patched XiaoMeili source to V0.8.8 direct correction + single-inference fast brain")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v088.py <source_root>")
    patch(Path(sys.argv[1]))
