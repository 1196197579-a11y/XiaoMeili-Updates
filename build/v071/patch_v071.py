# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7.1 patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    req_path = source_root / "app" / "requirements.txt"
    ndm_src = repo_root / "build" / "v071" / "ndm_bridge.py"
    ndm_dst = source_root / "app" / "src" / "ndm_bridge.py"
    shutil.copy2(ndm_src, ndm_dst)

    s = main_path.read_text(encoding="utf-8")
    s = must(
        s,
        'APP_NAME = "小美丽 V0.7｜Local Brain + Qwen3-TTS + Continuous Puppet V2"\nAPP_VERSION = "0.7.0"',
        'APP_NAME = "小美丽 V0.7.1｜NDM Accelerated Local Brain + Qwen3-TTS"\nAPP_VERSION = "0.7.1"',
        "version",
    )
    s = must(s, '"config_version": 19,', '"config_version": 20,', "config version")

    brain_cfg_old = '''        "brain": {
            "enabled": True,
            "auto_speak": True,
            "temperature": 0.78,
            "max_tokens": 220,
            "context_turns": 6,
            "persona": DEFAULT_PERSONA,
        },
'''
    brain_cfg_new = '''        "brain": {
            "enabled": True,
            "auto_speak": True,
            "temperature": 0.78,
            "max_tokens": 220,
            "context_turns": 6,
            "persona": DEFAULT_PERSONA,
            "download_mode": "ndm",
            "ndm_download_dir": str(Path.home() / "Downloads"),
        },
'''
    s = must(s, brain_cfg_old, brain_cfg_new, "NDM config")

    prepare_old = '        self.brain_prepare_btn = QPushButton("准备小美丽大脑（Qwen3-8B Q4_K_M，模型约 5.03 GB）")\n'
    prepare_new = '''        self.brain_prepare_btn = QPushButton("准备小美丽大脑（Qwen3-8B Q4_K_M，模型约 5.03 GB）")
'''
    s = must(s, prepare_old, prepare_new, "prepare button")

    insert_after = '''        self.brain_prepare_btn.clicked.connect(self._prepare_brain)
        bf.addRow(self.brain_prepare_btn)

'''
    ndm_ui = '''        self.brain_prepare_btn.clicked.connect(self._prepare_brain)
        bf.addRow(self.brain_prepare_btn)

        dl_row = QWidget(); dl_l = QHBoxLayout(dl_row); dl_l.setContentsMargins(0,0,0,0)
        self.brain_download_mode = QComboBox()
        self.brain_download_mode.addItem("NDM 加速下载（推荐）", "ndm")
        self.brain_download_mode.addItem("小美丽内置下载器", "builtin")
        wanted_mode = str(cfg.get("brain",{}).get("download_mode","ndm") or "ndm")
        idx = self.brain_download_mode.findData(wanted_mode)
        if idx >= 0: self.brain_download_mode.setCurrentIndex(idx)
        self.brain_ndm_test_btn = QPushButton("测试 NDM")
        self.brain_ndm_test_btn.clicked.connect(self._brain_test_ndm)
        dl_l.addWidget(self.brain_download_mode, 1); dl_l.addWidget(self.brain_ndm_test_btn)
        bf.addRow("下载方式", dl_row)

        dir_row = QWidget(); dir_l = QHBoxLayout(dir_row); dir_l.setContentsMargins(0,0,0,0)
        self.brain_ndm_dir = QLineEdit(str(cfg.get("brain",{}).get("ndm_download_dir") or (Path.home() / "Downloads")))
        self.brain_ndm_dir.setPlaceholderText("请选择 NDM 的 Download Directory")
        self.brain_ndm_browse_btn = QPushButton("选择目录")
        self.brain_ndm_browse_btn.clicked.connect(self._brain_choose_ndm_dir)
        dir_l.addWidget(self.brain_ndm_dir, 1); dir_l.addWidget(self.brain_ndm_browse_btn)
        bf.addRow("NDM 下载目录", dir_row)

        ndm_note = QLabel(
            "NDM 模式会直接连接本机 Neat Download Manager，不需要浏览器扩展。"
            "小美丽把任务交给 NDM 后，会等待下载完成并自动把文件搬回 XiaoMeiliData。"
            "由于 NDM 没有开放任务进度查询接口，实时速度/剩余时间请直接看 NDM 窗口。"
        )
        ndm_note.setWordWrap(True); bf.addRow(ndm_note)

'''
    s = must(s, insert_after, ndm_ui, "NDM UI")

    # Settings persistence.
    save_anchor = '''        self.cfg["brain"]["context_turns"] = int(self.brain_context.value())
        self.cfg["brain"]["persona"] = self.brain_persona.toPlainText().strip() or DEFAULT_PERSONA
        save_config(self.cfg)
'''
    save_new = '''        self.cfg["brain"]["context_turns"] = int(self.brain_context.value())
        self.cfg["brain"]["persona"] = self.brain_persona.toPlainText().strip() or DEFAULT_PERSONA
        self.cfg["brain"]["download_mode"] = str(self.brain_download_mode.currentData() or "ndm")
        self.cfg["brain"]["ndm_download_dir"] = self.brain_ndm_dir.text().strip()
        save_config(self.cfg)
'''
    s = must(s, save_anchor, save_new, "save NDM settings")

    # Replace prepare method and add NDM helpers.
    old_prepare_method = '''    def _prepare_brain(self):
        self.brain_prepare_btn.setEnabled(False)
        self.brain_status.setText("正在准备本地大脑…")
        self.brain_service.start_setup()

'''
    new_prepare_method = '''    def _brain_choose_ndm_dir(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.brain_ndm_dir.text().strip() or str(Path.home() / "Downloads")
        chosen = QFileDialog.getExistingDirectory(self, "选择 NDM 的 Download Directory", start)
        if chosen:
            self.brain_ndm_dir.setText(chosen)
            self._brain_save_settings()

    def _brain_test_ndm(self):
        ok, msg = self.brain_service.test_ndm()
        self.brain_status.setText(msg)
        if not ok:
            QMessageBox.warning(self, "NDM 未连接", "没有连接到 Neat Download Manager。\\n\\n请先打开 NDM，再点击“测试 NDM”。")

    def _prepare_brain(self):
        self._brain_save_settings()
        mode = str(self.brain_download_mode.currentData() or "ndm")
        ndm_dir = self.brain_ndm_dir.text().strip()
        if mode == "ndm":
            if not ndm_dir or not Path(ndm_dir).exists():
                self._brain_choose_ndm_dir()
                ndm_dir = self.brain_ndm_dir.text().strip()
            if not ndm_dir or not Path(ndm_dir).exists():
                QMessageBox.warning(self, "请选择 NDM 下载目录", "请先选择 NDM 设置里的 Download Directory。")
                return
            ok, msg = self.brain_service.test_ndm()
            if not ok:
                QMessageBox.warning(self, "NDM 未连接", "请先打开 Neat Download Manager。\\n\\n小美丽会直接连接 NDM 本机接收服务，不需要浏览器扩展。")
                return
        self.brain_prepare_btn.setEnabled(False)
        self.brain_status.setText("正在准备本地大脑…")
        self.brain_service.start_setup(mode, ndm_dir)

'''
    s = must(s, old_prepare_method, new_prepare_method, "NDM prepare method")

    # Mark downloader controls dirty/persistable together with brain settings.
    s = s.replace(
        '(self.brain_auto_speak, "toggled"),',
        '(self.brain_auto_speak, "toggled"), (self.brain_download_mode, "currentIndexChanged"), (self.brain_ndm_dir, "textChanged"),',
        1,
    )

    main_path.write_text(s, encoding="utf-8")

    b = brain_path.read_text(encoding="utf-8")
    b = must(
        b,
        'from PySide6.QtCore import QObject, Signal\n',
        'from PySide6.QtCore import QObject, Signal\nfrom ndm_bridge import test_connection as ndm_test_connection, download_and_import as ndm_download_and_import\n',
        "NDM brain import",
    )
    b = must(
        b,
        '        self._last_exchange = None\n',
        '        self._last_exchange = None\n        self._download_mode = "builtin"\n        self._ndm_download_dir = ""\n',
        "download state",
    )

    old_download = '''    def _download_file(self, url: str, dest: Path, start_pct: int, end_pct: int, label: str):
        dest.parent.mkdir(parents=True, exist_ok=True)
'''
    new_download = '''    def test_ndm(self):
        return ndm_test_connection()

    def _download_file(self, url: str, dest: Path, start_pct: int, end_pct: int, label: str, remote_filename=None, expected_min=1):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._download_mode == "ndm":
            if not self._ndm_download_dir:
                raise RuntimeError("NDM 下载目录尚未设置。")
            filename = str(remote_filename or dest.name)
            self.setup_progress.emit(start_pct, f"正在把 {filename} 发送给 NDM…")
            def note(message):
                self.setup_progress.emit(start_pct, str(message))
            ndm_download_and_import(
                url=url,
                filename=filename,
                download_root=self._ndm_download_dir,
                destination=dest,
                min_bytes=max(1, int(expected_min or 1)),
                progress_cb=note,
            )
            self.setup_progress.emit(end_pct, f"NDM 已完成：{filename}")
            return
'''
    b = must(b, old_download, new_download, "download dispatcher")

    # The replacement above intentionally keeps the original urllib body immediately after
    # our NDM branch. It now runs only when download_mode is builtin.

    b = must(
        b,
        '        self._download_file(str(core["browser_download_url"]), core_zip, 2, 12, "下载 llama.cpp CUDA 运行时")\n'
        '        self._download_file(str(cudart["browser_download_url"]), cudart_zip, 12, 18, "下载 CUDA 12.4 运行库")',
        '        self._download_file(str(core["browser_download_url"]), core_zip, 2, 12, "下载 llama.cpp CUDA 运行时", str(core.get("name") or core_zip.name), max(1, int(core.get("size") or 1) - 1024))\n'
        '        self._download_file(str(cudart["browser_download_url"]), cudart_zip, 12, 18, "下载 CUDA 12.4 运行库", str(cudart.get("name") or cudart_zip.name), max(1, int(cudart.get("size") or 1) - 1024))',
        "runtime NDM filenames",
    )
    b = must(
        b,
        '        self._download_file(MODEL_URL, MODEL_FILE, 20, 99, "下载 Qwen3-8B Q4_K_M")',
        '        self._download_file(MODEL_URL, MODEL_FILE, 20, 99, "下载 Qwen3-8B Q4_K_M", MODEL_FILE.name, MODEL_EXPECTED_MIN)',
        "model NDM filename",
    )
    b = must(
        b,
        '    def start_setup(self):\n',
        '    def start_setup(self, download_mode="builtin", ndm_download_dir=""):\n'
        '        self._download_mode = str(download_mode or "builtin").strip().lower()\n'
        '        self._ndm_download_dir = str(ndm_download_dir or "").strip()\n',
        "setup args",
    )

    brain_path.write_text(b, encoding="utf-8")

    req = req_path.read_text(encoding="utf-8")
    if "websocket-client" not in req.lower():
        req = req.rstrip() + "\nwebsocket-client>=1.8,<2\n"
        req_path.write_text(req, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    py_compile.compile(str(ndm_dst), doraise=True)
    print("Patched XiaoMeili source to V0.7.1 with NDM acceleration")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v071.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
