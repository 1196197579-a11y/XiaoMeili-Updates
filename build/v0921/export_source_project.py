# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path


DEVELOPMENT = r"""# XiaoMeili V0.9.2.1 完整源码工程

本包不是把旧版源码简单修改版本号。
`app/src` 与 `app/assets` 是 XiaoMeili V0.9.2.1 正式发布流水线在 canonical seed 上按正式顺序应用全部版本补丁后得到的最终可编辑源码快照。

## 源码来源
XiaoMeili 的发布仓库采用“V0.6.1.1 canonical seed + 顺序补丁”构建方式，并没有长期单独保存一个展开后的 V0.9.2.1 源码目录。
本源码包由与正式 V0.9.2.1 Release 相同的 CI 补丁链重新生成，并经过 py_compile 与版本校验。

## 主要目录
- app/src/：主程序、语音、大脑、NDM 等 Python 源码
- app/assets/：图标、基础图片、更新/迁移 PowerShell 脚本
- app/requirements.txt：Python 依赖清单
- _raw_user_assets/：原始角色分层素材
- release_pipeline/：V0.9.2 / V0.9.2.1 安全更新、Launcher、Installer 和发布流水线源码
- RUN_DEV.cmd：开发模式启动
- BUILD_V0921.ps1：从本源码快照重新构建 Windows EXE
- BUILD_EXE.bat：历史构建入口，保留参考
- SOURCE_PROVENANCE.txt：源码生成链说明

## 推荐开发环境
Windows 10/11 x64 + Python 3.12 x64

### 创建环境
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
.\.venv\Scripts\python.exe -m pip install "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8"

### 开发运行
RUN_DEV.cmd

### 构建
powershell -ExecutionPolicy Bypass -File .\BUILD_V0921.ps1

## V0.9.2.1 安全更新架构
- 固定托管根目录：%LOCALAPPDATA%\XiaoMeiliApp
- 每次更新写入新的 versions\v... 目录
- active.json 只切换激活版本，不镜像覆盖旧版本
- updater 禁止 /MIR、/PURGE、robocopy 镜像和自动删除
- Desktop/Documents/Downloads/UserProfile/系统路径受保护
- 必须验证 .xiaomeili-install.json 安装标记
- 旧 latest.json 通道保持关闭，新版本使用 latest_safe.json

## 不包含的运行期数据
以下内容不是 V0.9.2.1 程序源码，因此不打包：
- 外部下载的大模型权重、ASR/TTS 模型缓存
- 用户个人配置、聊天记忆、日志
- 用户后来导入的视频/音频素材
这些内容由程序按现有逻辑在用户数据目录读取或下载。
"""

RUN_DEV = r"""@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app\src\main.py
) else (
  py -3.12 app\src\main.py
)
"""

BUILD_PS1 = r"""$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -m pip install --disable-pip-version-check -r ".\app\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }

& $python -m pip install --disable-pip-version-check "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8"
if ($LASTEXITCODE -ne 0) { throw "build dependencies install failed" }

$dist = Join-Path $PSScriptRoot "dist"
$work = Join-Path $PSScriptRoot "build-work"
$spec = Join-Path $PSScriptRoot "build-spec"

$args = @(
  "-m","PyInstaller",
  "--noconfirm","--clean","--windowed",
  "--name","XiaoMeili",
  "--icon",".\app\assets\xiaomeili_icon.ico",
  "--distpath",$dist,
  "--workpath",$work,
  "--specpath",$spec,
  "--collect-all","rapidocr",
  "--collect-all","onnxruntime",
  "--collect-all","soundfile",
  "--collect-all","sounddevice",
  "--collect-all","dxcam",
  "--add-data",".\app\assets;assets",
  ".\app\src\main.py"
)
& $python @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed: $LASTEXITCODE" }

$exe = Join-Path $dist "XiaoMeili\XiaoMeili.exe"
if (-not (Test-Path $exe)) { throw "XiaoMeili.exe was not produced." }

& $exe --runtime-self-test
if ($LASTEXITCODE -ne 0) { throw "Runtime self-test failed." }

& $exe --settings-ui-self-test
if ($LASTEXITCODE -ne 0) { throw "Settings UI self-test failed." }

Write-Host "Build complete: $exe"
"""

PROVENANCE = """V0.9.2.1 SOURCE SNAPSHOT PROVENANCE
==================================
Release tag: v0.9.2.1
Canonical build model: V0.6.1.1 seed + sequential version patches
Seed: seed/XiaoMeili_V0_6_1_1_BootstrapFix_UpdateReady.zip
Final patch: build/v0921/patch_v0921.py

This package contains the fully-expanded final editable source after the complete
V0.9.2.1 release patch chain. It is not a renamed older source tree and is not
the PyInstaller _internal output.

Repository note:
The update repository did not keep a separate permanently expanded V0.9.2.1
source directory. The authoritative source form was the canonical seed plus
patch chain. This archive materializes that exact final source state.
"""


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main(source_root: Path, repo_root: Path, output_zip: Path):
    source_root = source_root.resolve()
    repo_root = repo_root.resolve()
    output_zip = output_zip.resolve()

    main_py = source_root / "app" / "src" / "main.py"
    if not main_py.is_file():
        raise FileNotFoundError(main_py)
    text = main_py.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.9.2.1"' not in text:
        raise RuntimeError("source root is not reconstructed V0.9.2.1")

    workspace = output_zip.parent / "source-project-work"
    project = workspace / "XiaoMeili_V0.9.2.1_SourceProject"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    copy_tree(source_root, project)

    pipeline = project / "release_pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    copy_tree(repo_root / "build" / "v092", pipeline / "v092")
    copy_tree(repo_root / "build" / "v0921", pipeline / "v0921")
    shutil.copy2(
        repo_root / ".github" / "workflows" / "build-v062.yml",
        pipeline / "build-v0921.yml",
    )
    for name in ("latest.json", "latest_safe.json"):
        p = repo_root / name
        if p.exists():
            shutil.copy2(p, pipeline / name)

    (project / "DEVELOPMENT.md").write_text(DEVELOPMENT, encoding="utf-8")
    (project / "RUN_DEV.cmd").write_text(RUN_DEV, encoding="utf-8-sig")
    (project / "BUILD_V0921.ps1").write_text(BUILD_PS1, encoding="utf-8-sig")
    (project / "SOURCE_PROVENANCE.txt").write_text(PROVENANCE, encoding="utf-8")

    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in project.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(workspace))

    digest = hashlib.sha256(output_zip.read_bytes()).hexdigest()
    print(f"source_zip={output_zip}")
    print(f"sha256={digest}")
    print(f"size={output_zip.stat().st_size}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: export_source_project.py <source_root> <repo_root> <output_zip>")
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
