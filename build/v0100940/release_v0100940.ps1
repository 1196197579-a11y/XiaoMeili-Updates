$ErrorActionPreference = "Stop"
$Repo = $env:GITHUB_REPOSITORY
if (-not $Repo) { $Repo = "1196197579-a11y/XiaoMeili-Updates" }
$Root = (Get-Location).Path
$Token = [guid]::NewGuid().ToString("N")

$Stage = Join-Path $env:RUNNER_TEMP ("xm0940-source-" + $Token)
$Base = Join-Path $env:RUNNER_TEMP ("xm0940-base-" + $Token)
$Out = Join-Path $Root "out-v0100940"
$Work = Join-Path $env:RUNNER_TEMP ("xm0940-pyi-" + $Token)
$Spec = Join-Path $env:RUNNER_TEMP ("xm0940-spec-" + $Token)
$MonitorOut = Join-Path $env:RUNNER_TEMP ("xm0940-monitor-out-" + $Token)
$MonitorWork = Join-Path $env:RUNNER_TEMP ("xm0940-monitor-work-" + $Token)
$MonitorSpec = Join-Path $env:RUNNER_TEMP ("xm0940-monitor-spec-" + $Token)
$ReleaseDir = Join-Path $Root "release-v0100940"

foreach($p in @($Base,$Stage,$Out,$Work,$Spec,$MonitorOut,$MonitorWork,$MonitorSpec,$ReleaseDir)){
  New-Item -ItemType Directory -Path $p | Out-Null
}

Write-Host "[1/13] Download V0.10.0.9.3.7 source baseline"
gh release download "v0.10.0.9.3.7" --repo $Repo --pattern "XiaoMeili_V0.10.0.9.3.7_SourceProject.zip" --dir $Base
if ($LASTEXITCODE -ne 0) { throw "Cannot download V0.10.0.9.3.7 source" }
Expand-Archive -LiteralPath (Join-Path $Base "XiaoMeili_V0.10.0.9.3.7_SourceProject.zip") -DestinationPath $Stage -Force
$Main = Get-ChildItem $Stage -Recurse -File -Filter main.py | Where-Object { $_.FullName -match '[\\/]app[\\/]src[\\/]main\.py$' } | Select-Object -First 1
if (-not $Main) { throw "main.py not found" }
$Source = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Main.FullName))
$SrcDir = Join-Path $Source "app\src"

Write-Host "[2/13] Add external monitor source and apply V0.10.0.9.4.0 patch"
Copy-Item -LiteralPath "build\v0100940\resource_monitor_v0100940.py" -Destination (Join-Path $SrcDir "resource_monitor_v0100940.py")
python "build\v0100940\patch_v0100940.py" $Source
if ($LASTEXITCODE -ne 0) { throw "patch failed" }

Write-Host "[3/13] Run source contracts + NDM + FullSafe"
python -m pip install --disable-pip-version-check "psutil>=6,<8" "PySide6>=6.7,<7" "numpy>=1.26,<3" "opencv-python-headless>=4.10,<5" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "contract dependency install failed" }
python "build\v0100940\test_v0100940_contract.py" $Source
if ($LASTEXITCODE -ne 0) { throw "external monitor source contract failed" }
python "build\v010092\test_ndm_fast_fallback_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "NDM regression contract failed" }
python "build\v010092\test_fullsafe_no_delete_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "FullSafe functional test failed" }

Write-Host "[4/13] Create exact source snapshot before EXE build"
$SourceZip = Join-Path $ReleaseDir "XiaoMeili_V0.10.0.9.4.0_SourceProject.zip"
Compress-Archive -Path (Join-Path $Source "*") -DestinationPath $SourceZip -CompressionLevel Optimal
$SourceHash = (Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$Embedded = Join-Path $Source "app\assets\XiaoMeili_V0.10.0.9.4.0_SourceProject.zip"
Copy-Item -LiteralPath $SourceZip -Destination $Embedded
if ((Get-FileHash $Embedded -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "embedded source hash mismatch" }

Write-Host "[5/13] Install build dependencies"
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check -r (Join-Path $Source "app\requirements.txt")
python -m pip install --disable-pip-version-check "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "[6/13] Build XiaoMeili main EXE"
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

Write-Host "[7/13] Build dedicated external resource monitor EXE"
$MonitorSource = Join-Path $Source "app\src\resource_monitor_v0100940.py"
$MonitorPyi = @(
  "--noconfirm","--onefile","--noconsole","--name","XiaoMeiliResourceMonitor",
  "--distpath",$MonitorOut,"--workpath",$MonitorWork,"--specpath",$MonitorSpec,
  "--hidden-import","pynvml",
  $MonitorSource
)
python -m PyInstaller @MonitorPyi
if ($LASTEXITCODE -ne 0) { throw "monitor PyInstaller failed" }
$MonitorExe = Join-Path $MonitorOut "XiaoMeiliResourceMonitor.exe"
if (-not (Test-Path $MonitorExe)) { throw "external monitor EXE missing" }
Copy-Item -LiteralPath $MonitorExe -Destination (Join-Path $Out "XiaoMeili\XiaoMeiliResourceMonitor.exe")

Write-Host "[8/13] Run packaged helper contract + app self-tests"
python "build\v0100940\test_v0100940_contract.py" $Source $MonitorExe
if ($LASTEXITCODE -ne 0) { throw "packaged external monitor contract failed" }
& $Exe --runtime-self-test
if ($LASTEXITCODE -ne 0) { throw "runtime self-test failed" }
& $Exe --settings-ui-self-test
if ($LASTEXITCODE -ne 0) { throw "settings self-test failed" }

Write-Host "[9/13] Reuse verified stable launcher"
$LauncherBase = Join-Path $env:RUNNER_TEMP ("xm0940-launcher-" + $Token)
$LauncherExpanded = Join-Path $env:RUNNER_TEMP ("xm0940-launcher-x-" + $Token)
New-Item -ItemType Directory -Path $LauncherBase | Out-Null
New-Item -ItemType Directory -Path $LauncherExpanded | Out-Null
gh release download "v0.10.0.9.3.7" --repo $Repo --pattern "XiaoMeili_0.10.0.9.3.7_update.zip" --dir $LauncherBase
if ($LASTEXITCODE -ne 0) { throw "launcher base download failed" }
Expand-Archive -LiteralPath (Join-Path $LauncherBase "XiaoMeili_0.10.0.9.3.7_update.zip") -DestinationPath $LauncherExpanded -Force
$Launcher = Get-ChildItem $LauncherExpanded -Recurse -File -Filter XiaoMeiliLauncher.exe | Select-Object -First 1
if (-not $Launcher) { throw "launcher missing" }
Copy-Item $Launcher.FullName (Join-Path $Out "XiaoMeili\XiaoMeiliLauncher.exe")

Write-Host "[10/13] Create and verify local update bundle"
$UpdateZip = Join-Path $ReleaseDir "XiaoMeili_0.10.0.9.4.0_update.zip"
Compress-Archive -Path (Join-Path $Out "XiaoMeili\*") -DestinationPath $UpdateZip -CompressionLevel Optimal
$UpdateHash = (Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant()
$UpdateSize = (Get-Item $UpdateZip).Length
Add-Type -AssemblyName System.IO.Compression.FileSystem
$A = [System.IO.Compression.ZipFile]::OpenRead($UpdateZip)
try {
  foreach($Required in @(
    'XiaoMeili.exe',
    'XiaoMeiliLauncher.exe',
    'XiaoMeiliResourceMonitor.exe',
    '_internal/assets/VERSION.txt',
    '_internal/assets/XiaoMeili_V0.10.0.9.4.0_SourceProject.zip'
  )) {
    if (-not ($A.Entries | Where-Object { $_.FullName -ieq $Required } | Select-Object -First 1)) {
      throw "update zip missing $Required"
    }
  }
} finally { $A.Dispose() }

Write-Host "[11/13] Publish release"
gh release view "v0.10.0.9.4.0" --repo $Repo --json tagName *> $null
$ReleaseExists = ($LASTEXITCODE -eq 0)
if ($ReleaseExists) {
  gh release upload "v0.10.0.9.4.0" $UpdateZip $SourceZip --repo $Repo --clobber
  if ($LASTEXITCODE -ne 0) { throw "release upload failed" }
} else {
  gh release create "v0.10.0.9.4.0" $UpdateZip $SourceZip --repo $Repo --title "XiaoMeili V0.10.0.9.4.0 | External Resource Diagnostic 4.0" --notes "Resource monitoring now runs in a dedicated XiaoMeiliResourceMonitor.exe outside the main app. The helper owns the authoritative 250ms CPU/RAM/GPU/VRAM timeline, has a ready handshake, survives host crashes and creates a Desktop crash ZIP independently. XiaoMeili itself only runs the normal automated stages and stage markers. Force-abort TTS and synthetic hard-silence actions remain excluded. NDM and FullSafe are preserved."
  if ($LASTEXITCODE -ne 0) { throw "release create failed" }
}

Write-Host "[12/13] Re-download public assets and verify hashes"
$PublicBase = "https://github.com/$Repo/releases/download/v0.10.0.9.4.0"
$VerifyUpdate = Join-Path $env:RUNNER_TEMP ("xm0940-verify-update-" + $Token + ".zip")
$VerifySource = Join-Path $env:RUNNER_TEMP ("xm0940-verify-source-" + $Token + ".zip")
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_0.10.0.9.4.0_update.zip" -OutFile $VerifyUpdate -UseBasicParsing
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_V0.10.0.9.4.0_SourceProject.zip" -OutFile $VerifySource -UseBasicParsing
if ((Get-FileHash $VerifyUpdate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UpdateHash) { throw "public update hash mismatch" }
if ((Get-FileHash $VerifySource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "public source hash mismatch" }

Write-Host "[13/13] Publish safe manifest only after all checks pass"
$Manifest = [ordered]@{
  protocol = 1
  version = "0.10.0.9.4.0"
  package_url = "https://github.com/$Repo/releases/download/v0.10.0.9.4.0/XiaoMeili_0.10.0.9.4.0_update.zip"
  sha256 = $UpdateHash
  package_size = [int64]$UpdateSize
  notes = @(
    'V0.10.0.9.4.0：External Resource Diagnostic 4.0，资源监控迁移到独立 XiaoMeiliResourceMonitor.exe',
    '外部监控器每250ms记录CPU/RAM/GPU/显存/线程/进程，小美丽内部只负责正常业务自动化与阶段标记',
    '外部监控器通过ready握手后才允许长测；XiaoMeili原生崩溃时监控器仍可独立生成桌面闪退ZIP',
    '正常结束时先让外部监控器关闭CSV，再由小美丽的正常诊断ZIP统一打包外部权威资源数据',
    '深度资源测试继续禁止强制TTS abort和伪造闭嘴ASR，只测试自然TTS完成后的资源回落',
    '继续保留ASR、大脑、TTS、白板、动画、30轮聊天、离线识别、综合满载和90秒回落',
    '继续保留NDM真实URL文件名识别与快速回退',
    'FullSafe继续禁止删除、移动、覆盖、递归清理任何用户文件、D盘数据或旧版本'
  )
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "latest_safe.json") -Encoding utf8
git config user.name "XiaoMeili Update Bot"
git config user.email "actions@users.noreply.github.com"
git pull --rebase origin main
git add latest_safe.json
git commit -m "Publish XiaoMeili v0.10.0.9.4.0 safe manifest"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "manifest publish failed" }

Write-Host "V0.10.0.9.4.0 RELEASE PASS"
