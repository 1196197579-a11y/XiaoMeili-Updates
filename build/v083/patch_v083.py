# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def _extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.8.3 could not locate WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.8.3 could not locate end of WORKER_CODE literal")
    return m, quote, end, source[m.end():end]


def _replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = _extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.8.3 worker unexpectedly contains source quote delimiter")
    replacement = f"WORKER_CODE = r{quote}{worker}{quote}"
    return source[:m.start()] + replacement + source[end + len(quote):]


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"V0.8.3 expected exactly one {label}, found {count}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    source_root = Path(source_root).resolve()
    main = source_root / "app" / "src" / "main.py"
    speech = source_root / "app" / "src" / "speech_input.py"
    if not main.exists() or not speech.exists():
        raise FileNotFoundError("V0.8.3 expected V0.8.2 source files")

    main_text = main.read_text(encoding="utf-8")
    speech_text = speech.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.2"' not in main_text:
        raise RuntimeError("V0.8.3 expected APP_VERSION 0.8.2 base")

    main_text = main_text.replace('APP_VERSION = "0.8.2"', 'APP_VERSION = "0.8.3"', 1)
    main_text = main_text.replace("V0.8.2", "V0.8.3")
    speech_text = speech_text.replace("V0.8.2", "V0.8.3")

    _m, _q, _end, worker = _extract_worker_literal(speech_text)

    worker = _replace_once(
        worker,
        "import logging\nimport queue\nimport re\nimport sys\n",
        "import logging\nimport os\nimport queue\nimport re\nimport sys\nimport traceback\n",
        "worker import block",
    )

    setup_old = '''def setup_log(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=path, level=logging.INFO, encoding="utf-8", force=True,
                        format="%(asctime)s [%(levelname)s] %(message)s")
'''
    setup_new = setup_old + '''

_DESKTOP_REPORT_ONCE = set()


def _desktop_dir():
    try:
        if sys.platform == "win32":
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            # CSIDL_DESKTOPDIRECTORY = 0x10, honors redirected/OneDrive desktop.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                p = Path(buf.value)
                p.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    for root in (os.environ.get("OneDrive"), os.environ.get("USERPROFILE"), str(Path.home())):
        if not root:
            continue
        p = Path(root) / "Desktop"
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            continue
    return Path.home()


def desktop_diagnostic(code, message, log_path="", extra=""):
    code = re.sub(r"[^A-Za-z0-9_-]+", "_", str(code or "UNKNOWN"))[:48]
    if code in _DESKTOP_REPORT_ONCE:
        return ""
    _DESKTOP_REPORT_ONCE.add(code)
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = _desktop_dir() / f"小美丽语音故障日志_{stamp}_{code}.txt"
        tail = ""
        try:
            lp = Path(log_path)
            if lp.exists():
                lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\\n".join(lines[-180:])
        except Exception as exc:
            tail = f"<读取 speech_worker.log 失败: {exc}>"
        body = [
            "小美丽 V0.8.3 语音诊断日志",
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"故障代码: {code}",
            f"说明: {message}",
            f"原始日志: {log_path}",
        ]
        if extra:
            body.extend(["", "附加信息:", str(extra)])
        body.extend(["", "speech_worker.log 最后 180 行:", tail])
        target.write_text("\\n".join(body), encoding="utf-8")
        logging.error("[DESKTOP_DIAGNOSTIC] %s code=%s message=%s", target, code, message)
        return str(target)
    except Exception:
        logging.exception("[DESKTOP_DIAGNOSTIC] failed to write desktop log")
        return ""
'''
    worker = _replace_once(worker, setup_old, setup_new, "desktop diagnostic helper insertion")

    vars_old = '''    vad_cache = {}
    preroll = []
    speech = []
    active = False
    max_chunks = int(25 / 0.20)  # hard cap 25 s
'''
    vars_new = '''    vad_cache = {}
    preroll = []
    speech = []
    active = False
    noise_floor_rms = 0.002
    active_peak_rms = 0.0
    silent_chunks = 0
    active_started_at = 0.0
    max_chunks = int(25 / 0.20)  # final hard cap 25 s
    silence_end_chunks = 4       # 0.8 s at 200 ms/chunk
'''
    worker = _replace_once(worker, vars_old, vars_new, "endpoint state variables")

    empty_old = '''        else:
            logging.warning("[ASR_EMPTY] no text returned")
        return text
'''
    empty_new = '''        else:
            logging.warning("[ASR_EMPTY] no text returned")
            desktop_diagnostic(
                "ASR_EMPTY",
                f"ASR 未返回文字；reason={reason} seconds={seconds:.3f}",
                args.log,
            )
        return text
'''
    worker = _replace_once(worker, empty_old, empty_new, "ASR empty diagnostic")

    pause_old = '''                vad_cache = {}; preroll = []; speech = []; active = False
'''
    pause_new = '''                vad_cache = {}; preroll = []; speech = []; active = False
                active_peak_rms = 0.0; silent_chunks = 0; active_started_at = 0.0
'''
    worker = _replace_once(worker, pause_old, pause_new, "pause endpoint reset")

    chunk_old = '''            preroll.append(chunk)
            if len(preroll) > 3:
                preroll.pop(0)
'''
    chunk_new = '''            chunk_rms = float(np.sqrt(np.mean(np.asarray(chunk, dtype=np.float64) ** 2))) if getattr(chunk, "size", 0) else 0.0
            if not active:
                noise_floor_rms = (noise_floor_rms * 0.94) + (chunk_rms * 0.06)
            preroll.append(chunk)
            if len(preroll) > 3:
                preroll.pop(0)
'''
    worker = _replace_once(worker, chunk_old, chunk_new, "chunk RMS calculation")

    vad_exc_old = '''            except Exception as exc:
                logging.exception("VAD failed")
                emit("error", message=f"VAD 识别失败：{type(exc).__name__}: {exc}")
                events = []
'''
    vad_exc_new = '''            except Exception as exc:
                logging.exception("VAD failed")
                desktop_diagnostic(
                    "VAD_EXCEPTION",
                    f"FSMN-VAD 调用失败：{type(exc).__name__}: {exc}",
                    args.log,
                    traceback.format_exc(),
                )
                emit("error", message=f"VAD 识别失败：{type(exc).__name__}: {exc}")
                events = []
'''
    worker = _replace_once(worker, vad_exc_old, vad_exc_new, "VAD exception diagnostic")

    start_old = '''                    active = True
                    speech = list(preroll)
                    emit("state", code="hearing", label="听到你说话了")
'''
    start_new = '''                    active = True
                    speech = list(preroll)
                    active_peak_rms = max(chunk_rms, noise_floor_rms, 0.001)
                    silent_chunks = 0
                    active_started_at = time.monotonic()
                    logging.info("[ENDPOINT_START] rms=%.6f noise=%.6f", chunk_rms, noise_floor_rms)
                    emit("state", code="hearing", label="听到你说话了")
'''
    worker = _replace_once(worker, start_old, start_new, "VAD start endpoint init")

    asr_exc_old = '''                    except Exception as exc:
                        logging.exception("ASR failed")
                        emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                    emit("state", code="listening", label="等待“美丽美丽”")
'''
    asr_exc_new = '''                    except Exception as exc:
                        logging.exception("ASR failed")
                        desktop_diagnostic(
                            "ASR_EXCEPTION",
                            f"Fun-ASR-Nano 识别失败：{type(exc).__name__}: {exc}",
                            args.log,
                            traceback.format_exc(),
                        )
                        emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                    emit("state", code="listening", label="等待“美丽美丽”")
'''
    worker = _replace_once(worker, asr_exc_old, asr_exc_new, "ASR exception diagnostic")

    hardcap_anchor = '''            if active and len(speech) >= max_chunks:
'''
    fallback_block = '''            # V0.8.3: FSMN-VAD on some Windows microphone/runtime combinations emits
            # START but never emits END. Use adaptive microphone-energy silence only as
            # an ENDPOINT fallback after VAD has already confirmed speech start.
            if active:
                active_peak_rms = max(active_peak_rms, chunk_rms)
                silence_threshold = max(
                    0.0035,
                    min(0.030, noise_floor_rms * 2.8),
                    min(0.030, active_peak_rms * 0.12),
                )
                if chunk_rms <= silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_end_chunks and len(speech) >= 5:
                    elapsed = max(0.0, time.monotonic() - active_started_at)
                    logging.warning(
                        "[VAD_END_FALLBACK] no FSMN end; forcing endpoint after %.3fs "
                        "silent_chunks=%s rms=%.6f threshold=%.6f noise=%.6f peak=%.6f",
                        elapsed, silent_chunks, chunk_rms, silence_threshold,
                        noise_floor_rms, active_peak_rms,
                    )
                    active = False
                    audio = np.concatenate(speech) if speech else np.zeros(0, dtype=np.float32)
                    speech = []; preroll = []; vad_cache = {}
                    silent_chunks = 0; active_peak_rms = 0.0; active_started_at = 0.0
                    if audio.size >= 1600:
                        emit("state", code="recognizing", label="正在识别你说的话")
                        try:
                            fallback_text = recognize_and_emit(audio, "energy_silence_fallback")
                            desktop_diagnostic(
                                "VAD_END_MISSING",
                                f"FSMN-VAD 检测到开始但未返回结束；已由 V0.8.3 静音兜底收句。ASR={fallback_text!r}",
                                args.log,
                                f"elapsed={elapsed:.3f}s threshold={silence_threshold:.6f}",
                            )
                        except Exception as exc:
                            logging.exception("ASR failed after energy endpoint fallback")
                            desktop_diagnostic(
                                "ASR_EXCEPTION",
                                f"静音兜底后 ASR 失败：{type(exc).__name__}: {exc}",
                                args.log,
                                traceback.format_exc(),
                            )
                            emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                    emit("state", code="listening", label="等待“美丽美丽”")

''' + hardcap_anchor
    worker = _replace_once(worker, hardcap_anchor, fallback_block, "adaptive endpoint fallback")

    hard_exc_old = '''                except Exception as exc:
                    logging.exception("ASR failed at hard cap")
                    emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
'''
    hard_exc_new = '''                except Exception as exc:
                    logging.exception("ASR failed at hard cap")
                    desktop_diagnostic(
                        "ASR_HARD_CAP_EXCEPTION",
                        f"25 秒强制收句后 ASR 失败：{type(exc).__name__}: {exc}",
                        args.log,
                        traceback.format_exc(),
                    )
                    emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
'''
    worker = _replace_once(worker, hard_exc_old, hard_exc_new, "hard-cap exception diagnostic")

    fatal_old = '''        except Exception as exc:
            logging.exception("Speech listener failed")
            message = f"迟回语音监启失败：{type(exc).__name__}: {exc}"
            emit("error", message=message)
'''
    fatal_new = '''        except Exception as exc:
            logging.exception("Speech listener failed")
            message = f"语音监听启动失败：{type(exc).__name__}: {exc}"
            desktop_diagnostic(
                "WORKER_FATAL",
                message,
                args.log,
                traceback.format_exc(),
            )
            emit("error", message=message)
'''
    worker = _replace_once(worker, fatal_old, fatal_new, "fatal worker diagnostic")

    compile(worker, "speech_worker_v083.py", "exec")
    speech_text = _replace_worker_literal(speech_text, worker)

    main.write_text(main_text, encoding="utf-8")
    speech.write_text(speech_text, encoding="utf-8")

    py_compile.compile(str(main), doraise=True)
    py_compile.compile(str(speech), doraise=True)

    m = main.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")
    for token in (
        'APP_VERSION = "0.8.3"',
    ):
        if token not in m:
            raise RuntimeError(f"V0.8.3 main verification failed: {token}")
    for token in (
        "VAD_END_FALLBACK",
        "energy_silence_fallback",
        "silence_end_chunks = 4",
        "desktop_diagnostic(",
        "小美丽语音故障日志_",
        "ASR_EMPTY",
        "VAD_END_MISSING",
        "WORKER_FATAL",
    ):
        if token not in sp:
            raise RuntimeError(f"V0.8.3 speech verification failed: {token}")

    print("Patched XiaoMeili source to V0.8.3 adaptive VAD endpoint + desktop diagnostics")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v083.py <source_root>")
    patch(Path(sys.argv[1]))
