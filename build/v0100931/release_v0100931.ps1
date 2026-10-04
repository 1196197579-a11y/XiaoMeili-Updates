$ErrorActionPreference = "Stop"
$Repo = $env:GITHUB_REPOSITORY
if (-not $Repo) { $Repo = "1196197579-a11y/XiaoMeili-Updates" }
$Root = (Get-Location).Path
$Token = [guid]::NewGuid().ToString("N")
$Stage = Join-Path $env:RUNNER_TEMP ("xm0931-source-" + $Token)
$Base = Join-Path $env:RUNNER_TEMP ("xm0931-base-" + $Token)
$Out = Join-Path $Root "out-v0100931"
$Work = Join-Path $env:RUNNER_TEMP ("xm0931-pyi-" + $Token)
$Spec = Join-Path $env:RUNNER_TEMP ("xm0931-spec-" + $Token)
$ReleaseDir = Join-Path $Root "release-v0100931"
New-Item -ItemType Directory -Path $Base | Out-Null
New-Item -ItemType Directory -Path $Stage | Out-Null
New-Item -ItemType Directory -Path $Out | Out-Null
New-Item -ItemType Directory -Path $Work | Out-Null
New-Item -ItemType Directory -Path $Spec | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "[1/12] Download V0.10.0.9.3 source baseline"
gh release download "v0.10.0.9.3" --repo $Repo --pattern "XiaoMeili_V0.10.0.9.3_SourceProject.zip" --dir $Base
if ($LASTEXITCODE -ne 0) { throw "Cannot download V0.10.0.9.3 source" }
Expand-Archive -LiteralPath (Join-Path $Base "XiaoMeili_V0.10.0.9.3_SourceProject.zip") -DestinationPath $Stage -Force
$Main = Get-ChildItem $Stage -Recurse -File -Filter main.py | Where-Object { $_.FullName -match '[\\/]app[\\/]src[\\/]main\.py$' } | Select-Object -First 1
if (-not $Main) { throw "main.py not found" }
$Source = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Main.FullName))

Write-Host "[2/12] Apply V0.10.0.9.3.1 patch and contracts"
python "build\v0100931\patch_v0100931.py" $Source $Root
if ($LASTEXITCODE -ne 0) { throw "patch failed" }
python -m pip install --disable-pip-version-check "psutil>=6,<8"
if ($LASTEXITCODE -ne 0) { throw "psutil contract dependency install failed" }
python "build\v0100931\test_v0100931_contract.py" $Source
if ($LASTEXITCODE -ne 0) { throw "V0.10.0.9.3.1 contract failed" }
python "build\v010092\test_ndm_fast_fallback_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "NDM regression contract failed" }
python "build\v010092\test_fullsafe_no_delete_v010092.py" $Source
if ($LASTEXITCODE -ne 0) { throw "FullSafe functional test failed" }

Write-Host "[3/12] Create exact source snapshot before EXE build"
$SourceZip = Join-Path $ReleaseDir "XiaoMeili_V0.10.0.9.3.1_SourceProject.zip"
Compress-Archive -Path (Join-Path $Source "*") -DestinationPath $SourceZip -CompressionLevel Optimal
$SourceHash = (Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$Embedded = Join-Path $Source "app\assets\XiaoMeili_V0.10.0.9.3.1_SourceProject.zip"
Copy-Item -LiteralPath $SourceZip -Destination $Embedded
if ((Get-FileHash $Embedded -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "embedded source hash mismatch" }

Write-Host "[4/12] Install build dependencies"
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check -r (Join-Path $Source "app\requirements.txt")
python -m pip install --disable-pip-version-check "pyinstaller>=6.10,<7" "dxcam>=0.0.5" "psutil>=6.0,<8"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "[5/12] Build Windows app"
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
$LauncherBase = Join-Path $env:RUNNER_TEMP ("xm0931-launcher-" + $Token)
$LauncherExpanded = Join-Path $env:RUNNER_TEMP ("xm0931-launcher-x-" + $Token)
New-Item -ItemType Directory -Path $LauncherBase | Out-Null
New-Item -ItemType Directory -Path $LauncherExpanded | Out-Null
gh release download "v0.10.0.9.3" --repo $Repo --pattern "XiaoMeili_0.10.0.9.3_update.zip" --dir $LauncherBase
if ($LASTEXITCODE -ne 0) { throw "launcher base download failed" }
Expand-Archive -LiteralPath (Join-Path $LauncherBase "XiaoMeili_0.10.0.9.3_update.zip") -DestinationPath $LauncherExpanded -Force
$Launcher = Get-ChildItem $LauncherExpanded -Recurse -File -Filter XiaoMeiliLauncher.exe | Select-Object -First 1
if (-not $Launcher) { throw "launcher missing" }
Copy-Item $Launcher.FullName (Join-Path $Out "XiaoMeili\XiaoMeiliLauncher.exe")

Write-Host "[7/12] Create update bundle"
$UpdateZip = Join-Path $ReleaseDir "XiaoMeili_0.10.0.9.3.1_update.zip"
Compress-Archive -Path (Join-Path $Out "XiaoMeili\*") -DestinationPath $UpdateZip -CompressionLevel Optimal
$UpdateHash = (Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant()
$UpdateSize = (Get-Item $UpdateZip).Length

Write-Host "[8/12] Verify local bundle contract"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$A = [System.IO.Compression.ZipFile]::OpenRead($UpdateZip)
try {
  foreach($Required in @('XiaoMeili.exe','XiaoMeiliLauncher.exe','_internal/assets/VERSION.txt','_internal/assets/XiaoMeili_V0.10.0.9.3.1_SourceProject.zip')) {
    if (-not ($A.Entries | Where-Object { $_.FullName -ieq $Required } | Select-Object -First 1)) { throw "update zip missing $Required" }
  }
} finally { $A.Dispose() }

Write-Host "[9/12] Publish release"
gh release view "v0.10.0.9.3.1" --repo $Repo --json tagName *> $null
$ReleaseExists = ($LASTEXITCODE -eq 0)
if ($ReleaseExists) {
  gh release upload "v0.10.0.9.3.1" $UpdateZip $SourceZip --repo $Repo --clobber
  if ($LASTEXITCODE -ne 0) { throw "release upload failed" }
} else {
  gh release create "v0.10.0.9.3.1" $UpdateZip $SourceZip --repo $Repo --title "XiaoMeili V0.10.0.9.3.1 | Resource Diagnostic 2.0 Fix" --notes "Fixes the V0.10.0.9.3 diagnostic round-event crash, console-window flashing, zero CPU readings and timing catch-up distortion. GPU/VRAM collection now prefers in-process NVML with a hidden nvidia-smi fallback on a separate collector thread. Preflight catches diagnostic API failures before the 60-second baseline. Failed tests are labeled as interrupted reports, not completed reports. FullSafe and V0.10.0.9.3 automatic test coverage are preserved."
  if ($LASTEXITCODE -ne 0) { throw "release create failed" }
}

Write-Host "[10/12] Verify public release hashes"
$PublicBase = "https://github.com/$Repo/releases/download/v0.10.0.9.3.1"
$VerifyUpdate = Join-Path $env:RUNNER_TEMP ("xm0931-verify-update-" + $Token + ".zip")
$VerifySource = Join-Path $env:RUNNER_TEMP ("xm0931-verify-source-" + $Token + ".zip")
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_0.10.0.9.3.1_update.zip" -OutFile $VerifyUpdate -UseBasicParsing
Invoke-WebRequest -Uri "$PublicBase/XiaoMeili_V0.10.0.9.3.1_SourceProject.zip" -OutFile $VerifySource -UseBasicParsing
if ((Get-FileHash $VerifyUpdate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UpdateHash) { throw "public update hash mismatch" }
if ((Get-FileHash $VerifySource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "public source hash mismatch" }

Write-Host "[11/12] Publish safe manifest"
$Manifest = [ordered]@{
  protocol = 1
  version = "0.10.0.9.3.1"
  package_url = "https://github.com/$Repo/releases/download/v0.10.0.9.3.1/XiaoMeili_0.10.0.9.3.1_update.zip"
  sha256 = $UpdateHash
  package_size = [int64]$UpdateSize
  notes = @(
    'V0.10.0.9.3.1：修复一键深度资源测试在白板第1轮因事件参数冲突而中止的问题，完整30轮测试可继续执行',
    'GPU/显存采集优先改为进程内NVML，不再高频启动可见的nvidia-smi控制台；备用nvidia-smi同样强制隐藏窗口并移到独立采集线程',
    '修复CPU采样长期为0：复用psutil进程对象并预热，再按真实时间窗计算进程CPU',
    '修复250ms采样器被GPU查询阻塞后疯狂补帧的问题；错过节拍后直接进入下一周期，不再产生0.03秒级补采样',
    '新增启动前快速自检，事件/轮次/CPU采样接口异常会在长时间测试前立即发现',
    '测试途中异常时明确显示“测试中止，已生成故障报告”，不再误标为测试完成',
    '继续保留无需打开VALORANT、无需用户说话的自动白板/ASR/云端大脑/TTS/30轮聊天/闭嘴/离线识别/综合满载/90秒回落测试',
    'FullSafe继续生效：更新与诊断不删除、不移动、不递归清理桌面、下载、文档、D盘、XiaoMeiliData或任何旧版本；NDM源文件只复制不删除'
  )
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "latest_safe.json") -Encoding utf8
git config user.name "XiaoMeili Update Bot"
git config user.email "actions@users.noreply.github.com"
git pull --rebase origin main
git add latest_safe.json
git commit -m "Publish XiaoMeili v0.10.0.9.3.1 safe manifest"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "manifest publish failed" }

Write-Host "[12/12] V0.10.0.9.3.1 RELEASE PASS"