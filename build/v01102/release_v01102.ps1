$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '0.11.0.2'
$BaselineVersion = '0.11.0'
$Repo = $env:GITHUB_REPOSITORY
$Root = (Resolve-Path '.').Path
$Work = Join-Path $Root 'work-v01102'
$Baseline = Join-Path $Work 'baseline'
$Source = Join-Path $Work 'source'
$DistRoot = Join-Path $Work 'pyinstaller'
$Bundle = Join-Path $Work 'bundle'
$Out = Join-Path $Work 'out'
$Evidence = Join-Path $Work 'test-output.txt'
$V01101Delta = Join-Path $Root 'build/v01101/source-delta'

if (Test-Path -LiteralPath $Work) { throw 'Append-only build workspace already exists.' }
New-Item -ItemType Directory -Path $Baseline,$Out | Out-Null

gh release view "v$Version" --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) { throw "Formal release v$Version already exists; refusing to overwrite it." }

gh release download "v$BaselineVersion" --repo $Repo --dir $Baseline --pattern 'XiaoMeili_0.11.0_update.zip' --pattern 'XiaoMeili_V0.11.0_SourceProject.zip'
if ($LASTEXITCODE -ne 0) { throw 'Failed to download formal V0.11.0 baseline.' }
$BaselineUpdate = Join-Path $Baseline 'XiaoMeili_0.11.0_update.zip'
$BaselineSource = Join-Path $Baseline 'XiaoMeili_V0.11.0_SourceProject.zip'
$UpdateSha = (Get-FileHash -LiteralPath $BaselineUpdate -Algorithm SHA256).Hash.ToLowerInvariant()
$SourceSha = (Get-FileHash -LiteralPath $BaselineSource -Algorithm SHA256).Hash.ToLowerInvariant()
if ($UpdateSha -ne '7c7feab9da979fd4a9b178bc960345110d595ddba9665b5098fec32fc4cb31ef') { throw 'Formal V0.11.0 update baseline hash mismatch.' }
if ($SourceSha -ne '295addead4d866501c32f2c2e70a6b0b53452765e5c4eb3849fb69639b5e5bba') { throw 'Formal V0.11.0 source baseline hash mismatch.' }

Expand-Archive -LiteralPath $BaselineSource -DestinationPath $Source
python build/v01101/apply_main_delta_v01101.py --target (Join-Path $Source 'app/src/main.py') --patch (Join-Path $V01101Delta 'main_v01101.patch') --expected-sha256 '84c03b6ec60969f87874077188a3bf6e32e91124e749cffe48ca7437982538c3'
if ($LASTEXITCODE -ne 0) { throw 'Deterministic V0.11.0.1 main delta failed.' }
Copy-Item -LiteralPath (Join-Path $V01101Delta 'video_import_alpha.py') -Destination (Join-Path $Source 'app/src/video_import_alpha.py') -Force
python build/v01102/apply_v01102_delta.py (Join-Path $Source 'app/src/main.py')
if ($LASTEXITCODE -ne 0) { throw 'Deterministic V0.11.0.2 main delta failed.' }
'0.11.0.2' | Set-Content -LiteralPath (Join-Path $Source 'app/assets/VERSION.txt') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $Root 'build/v01102/release-notes.md') -Destination (Join-Path $Source 'V01102_CHANGELOG.md') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v01101/test_v01101_transparent_webm_runtime.py') -Destination (Join-Path $Source 'tests/test_v01101_transparent_webm_runtime.py') -Force

python -m pip install --disable-pip-version-check -r (Join-Path $Source 'BUILD_DEPENDENCIES_V0100943.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependencies failed to install.' }

Push-Location $Source
try {
    $MainText = Get-Content -Raw -Encoding UTF8 'app/src/main.py'
    $HelperText = Get-Content -Raw -Encoding UTF8 'app/src/video_import_alpha.py'
    if (-not $MainText.Contains('APP_VERSION = "0.11.0.2"')) { throw 'V01102 contract failed: version.' }
    if (-not $MainText.Contains('convert_action_video(path,dst,max_width=420,target_fps=12)')) { throw 'V01102 contract failed: transparent action importer.' }
    if (-not $MainText.Contains('validate_update_ndm_download_root')) { throw 'V01102 contract failed: Desktop zero-landing helper.' }
    $Guard = $MainText.IndexOf('ndm_dir = validate_update_ndm_download_root(ndm_dir)')
    $Submit = $MainText.IndexOf('ndm_download_and_import(', $Guard)
    if ($Guard -lt 0 -or $Submit -lt 0 -or $Guard -ge $Submit) { throw 'V01102 contract failed: NDM guard is not before task submission.' }
    if (-not $MainText.Contains('小美丽不会删除、移动或覆盖桌面上的任何现有文件')) { throw 'V01102 contract failed: no-delete user message.' }
    if (-not $HelperText.Contains('imageio_ffmpeg.read_frames')) { throw 'V01102 contract failed: Alpha decoder.' }
    'V01102_CONTRACT_OK' | Tee-Object -FilePath $Evidence
    python tests/test_v01101_transparent_webm_runtime.py *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'Transparent WebM Alpha runtime test failed.' }

    $IconPath = Join-Path $Source 'app/assets/xiaomeili_icon.ico'
    $AssetsData = "$(Join-Path $Source 'app/assets');assets"
    $EntryPoint = Join-Path $Source 'app/src/main.py'
    python -m PyInstaller --windowed --name XiaoMeili --icon $IconPath `
      --distpath (Join-Path $DistRoot 'dist') --workpath (Join-Path $DistRoot 'work') --specpath (Join-Path $DistRoot 'spec') `
      --collect-all rapidocr --collect-all onnxruntime --collect-all soundfile --collect-all sounddevice `
      --collect-all dxcam --collect-all dashscope --collect-all websocket --collect-all imageio_ffmpeg `
      --hidden-import pynvml --hidden-import resource_e2e --hidden-import desktop_acceptance `
      --add-data $AssetsData $EntryPoint
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.2 candidate EXE build failed.' }
} finally { Pop-Location }

$Built = Join-Path $DistRoot 'dist/XiaoMeili'
$BuiltExe = Join-Path $Built 'XiaoMeili.exe'
$BuiltFFmpeg = Join-Path $Built '_internal/imageio_ffmpeg'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) { throw 'Built XiaoMeili.exe missing.' }
if (-not (Test-Path -LiteralPath $BuiltFFmpeg -PathType Container)) { throw 'imageio_ffmpeg runtime data missing from frozen build.' }
$FfmpegExe = Get-ChildItem -LiteralPath $BuiltFFmpeg -Recurse -File | Where-Object { $_.Name -match '^ffmpeg.*\.exe$' } | Select-Object -First 1
if ($null -eq $FfmpegExe) { throw 'Bundled FFmpeg executable missing; transparent WebM would fail after freezing.' }

$PreSourceDir = Join-Path $Work 'pre-source'
$PreSourceZip = Join-Path $PreSourceDir 'XiaoMeili_V0.11.0.2_SourceProject.zip'
python build/v01101/source_zip_v01101.py --source $Source --out $PreSourceZip
if ($LASTEXITCODE -ne 0) { throw 'Pre-self-test source archive build failed.' }
$BuiltAssets = Join-Path $Built '_internal/assets'
if (-not (Test-Path -LiteralPath $BuiltAssets)) { New-Item -ItemType Directory -Path $BuiltAssets | Out-Null }
Copy-Item -LiteralPath $PreSourceZip -Destination (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.2_SourceProject.zip')
if (-not (Test-Path -LiteralPath (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.2_SourceProject.zip') -PathType Leaf)) { throw 'Frozen source archive embed failed.' }

$env:QT_QPA_PLATFORM = 'offscreen'
& $BuiltExe --runtime-self-test *>&1 | Tee-Object -FilePath $Evidence -Append
if ($LASTEXITCODE -ne 0) { throw 'Frozen runtime self-test failed.' }
& $BuiltExe --settings-ui-self-test *>&1 | Tee-Object -FilePath $Evidence -Append
if ($LASTEXITCODE -ne 0) { throw 'Frozen settings UI self-test failed.' }

Expand-Archive -LiteralPath $BaselineUpdate -DestinationPath $Bundle
Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $Bundle 'XiaoMeili.exe') -Force
Copy-Item -LiteralPath (Join-Path $Source 'app/assets/VERSION.txt') -Destination (Join-Path $Bundle '_internal/assets/VERSION.txt') -Force
$BundleFFmpeg = Join-Path $Bundle '_internal/imageio_ffmpeg'
if (-not (Test-Path -LiteralPath $BundleFFmpeg)) { New-Item -ItemType Directory -Path $BundleFFmpeg | Out-Null }
Copy-Item -Path (Join-Path $BuiltFFmpeg '*') -Destination $BundleFFmpeg -Recurse -Force

python build/v01101/package_v01101.py --source $Source --bundle $Bundle --out $Out --version $Version --source-zip $PreSourceZip
if ($LASTEXITCODE -ne 0) { throw 'Package assembly or CRC verification failed.' }
$Meta = Get-Content -Raw -Encoding UTF8 (Join-Path $Out 'build-metadata.json') | ConvertFrom-Json
if ($Meta.version -ne $Version -or -not $Meta.all_pass) { throw 'Build metadata gate rejected.' }
Copy-Item -LiteralPath (Join-Path $Out 'build-metadata.json') -Destination (Join-Path $Work 'build-metadata.json')

gh release create "v$Version" --repo $Repo --target $env:GITHUB_SHA --latest=false --title '小美丽 V0.11.0.2｜透明 WebM + 更新桌面零落地' --notes-file 'build/v01102/release-notes.md' (Join-Path $Out 'XiaoMeili_0.11.0.2_update.zip') (Join-Path $Out 'XiaoMeili_V0.11.0.2_SourceProject.zip') (Join-Path $Out 'build-metadata.json')
if ($LASTEXITCODE -ne 0) { throw 'Formal release upload failed; safe manifest remains unchanged.' }

python build/v01101/public_readback_v01101.py --metadata (Join-Path $Out 'build-metadata.json') --out (Join-Path $Work 'public-readback.json')
if ($LASTEXITCODE -ne 0) { throw 'Public unauthenticated readback failed; safe manifest remains unchanged.' }

$Manifest = [ordered]@{
  protocol = 1
  version = $Version
  package_url = "https://github.com/$Repo/releases/download/v$Version/XiaoMeili_0.11.0.2_update.zip"
  sha256 = [string]$Meta.update.sha256
  package_size = [int64]$Meta.update.size
  notes = @(
    '动作库全部8类视频支持透明 WebM Alpha 直读，可直接导入自己已抠好的透明素材',
    '透明 WebM 跳过绿幕取色、抠绿和去绿边；无 Alpha 的 WebM 与其他视频继续原绿幕流程',
    '更新安全修正：NDM 更新目录若为桌面或桌面子目录，会在发送下载任务前停止，不再让更新 ZIP 落到桌面',
    '不会采用更新后自动删除桌面 ZIP 的方式，因此不会删除、移动或覆盖桌面已有文件',
    '保留一键深度资源测试、长时间交互诊断和闪退诊断 ZIP；这些诊断包不属于本次取消范围',
    '继续沿用 FullSafe 追加式安装、版本并存、回滚、现有配置与全部素材保留'
  )
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'latest_safe.json' -Encoding utf8NoBOM

git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fresh main fetch failed before promotion.' }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Main changed incompatibly; safe manifest not promoted.' }
git config user.name 'XiaoMeili Update Bot'
git config user.email 'actions@users.noreply.github.com'
git add latest_safe.json
git commit -m 'Promote V0.11.0.2 after Windows and public readback verification'
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest commit failed.' }
git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest push failed.' }
gh release edit "v$Version" --repo $Repo --latest=true
if ($LASTEXITCODE -ne 0) { throw 'Release latest marker failed after manifest promotion.' }
Write-Host 'V01102_FORMAL_RELEASE_PROMOTED_AFTER_ALL_GATES'
