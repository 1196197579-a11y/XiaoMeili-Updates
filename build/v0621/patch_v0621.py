# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

FIXED_HELPER = r'''param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$DesktopLog
)
$ErrorActionPreference = 'Stop'
function Log([string]$Text) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $DesktopLog -Value ("[$stamp] $Text") -Encoding UTF8
}
try {
    Log "XiaoMeili updater started. package=$Package target=$Target parentPid=$ParentPid"
    for ($i=0; $i -lt 120; $i++) {
        $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        throw "Old XiaoMeili process did not exit in time."
    }
    if (-not (Test-Path -LiteralPath $Package)) { throw "Update package not found: $Package" }
    if (-not (Test-Path -LiteralPath $Target)) { throw "Target folder not found: $Target" }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $work = Join-Path ([System.IO.Path]::GetTempPath()) ("XiaoMeiliUpdate_" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Expand-Archive -LiteralPath $Package -DestinationPath $work -Force

    $payload = $null
    $directExe = Join-Path $work $ExeName
    $nested = Get-ChildItem -LiteralPath $work -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName $ExeName) } | Select-Object -First 1
    if (Test-Path -LiteralPath $directExe) { $payload = $work }
    elseif ($nested) { $payload = $nested.FullName }
    else { throw "Update package does not contain $ExeName" }

    $backup = $Target + '.backup'
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item -LiteralPath $Target -Destination $backup -Recurse -Force

    try {
        & robocopy.exe $payload $Target /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        $rc = $LASTEXITCODE
        if ($rc -ge 8) { throw "robocopy failed with exit code $rc" }
        $newExe = Join-Path $Target $ExeName
        if (-not (Test-Path -LiteralPath $newExe)) { throw "Updated EXE missing: $newExe" }
        Log "Update copied successfully. Starting new version."
        Start-Process -FilePath $newExe -WorkingDirectory $Target
        Start-Sleep -Milliseconds 800
        $started = Get-Process | Where-Object { $_.Path -eq $newExe } | Select-Object -First 1
        if (-not $started) { Log "Warning: could not confirm relaunched process; Start-Process returned without exception." }
        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    }
    catch {
        Log ("Update apply failed. Restoring backup. " + $_.Exception.Message)
        if (Test-Path -LiteralPath $backup) {
            & robocopy.exe $backup $Target /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        }
        throw
    }
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    Log "Updater finished successfully."
}
catch {
    try {
        Log ("ERROR: " + $_.Exception.Message)
        Log ($_ | Out-String)
    } catch {}
    try { Start-Process notepad.exe -ArgumentList $DesktopLog } catch {}
    exit 1
}
exit 0
'''

def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(root: Path):
    main = root / 'app' / 'src' / 'main.py'
    helper = root / 'app' / 'assets' / 'update_helper.ps1'
    s = main.read_text(encoding='utf-8')
    s = replace_once(s,
        'APP_NAME = "小美丽 V0.6.2｜Qwen3-TTS Voice Mouth + Continuous Puppet V2"\nAPP_VERSION = "0.6.2"',
        'APP_NAME = "小美丽 V0.6.2.1｜Qwen3-TTS Voice Mouth + Updater Hotfix"\nAPP_VERSION = "0.6.2.1"',
        'version')
    old = '''                helper = Path(resource("assets/update_helper.ps1"))
                if not helper.exists():
                    raise FileNotFoundError(f"更新助手缺失：{helper}")
                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行覆盖更新，请在正式 XiaoMeili.exe 中测试。")
                target = Path(sys.executable).parent
                exe_name = Path(sys.executable).name
                desktop_log = desktop_dir() / "小美丽更新错误日志_请上传给ChatGPT.txt"
                args = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(helper),
                    "-Package", str(package),
                    "-Target", str(target),
                    "-ExeName", exe_name,
                    "-Pid", str(os.getpid()),
                    "-DesktopLog", str(desktop_log),
                ]
                subprocess.Popen(args, cwd=str(UPDATE_DIR), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.progress_changed.emit(100, "更新包已准备，正在重启安装…")
                self.restart_requested.emit()
'''
    new = '''                helper = Path(resource("assets/update_helper.ps1"))
                if not helper.exists():
                    raise FileNotFoundError(f"更新助手缺失：{helper}")
                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行覆盖更新，请在正式 XiaoMeili.exe 中测试。")
                target = Path(sys.executable).parent
                exe_name = Path(sys.executable).name
                desktop_log = desktop_dir() / "小美丽更新错误日志_请上传给ChatGPT.txt"
                # Run the updater from outside the application directory. This prevents the
                # helper itself from being replaced while robocopy mirrors the new build.
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
                proc = subprocess.Popen(args, cwd=str(UPDATE_DIR), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                # Parameter-binding/script-start failures happen immediately. Do not shut
                # XiaoMeili down unless the helper is demonstrably alive and waiting for us.
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
                self.progress_changed.emit(100, "更新助手已启动，正在安全重启…")
                self.restart_requested.emit()
'''
    s = replace_once(s, old, new, 'updater launch')
    s = s.replace('LOGGER.exception("清理全局快捷键失败")', 'LOGGER.warning("清理全局快捷键时 keyboard 库返回异常，已忽略", exc_info=True)')
    main.write_text(s, encoding='utf-8')
    helper.write_text(FIXED_HELPER, encoding='utf-8-sig', newline='\r\n')
    py_compile.compile(str(main), doraise=True)
    print('patched', root)

if __name__ == '__main__':
    patch(Path(sys.argv[1]).resolve())
