$ErrorActionPreference = "Stop"
$Repo = $env:GITHUB_REPOSITORY
if (-not $Repo) { $Repo = "1196197579-a11y/XiaoMeili-Updates" }
$Root = (Get-Location).Path
$Token = [guid]::NewGuid().ToString("N")
$Stage = Join-Path $env:RUNNER_TEMP ("xm0932-source-" + $Token)
$Base = Join-Path $env:RUNNER_TEMP ("xm0932-base-" + $Token)
$Out = Join-Path $Root "out-v0100932"
$Work = Join-Path $env:RUNNER_TEMP ("xm0932-pyi-" + $Token)
$Spec = Join-Path $env:RUNNER_TEMP ("xm0932-spec-" + $Token)
$ReleaseDir = Join-Path $Root "release-v0100932"
New-Item -ItemType Directory -Path $Base | Out-Null
New-Item -ItemType Directory -Path $Stage | Out-Null
New-Item -ItemType Directory -Path $Out | Out-Null
New-Item -ItemType Directory -Path $Work | Out-Null
New-Item -ItemType Directory -Path $Spec | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "[1/12] Download V0.10.0.9.3.1 source baseline"
gh release download "v0.10.0.9.3.1" --repo $Repo --pattern "XiaoMeili_V0.10.0.9.3.1_SourceProject.zip" --dir $Base
if ($LASTEXITCODE -ne 0) { throw "Cannot download V0.10.0.9.3.1 source" }
Expand-Archive -LiteralPath (Join-Path $Base "XiaoMeili_V0.10.0.9.3.1_SourceProject.zip") -DestinationPath $Stage -Force
$Main = Get-ChildItem $Stage -Recurse -File -Filter main.py | Where-Object { $_.FullName -match '[\\/]app[\\/]src[\\/]main\.py$' } | Select-Object -First 1
if (-not $Main) { throw "main.py not found" }
$Source = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Main.FullName))

Write-Host "[2/12] Apply V0.10.0.9.3.2 patch and contracts"
python "build\v0100932\patch_v0100932.py" $Source
if ($LASTEXITCODE -ne 0) { throw "patch failed" }
python -m pip install --disable-pip-version-check "psutil>=6,<8" "PySide6>=6.7,<7" "numpy>=1.26,<3" "opencv-python-headless>=4.10,<5" "nvidia-ml-py>=12,<14"
if ($LASTEXITCODE -ne 0) { throw "contract dependency install failed" }
python "build\v0100932\test_v0100932_contract.py" $Source
if ($LASTEXITCODE -ne 0) { throw "V0.10.0.9.3.2 WAV/ASR contract failed" }
python "build\v010092\test_ndm_fast_fallback_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "NDM regression contract failed" }
python "build\v010092\test_fullsafe_no_delete_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "FullSafe functional test failed" }

Write-Host "[3/12] Create exact source snapshot before EXE build"
$SourceZip = Join-Path $ReleaseDir "XiaoMeili_V0.10.0.9.3.2_SourceProject.zip"
Compress-Archive -Path (Join-Path $Source "*") -DestinationPath $SourceZip -CompressionLevel Optimal
$SourceHash = (Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$Embedded = Join-Path $Source "app\assets\XiaoMeili_V0.10.0.9.3.2_SourceProject.zip"
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
gh release download "v0.10.0.9.3.1" --repo $Repo --pattern "XiaoMeili_0.10.0.9.3.1_update.zip" --dir $LauncherBase
if ($LASTEXITCODE -ne 0) { throw "launcher base download failed" }
Expand-Archive -LiteralPath (Join-Path $LauncherBase "XiaoMeili_0.10.0.9.3.1_update.zip") -DestinationPath $LauncherExpanded -Force
$Launcher = Get-ChildItem $LauncherExpanded -Recurse -File -Filter XiaoMeiliLauncher.exe | Select-Object -First 1
if (-not $Launcher) { throw "launcher missing" }
Copy-Item $Launcher.FullName (Join-Path $Out "XiaoMeili\XiaoMeiliLauncher.exe")

Write-Host "[7/12] Create update bundle"
$UpdateZip = Join-Path $ReleaseDir "XiaoMeili_0.10.0.9.3.2_update.zip"
Compress-Archive -Path (Join-Path $Out "XiaoMeili\*") -DestinationPath $UpdateZip -CompressionLevel Optimal
$UpdateHash = (Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant()
$UpdateSize = (Get-Item $UpdateZip).Length

Write-Host "[8/12] Verify local bundle contract"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$A = [System.IO.Compression.ZipFile]::OpenRead($UpdateZip)
try {
  foreach($Required in @('XiaoMeili.exe','XiaoMeiliLauncher.exe','_internal/assets/VERSION.txt','_internal/assets/XiaoMeili_V0.10.0.9.3.2_SourceProject.zip')) {
    if (-not ($A.Entries | Where-Object { $_.FullName -ieq $Required } | Select-Object -First 1)) { throw "update zip missing $Required" }
  }
} finally { $A.Dispose() }

Write-Host "[9/12] Publish release"
gh release view "v0.10.0.9.3.2" --repo $Repo --json tagName *> $null
$ReleaseExists = ($LASTEXITCODE -eq 0)
if ($ReleaseExists) {
  gh release upload "v0.10.0.9.3.2" $UpdateZip $SourceZip --repo $Repo --clobber
  if ($LASTEXITCODE -ne 0) { throw "release upload failed" }
} else {
  gh release create "v0.10.0.9.3.2" $UpdateZip $SourceZip --repo $Repo --title "XiaoMeili V0.10.0.9.3.2 | Resource Diagnostic WAV/ASR Fix" --notes "Fixes the ASR fixture WAV creation failure in the automatic resource diagnostic. The runner now preserves no-overwrite semantics explicitly, creates WAV with the supported wb mode, immediately reopens it with rb to verify 16 kHz mono 16-bit PCM, and performs that fixture check before the 60-second baseline. CI now executes a real WAV round-trip, overwrite-refusal check, and a mocked ASR diag_ready entry smoke test. V0.10.0.9.3.1 NVML/no-console, CPU sampling, timing, FullSafe and NDM fixes are preserved."
  if ($LASTEXITCODE -ne 0) { throw "release create failed" }
}

Write-Host "[10/12] Verify public release hashes"
$PublicBase = "https://github.com/$Repo/releases/download/v0.10.0.9.3.2"
$VerifyUpdate = Join-Path $env:RUNNER_TEMP ("xm0932-verify-update-" + $Token + ".zip")
$VerifySource = Join-Path $env:RUNNER_TEMP ("xm0932-verify-source-" + $Token + ".zip")
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_0.10.0.9.3.2_update.zip" -OutFile $VerifyUpdate -UseBasicParsing
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_V0.10.0.9.3.2_SourceProject.zip" -OutFile $VerifySource -UseBasicParsing
if ((Get-FileHash $VerifyUpdate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UpdateHash) { throw "public update hash mismatch" }
if ((Get-FileHash $VerifySource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "public source hash mismatch" }

Write-Host "[11/12] Publish safe manifest"
$Manifest = [ordered]@{
  protocol = 1
  version = "0.10.0.9.3.2"
  package_url = "https://github.com/$Repo/releases/download/v0.10.0.9.3.2/XiaoMeili_0.10.0.9.3.2_update.zip"
  sha256 = $UpdateHash
  package_size = [int64]$UpdateSize
  notes = @(
    'V0.10.0.9.3.2：修复一键深度资源测试进入ASR阶段前生成测试WAV时因 wave 不支持 xb 模式而中止的问题',
    '继续坚持不覆盖现有文件：诊断音频若已存在直接拒绝；新文件使用 wave 支持的 wb 创建，不删除、不移动任何旧文件',
    'WAV创建后立即用 rb 重新读取并验证16kHz、单声道、16-bit PCM和有效帧数；失败会在60秒待机之前的预检阶段立即提示',
    'CI新增真实WAV创建/回读、二次创建拒绝覆盖、模拟ASR diag_ready入口运行测试，避免同类错误再次进入正式版',
    '继续保留V0.10.0.9.3.1的NVML无黑框GPU/显存采集、真实CPU采样、250ms稳定采样和准确的测试中止提示',
    '继续保留自动白板、ASR、云端大脑、TTS、30轮聊天、闭嘴打断、离线画面识别、综合满载与90秒资源回落测试',
    '继续保留NDM真实URL文件名识别和25秒/75秒快速回退；NDM源文件只复制、不移动、不删除',
    'FullSafe继续生效：更新和诊断不删除、不移动、不递归清理桌面、下载、文档、D盘、XiaoMeiliData或任何旧版本'
  )
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "latest_safe.json") -Encoding utf8
git config user.name "XiaoMeili Update Bot"
git config user.email "actions@users.noreply.github.com"
git pull --rebase origin main
git add latest_safe.json
git commit -m "Publish XiaoMeili v0.10.0.9.3.2 safe manifest"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "manifest publish failed" }

Write-Host "[12/12] V0.10.0.9.3.2 RELEASE PASS"