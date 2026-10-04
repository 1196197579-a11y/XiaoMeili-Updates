$ErrorActionPreference = "Stop"
$Repo = $env:GITHUB_REPOSITORY
if (-not $Repo) { $Repo = "1196197579-a11y/XiaoMeili-Updates" }
$Root = (Get-Location).Path
$Token = [guid]::NewGuid().ToString("N")
$Stage = Join-Path $env:RUNNER_TEMP ("xm0932-source-" + $Token)
$Base = Join-Path $env:RUNNER_TEMP ("xm0932-base-" + $Token)
$Out = Join-Path $Root "out-v0100934"
$Work = Join-Path $env:RUNNER_TEMP ("xm0932-pyi-" + $Token)
$Spec = Join-Path $env:RUNNER_TEMP ("xm0932-spec-" + $Token)
$ReleaseDir = Join-Path $Root "release-v0100934"
New-Item -ItemType Directory -Path $Base | Out-Null
New-Item -ItemType Directory -Path $Stage | Out-Null
New-Item -ItemType Directory -Path $Out | Out-Null
New-Item -ItemType Directory -Path $Work | Out-Null
New-Item -ItemType Directory -Path $Spec | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "[1/12] Download V0.10.0.9.3.3 source baseline"
gh release download "v0.10.0.9.3.3" --repo $Repo --pattern "XiaoMeili_V0.10.0.9.3.3_SourceProject.zip" --dir $Base
if ($LASTEXITCODE -ne 0) { throw "Cannot download V0.10.0.9.3.3 source" }
Expand-Archive -LiteralPath (Join-Path $Base "XiaoMeili_V0.10.0.9.3.3_SourceProject.zip") -DestinationPath $Stage -Force
$Main = Get-ChildItem $Stage -Recurse -File -Filter main.py | Where-Object { $_.FullName -match '[\\/]app[\\/]src[\\/]main\.py$' } | Select-Object -First 1
if (-not $Main) { throw "main.py not found" }
$Source = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Main.FullName))

Write-Host "[2/12] Apply V0.10.0.9.3.4 patch and contracts"
python "build\v0100934\patch_v0100934.py" $Source
if ($LASTEXITCODE -ne 0) { throw "patch failed" }
python -m pip install --disable-pip-version-check "psutil>=6,<8" "PySide6>=6.7,<7" "numpy>=1.26,<3" "opencv-python-headless>=4.10,<5" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "contract dependency install failed" }
python "build\v0100934\test_v0100934_contract.py" $Source
if ($LASTEXITCODE -ne 0) { throw "V0.10.0.9.3.4 queued-dispatch/watchdog contract failed" }
python "build\v010092\test_ndm_fast_fallback_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "NDM regression contract failed" }
python "build\v010092\test_fullsafe_no_delete_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "FullSafe functional test failed" }

Write-Host "[3/12] Create exact source snapshot before EXE build"
$SourceZip = Join-Path $ReleaseDir "XiaoMeili_V0.10.0.9.3.4_SourceProject.zip"
Compress-Archive -Path (Join-Path $Source "*") -DestinationPath $SourceZip -CompressionLevel Optimal
$SourceHash = (Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$Embedded = Join-Path $Source "app\assets\XiaoMeili_V0.10.0.9.3.4_SourceProject.zip"
Copy-Item -LiteralPath $SourceZip -Destination $Embedded
if ((Get-FileHash $Embedded -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "embedded source hash mismatch" }

Write-Host "[4/12] Install build dependencies"
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check -r (Join-Path $Source "app\requirements.txt")
python -m pip install --disable-pip-version-check "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "[5/12] Build Windows app and self-test"
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
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$Exe = Join-Path $Out "XiaoMeili\XiaoMeili.exe"
& $Exe --runtime-self-test
if ($LASTEXITCODE -ne 0) { throw "runtime self-test failed" }
& $Exe --settings-ui-self-test
if ($LASTEXITCODE -ne 0) { throw "settings self-test failed" }

Write-Host "[6/12] Reuse verified stable launcher"
$LauncherBase = Join-Path $env:RUNNER_TEMP ("xm0932-launcher-" + $Token)
$LauncherExpanded = Join-Path $env:RUNNER_TEMP ("xm0932-launcher-x-" + $Token)
New-Item -ItemType Directory -Path $LauncherBase | Out-Null
New-Item -ItemType Directory -Path $LauncherExpanded | Out-Null
gh release download "v0.10.0.9.3.3" --repo $Repo --pattern "XiaoMeili_0.10.0.9.3.3_update.zip" --dir $LauncherBase
if ($LASTEXITCODE -ne 0) { throw "launcher base download failed" }
Expand-Archive -LiteralPath (Join-Path $LauncherBase "XiaoMeili_0.10.0.9.3.3_update.zip") -DestinationPath $LauncherExpanded -Force
$Launcher = Get-ChildItem $LauncherExpanded -Recurse -File -Filter XiaoMeiliLauncher.exe | Select-Object -First 1
if (-not $Launcher) { throw "launcher missing" }
Copy-Item $Launcher.FullName (Join-Path $Out "XiaoMeili\XiaoMeiliLauncher.exe")

Write-Host "[7/12] Create update bundle"
$UpdateZip = Join-Path $ReleaseDir "XiaoMeili_0.10.0.9.3.4_update.zip"
Compress-Archive -Path (Join-Path $Out "XiaoMeili\*") -DestinationPath $UpdateZip -CompressionLevel Optimal
$UpdateHash = (Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant()
$UpdateSize = (Get-Item $UpdateZip).Length

Write-Host "[8/12] Verify local bundle contract"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$A = [System.IO.Compression.ZipFile]::OpenRead($UpdateZip)
try {
  foreach($Required in @('XiaoMeili.exe','XiaoMeiliLauncher.exe','_internal/assets/VERSION.txt','_internal/assets/XiaoMeili_V0.10.0.9.3.4_SourceProject.zip')) {
    if (-not ($A.Entries | Where-Object { $_.FullName -ieq $Required } | Select-Object -First 1)) { throw "update zip missing $Required" }
  }
} finally { $A.Dispose() }

Write-Host "[9/12] Publish release"
gh release view "v0.10.0.9.3.4" --repo $Repo --json tagName *> $null
$ReleaseExists = ($LASTEXITCODE -eq 0)
if ($ReleaseExists) {
  gh release upload "v0.10.0.9.3.4" $UpdateZip $SourceZip --repo $Repo --clobber
  if ($LASTEXITCODE -ne 0) { throw "release upload failed" }
} else {
  gh release create "v0.10.0.9.3.4" $UpdateZip $SourceZip --repo $Repo --title "XiaoMeili V0.10.0.9.3.4 | Crash-Safe Diagnostic 3.0" --notes "Crash-Safe Diagnostic 3.0: all mutating Brain/TTS/Speech/Pet actions are marshalled back to the GUI thread through explicit Qt queued connections; the dangerous TTS-to-hard-silence path is smoke-tested before the long run; an independent hidden PowerShell watchdog survives native app crashes and writes crash evidence including Windows Application Error/WER data. Persistent live journals, Python faulthandler, NDM and FullSafe remain enabled."
  if ($LASTEXITCODE -ne 0) { throw "release create failed" }
}

Write-Host "[10/12] Verify public release hashes"
$PublicBase = "https://github.com/$Repo/releases/download/v0.10.0.9.3.4"
$VerifyUpdate = Join-Path $env:RUNNER_TEMP ("xm0932-verify-update-" + $Token + ".zip")
$VerifySource = Join-Path $env:RUNNER_TEMP ("xm0932-verify-source-" + $Token + ".zip")
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_0.10.0.9.3.4_update.zip" -OutFile $VerifyUpdate -UseBasicParsing
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_V0.10.0.9.3.4_SourceProject.zip" -OutFile $VerifySource -UseBasicParsing
if ((Get-FileHash $VerifyUpdate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UpdateHash) { throw "public update hash mismatch" }
if ((Get-FileHash $VerifySource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "public source hash mismatch" }

Write-Host "[11/12] Publish safe manifest"
$Manifest = [ordered]@{
  protocol = 1
  version = "0.10.0.9.3.4"
  package_url = "https://github.com/$Repo/releases/download/v0.10.0.9.3.4/XiaoMeili_0.10.0.9.3.4_update.zip"
  sha256 = $UpdateHash
  package_size = [int64]$UpdateSize
  notes = @(
    'V0.10.0.9.3.4：一键深度资源测试升级为 Crash-Safe Diagnostic 3.0，重点修复闭嘴阶段的跨线程竞态',
    'Brain/TTS/Speech/Pet 的所有状态修改都通过 Qt.QueuedConnection 回到GUI主线程串行执行；诊断后台线程不再直接 voice.speak / brain.ask / utterance_ready.emit',
    '正式长测前增加高风险 TTS→闭嘴→白板关闭预检，若预检失败会在约10秒内停止，不再让用户白等整轮',
    '新增独立隐藏PowerShell看门狗：即使 XiaoMeili.exe 原生闪退，看门狗仍会在桌面生成崩溃ZIP',
    '看门狗会收集最后阶段/事件、Windows Application Error/WER、crashrpt/Sogou相关线索；新增 Python faulthandler 全线程证据',
    '持续保留live timeline/events/rounds/status；自动恢复与看门狗报告均只复制/追加，不删除、不移动、不覆盖原始文件',
    '继续保留30轮聊天、离线画面识别、综合满载、90秒回落、NVML无黑框、真实CPU、稳定250ms、WAV/ASR修复',
    '继续保留NDM真实URL文件名识别与25秒/75秒快速回退；FullSafe不删除、不移动、不递归清理用户文件或任何旧版本'
  )
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "latest_safe.json") -Encoding utf8
git config user.name "XiaoMeili Update Bot"
git config user.email "actions@users.noreply.github.com"
git pull --rebase origin main
git add latest_safe.json
git commit -m "Publish XiaoMeili v0.10.0.9.3.4 safe manifest"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "manifest publish failed" }

Write-Host "[12/12] V0.10.0.9.3.4 RELEASE PASS"