$ErrorActionPreference = "Stop"
$Repo = $env:GITHUB_REPOSITORY
if (-not $Repo) { $Repo = "1196197579-a11y/XiaoMeili-Updates" }
$Root = (Get-Location).Path
$Token = [guid]::NewGuid().ToString("N")

$Stage = Join-Path $env:RUNNER_TEMP ("xm0941-source-" + $Token)
$Base = Join-Path $env:RUNNER_TEMP ("xm0941-base-" + $Token)
$Out = Join-Path $Root "out-v0100941"
$Work = Join-Path $env:RUNNER_TEMP ("xm0941-pyi-" + $Token)
$Spec = Join-Path $env:RUNNER_TEMP ("xm0941-spec-" + $Token)
$MonitorOut = Join-Path $env:RUNNER_TEMP ("xm0941-monitor-out-" + $Token)
$MonitorWork = Join-Path $env:RUNNER_TEMP ("xm0941-monitor-work-" + $Token)
$MonitorSpec = Join-Path $env:RUNNER_TEMP ("xm0941-monitor-spec-" + $Token)
$ReleaseDir = Join-Path $Root "release-v0100941"

foreach($p in @($Base,$Stage,$Out,$Work,$Spec,$MonitorOut,$MonitorWork,$MonitorSpec,$ReleaseDir)){
  New-Item -ItemType Directory -Path $p | Out-Null
}

Write-Host "[1/14] Download V0.10.0.9.4.0 source baseline"
gh release download "v0.10.0.9.4.0" --repo $Repo --pattern "XiaoMeili_V0.10.0.9.4.0_SourceProject.zip" --dir $Base
if ($LASTEXITCODE -ne 0) { throw "Cannot download V0.10.0.9.4.0 source" }
Expand-Archive -LiteralPath (Join-Path $Base "XiaoMeili_V0.10.0.9.4.0_SourceProject.zip") -DestinationPath $Stage -Force
$Main = Get-ChildItem $Stage -Recurse -File -Filter main.py | Where-Object { $_.FullName -match '[\\/]app[\\/]src[\\/]main\.py$' } | Select-Object -First 1
if (-not $Main) { throw "main.py not found" }
$Source = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Main.FullName))
$SrcDir = Join-Path $Source "app\src"

Write-Host "[2/14] Add onedir monitor source and apply V0.10.0.9.4.1 patch"
Copy-Item -LiteralPath "build\v0100941\resource_monitor_v0100941.py" -Destination (Join-Path $SrcDir "resource_monitor_v0100941.py")
python "build\v0100941\patch_v0100941.py" $Source
if ($LASTEXITCODE -ne 0) { throw "patch failed" }

Write-Host "[3/14] Install contract dependencies"
python -m pip install --disable-pip-version-check "psutil>=6,<8" "PySide6>=6.7,<7" "numpy>=1.26,<3" "opencv-python-headless>=4.10,<5" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "contract dependency install failed" }

Write-Host "[4/14] Run source monitor 5x ready/crash contract + NDM + FullSafe"
python "build\v0100941\test_v0100941_contract.py" $Source
if ($LASTEXITCODE -ne 0) { throw "source onedir monitor contract failed" }
python "build\v010092\test_ndm_fast_fallback_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "NDM regression contract failed" }
python "build\v010092\test_fullsafe_no_delete_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "FullSafe functional test failed" }

Write-Host "[5/14] Create exact source snapshot before EXE build"
$SourceZip = Join-Path $ReleaseDir "XiaoMeili_V0.10.0.9.4.1_SourceProject.zip"
Compress-Archive -Path (Join-Path $Source "*") -DestinationPath $SourceZip -CompressionLevel Optimal
$SourceHash = (Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$Embedded = Join-Path $Source "app\assets\XiaoMeili_V0.10.0.9.4.1_SourceProject.zip"
Copy-Item -LiteralPath $SourceZip -Destination $Embedded
if ((Get-FileHash $Embedded -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "embedded source hash mismatch" }

Write-Host "[6/14] Install build dependencies"
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check -r (Join-Path $Source "app\requirements.txt")
python -m pip install --disable-pip-version-check "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "[7/14] Build XiaoMeili main EXE"
$Pyi = @(
  "--noconfirm","--windowed","--name","XiaoMeili",
  "--icon",(Join-Path $Source "app\assets\xiaomeili_icon.ico"),
  "--distpath",$Out,"--workpath",$Work,"--specpath",$Spec,
  "--collect-all","rapidocr","--collect-all","onnxruntime","--collect-all","soundfile",
  "--collect-all","sounddevice","--collect-all","dxcam","--collect-all","dashscope",
  "--collect-all","websocket","--hidden-import","pynvml",
  "--add-data",((Join-Path $Source "app\assets") + ";assets"),
  (Join-Path $Source "app\src\main.py")
)
python -m PyInstaller @Pyi
if ($LASTEXITCODE -ne 0) { throw "main PyInstaller failed" }
$Exe = Join-Path $Out "XiaoMeili\XiaoMeili.exe"
if (-not (Test-Path $Exe)) { throw "XiaoMeili.exe missing" }

Write-Host "[8/14] Build fixed ONEDIR external monitor"
$MonitorSource = Join-Path $Source "app\src\resource_monitor_v0100941.py"
$MonitorPyi = @(
  "--noconfirm","--noconsole","--name","XiaoMeiliResourceMonitor",
  "--distpath",$MonitorOut,"--workpath",$MonitorWork,"--specpath",$MonitorSpec,
  "--hidden-import","pynvml",
  $MonitorSource
)
python -m PyInstaller @MonitorPyi
if ($LASTEXITCODE -ne 0) { throw "monitor onedir PyInstaller failed" }
$MonitorDir = Join-Path $MonitorOut "XiaoMeiliResourceMonitor"
$MonitorExe = Join-Path $MonitorDir "XiaoMeiliResourceMonitor.exe"
if (-not (Test-Path $MonitorExe)) { throw "onedir monitor EXE missing" }
$DestMonitor = Join-Path $Out "XiaoMeili\ResourceMonitor"
New-Item -ItemType Directory -Force -Path $DestMonitor | Out-Null
Copy-Item -Path (Join-Path $MonitorDir "*") -Destination $DestMonitor -Recurse -Force

Write-Host "[9/14] Run packaged ONEDIR monitor 5x ready/crash contract"
$PackagedMonitor = Join-Path $DestMonitor "XiaoMeiliResourceMonitor.exe"
python "build\v0100941\test_v0100941_contract.py" $Source $PackagedMonitor
if ($LASTEXITCODE -ne 0) { throw "packaged onedir monitor contract failed" }

Write-Host "[10/14] Run app self-tests"
& $Exe --runtime-self-test
if ($LASTEXITCODE -ne 0) { throw "runtime self-test failed" }
& $Exe --settings-ui-self-test
if ($LASTEXITCODE -ne 0) { throw "settings self-test failed" }

Write-Host "[11/14] Reuse verified stable launcher"
$LauncherBase = Join-Path $env:RUNNER_TEMP ("xm0941-launcher-" + $Token)
$LauncherExpanded = Join-Path $env:RUNNER_TEMP ("xm0941-launcher-x-" + $Token)
New-Item -ItemType Directory -Path $LauncherBase | Out-Null
New-Item -ItemType Directory -Path $LauncherExpanded | Out-Null
gh release download "v0.10.0.9.4.0" --repo $Repo --pattern "XiaoMeili_0.10.0.9.4.0_update.zip" --dir $LauncherBase
if ($LASTEXITCODE -ne 0) { throw "launcher base download failed" }
Expand-Archive -LiteralPath (Join-Path $LauncherBase "XiaoMeili_0.10.0.9.4.0_update.zip") -DestinationPath $LauncherExpanded -Force
$Launcher = Get-ChildItem $LauncherExpanded -Recurse -File -Filter XiaoMeiliLauncher.exe | Select-Object -First 1
if (-not $Launcher) { throw "launcher missing" }
Copy-Item $Launcher.FullName (Join-Path $Out "XiaoMeili\XiaoMeiliLauncher.exe")

Write-Host "[12/14] Create and verify local update bundle"
$UpdateZip = Join-Path $ReleaseDir "XiaoMeili_0.10.0.9.4.1_update.zip"
Compress-Archive -Path (Join-Path $Out "XiaoMeili\*") -DestinationPath $UpdateZip -CompressionLevel Optimal
$UpdateHash = (Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant()
$UpdateSize = (Get-Item $UpdateZip).Length
Add-Type -AssemblyName System.IO.Compression.FileSystem
$A = [System.IO.Compression.ZipFile]::OpenRead($UpdateZip)
try {
  foreach($Required in @(
    'XiaoMeili.exe',
    'XiaoMeiliLauncher.exe',
    'ResourceMonitor/XiaoMeiliResourceMonitor.exe',
    '_internal/assets/VERSION.txt',
    '_internal/assets/XiaoMeili_V0.10.0.9.4.1_SourceProject.zip'
  )) {
    if (-not ($A.Entries | Where-Object { $_.FullName -ieq $Required } | Select-Object -First 1)) {
      throw "update zip missing $Required"
    }
  }
  $InternalCount = @($A.Entries | Where-Object { $_.FullName -like 'ResourceMonitor/_internal/*' }).Count
  if ($InternalCount -lt 20) { throw "ResourceMonitor onedir _internal payload incomplete: $InternalCount entries" }
} finally { $A.Dispose() }

Write-Host "[13/14] Publish release and verify public hashes"
gh release view "v0.10.0.9.4.1" --repo $Repo --json tagName *> $null
$ReleaseExists = ($LASTEXITCODE -eq 0)
if ($ReleaseExists) {
  gh release upload "v0.10.0.9.4.1" $UpdateZip $SourceZip --repo $Repo --clobber
  if ($LASTEXITCODE -ne 0) { throw "release upload failed" }
} else {
  gh release create "v0.10.0.9.4.1" $UpdateZip $SourceZip --repo $Repo --title "XiaoMeili V0.10.0.9.4.1 | External Resource Diagnostic 4.1" --notes "The external resource monitor is now a fixed onedir component installed under ResourceMonitor/, avoiding one-file startup self-extraction. CI runs five ready-handshake/normal-stop cycles plus a host-crash survival test on the packaged monitor. The UI reports monitor startup/connected states and fails within 8 seconds with a diagnostic report instead of hanging at 0%. NDM and FullSafe are preserved."
  if ($LASTEXITCODE -ne 0) { throw "release create failed" }
}
$PublicBase = "https://github.com/$Repo/releases/download/v0.10.0.9.4.1"
$VerifyUpdate = Join-Path $env:RUNNER_TEMP ("xm0941-verify-update-" + $Token + ".zip")
$VerifySource = Join-Path $env:RUNNER_TEMP ("xm0941-verify-source-" + $Token + ".zip")
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_0.10.0.9.4.1_update.zip" -OutFile $VerifyUpdate -UseBasicParsing
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_V0.10.0.9.4.1_SourceProject.zip" -OutFile $VerifySource -UseBasicParsing
if ((Get-FileHash $VerifyUpdate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UpdateHash) { throw "public update hash mismatch" }
if ((Get-FileHash $VerifySource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "public source hash mismatch" }

Write-Host "[14/14] Publish safe manifest only after every check passes"
$Manifest = [ordered]@{
  protocol = 1
  version = "0.10.0.9.4.1"
  package_url = "https://github.com/$Repo/releases/download/v0.10.0.9.4.1/XiaoMeili_0.10.0.9.4.1_update.zip"
  sha256 = $UpdateHash
  package_size = [int64]$UpdateSize
  notes = @(
    'V0.10.0.9.4.1：外部资源监控器改为固定 onedir 组件 ResourceMonitor/XiaoMeiliResourceMonitor.exe，不再使用one-file启动自解压',
    '发布前对打包后的监控器实际运行5轮ready握手/正常停止，并额外执行1轮宿主进程异常退出测试',
    '点击测试会明确显示“正在启动外部资源监控器…”和“外部资源监控器已连接，开始测试”；8秒未ready会停止并生成故障报告，不再无限卡0%',
    '外部监控器继续每250ms记录CPU/RAM/GPU/显存/线程/进程，且自身资源不计入小美丽',
    '深度资源测试继续禁止强制TTS abort和伪造闭嘴ASR；保留自然TTS、ASR、大脑、白板、动画、30轮聊天、离线识别、综合满载和90秒回落',
    '外部监控启动日志会随诊断ZIP打包，后续启动故障不再是黑箱',
    '继续保留NDM真实URL文件名识别与快速回退',
    'FullSafe继续禁止删除、移动、覆盖、递归清理任何用户文件、D盘数据或旧版本'
  )
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "latest_safe.json") -Encoding utf8
git config user.name "XiaoMeili Update Bot"
git config user.email "actions@users.noreply.github.com"
git pull --rebase origin main
git add latest_safe.json
git commit -m "Publish XiaoMeili v0.10.0.9.4.1 safe manifest"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "manifest publish failed" }

Write-Host "V0.10.0.9.4.1 RELEASE PASS"
