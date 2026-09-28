# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import shutil
import sys
from pathlib import Path


def replace_method_until(text: str, start_token: str, end_token: str, replacement: str, label: str) -> str:
    start = text.find(start_token)
    if start < 0:
        raise RuntimeError(f"V0.8.9.2 missing start anchor: {label}")
    end = text.find(end_token, start + len(start_token))
    if end < 0:
        raise RuntimeError(f"V0.8.9.2 missing end anchor: {label}")
    return text[:start] + replacement + text[end:]


def extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.8.9.2 could not locate WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.8.9.2 could not locate WORKER_CODE end")
    return m, quote, end, source[m.end():end]


def replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.8.9.2 worker contains delimiter")
    return source[:m.start()] + f"WORKER_CODE = r{quote}{worker}{quote}" + source[end + len(quote):]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.9.1"' not in s:
        raise RuntimeError("V0.8.9.2 expected APP_VERSION 0.8.9.1 base")
    s = s.replace('APP_VERSION = "0.8.9.1"', 'APP_VERSION = "0.8.9.2"', 1)
    s = s.replace("V0.8.9.1｜", "V0.8.9.2｜", 1)
    # Favorites added a seventh navigation section; keep the frozen UI self-test in sync.\n    s = s.replace('raise RuntimeError(f"expected 6 in-layout theme buttons, got {len(theme_buttons)}")', 'raise RuntimeError(f"expected 7 in-layout theme buttons, got {len(theme_buttons)}")', 1)\n
    import_anchor = "from speech_input import SpeechInputService\n"
    if import_anchor not in s:
        raise RuntimeError("V0.8.9.2 speech import anchor missing")
    if "from ndm_bridge import test_connection as ndm_test_connection" not in s:
        s = s.replace(
            import_anchor,
            import_anchor
            + "from ndm_bridge import test_connection as ndm_test_connection, download_and_import as ndm_download_and_import\n",
            1,
        )

    dirs_anchor = '''UPDATE_DIR = USER / "updates"\nUPDATE_DIR.mkdir(parents=True, exist_ok=True)\n'''
    if dirs_anchor not in s:
        raise RuntimeError("V0.8.9.2 update-dir anchor missing")
    dirs_new = '''UPDATE_DIR = USER / "updates"\nUPDATE_DIR.mkdir(parents=True, exist_ok=True)\nUPDATE_LOG_DIR = LOG_DIR / "update"\nDIAGNOSTIC_DIR = LOG_DIR / "diagnostics"\nAPP_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "app"\nUPDATE_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "update"\nSTORAGE_DIAGNOSTIC_DIR = DIAGNOSTIC_DIR / "storage"\nfor _dir in (UPDATE_LOG_DIR, DIAGNOSTIC_DIR, APP_DIAGNOSTIC_DIR, UPDATE_DIAGNOSTIC_DIR, STORAGE_DIAGNOSTIC_DIR):\n    _dir.mkdir(parents=True, exist_ok=True)\n'''
    s = s.replace(dirs_anchor, dirs_new, 1)

    old_error = 'DESKTOP_ERROR_LOG = desktop_dir() / "小美丽错误日志_请上传给ChatGPT.txt"'
    if old_error not in s:
        raise RuntimeError("V0.8.9.2 desktop error path anchor missing")
    s = s.replace(
        old_error,
        'DESKTOP_ERROR_LOG = APP_DIAGNOSTIC_DIR / "xiaomeili_errors.log"  # compatibility name; no longer on Desktop',
        1,
    )
    s = s.replace(
        '"""Every ERROR+ also leaves one easy-to-find desktop report for the user to upload."""',
        '"""Mirror ERROR+ into the internal diagnostics folder; never litter the Desktop."""',
        1,
    )
    s = s.replace(
        'f"错误已自动保存到桌面：\\n{DESKTOP_ERROR_LOG}\\n\\n{exc}"',
        'f"错误诊断已保存到：\\n{DESKTOP_ERROR_LOG}\\n\\n{exc}"',
        1,
    )

    s = s.replace(
        'desktop_log = desktop_dir() / "小美丽_D盘迁移日志_请上传给ChatGPT.txt"',
        'desktop_log = STORAGE_DIAGNOSTIC_DIR / f"migration_{time.strftime(\'%Y%m%d_%H%M%S\')}.log"',
        1,
    )
    s = s.replace(
        '"如果桌面生成了「小美丽_D盘迁移日志_请上传给ChatGPT.txt」，请直接上传给我。",',
        'f"迁移诊断会保存在：{STORAGE_DIAGNOSTIC_DIR}",',
        1,
    )

    install_method = r'''    def install_latest_async(self):
        manifest = self._latest_manifest
        if not isinstance(manifest, dict):
            self.check_finished.emit(False, None, "请先检查更新。")
            return
        if self._busy:
            return
        self._busy = True

        def job():
            try:
                version = str(manifest.get("version", "")).strip()
                url = str(manifest.get("package_url", "")).strip()
                expected = str(manifest.get("sha256", "") or "").strip().lower()
                try:
                    expected_bytes = max(0, int(manifest.get("package_size", 0) or 0))
                except Exception:
                    expected_bytes = 0

                package = UPDATE_DIR / f"XiaoMeili_{version}_update.zip"
                part = package.with_suffix(".zip.part")
                UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                UPDATE_LOG_DIR.mkdir(parents=True, exist_ok=True)
                UPDATE_DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)

                try:
                    part.unlink(missing_ok=True)
                    package.unlink(missing_ok=True)
                except Exception:
                    pass

                def verify_download(path_obj: Path):
                    if not path_obj.exists() or path_obj.stat().st_size < 5 * 1024 * 1024:
                        raise RuntimeError("更新包不存在或文件尺寸明显异常")
                    actual = self._sha256(path_obj)
                    if expected and actual != expected:
                        raise RuntimeError(
                            f"SHA-256 不一致：期望 {expected}，实际 {actual}，"
                            f"本次文件 {path_obj.stat().st_size} 字节"
                        )
                    with zipfile.ZipFile(path_obj, "r") as zf:
                        bad = zf.testzip()
                        if bad:
                            raise RuntimeError(f"ZIP 内部文件损坏：{bad}")
                        names = {Path(x).name.lower() for x in zf.namelist()}
                        if "xiaomeili.exe" not in names:
                            raise RuntimeError("ZIP 中没有 XiaoMeili.exe")
                    return actual

                download_ok = False
                source_name = ""
                last_detail = ""
                last_actual = ""

                brain_cfg = self.cfg.get("brain", {}) if isinstance(self.cfg.get("brain"), dict) else {}
                mode = str(brain_cfg.get("download_mode", "ndm") or "ndm").strip().lower()
                ndm_dir_raw = str(brain_cfg.get("ndm_download_dir") or (Path.home() / "Downloads")).strip()
                ndm_dir = Path(ndm_dir_raw) if ndm_dir_raw else Path.home() / "Downloads"

                if mode == "ndm" and ndm_dir.exists():
                    try:
                        ok, ndm_msg = ndm_test_connection(timeout=2.5)
                    except Exception as exc:
                        ok, ndm_msg = False, f"NDM 检测异常：{type(exc).__name__}: {exc}"
                    if ok:
                        try:
                            self.progress_changed.emit(2, f"已连接 NDM，正在发送 V{version} 更新任务…")

                            def ndm_note(message, done=0, total=0, speed_bps=0):
                                try:
                                    done = max(0, int(done or 0))
                                    total = max(0, int(total or 0))
                                    speed_bps = max(0, float(speed_bps or 0))
                                except Exception:
                                    done, total, speed_bps = 0, 0, 0.0
                                effective_total = total or expected_bytes
                                if effective_total > 0 and done > 0:
                                    pct = 3 + int(min(1.0, done / effective_total) * 91)
                                else:
                                    pct = 5
                                speed = f" · {speed_bps/1024/1024:.1f} MB/s" if speed_bps > 0 else ""
                                self.progress_changed.emit(
                                    max(2, min(94, pct)),
                                    f"NDM 下载 V{version}｜{message}{speed}",
                                )

                            ndm_download_and_import(
                                url=url,
                                filename=package.name,
                                download_root=ndm_dir,
                                destination=part,
                                min_bytes=5 * 1024 * 1024,
                                expected_bytes=expected_bytes,
                                progress_cb=ndm_note,
                                timeout_seconds=6 * 3600,
                            )
                            self.progress_changed.emit(95, "NDM 下载完成，正在校验 SHA-256 与 ZIP…")
                            last_actual = verify_download(part)
                            part.replace(package)
                            download_ok = True
                            source_name = "NDM"
                            LOGGER.info("更新包通过 NDM 下载并完成校验 | version=%s | sha256=%s", version, last_actual)
                        except Exception as exc:
                            last_detail = f"NDM 下载/校验失败：{type(exc).__name__}: {exc}"
                            LOGGER.warning("%s；自动回退内置下载器", last_detail, exc_info=True)
                            try:
                                part.unlink(missing_ok=True)
                            except Exception:
                                pass
                            self.progress_changed.emit(0, "NDM 未能完成本次更新，自动切换小美丽内置下载器…")
                    else:
                        LOGGER.info("NDM 当前不可用，自动使用内置下载器：%s", ndm_msg)
                        self.progress_changed.emit(0, "NDM 未连接，自动使用小美丽内置下载器…")
                elif mode == "ndm":
                    LOGGER.info("NDM 下载目录无效，自动使用内置下载器：%s", ndm_dir)
                    self.progress_changed.emit(0, "NDM 下载目录无效，自动使用小美丽内置下载器…")

                if not download_ok:
                    for attempt in range(1, 4):
                        try:
                            part.unlink(missing_ok=True)
                        except Exception:
                            pass
                        sep = "&" if "?" in url else "?"
                        attempt_url = (
                            url if attempt == 1
                            else f"{url}{sep}xm_retry={version}-{attempt}-{expected[:12]}-{int(time.time())}"
                        )
                        headers = {
                            "User-Agent": f"XiaoMeili/{APP_VERSION}",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache",
                            "Accept-Encoding": "identity",
                        }
                        try:
                            req = urllib.request.Request(attempt_url, headers=headers)
                            self.progress_changed.emit(0, f"内置下载器正在下载 V{version}（第 {attempt}/3 次）…")
                            with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as f:
                                status = int(getattr(resp, "status", 200) or 200)
                                if status not in (200, 206):
                                    raise RuntimeError(f"HTTP {status}")
                                total = int(resp.headers.get("Content-Length") or 0)
                                done = 0
                                while True:
                                    chunk = resp.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    done += len(chunk)
                                    pct = int(done * 94 / total) if total else 0
                                    self.progress_changed.emit(
                                        max(0, min(94, pct)),
                                        f"内置下载器 V{version}（第 {attempt}/3 次）… {done/1024/1024:.1f} MB",
                                    )
                                f.flush()
                                try:
                                    os.fsync(f.fileno())
                                except Exception:
                                    pass
                            if total and done != total:
                                raise RuntimeError(f"下载不完整：收到 {done} 字节，服务器声明 {total} 字节")
                            self.progress_changed.emit(95, "下载完成，正在校验 SHA-256 与 ZIP…")
                            last_actual = verify_download(part)
                            part.replace(package)
                            download_ok = True
                            source_name = "内置下载器"
                            break
                        except Exception as exc:
                            last_detail = f"第 {attempt}/3 次失败：{type(exc).__name__}: {exc}"
                            LOGGER.warning("更新内置下载失败 | %s", last_detail, exc_info=True)
                            try:
                                part.unlink(missing_ok=True)
                            except Exception:
                                pass
                            if attempt < 3:
                                time.sleep(1.2)

                if not download_ok:
                    raise RuntimeError(
                        "更新包下载/校验失败。"
                        + (f" 最后一次实际 SHA-256：{last_actual}。" if last_actual else "")
                        + (f" {last_detail}" if last_detail else "")
                        + f" 详细日志保存在 {UPDATE_LOG_DIR}。"
                    )

                helper = Path(resource("assets/update_helper.ps1"))
                if not helper.exists():
                    raise FileNotFoundError(f"更新助手缺失：{helper}")
                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行覆盖更新，请在正式 XiaoMeili.exe 中测试。")

                target = Path(sys.executable).parent
                exe_name = Path(sys.executable).name
                updater_log = UPDATE_LOG_DIR / "updater.log"
                runtime_helper = UPDATE_DIR / "update_helper_runtime.ps1"
                shutil.copy2(helper, runtime_helper)
                args = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(runtime_helper),
                    "-Package", str(package),
                    "-Target", str(target),
                    "-ExeName", exe_name,
                    "-ParentPid", str(os.getpid()),
                    "-LogPath", str(updater_log),
                    "-DiagnosticDir", str(UPDATE_DIAGNOSTIC_DIR),
                ]
                proc = subprocess.Popen(
                    args,
                    cwd=str(UPDATE_DIR),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                time.sleep(0.9)
                rc = proc.poll()
                if rc is not None:
                    detail = ""
                    try:
                        if updater_log.exists():
                            detail = updater_log.read_text(encoding="utf-8-sig", errors="replace")[-2000:]
                    except Exception:
                        pass
                    raise RuntimeError(f"更新助手启动失败（exit={rc}）。{detail}")

                self.progress_changed.emit(100, f"{source_name}下载并校验完成，正在安全重启安装…")
                self.restart_requested.emit()
            except Exception as e:
                LOGGER.exception("安装更新失败")
                self.check_finished.emit(False, None, f"安装更新失败：{type(e).__name__}: {e}")
            finally:
                self._busy = False

        threading.Thread(target=job, name="XiaoMeiliUpdateInstall", daemon=True).start()
'''
    s = replace_method_until(
        s,
        "    def install_latest_async(self):\n",
        "\n\ndef _path_size_bytes",
        install_method,
        "UpdateService.install_latest_async",
    )

    old_export = '''            logs = sorted(
                [p for p in LOG_DIR.glob("*.log") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:8]
            files.extend(logs)
'''
    new_export = '''            logs = sorted(
                [
                    p for p in LOG_DIR.rglob("*")
                    if p.is_file() and p.suffix.lower() in {".log", ".txt", ".json"}
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]
            files.extend(logs)
'''
    if old_export not in s:
        raise RuntimeError("V0.8.9.2 diagnostics export anchor missing")
    s = s.replace(old_export, new_export, 1)
    s = s.replace(
        'zf.write(p, arcname=f"data/{p.name}")',
        'zf.write(p, arcname=f"data/{p.relative_to(USER) if p.is_relative_to(USER) else p.name}")',
        1,
    )

    s = s.replace(
        '"遇到报错时可以一键导出最近日志和配置摘要，再把 ZIP 直接上传给 ChatGPT。"',
        '"普通更新记录与可恢复语音事件只保存在 XiaoMeiliData/logs，不再自动往桌面生成 TXT。真正异常可在这里一键导出诊断包。"',
        1,
    )

    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_ndm(path: Path):
    s = path.read_text(encoding="utf-8")
    old = '''    expected = int(expected_bytes or 0)
    if expected <= 0:
        expected = int(min_bytes or 0)
'''
    new = '''    # If the caller does not know the remote size, keep total=0 rather than
    # pretending the minimum accepted size is the full download size. This keeps
    # update progress honest while preserving the same completion checks.
    expected = max(0, int(expected_bytes or 0))
'''
    if old not in s:
        raise RuntimeError("V0.8.9.2 ndm expected-bytes anchor missing")
    s = s.replace(old, new, 1)
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    _m, _q, _end, worker = extract_worker_literal(s)

    start = worker.find('def desktop_diagnostic(code, message, log_path="", extra=""):\n')
    end = worker.find("\n\ndef download_model", start)
    if start < 0 or end < 0:
        raise RuntimeError("V0.8.9.2 speech diagnostic anchors missing")

    new_func = r'''def desktop_diagnostic(code, message, log_path="", extra=""):
    code = re.sub(r"[^A-Za-z0-9_-]+", "_", str(code or "UNKNOWN"))[:48]

    if code in {"ASR_EMPTY", "VAD_END_MISSING"}:
        logging.warning("[RECOVERABLE_SPEECH_EVENT] code=%s message=%s", code, message)
        return ""

    if code in _DESKTOP_REPORT_ONCE:
        return ""
    _DESKTOP_REPORT_ONCE.add(code)
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        log_file = Path(log_path) if str(log_path or "").strip() else None
        base = log_file.parent if log_file is not None else Path.cwd()
        target_dir = base / "diagnostics" / "speech"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"speech_{stamp}_{code}.txt"
        tail = ""
        try:
            if log_file is not None and log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-180:])
        except Exception as exc:
            tail = f"<读取 speech_worker.log 失败: {exc}>"
        body = [
            "小美丽 V0.8.9.2 语音诊断日志",
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"故障代码: {code}",
            f"说明: {message}",
            f"原始日志: {log_path}",
        ]
        if extra:
            body.extend(["", "附加信息:", str(extra)])
        body.extend(["", "speech_worker.log 最后 180 行:", tail])
        target.write_text("\n".join(body), encoding="utf-8")
        logging.error("[INTERNAL_SPEECH_DIAGNOSTIC] %s code=%s message=%s", target, code, message)
        return str(target)
    except Exception:
        logging.exception("[INTERNAL_SPEECH_DIAGNOSTIC] failed to write diagnostic")
        return ""
'''
    worker = worker[:start] + new_func + worker[end:]
    worker = worker.replace("小美丽 V0.8.9.1 语音诊断日志", "小美丽 V0.8.9.2 语音诊断日志")
    compile(worker, "speech_worker_v0892.py", "exec")
    s = replace_worker_literal(s, worker)
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch(source_root: Path, repo_root: Path):
    root = Path(source_root).resolve()
    repo_root = Path(repo_root).resolve()
    main = root / "app" / "src" / "main.py"
    ndm = root / "app" / "src" / "ndm_bridge.py"
    speech = root / "app" / "src" / "speech_input.py"
    helper = root / "app" / "assets" / "update_helper.ps1"
    helper_src = repo_root / "build" / "v0892" / "update_helper_v0892.ps1"
    for p in (main, ndm, speech, helper_src):
        if not p.exists():
            raise FileNotFoundError(p)

    patch_main(main)
    patch_ndm(ndm)
    patch_speech(speech)
    shutil.copy2(helper_src, helper)

    m = main.read_text(encoding="utf-8")
    n = ndm.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")
    hp = helper.read_text(encoding="utf-8-sig")

    main_checks = [
        'APP_VERSION = "0.8.9.2"',
        'from ndm_bridge import test_connection as ndm_test_connection, download_and_import as ndm_download_and_import',
        'UPDATE_LOG_DIR = LOG_DIR / "update"',
        'DESKTOP_ERROR_LOG = APP_DIAGNOSTIC_DIR / "xiaomeili_errors.log"',
        'NDM 未能完成本次更新，自动切换小美丽内置下载器',
        '"-LogPath", str(updater_log)',
        '"-DiagnosticDir", str(UPDATE_DIAGNOSTIC_DIR)',
        'LOG_DIR.rglob("*")',
    ]
    for token in main_checks:
        if token not in m:
            raise RuntimeError("V0.8.9.2 main verification failed: " + token)
    for forbidden in (
        'desktop_dir() / "小美丽更新错误日志_请上传给ChatGPT.txt"',
        'desktop_dir() / "小美丽错误日志_请上传给ChatGPT.txt"',
    ):
        if forbidden in m:
            raise RuntimeError("V0.8.9.2 still has automatic desktop log path: " + forbidden)

    if "expected = max(0, int(expected_bytes or 0))" not in n:
        raise RuntimeError("V0.8.9.2 NDM unknown-size progress fix missing")

    _m, _q, _end, worker = extract_worker_literal(sp)
    for token in (
        'if code in {"ASR_EMPTY", "VAD_END_MISSING"}:',
        'target_dir = base / "diagnostics" / "speech"',
        '小美丽 V0.8.9.2 语音诊断日志',
        '[RECOVERABLE_SPEECH_EVENT]',
    ):
        if token not in worker:
            raise RuntimeError("V0.8.9.2 speech verification failed: " + token)
    if 'target = _desktop_dir() / f"小美丽语音故障日志_' in worker:
        raise RuntimeError("V0.8.9.2 speech diagnostics still target Desktop")

    for token in ("[string]$LogPath", "[string]$DiagnosticDir", "update_failure_", "Updater finished successfully."):
        if token not in hp:
            raise RuntimeError("V0.8.9.2 helper verification failed: " + token)
    if "$DesktopLog" in hp:
        raise RuntimeError("V0.8.9.2 update helper still writes DesktopLog")

    print("Patched XiaoMeili source to V0.8.9.2: NDM updater + internal diagnostics/log routing")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0892.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]), Path(sys.argv[2]))
