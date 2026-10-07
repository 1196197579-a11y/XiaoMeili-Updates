$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '0.11.0.3.1'
$BaselineVersion = '0.11.0.3'
$Repo = $env:GITHUB_REPOSITORY
$Root = (Resolve-Path '.').Path
$Work = Join-Path $Root 'work-v011031'
$Baseline = Join-Path $Work 'baseline'
$Source = Join-Path $Work 'source'
$DistRoot = Join-Path $Work 'pyinstaller'
$Bundle = Join-Path $Work 'bundle'
$Out = Join-Path $Work 'out'
$Evidence = Join-Path $Work 'test-output.txt'

if (Test-Path -LiteralPath $Work) { throw 'Append-only build workspace already exists.' }
New-Item -ItemType Directory -Path $Baseline,$Out | Out-Null

gh release view "v$Version" --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) { throw "Formal release v$Version already exists; refusing to overwrite it." }

gh release download "v$BaselineVersion" --repo $Repo --dir $Baseline --pattern 'XiaoMeili_0.11.0.3_update.zip' --pattern 'XiaoMeili_V0.11.0.3_SourceProject.zip'
if ($LASTEXITCODE -ne 0) { throw 'Failed to download formal V0.11.0.3 baseline.' }
$BaselineUpdate = Join-Path $Baseline 'XiaoMeili_0.11.0.3_update.zip'
$BaselineSource = Join-Path $Baseline 'XiaoMeili_V0.11.0.3_SourceProject.zip'
$UpdateSha = (Get-FileHash -LiteralPath $BaselineUpdate -Algorithm SHA256).Hash.ToLowerInvariant()
$SourceSha = (Get-FileHash -LiteralPath $BaselineSource -Algorithm SHA256).Hash.ToLowerInvariant()
if ($UpdateSha -ne 'd2d30647d00187056e3548a19865208225c77fc65c276cf7af3bd67291e22aea') { throw 'Formal V0.11.0.3 update baseline hash mismatch.' }
if ($SourceSha -ne '96f0d86be89f6490bece83cf4ff57d246f530233080b60c9deb0c2d0888053ed') { throw 'Formal V0.11.0.3 source baseline hash mismatch.' }

Expand-Archive -LiteralPath $BaselineSource -DestinationPath $Source
python build/v011031/apply_v011031_hotfix.py (Join-Path $Source 'app/src/main.py') (Join-Path $Source 'app/src/desktop_actions.py')
if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3.1 hotfix delta failed.' }
'0.11.0.3.1' | Set-Content -LiteralPath (Join-Path $Source 'app/assets/VERSION.txt') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $Root 'build/v011031/release-notes.md') -Destination (Join-Path $Source 'V011031_CHANGELOG.md') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v011031/test_v011031_contract.py') -Destination (Join-Path $Source 'tests/test_v011031_contract.py') -Force

python -m pip install --disable-pip-version-check -r (Join-Path $Source 'BUILD_DEPENDENCIES_V0100943.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependencies failed to install.' }

Push-Location $Source
try {
    $MainText = Get-Content -Raw -Encoding UTF8 'app/src/main.py'
    $DesktopText = Get-Content -Raw -Encoding UTF8 'app/src/desktop_actions.py'
    if (-not $MainText.Contains('APP_VERSION = "0.11.0.3.1"')) { throw 'V011031 contract failed: version.' }
    if (-not $MainText.Contains('IDLE_MAX_ASSETS = 30')) { throw 'V011031 contract failed: idle cap.' }
    if ($MainText.Contains('target = desktop_dir() / "小美丽.exe"')) { throw 'V011031 contract failed: Desktop EXE generator remains.' }
    if (-not $DesktopText.Contains('def live_panel(self):')) { throw 'V011031 contract failed: template lifetime helper missing.' }
    if (-not $DesktopText.Contains('WA_DeleteOnClose, False')) { throw 'V011031 contract failed: dialog persistence missing.' }
    if (-not $DesktopText.Contains("'exit_chain': '爬出屏幕后接下一支动作'")) { throw 'V011031 regression: exit-chain missing.' }
    if (-not $DesktopText.Contains("'fixed': '固定位置播放（视频内部自己动）'")) { throw 'V011031 regression: fixed mode missing.' }
    if (-not $MainText.Contains('validate_update_ndm_download_root')) { throw 'V011031 regression: NDM guard missing.' }
    if (-not $MainText.Contains('asset_aliases')) { throw 'V011031 regression: asset aliases missing.' }

    'V011031_STATIC_CONTRACT_OK' | Tee-Object -FilePath $Evidence
    python tests/test_v011031_contract.py . *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3.1 contract/runtime test failed.' }
    python tests/test_v01101_transparent_webm_runtime.py *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'Transparent WebM runtime test failed.' }

    $IconPath = Join-Path $Source 'app/assets/xiaomeili_icon.ico'
    $AssetsData = "$(Join-Path $Source 'app/assets');assets"
    $EntryPoint = Join-Path $Source 'app/src/main.py'
    $PyArgs = @(
      '-m','PyInstaller','--windowed','--name','XiaoMeili','--icon',$IconPath,
      '--distpath',(Join-Path $DistRoot 'dist'),'--workpath',(Join-Path $DistRoot 'work'),'--specpath',(Join-Path $DistRoot 'spec'),
      '--collect-all','rapidocr','--collect-all','onnxruntime','--collect-all','soundfile','--collect-all','sounddevice',
      '--collect-all','dxcam','--collect-all','dashscope','--collect-all','websocket','--collect-all','imageio_ffmpeg',
      '--hidden-import','pynvml','--hidden-import','resource_e2e','--hidden-import','desktop_acceptance','--hidden-import','shiboken6',
      '--add-data',$AssetsData,$EntryPoint
    )
    python @PyArgs
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3.1 candidate EXE build failed.' }
} finally { Pop-Location }

$Built = Join-Path $DistRoot 'dist/XiaoMeili'
$BuiltExe = Join-Path $Built 'XiaoMeili.exe'
$BuiltFFmpeg = Join-Path $Built '_internal/imageio_ffmpeg'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) { throw 'Built XiaoMeili.exe missing.' }
if (-not (Test-Path -LiteralPath $BuiltFFmpeg -PathType Container)) { throw 'imageio_ffmpeg runtime data missing.' }
$FfmpegExe = Get-ChildItem -LiteralPath $BuiltFFmpeg -Recurse -File | Where-Object { $_.Name -match '^ffmpeg.*\.exe$' } | Select-Object -First 1
if ($null -eq $FfmpegExe) { throw 'Bundled FFmpeg executable missing.' }

$PreSourceDir = Join-Path $Work 'pre-source'
$PreSourceZip = Join-Path $PreSourceDir 'XiaoMeili_V0.11.0.3.1_SourceProject.zip'
python build/v01101/source_zip_v01101.py --source $Source --out $PreSourceZip
if ($LASTEXITCODE -ne 0) { throw 'Source archive build failed.' }
$BuiltAssets = Join-Path $Built '_internal/assets'
if (-not (Test-Path -LiteralPath $BuiltAssets)) { New-Item -ItemType Directory -Path $BuiltAssets | Out-Null }
Copy-Item -LiteralPath $PreSourceZip -Destination (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.3.1_SourceProject.zip')

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

$UpdateName = 'XiaoMeili_' + $Version + '_update.zip'
$SourceName = 'XiaoMeili_V' + $Version + '_SourceProject.zip'
gh release create "v$Version" --repo $Repo --target $env:GITHUB_SHA --latest=false --title '小美丽 V0.11.0.3.1｜V0.11.0.3 桌面动作模板热修复' --notes-file 'build/v011031/release-notes.md' (Join-Path $Out $UpdateName) (Join-Path $Out $SourceName) (Join-Path $Out 'build-metadata.json')
if ($LASTEXITCODE -ne 0) { throw 'Formal release upload failed; safe manifest remains unchanged.' }

python build/v01101/public_readback_v01101.py --metadata (Join-Path $Out 'build-metadata.json') --out (Join-Path $Work 'public-readback.json')
if ($LASTEXITCODE -ne 0) { throw 'Public readback failed; safe manifest remains unchanged.' }

$Manifest = [ordered]@{
  protocol = 1
  version = $Version
  package_url = "https://github.com/$Repo/releases/download/v$Version/$UpdateName"
  sha256 = [string]$Meta.update.sha256
  package_size = [int64]$Meta.update.size
  notes = @(
    '修复桌面动作模板真实测试/退出时偶发 libshiboken 已删除对象崩溃',
    '待机素材池单独扩展至 30 支；其余状态继续保持 20 支',
    '永久停用启动时自动在桌面生成“小美丽.exe”的旧机制；既有桌面文件完全不碰',
    '保留 V0.11.0.3 的美蜘蛛动作链、透明 WebM、素材重命名显示别名、模板置前与自适应布局',
    '继续保留 NDM 桌面零落地、FullSafe、旧版本回滚、现有配置与全部素材'
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
git commit -m 'Promote V0.11.0.3.1 after template lifetime and Desktop EXE safety verification'
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest commit failed.' }
git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest push failed.' }
gh release edit "v$Version" --repo $Repo --latest=true
if ($LASTEXITCODE -ne 0) { throw 'Release latest marker failed.' }
Write-Host 'V011031_FORMAL_RELEASE_PROMOTED_AFTER_ALL_GATES'
