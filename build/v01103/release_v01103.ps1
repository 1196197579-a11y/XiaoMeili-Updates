$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '0.11.0.3'
$BaselineVersion = '0.11.0'
$Repo = $env:GITHUB_REPOSITORY
$Root = (Resolve-Path '.').Path
$Work = Join-Path $Root 'work-v01103'
$Baseline = Join-Path $Work 'baseline'
$Source = Join-Path $Work 'source'
$DistRoot = Join-Path $Work 'pyinstaller'
$Bundle = Join-Path $Work 'bundle'
$Out = Join-Path $Work 'out'
$Evidence = Join-Path $Work 'test-output.txt'
$V01101Delta = Join-Path $Root 'build/v01101/source-delta'

# Builder workspace is repository-local and append-only. Never use Desktop,
# Documents, Downloads, or another user folder as a cleanup target.
if (Test-Path -LiteralPath $Work) { throw 'Append-only build workspace already exists.' }
New-Item -ItemType Directory -Path $Baseline,$Out | Out-Null

gh release view "v$Version" --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) { throw "Formal release v$Version already exists; refusing to overwrite it." }

# Reconstruct from the immutable formal V0.11.0 baseline, then replay the
# already-verified V0.11.0.1 and V0.11.0.2 deltas before applying V0.11.0.3.
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
python build/v01103/apply_v01103_delta.py (Join-Path $Source 'app/src/main.py') (Join-Path $Source 'app/src/desktop_actions.py')
if ($LASTEXITCODE -ne 0) { throw 'Deterministic V0.11.0.3 delta failed.' }
'0.11.0.3' | Set-Content -LiteralPath (Join-Path $Source 'app/assets/VERSION.txt') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $Root 'build/v01102/release-notes.md') -Destination (Join-Path $Source 'V01102_CHANGELOG.md') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v01103/release-notes.md') -Destination (Join-Path $Source 'V01103_CHANGELOG.md') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v01101/test_v01101_transparent_webm_runtime.py') -Destination (Join-Path $Source 'tests/test_v01101_transparent_webm_runtime.py') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v01103/test_v01103_contract.py') -Destination (Join-Path $Source 'tests/test_v01103_contract.py') -Force

python -m pip install --disable-pip-version-check -r (Join-Path $Source 'BUILD_DEPENDENCIES_V0100943.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependencies failed to install.' }

Push-Location $Source
try {
    $MainText = Get-Content -Raw -Encoding UTF8 'app/src/main.py'
    $DesktopText = Get-Content -Raw -Encoding UTF8 'app/src/desktop_actions.py'
    $HelperText = Get-Content -Raw -Encoding UTF8 'app/src/video_import_alpha.py'

    if (-not $MainText.Contains('APP_VERSION = "0.11.0.3"')) { throw 'V01103 contract failed: version.' }
    if (-not $MainText.Contains('convert_action_video(path,dst,max_width=420,target_fps=12)')) { throw 'V01103 contract failed: transparent action importer.' }
    if (-not $HelperText.Contains('imageio_ffmpeg.read_frames')) { throw 'V01103 contract failed: Alpha decoder.' }

    # V0.11.0.2 no-Desktop-landing protection is a non-regression gate.
    if (-not $MainText.Contains('validate_update_ndm_download_root')) { throw 'V01103 contract failed: Desktop zero-landing helper missing.' }
    $Guard = $MainText.IndexOf('ndm_dir = validate_update_ndm_download_root(ndm_dir)')
    $Submit = $MainText.IndexOf('ndm_download_and_import(', $Guard)
    if ($Guard -lt 0 -or $Submit -lt 0 -or $Guard -ge $Submit) { throw 'V01103 contract failed: NDM guard is not before task submission.' }
    if (-not $MainText.Contains('小美丽不会删除、移动或覆盖桌面上的任何现有文件')) { throw 'V01103 contract failed: no-delete update contract missing.' }

    # V0.11.0.3 linkage/template/rename contracts.
    if (-not $DesktopText.Contains("'exit_chain': '爬出屏幕后接下一支动作'")) { throw 'V01103 contract failed: exit-chain missing.' }
    if (-not $DesktopText.Contains("'fixed': '固定位置播放（视频内部自己动）'")) { throw 'V01103 contract failed: fixed-position mode missing.' }
    if (-not $DesktopText.Contains('WindowModal if parent_window is not None')) { throw 'V01103 contract failed: template stacking fix missing.' }
    if (-not $MainText.Contains('不改原文件名、不移动、不覆盖文件')) { throw 'V01103 contract failed: safe display rename missing.' }

    'V01103_STATIC_CONTRACT_OK' | Tee-Object -FilePath $Evidence
    python tests/test_v01101_transparent_webm_runtime.py *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'Transparent WebM Alpha runtime test failed.' }
    python tests/test_v01103_contract.py . *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3 desktop linkage contract test failed.' }

    $IconPath = Join-Path $Source 'app/assets/xiaomeili_icon.ico'
    $AssetsData = "$(Join-Path $Source 'app/assets');assets"
    $EntryPoint = Join-Path $Source 'app/src/main.py'
    python -m PyInstaller --windowed --name XiaoMeili --icon $IconPath `
      --distpath (Join-Path $DistRoot 'dist') --workpath (Join-Path $DistRoot 'work') --specpath (Join-Path $DistRoot 'spec') `
      --collect-all rapidocr --collect-all onnxruntime --collect-all soundfile --collect-all sounddevice `
      --collect-all dxcam --collect-all dashscope --collect-all websocket --collect-all imageio_ffmpeg `
      --hidden-import pynvml --hidden-import resource_e2e --hidden-import desktop_acceptance `
      --add-data $AssetsData $EntryPoint
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3 candidate EXE build failed.' }
} finally { Pop-Location }

$Built = Join-Path $DistRoot 'dist/XiaoMeili'
$BuiltExe = Join-Path $Built 'XiaoMeili.exe'
$BuiltFFmpeg = Join-Path $Built '_internal/imageio_ffmpeg'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) { throw 'Built XiaoMeili.exe missing.' }
if (-not (Test-Path -LiteralPath $BuiltFFmpeg -PathType Container)) { throw 'imageio_ffmpeg runtime data missing from frozen build.' }
$FfmpegExe = Get-ChildItem -LiteralPath $BuiltFFmpeg -Recurse -File | Where-Object { $_.Name -match '^ffmpeg.*\.exe$' } | Select-Object -First 1
if ($null -eq $FfmpegExe) { throw 'Bundled FFmpeg executable missing; transparent WebM would fail after freezing.' }

# Embed the exact tested source used by this frozen EXE for later append-only work.
$PreSourceDir = Join-Path $Work 'pre-source'
$PreSourceZip = Join-Path $PreSourceDir 'XiaoMeili_V0.11.0.3_SourceProject.zip'
python build/v01101/source_zip_v01101.py --source $Source --out $PreSourceZip
if ($LASTEXITCODE -ne 0) { throw 'Pre-self-test source archive build failed.' }
$BuiltAssets = Join-Path $Built '_internal/assets'
if (-not (Test-Path -LiteralPath $BuiltAssets)) { New-Item -ItemType Directory -Path $BuiltAssets | Out-Null }
Copy-Item -LiteralPath $PreSourceZip -Destination (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.3_SourceProject.zip')
if (-not (Test-Path -LiteralPath (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.3_SourceProject.zip') -PathType Leaf)) { throw 'Frozen source archive embed failed.' }

# Frozen Windows gates. The public update manifest is not touched unless all pass.
$env:QT_QPA_PLATFORM = 'offscreen'
& $BuiltExe --runtime-self-test *>&1 | Tee-Object -FilePath $Evidence -Append
if ($LASTEXITCODE -ne 0) { throw 'Frozen runtime self-test failed.' }
& $BuiltExe --settings-ui-self-test *>&1 | Tee-Object -FilePath $Evidence -Append
if ($LASTEXITCODE -ne 0) { throw 'Frozen settings UI self-test failed.' }

# Start from the immutable V0.11.0 update bundle so old source archives are not
# repeatedly accumulated. Replace only app-owned runtime/version components.
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

gh release create "v$Version" --repo $Repo --target $env:GITHUB_SHA --latest=false --title '小美丽 V0.11.0.3｜桌面动作联动与模板修复' --notes-file 'build/v01103/release-notes.md' (Join-Path $Out 'XiaoMeili_0.11.0.3_update.zip') (Join-Path $Out 'XiaoMeili_V0.11.0.3_SourceProject.zip') (Join-Path $Out 'build-metadata.json')
if ($LASTEXITCODE -ne 0) { throw 'Formal release upload failed; safe manifest remains unchanged.' }

python build/v01101/public_readback_v01101.py --metadata (Join-Path $Out 'build-metadata.json') --out (Join-Path $Work 'public-readback.json')
if ($LASTEXITCODE -ne 0) { throw 'Public unauthenticated readback failed; safe manifest remains unchanged.' }

$Manifest = [ordered]@{
  protocol = 1
  version = $Version
  package_url = "https://github.com/$Repo/releases/download/v$Version/XiaoMeili_0.11.0.3_update.zip"
  sha256 = [string]$Meta.update.sha256
  package_size = [int64]$Meta.update.size
  notes = @(
    '新增“爬出屏幕后接下一支动作”：完整离屏后无闪回接续指定桌面动作',
    '新增“固定位置播放（视频内部自己动）”：适合美蜘蛛这类视频内部已有悬挂/摆动的透明素材',
    '下一支动作仅在两种接续结束行为中生效，并使用下一支动作自己的模板位置与运动方式',
    '修复从管理素材池打开模板时模板页被压到下方的问题；模板窗口主动置前并采用窗口模态',
    '桌面动作模板改为屏幕自适应与滚动布局，修复小屏/缩放环境下参数显示不完整',
    '管理素材池支持右键重命名；只保存显示别名，不改文件名、不移动、不覆盖、不删除任何素材文件',
    '完整保留透明 WebM、NDM 桌面零落地、FullSafe、旧版本回滚、现有配置与全部素材'
  )
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'latest_safe.json' -Encoding utf8NoBOM

# Promote only after build, frozen self-tests, packaging, upload and public
# unauthenticated readback all succeed.
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fresh main fetch failed before promotion.' }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Main changed incompatibly; safe manifest not promoted.' }
git config user.name 'XiaoMeili Update Bot'
git config user.email 'actions@users.noreply.github.com'
git add latest_safe.json
git commit -m 'Promote V0.11.0.3 after Windows and public readback verification'
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest commit failed.' }
git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest push failed.' }
gh release edit "v$Version" --repo $Repo --latest=true
if ($LASTEXITCODE -ne 0) { throw 'Release latest marker failed after manifest promotion.' }
Write-Host 'V01103_FORMAL_RELEASE_PROMOTED_AFTER_ALL_GATES'
