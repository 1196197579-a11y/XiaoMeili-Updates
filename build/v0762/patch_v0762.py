# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.6.2 patch anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    if not main_path.exists():
        raise FileNotFoundError(main_path)

    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.6\.1"',
        'APP_NAME = "小美丽 V0.7.6.2｜Reliable Updater + D Drive Hotfix"\nAPP_VERSION = "0.7.6.2"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Add zipfile for package integrity validation.
    if "import zipfile\n" not in s:
        s = replace_once(s, "import urllib.request\n", "import urllib.request\nimport zipfile\n", "zipfile import")

    start = s.index("    def install_latest_async(self):\n", s.index("class UpdateService(QObject):"))
    end = s.index("\n\ndef _path_size_bytes", start)
    new_method = r'''    def install_latest_async(self):
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
                package = UPDATE_DIR / f"XiaoMeili_{version}_update.zip"
                part = package.with_suffix(".zip.part")

                UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                try:
                    part.unlink(missing_ok=True)
                    package.unlink(missing_ok=True)
                except Exception:
                    pass

                last_actual = ""
                last_detail = ""
                download_ok = False

                # V0.7.6.2: direct GitHub release downloads can occasionally terminate early
                # or a network/CDN layer can return stale bytes. Never trust "100%" alone.
                # Retry with a cache-busting query, verify Content-Length when provided,
                # verify SHA-256 on the .part file, then validate ZIP structure before install.
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
                    req = urllib.request.Request(attempt_url, headers=headers)
                    self.progress_changed.emit(0, f"正在下载 V{version}（第 {attempt}/3 次）…")

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
                            pct = int(done * 100 / total) if total else 0
                            self.progress_changed.emit(
                                max(0, min(99, pct)),
                                f"正在下载 V{version}（第 {attempt}/3 次）… {done/1024/1024:.1f} MB"
                            )
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except Exception:
                            pass

                    if total and done != total:
                        last_detail = f"下载不完整：收到 {done} 字节，服务器声明 {total} 字节"
                        LOGGER.warning("更新下载长度不一致 | attempt=%s | %s", attempt, last_detail)
                        try:
                            part.unlink(missing_ok=True)
                        except Exception:
                            pass
                        time.sleep(1.2)
                        continue

                    actual = self._sha256(part)
                    last_actual = actual
                    if expected and actual != expected:
                        last_detail = (
                            f"SHA-256 不一致：期望 {expected}，实际 {actual}，"
                            f"本次文件 {part.stat().st_size if part.exists() else 0} 字节"
                        )
                        LOGGER.warning("更新包校验失败 | attempt=%s | %s", attempt, last_detail)
                        try:
                            part.unlink(missing_ok=True)
                        except Exception:
                            pass
                        time.sleep(1.2)
                        continue

                    try:
                        with zipfile.ZipFile(part, "r") as zf:
                            bad = zf.testzip()
                            if bad:
                                raise RuntimeError(f"ZIP 内部文件损坏：{bad}")
                            names = {Path(x).name.lower() for x in zf.namelist()}
                            if "xiaomeili.exe" not in names:
                                raise RuntimeError("ZIP 中没有 XiaoMeili.exe")
                    except Exception as exc:
                        last_detail = f"ZIP 完整性检查失败：{type(exc).__name__}: {exc}"
                        LOGGER.warning("更新 ZIP 检查失败 | attempt=%s", attempt, exc_info=True)
                        try:
                            part.unlink(missing_ok=True)
                        except Exception:
                            pass
                        time.sleep(1.2)
                        continue

                    part.replace(package)
                    download_ok = True
                    break

                if not download_ok:
                    raise RuntimeError(
                        "更新包连续 3 次下载/校验失败。"
                        + (f" 最后一次实际 SHA-256：{last_actual}。" if last_actual else "")
                        + (f" {last_detail}" if last_detail else "")
                        + " 请把桌面错误日志上传给 ChatGPT。"
                    )

                helper = Path(resource("assets/update_helper.ps1"))
                if not helper.exists():
                    raise FileNotFoundError(f"更新助手缺失：{helper}")
                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行覆盖更新，请在正式 XiaoMeili.exe 中测试。")

                target = Path(sys.executable).parent
                exe_name = Path(sys.executable).name
                desktop_log = desktop_dir() / "小美丽更新错误日志_请上传给ChatGPT.txt"
                runtime_helper = UPDATE_DIR / "update_helper_runtime.ps1"
                shutil.copy2(helper, runtime_helper)
                args = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(runtime_helper),
                    "-Package", str(package),
                    "-Target", str(target),
                    "-ExeName", exe_name,
                    "-ParentPid", str(os.getpid()),
                    "-DesktopLog", str(desktop_log),
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
                        if desktop_log.exists():
                            detail = desktop_log.read_text(encoding="utf-8-sig", errors="replace")[-2000:]
                    except Exception:
                        pass
                    raise RuntimeError(f"更新助手启动失败（exit={rc}）。{detail}")

                self.progress_changed.emit(100, "更新包已三重校验通过，正在安全重启…")
                self.restart_requested.emit()
            except Exception as e:
                LOGGER.exception("安装更新失败")
                self.check_finished.emit(False, None, f"安装更新失败：{type(e).__name__}: {e}")
            finally:
                self._busy = False

        threading.Thread(target=job, name="XiaoMeiliUpdateInstall", daemon=True).start()
'''
    s = s[:start] + new_method + s[end:]

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.6.2 reliable updater")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0762.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
