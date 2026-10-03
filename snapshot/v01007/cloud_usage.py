# -*- coding: utf-8 -*-
"""Local cloud-usage ledger for XiaoMeili V0.10.0.7.

The ledger records only usage values already returned by Alibaba Cloud APIs.
It never sends an extra API request just to calculate cost.
Displayed currency is an estimate based on public Beijing list prices and can
be lower on the real bill because of free quota, discounts or promotions.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()


def _data_root() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    else:
        root = Path.home() / ".xiaomeili"
    root.mkdir(parents=True, exist_ok=True)
    return root


ROOT = _data_root() / "cloud"
ROOT.mkdir(parents=True, exist_ok=True)
LEDGER = ROOT / "cloud_usage.json"

# China (Beijing) public list prices checked for the V0.10.0.7 build.
# qwen3-8b: input 0.5 CNY / 1M tokens, output 2 CNY / 1M tokens.
# qwen-audio-3.1-tts-flash: input 1.5 CNY / 1M tokens,
# output 12 CNY / 1M tokens.
BRAIN_INPUT_CNY_PER_M = 0.5
BRAIN_OUTPUT_CNY_PER_M = 2.0
TTS_INPUT_CNY_PER_M = 1.5
TTS_OUTPUT_CNY_PER_M = 12.0


def _blank():
    return {
        "brain_requests": 0,
        "brain_dialogue_requests": 0,
        "brain_test_requests": 0,
        "brain_input_tokens": 0,
        "brain_output_tokens": 0,
        "brain_cost_cny": 0.0,
        "tts_requests": 0,
        "tts_dialogue_requests": 0,
        "tts_preview_requests": 0,
        "tts_input_tokens": 0,
        "tts_output_tokens": 0,
        "tts_cost_cny": 0.0,
        "tts_usage_missing": 0,
    }


def _normalize_bucket(value):
    out = _blank()
    if isinstance(value, dict):
        for k in out:
            try:
                if isinstance(out[k], float):
                    out[k] = float(value.get(k, out[k]) or 0.0)
                else:
                    out[k] = int(value.get(k, out[k]) or 0)
            except Exception:
                pass
    return out


def _read():
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"version": 1, "months": {}}


def _write(data):
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = LEDGER.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(LEDGER)


_SESSION = _blank()
_SESSION_STARTED = datetime.now().isoformat(timespec="seconds")


def _month_key():
    return datetime.now().strftime("%Y-%m")


def _add(bucket, key, value):
    bucket[key] = bucket.get(key, 0) + value


def record_brain_usage(input_tokens: int, output_tokens: int, tag: str = "dialogue") -> dict:
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    tag = str(tag or "dialogue").lower()
    is_test = "test" in tag or "connection" in tag
    is_dialogue = not is_test
    cost = inp * BRAIN_INPUT_CNY_PER_M / 1_000_000.0 + out * BRAIN_OUTPUT_CNY_PER_M / 1_000_000.0
    with _LOCK:
        _SESSION["brain_requests"] += 1
        _SESSION["brain_dialogue_requests"] += int(is_dialogue)
        _SESSION["brain_test_requests"] += int(is_test)
        _SESSION["brain_input_tokens"] += inp
        _SESSION["brain_output_tokens"] += out
        _SESSION["brain_cost_cny"] += cost
        data = _read()
        months = data.setdefault("months", {})
        bucket = _normalize_bucket(months.get(_month_key()))
        bucket["brain_requests"] += 1
        bucket["brain_dialogue_requests"] += int(is_dialogue)
        bucket["brain_test_requests"] += int(is_test)
        bucket["brain_input_tokens"] += inp
        bucket["brain_output_tokens"] += out
        bucket["brain_cost_cny"] += cost
        months[_month_key()] = bucket
        _write(data)
    return snapshot()


def record_tts_usage(input_tokens: int | None, output_tokens: int | None, tag: str = "") -> dict:
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    missing = input_tokens is None or output_tokens is None
    cost = inp * TTS_INPUT_CNY_PER_M / 1_000_000.0 + out * TTS_OUTPUT_CNY_PER_M / 1_000_000.0
    tag = str(tag or "")
    is_preview = "preview" in tag.lower()
    is_dialogue = tag == "dialogue_answer" or tag == "dialogue"
    with _LOCK:
        _SESSION["tts_requests"] += 1
        _SESSION["tts_input_tokens"] += inp
        _SESSION["tts_output_tokens"] += out
        _SESSION["tts_cost_cny"] += cost
        _SESSION["tts_preview_requests"] += int(is_preview)
        _SESSION["tts_dialogue_requests"] += int(is_dialogue)
        _SESSION["tts_usage_missing"] += int(missing)
        data = _read()
        months = data.setdefault("months", {})
        bucket = _normalize_bucket(months.get(_month_key()))
        bucket["tts_requests"] += 1
        bucket["tts_input_tokens"] += inp
        bucket["tts_output_tokens"] += out
        bucket["tts_cost_cny"] += cost
        bucket["tts_preview_requests"] += int(is_preview)
        bucket["tts_dialogue_requests"] += int(is_dialogue)
        bucket["tts_usage_missing"] += int(missing)
        months[_month_key()] = bucket
        _write(data)
    return snapshot()


def snapshot() -> dict:
    with _LOCK:
        data = _read()
        month = _normalize_bucket(data.get("months", {}).get(_month_key()))
        session = dict(_SESSION)
        session["total_cost_cny"] = float(session["brain_cost_cny"]) + float(session["tts_cost_cny"])
        session["dialogue_turns"] = max(int(session["brain_dialogue_requests"]), int(session["tts_dialogue_requests"]))
        month["total_cost_cny"] = float(month["brain_cost_cny"]) + float(month["tts_cost_cny"])
        month["dialogue_turns"] = max(int(month["brain_dialogue_requests"]), int(month["tts_dialogue_requests"]))
        return {
            "session_started": _SESSION_STARTED,
            "session": session,
            "month_key": _month_key(),
            "month": month,
        }


def format_summary() -> str:
    snap = snapshot()
    s = snap["session"]
    m = snap["month"]
    missing = int(s.get("tts_usage_missing", 0))
    note = f" · {missing}次TTS未返回Token用量" if missing else ""
    return (
        f"本场：云端对话 {s['dialogue_turns']} 次 · "
        f"大脑 ¥{s['brain_cost_cny']:.4f} · TTS ¥{s['tts_cost_cny']:.4f} · "
        f"合计 ¥{s['total_cost_cny']:.4f}\n"
        f"本月 {snap['month_key']}：大脑 ¥{m['brain_cost_cny']:.4f} · "
        f"TTS ¥{m['tts_cost_cny']:.4f} · 合计 ¥{m['total_cost_cny']:.4f}{note}"
    )
