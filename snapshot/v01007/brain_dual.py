# -*- coding: utf-8 -*-
"""Dual-engine brain for XiaoMeili V0.10.0.7.

Cloud preferred:
- Rule retrieval / memories / history remain local.
- Qwen3-8B reasoning runs through Alibaba Cloud Model Studio.
- spoken_text is extracted from the streaming JSON response and emitted while
  generation is still in progress, so cloud TTS can start before the full JSON
  response is complete.
- Local Qwen3-8B is preserved as an explicit mode and optional emergency fallback.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from PySide6.QtCore import Signal

from brain_qwen import (
    BrainService as LocalBrainService,
    DEFAULT_PERSONA,
    OUTPUT_CONTRACT,
    _normalize_answer,
)
from cloud_support import cloud_cfg, load_api_key, brain_endpoint, test_brain_connection
from cloud_usage import record_brain_usage

LOGGER = logging.getLogger("XiaoMeili")


def _partial_spoken(raw: str):
    """Decode the current spoken_text prefix from an incomplete JSON stream."""
    m = re.search(r'"spoken_text"\s*:\s*"', str(raw or ""))
    if not m:
        return "", False
    i = m.end()
    out = []
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if escaped:
            mapping = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}
            if ch == "u":
                if i + 4 >= len(raw):
                    break
                code = raw[i + 1:i + 5]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", code):
                    break
                out.append(chr(int(code, 16)))
                i += 5
                escaped = False
                continue
            out.append(mapping.get(ch, ch))
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue
        if ch == '"':
            return "".join(out), True
        out.append(ch)
        i += 1
    return "".join(out), False


class BrainService(LocalBrainService):
    # Incremental spoken text. delta is newly generated characters; text is the
    # complete spoken_text prefix known so far.
    spoken_stream_delta = Signal(str)
    spoken_stream_text = Signal(str)
    spoken_stream_done = Signal(bool, str)
    spoken_stream_aborted = Signal(str)
    cloud_latency_updated = Signal(object)
    cloud_status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_cfg = {}
        self._last_cloud_latency = {}

    def configure(self, cfg):
        self._app_cfg = cfg if isinstance(cfg, dict) else {}
        self.cloud_status_changed.emit(self.component_status())

    def _ccfg(self):
        return cloud_cfg(self._app_cfg)

    def cloud_mode(self):
        return self._ccfg().get("mode") != "local"

    def cloud_ready(self):
        return self.cloud_mode() and bool(load_api_key())

    def local_ready(self):
        return super().ready()

    def ready(self):
        c = self._ccfg()
        if c["mode"] != "local":
            if load_api_key():
                return True
            if c.get("fallback_local"):
                return super().ready()
            return False
        return super().ready()

    def component_status(self):
        c = self._ccfg()
        if c["mode"] != "local":
            if load_api_key():
                return f"云端大脑已配置：{c['brain_model']} · 阿里云百炼（本地 Qwen3-8B 保留作回退）"
            if c.get("fallback_local") and super().ready():
                return "云端模式尚未保存 API Key；当前可自动回退到本地 Qwen3-8B"
            return "云端模式尚未保存阿里云 API Key"
        return super().component_status()

    def warm_up_async(self):
        # Cloud-preferred mode must NEVER preload the local 8B model. V0.10.0.7
        # also removes the old automatic paid "connection probe": merely starting
        # XiaoMeili does not call Qwen3-8B. The explicit Settings test button is
        # still available when the user wants to test the connection.
        c = self._ccfg()
        if c["mode"] != "local":
            if load_api_key():
                self.cloud_status_changed.emit(
                    f"云端大脑待命：{c['brain_model']} · 启动未产生模型调用（本地 Qwen3-8B 未预加载）。"
                )
            else:
                self.cloud_status_changed.emit("云端优先模式：等待保存阿里云 API Key；本地 Qwen3-8B 未预加载。")
            return
        super().warm_up_async()

    def test_cloud_async(self):
        c = self._ccfg()
        key = load_api_key()
        def job():
            ok, msg, ms = test_brain_connection(key, c["brain_base_url"], c["brain_model"], timeout=8)
            self.cloud_status_changed.emit(msg)
            if ms is not None:
                self.cloud_latency_updated.emit({"brain_test_ms": int(ms), "ok": bool(ok)})
        threading.Thread(target=job, name="XiaoMeiliCloudBrainTest", daemon=True).start()

    def last_cloud_latency(self):
        return dict(self._last_cloud_latency)

    def _cloud_context(self, user_text, persona, context_turns, long_term_memory, best_rule, exact_rule):
        system = str(persona or DEFAULT_PERSONA).strip() + "\n\n" + OUTPUT_CONTRACT.strip()
        system += (
            "\n\n【回答总原则】先回答主人真正问的事，再体现小美丽的性格。"
            "养成规则表达的是必须保持的意思和立场，不是台词模板。"
            "绝不能为了搞笑而把主人问题转去另一个 VALORANT 话题。"
            "除固定模式外，参考回答只用于理解意思，禁止机械复读。"
        )

        recalled = []
        if bool(long_term_memory):
            recalled = self.recall_memories(user_text, 8)
            if recalled:
                system += (
                    "\n\n【小美丽的长期记忆｜仅在相关时自然使用】\n"
                    "只在与当前话题真正有关时使用，不主动背诵，不编造。\n"
                    + "\n".join(f"• {item}" for item in recalled)
                )

        mimic_rule = None
        rule_score = 0.0
        strong_rule = False
        if best_rule and str(best_rule.get("mode") or "") == "semantic":
            rule_score = float(best_rule.get("_match_confidence") or (1.0 if exact_rule else 0.0))
            if bool(exact_rule) or (rule_score >= 0.28 and not bool(best_rule.get("_ambiguous"))):
                mimic_rule = dict(best_rule)
                strong_rule = bool(exact_rule) or (rule_score >= 0.58 and not bool(best_rule.get("_ambiguous")))

        recent_rule_replies = []
        if mimic_rule:
            if strong_rule:
                system += (
                    "\n\n【本轮已确认命中的养成语义｜最高优先级】\n"
                    + self._rule_prompt(mimic_rule)
                    + "\n这条规则已由本地养成库确认命中，不需要再次判断是否相关。"
                    "回答必须明确表达『核心立场』与『必须体现』的意思；"
                    "不能只做泛化吐槽，不能转移到枪法、队友或其他游戏话题来逃避核心意思。"
                    "允许完全换措辞，但语义不能削弱、反转或遗漏。"
                )
                ref = str(mimic_rule.get("reference_answer") or "").strip()
                if ref:
                    system += f"\n主人当时的纠正样本：{ref}\n只提取意思，不照抄句子。"
            else:
                system += (
                    "\n\n【可能相关的养成语义】\n"
                    + self._rule_prompt(mimic_rule)
                    + "\n先判断当前问题是否真的属于该触发范围。属于才采用；不属于就忽略。"
                )
            recent_rule_replies = self._v089_rule_recent(mimic_rule)
            if recent_rule_replies:
                system += (
                    "\n\n【该语义最近说过的话｜本轮不要近似复读】\n"
                    + "\n".join(f"- {x}" for x in recent_rule_replies)
                )

        examples = self._feedback_examples(8)
        if examples:
            system += "\n\n【整体说话口吻样本｜只学风格，不当作当前问题答案】"
            for u, a in examples:
                system += f"\n主人：{u}\n小美丽：{a}"

        history = self._load_history()
        max_msgs = max(2, int(context_turns) * 2)
        history = history[-max_msgs:]
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": str(user_text)})
        return messages, history, mimic_rule, strong_rule, rule_score

    def _fixed_answer(self, best_rule, user_text, retrieval_ms):
        forced = self._v089_fixed_reply(best_rule)
        if not forced:
            raise RuntimeError("固定回复池为空")
        answer = {"spoken_text": forced[:180], "board_text": forced[:24], "emotion": "neutral"}
        history = self._load_history()
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": answer["spoken_text"]})
        self._save_history(history)
        self._increment_rule_hit(best_rule.get("id"))
        self._v089_remember_rule_reply(best_rule.get("id"), answer["spoken_text"])
        self._last_exchange = {"user_text": user_text, "assistant_text": answer["spoken_text"], "answer": answer}
        # Fixed rules skip the cloud brain, but still flow through the same
        # streaming hooks so the pre-opened cloud TTS can speak immediately.
        self.spoken_stream_delta.emit(answer["spoken_text"])
        self.spoken_stream_text.emit(answer["spoken_text"])
        self.spoken_stream_done.emit(True, answer["spoken_text"])
        self.generation_finished.emit(
            True, answer,
            f"命中固定规则 #{best_rule.get('id')}｜本地极速回复 · 0 次云端推理 · 检索 {retrieval_ms}ms",
        )

    def ask(self, user_text: str, persona: str, temperature=0.78, max_tokens=220, context_turns=6, long_term_memory=True):
        user_text = str(user_text or "").strip()
        if not user_text:
            self.generation_finished.emit(False, {}, "请输入一句话。")
            return
        if self._generate_busy:
            self.generation_finished.emit(False, {}, "小美丽还在想上一句话，稍等一下。")
            return

        c = self._ccfg()
        # Explicit local mode keeps V0.10.0.5 behaviour intact.
        if c["mode"] == "local":
            return super().ask(user_text, persona, temperature, max_tokens, context_turns, long_term_memory)

        retrieval_started = time.time()
        exact_rule = self._exact_rule(user_text)
        best_rule = dict(exact_rule or self._v089_best_rule(user_text) or {})
        retrieval_ms = int((time.time() - retrieval_started) * 1000)

        # Fixed rules stay local even in cloud mode.
        if best_rule and str(best_rule.get("mode") or "") == "fixed":
            confidence = float(best_rule.get("_match_confidence") or (1.0 if exact_rule else 0.0))
            safe_fixed = bool(exact_rule) or (confidence >= 0.72 and not bool(best_rule.get("_ambiguous")))
            if safe_fixed:
                self._generate_busy = True
                self.generation_started.emit()
                try:
                    self._fixed_answer(best_rule, user_text, retrieval_ms)
                except Exception as exc:
                    LOGGER.exception("固定回复池回答失败")
                    self.generation_finished.emit(False, {}, f"固定回复失败：{type(exc).__name__}: {exc}")
                finally:
                    self._generate_busy = False
                return

        api_key = load_api_key()
        if not api_key:
            if c.get("fallback_local") and super().ready():
                return super().ask(user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
            self.generation_finished.emit(False, {}, "云端模式尚未保存阿里云 API Key。请到「大脑 → 云端双引擎」配置。")
            return

        self._generate_busy = True
        self.generation_started.emit()
        if bool(long_term_memory):
            self.auto_remember(user_text)

        def job():
            sent_len = 0
            raw_output = ""
            first_raw_at = None
            first_spoken_at = None
            usage = {}
            started = time.perf_counter()
            try:
                messages, history, mimic_rule, strong_rule, rule_score = self._cloud_context(
                    user_text, persona, context_turns, long_term_memory, best_rule, exact_rule
                )
                payload = {
                    "model": c["brain_model"],
                    "messages": messages,
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "max_tokens": int(max_tokens),
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "enable_thinking": False,
                }
                req = urllib.request.Request(
                    brain_endpoint(c["brain_base_url"]),
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json; charset=utf-8",
                        "Accept": "text/event-stream",
                    },
                    method="POST",
                )

                timeout_s = max(4.0, float(c["first_response_timeout_ms"]) / 1000.0 + 1.0)
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    while True:
                        raw_line = resp.readline()
                        if not raw_line:
                            break
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        if not data:
                            continue
                        try:
                            obj = json.loads(data)
                            if isinstance(obj.get("usage"), dict):
                                usage = dict(obj.get("usage") or {})
                            choices = obj.get("choices") or []
                            delta = choices[0].get("delta", {}).get("content") if choices else None
                        except Exception:
                            delta = None
                        if not delta:
                            continue
                        now = time.perf_counter()
                        if first_raw_at is None:
                            first_raw_at = now
                            elapsed_ms = (now - started) * 1000.0
                            if elapsed_ms > float(c["first_response_timeout_ms"]):
                                raise TimeoutError(f"云端大脑首字超过 {c['first_response_timeout_ms']}ms")
                        raw_output += str(delta)
                        spoken_partial, _closed = _partial_spoken(raw_output)
                        if spoken_partial and first_spoken_at is None:
                            first_spoken_at = now
                        if len(spoken_partial) > sent_len:
                            new_text = spoken_partial[sent_len:]
                            sent_len = len(spoken_partial)
                            self.spoken_stream_delta.emit(new_text)
                            self.spoken_stream_text.emit(spoken_partial)

                answer = _normalize_answer(raw_output)
                spoken = str(answer.get("spoken_text") or "").strip()
                if len(spoken) > sent_len:
                    tail = spoken[sent_len:]
                    if tail:
                        self.spoken_stream_delta.emit(tail)
                    self.spoken_stream_text.emit(spoken)

                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": spoken})
                self._save_history(history)

                if mimic_rule and strong_rule:
                    self._increment_rule_hit(mimic_rule.get("id"))
                    self._v089_remember_rule_reply(mimic_rule.get("id"), spoken)

                self._last_exchange = {"user_text": user_text, "assistant_text": spoken, "answer": answer}
                ended = time.perf_counter()
                brain_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                brain_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                if brain_in or brain_out:
                    try:
                        record_brain_usage(brain_in, brain_out, tag="dialogue")
                    except Exception:
                        LOGGER.warning("记录云端大脑用量失败", exc_info=True)
                metrics = {
                    "brain_first_raw_ms": int((first_raw_at - started) * 1000) if first_raw_at else None,
                    "brain_first_spoken_ms": int((first_spoken_at - started) * 1000) if first_spoken_at else None,
                    "brain_total_ms": int((ended - started) * 1000),
                    "brain_input_tokens": brain_in,
                    "brain_output_tokens": brain_out,
                    "retrieval_ms": int(retrieval_ms),
                    "rule_id": str((mimic_rule or {}).get("id") or ""),
                    "rule_strong": bool(strong_rule),
                }
                self._last_cloud_latency = dict(metrics)
                self.cloud_latency_updated.emit(dict(metrics))
                self.spoken_stream_done.emit(True, spoken)
                if mimic_rule and strong_rule:
                    prefix = f"命中语义规则 #{mimic_rule.get('id')}｜"
                elif mimic_rule:
                    prefix = "参考 1 条可能相关规则｜"
                else:
                    prefix = ""
                status = (
                    f"{prefix}云端 {c['brain_model']} · 首个可说文字 "
                    f"{(metrics['brain_first_spoken_ms'] or 0)/1000:.2f}s · 完整 {metrics['brain_total_ms']/1000:.2f}s"
                )
                LOGGER.info("[CLOUD_BRAIN_LATENCY] %s", json.dumps(metrics, ensure_ascii=False))
                self._generate_busy = False
                self.generation_finished.emit(True, answer, status)
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    body = ""
                reason = f"HTTP {getattr(exc, 'code', '')} {getattr(exc, 'reason', '')} {body}".strip()
                self._cloud_fail_or_fallback(reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
                return
            except Exception as exc:
                LOGGER.exception("云端大脑回答失败")
                reason = f"{type(exc).__name__}: {exc}"
                self._cloud_fail_or_fallback(reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
                return

        threading.Thread(target=job, name="XiaoMeiliCloudBrain", daemon=True).start()

    def _cloud_fail_or_fallback(self, reason, sent_len, user_text, persona, temperature, max_tokens, context_turns, long_term_memory):
        c = self._ccfg()
        self.cloud_status_changed.emit(f"云端异常：{reason}")
        if int(sent_len or 0) <= 0 and c.get("fallback_local") and super().ready():
            LOGGER.warning("[CLOUD_BRAIN] failed before speech, fallback local: %s", reason)
            self.spoken_stream_aborted.emit(reason)
            self._generate_busy = False
            super().ask(user_text, persona, temperature, max_tokens, context_turns, long_term_memory)
            return
        self._generate_busy = False
        self.spoken_stream_done.emit(False, "")
        self.generation_finished.emit(False, {}, f"云端回答失败：{reason}")
