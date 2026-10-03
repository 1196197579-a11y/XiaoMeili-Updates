# -*- coding: utf-8 -*-
"""Dual-engine voice service for XiaoMeili V0.10.0.7.

Cloud mode uses Alibaba Cloud Qwen-Audio-3.1-TTS-Flash with the user's cloned
XiaoMeili voice. Text from the streaming Qwen3-8B brain is forwarded to the TTS
SDK incrementally, while PCM audio is played as soon as the first binary chunk
arrives. The existing local Qwen3-TTS runtime is kept unchanged as a manual or
emergency fallback.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time

from PySide6.QtCore import Signal

from voice_qwen import VoiceService as LocalVoiceService, PRESETS
from cloud_support import cloud_cfg, load_api_key, audio_tts_ws_url
from cloud_usage import record_tts_usage

LOGGER = logging.getLogger("XiaoMeili")

try:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat
    DASHSCOPE_OK = True
    DASHSCOPE_ERROR = ""
except Exception as exc:
    dashscope = None
    SpeechSynthesizer = None
    ResultCallback = object
    AudioFormat = None
    DASHSCOPE_OK = False
    DASHSCOPE_ERROR = f"{type(exc).__name__}: {exc}"


class _AudioCallback(ResultCallback):
    """Callback for one Qwen-Audio TTS task."""

    def __init__(self, service, ctx):
        super().__init__()
        self.service = service
        self.ctx = ctx

    def on_open(self):
        self.ctx["socket_open_at"] = time.perf_counter()

    def on_data(self, data: bytes) -> None:
        self.service._cloud_audio(self.ctx, data)

    def on_event(self, message) -> None:
        try:
            obj = json.loads(message) if isinstance(message, str) else (message or {})
            if not isinstance(obj, dict):
                return
            header = obj.get("header") or {}
            payload = obj.get("payload") or {}
            usage = payload.get("usage")
            if isinstance(usage, dict):
                # task-finished contains cumulative usage. sentence-end may also
                # contain usage; always keep the largest values observed.
                with self.service._cloud_lock:
                    old = self.ctx.setdefault("usage", {})
                    for key in ("input_tokens", "output_tokens", "total_tokens", "characters"):
                        if usage.get(key) is not None:
                            try:
                                old[key] = max(int(old.get(key) or 0), int(usage.get(key) or 0))
                            except Exception:
                                pass
            if str(header.get("event") or "") == "task-finished":
                self.ctx["task_finished"] = True
        except Exception:
            LOGGER.debug("解析 Qwen-Audio TTS 事件失败", exc_info=True)

    def on_complete(self) -> None:
        self.ctx["sdk_complete_at"] = time.perf_counter()
        self.ctx["complete_event"].set()

    def on_error(self, message: str) -> None:
        self.ctx["sdk_error"] = str(message or "未知 TTS 错误")
        self.ctx["complete_event"].set()

    def on_close(self) -> None:
        self.ctx["socket_closed_at"] = time.perf_counter()


class VoiceService(LocalVoiceService):
    cloud_latency_updated = Signal(object)
    cloud_status_changed = Signal(str)

    CLOUD_VOICE_SELECTOR_ID = "cloud_xiaomeili_clone"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_cfg = {}
        self._cloud_lock = threading.RLock()
        self._cloud_active = None
        self._last_cloud_latency = {}

    def configure(self, cfg):
        self._app_cfg = cfg if isinstance(cfg, dict) else {}
        self.cloud_status_changed.emit(self.component_status())
        # No paid TTS request is made here. Qwen-Audio creates the real task only
        # when XiaoMeili has text to speak.

    def _ccfg(self):
        return cloud_cfg(self._app_cfg)

    def cloud_mode(self):
        return self._ccfg().get("mode") != "local"

    def cloud_ready(self):
        return self.cloud_mode() and bool(load_api_key()) and bool(DASHSCOPE_OK)

    def local_ready(self):
        return super().ready()

    def ready(self):
        c = self._ccfg()
        if c["mode"] != "local":
            if load_api_key() and DASHSCOPE_OK:
                return True
            if c.get("fallback_local"):
                return super().ready()
            return False
        return super().ready()

    def component_status(self):
        c = self._ccfg()
        if c["mode"] != "local":
            if not DASHSCOPE_OK:
                if c.get("fallback_local") and super().ready():
                    return f"云端 TTS 依赖不可用（{DASHSCOPE_ERROR}）；可回退本地 Qwen3-TTS"
                return f"云端 TTS 依赖不可用：{DASHSCOPE_ERROR}"
            if load_api_key():
                return "云端 Qwen-Audio-3.1-TTS-Flash · 小美丽复刻音色 · 待命（启动不产生TTS调用）"
            if c.get("fallback_local") and super().ready():
                return "云端模式尚未保存 API Key；当前可回退本地 Qwen3-TTS"
            return "云端模式尚未保存阿里云 API Key"
        return super().component_status()

    def display_name(self, voice_id):
        if str(voice_id or "") == self.CLOUD_VOICE_SELECTOR_ID:
            return "小美丽｜云端复刻音色"
        return super().display_name(voice_id)

    def load_voices_async(self):
        if self.cloud_ready():
            self.voices_ready.emit([self.CLOUD_VOICE_SELECTOR_ID])
            return
        super().load_voices_async()

    def _local_fallback_voice(self, voice_id):
        vid = str(voice_id or "")
        if vid in PRESETS:
            return vid
        if self.design_ready():
            return "design_xiaomeili_cool"
        if super().ready():
            return "vivian_cool"
        return vid

    def warm_up_async(self):
        # Qwen-Audio's public SDK establishes the actual synthesis task when
        # text is submitted. Do not send dummy text just to prewarm because that
        # would create billable usage. begin_cloud_stream() starts its worker
        # before Qwen3-8B answers so local preparation happens in parallel.
        if self.cloud_ready():
            self.cloud_status_changed.emit(self.component_status())
            return
        if self._ccfg().get("mode") == "local":
            super().warm_up_async()

    def last_cloud_latency(self):
        return dict(self._last_cloud_latency)

    def cloud_stream_in_progress(self, tag=None):
        with self._cloud_lock:
            ctx = self._cloud_active
            if not ctx or ctx.get("finished") or ctx.get("aborted"):
                return False
            if tag is None:
                return True
            return str(ctx.get("tag") or "") == str(tag)

    def begin_cloud_stream(self, output_device="default", tag="dialogue_answer", speed=1.0, extra_instruct=""):
        if not self.cloud_ready():
            return False
        with self._cloud_lock:
            if self._cloud_active and not self._cloud_active.get("finished") and not self._cloud_active.get("aborted"):
                return False
            ctx = {
                "tag": str(tag or "dialogue_answer"),
                "output_device": str(output_device or "default"),
                "speed": max(0.5, min(2.0, float(speed or 1.0))),
                "extra_instruct": str(extra_instruct or "").strip(),
                "started": time.perf_counter(),
                "first_text_sent_at": None,
                "first_audio_at": None,
                "audio_bytes": 0,
                "stream": None,
                "text": "",
                "pending": "",
                "finished": False,
                "aborted": False,
                "preview": False,
                "queue": queue.Queue(),
                "complete_event": threading.Event(),
                "usage": {},
                "sdk_error": "",
                "task_finished": False,
                "tts": None,
            }
            self._cloud_active = ctx

        threading.Thread(
            target=self._cloud_worker,
            args=(ctx,),
            name="XiaoMeiliQwenAudioTts",
            daemon=True,
        ).start()
        return True

    def _cloud_worker(self, ctx):
        try:
            if not DASHSCOPE_OK:
                raise RuntimeError(f"DashScope SDK 不可用：{DASHSCOPE_ERROR}")
            key = load_api_key()
            if not key:
                raise RuntimeError("尚未保存阿里云 API Key")
            c = self._ccfg()
            dashscope.api_key = key
            dashscope.base_websocket_api_url = audio_tts_ws_url(c.get("brain_base_url"))
            instruction = str(ctx.get("extra_instruct") or c.get("tts_instruction") or "").strip()
            cb = _AudioCallback(self, ctx)
            kwargs = dict(
                model=c["tts_model"],
                voice=c["tts_voice"],
                format=AudioFormat.PCM_22050HZ_MONO_16BIT,
                volume=50,
                speech_rate=float(ctx.get("speed") or 1.0),
                pitch_rate=1.0,
                callback=cb,
            )
            if instruction:
                kwargs["instruction"] = instruction
            try:
                tts = SpeechSynthesizer(**kwargs)
            except TypeError:
                # DashScope SDK minor versions have exposed instruction either
                # as a direct constructor argument or through additional_params.
                # Keep both paths so the frozen V0.10.0.7 build is not coupled
                # to one exact SDK signature.
                instruction_value = kwargs.pop("instruction", "")
                if instruction_value:
                    kwargs["additional_params"] = {"instruction": instruction_value}
                tts = SpeechSynthesizer(**kwargs)
            ctx["tts"] = tts

            while True:
                item = ctx["queue"].get()
                if isinstance(item, tuple):
                    op = item[0]
                    if op == "abort":
                        ctx["aborted"] = True
                        try:
                            tts.streaming_cancel()
                        except Exception:
                            pass
                        return
                    if op == "finish":
                        break
                text = str(item or "")
                if not text:
                    continue
                if ctx.get("first_text_sent_at") is None:
                    ctx["first_text_sent_at"] = time.perf_counter()
                tts.streaming_call(text)

            if ctx.get("aborted"):
                return
            tts.streaming_complete()
            # The public SDK says first-package delay becomes valid after the
            # task completes. Keep both that pure-TTS metric and our end-to-end
            # metric from begin_cloud_stream() to first PCM audio.
            try:
                ctx["sdk_first_package_ms"] = float(tts.get_first_package_delay())
            except Exception:
                ctx["sdk_first_package_ms"] = None
            try:
                ctx["request_id"] = str(tts.get_last_request_id() or "")
            except Exception:
                ctx["request_id"] = ""
            if ctx.get("sdk_error"):
                raise RuntimeError(ctx.get("sdk_error"))
            self._complete_cloud_ctx(ctx, True, "播放完成")
        except Exception as exc:
            LOGGER.exception("Qwen-Audio 云端 TTS 失败")
            self._cloud_session_error(ctx, f"{type(exc).__name__}: {exc}")
        finally:
            try:
                dashscope.api_key = None
            except Exception:
                pass

    def cloud_stream_append(self, text):
        chunk = str(text or "")
        if not chunk:
            return
        with self._cloud_lock:
            ctx = self._cloud_active
            if not ctx or ctx.get("finished") or ctx.get("aborted"):
                return
            ctx["text"] = str(ctx.get("text") or "") + chunk
            ctx["pending"] = str(ctx.get("pending") or "") + chunk
            pending = str(ctx.get("pending") or "")
            # Submit early to start the WebSocket/TTS task, but keep very tiny
            # single-character LLM deltas together. Qwen-Audio performs its own
            # sentence segmentation server-side.
            flush = len(pending) >= 3 or bool(re.search(r"[，。！？!?；;：:]$", pending))
            if not flush:
                return
            ctx["pending"] = ""
            q = ctx["queue"]
        q.put(pending)

    def cloud_stream_finish(self, ok=True, final_text=""):
        with self._cloud_lock:
            ctx = self._cloud_active
            if not ctx or ctx.get("finished") or ctx.get("aborted"):
                return
            if final_text:
                current = str(ctx.get("text") or "")
                final_text = str(final_text)
                if final_text.startswith(current):
                    tail = final_text[len(current):]
                    if tail:
                        ctx["text"] = final_text
                        ctx["pending"] = str(ctx.get("pending") or "") + tail
            if not ok:
                ctx["aborted"] = True
                q = ctx["queue"]
                pending = ""
            else:
                q = ctx["queue"]
                pending = str(ctx.get("pending") or "")
                ctx["pending"] = ""
        if not ok:
            q.put(("abort", "brain failed"))
            return
        if pending:
            q.put(pending)
        q.put(("finish", ""))

    def cloud_stream_abort(self, reason=""):
        with self._cloud_lock:
            ctx = self._cloud_active
            if not ctx or ctx.get("finished") or ctx.get("aborted"):
                return
            ctx["aborted"] = True
            q = ctx.get("queue")
            stream = ctx.get("stream")
            if self._cloud_active is ctx:
                self._cloud_active = None
        if q:
            q.put(("abort", str(reason or "")))
        try:
            if stream:
                stream.abort(ignore_errors=True)
                stream.close(ignore_errors=True)
        except Exception:
            pass
        LOGGER.warning("[CLOUD_TTS] stream aborted: %s", reason)

    def _cloud_audio(self, ctx, data: bytes):
        if not ctx or ctx.get("aborted") or ctx.get("finished") or not data:
            return
        try:
            if ctx.get("first_audio_at") is None:
                ctx["first_audio_at"] = time.perf_counter()
            stream = ctx.get("stream")
            if stream is None:
                import sounddevice as sd
                stream = sd.RawOutputStream(
                    samplerate=22050,
                    channels=1,
                    dtype="int16",
                    device=self._device_index(ctx.get("output_device", "default")),
                    blocksize=0,
                )
                stream.start()
                ctx["stream"] = stream
            if not ctx.get("playback_started"):
                ctx["playback_started"] = True
                shown_text = str(ctx.get("text") or "").strip() or "小美丽正在说话…"
                duration_ms = max(2600, min(9000, len(shown_text) * 150 + 2200))
                self.playback_started.emit(shown_text, int(duration_ms), str(ctx.get("tag") or "dialogue"))
            stream.write(data)
            ctx["audio_bytes"] = int(ctx.get("audio_bytes") or 0) + len(data)
        except Exception as exc:
            self._cloud_session_error(ctx, f"audio output: {type(exc).__name__}: {exc}")

    def _cloud_session_error(self, ctx, error):
        if not ctx or ctx.get("finished"):
            return
        LOGGER.warning("[CLOUD_TTS] session error: %s", error)
        self._complete_cloud_ctx(ctx, False, f"云端播报失败：{error}")

    def _complete_cloud_ctx(self, ctx, ok, message):
        with self._cloud_lock:
            if ctx.get("finished"):
                return
            ctx["finished"] = True
            if self._cloud_active is ctx:
                self._cloud_active = None
            stream = ctx.get("stream")
        try:
            if stream:
                time.sleep(0.05)
                stream.stop(ignore_errors=True)
                stream.close(ignore_errors=True)
        except Exception:
            pass

        usage = dict(ctx.get("usage") or {})
        inp = usage.get("input_tokens")
        out = usage.get("output_tokens")
        if ok:
            try:
                record_tts_usage(inp if inp is not None else None, out if out is not None else None, str(ctx.get("tag") or ""))
            except Exception:
                LOGGER.warning("记录云端TTS用量失败", exc_info=True)

        first = ctx.get("first_audio_at")
        started = ctx.get("started")
        first_text = ctx.get("first_text_sent_at")
        metrics = {
            "tts_first_audio_ms": int((first - started) * 1000) if first and started else None,
            "tts_from_first_text_ms": int((first - first_text) * 1000) if first and first_text else None,
            "tts_sdk_first_package_ms": ctx.get("sdk_first_package_ms"),
            "tts_input_tokens": int(inp or 0),
            "tts_output_tokens": int(out or 0),
            "tts_audio_bytes": int(ctx.get("audio_bytes") or 0),
            "tag": str(ctx.get("tag") or ""),
            "ok": bool(ok),
            "request_id": str(ctx.get("request_id") or ""),
        }
        self._last_cloud_latency = dict(metrics)
        self.cloud_latency_updated.emit(dict(metrics))
        self.cloud_status_changed.emit(self.component_status())
        if ctx.get("preview"):
            self.synthesis_finished.emit(bool(ok), "云端复刻音色试听完成" if ok else str(message))
        self.playback_finished.emit(bool(ok), str(message), str(ctx.get("tag") or "dialogue"))

    def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue", extra_instruct=""):
        if self.cloud_ready():
            text = str(text or "").strip()
            if not text:
                self.playback_finished.emit(False, "没有可播报的文字。", str(tag or "dialogue"))
                return
            if not self.begin_cloud_stream(output_device=output_device, tag=tag, speed=speed, extra_instruct=extra_instruct):
                self.playback_finished.emit(False, "上一条云端语音还在生成或播放，请稍等。", str(tag or "dialogue"))
                return
            self.cloud_stream_append(text)
            self.cloud_stream_finish(True, text)
            return

        if self._ccfg().get("mode") != "local" and self._ccfg().get("fallback_local"):
            voice_id = self._local_fallback_voice(voice_id)
        super().speak(text, voice_id, speed, output_device, tag, extra_instruct)

    def preview(self, text, voice_id, speed=1.0, output_device="default", extra_instruct=""):
        if self.cloud_ready():
            text = str(text or "").strip()
            if not text:
                self.synthesis_finished.emit(False, "请输入试听文字。")
                return
            self.synthesis_started.emit()
            if not self.begin_cloud_stream(output_device=output_device, tag="cloud_preview", speed=speed, extra_instruct=extra_instruct):
                self.synthesis_finished.emit(False, "上一条云端语音还在生成或播放，请稍等。")
                return
            with self._cloud_lock:
                if self._cloud_active:
                    self._cloud_active["preview"] = True
            self.cloud_stream_append(text)
            self.cloud_stream_finish(True, text)
            return

        if self._ccfg().get("mode") != "local" and self._ccfg().get("fallback_local"):
            voice_id = self._local_fallback_voice(voice_id)
        super().preview(text, voice_id, speed, output_device, extra_instruct)

    def warm_phrase_cache(self, phrases, voice_id, speed=1.0, phrase_styles=None):
        if self.cloud_ready():
            self.phrase_cache_ready.emit(True, "云端复刻音色已待命；固定短句无需占用本地显存缓存。")
            return
        super().warm_phrase_cache(phrases, voice_id, speed, phrase_styles)

    def abort_playback(self, reason="voice_interrupt"):
        try:
            self.cloud_stream_abort(str(reason or "voice_interrupt"))
        except Exception:
            pass
        try:
            super().shutdown()
        except Exception:
            pass

    def shutdown(self):
        with self._cloud_lock:
            active = self._cloud_active
            self._cloud_active = None
        if active and not active.get("finished"):
            try:
                active["aborted"] = True
                active["queue"].put(("abort", "shutdown"))
            except Exception:
                pass
            try:
                stream = active.get("stream")
                if stream:
                    stream.abort(ignore_errors=True)
                    stream.close(ignore_errors=True)
            except Exception:
                pass
        super().shutdown()
