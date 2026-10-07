$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '0.11.0.3.2'
$BaselineVersion = '0.11.0.3.1'
$Repo = $env:GITHUB_REPOSITORY
$Root = (Resolve-Path '.').Path
$Work = Join-Path $Root 'work-v011032'
$Baseline = Join-Path $Work 'baseline'
$Source = Join-Path $Work 'source'
$DistRoot = Join-Path $Work 'pyinstaller'
$Bundle = Join-Path $Work 'bundle'
$Out = Join-Path $Work 'out'
$Evidence = Join-Path $Work 'test-output.txt'

if (Test-Path -LiteralPath $Work) { throw 'Append-only build workspace already exists.' }
New-Item -ItemType Directory -Path $Baseline,$Out | Out-Null

gh release view "v$Version" --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) { throw "Formal release v$Version already exists." }

gh release download "v$BaselineVersion" --repo $Repo --dir $Baseline --pattern 'XiaoMeili_0.11.0.3.1_update.zip' --pattern 'XiaoMeili_V0.11.0.3.1_SourceProject.zip'
if ($LASTEXITCODE -ne 0) { throw 'Failed to download formal baseline.' }

$BaselineUpdate = Join-Path $Baseline 'XiaoMeili_0.11.0.3.1_update.zip'
$BaselineSource = Join-Path $Baseline 'XiaoMeili_V0.11.0.3.1_SourceProject.zip'
$UpdateSha = (Get-FileHash -LiteralPath $BaselineUpdate -Algorithm SHA256).Hash.ToLowerInvariant()
$SourceSha = (Get-FileHash -LiteralPath $BaselineSource -Algorithm SHA256).Hash.ToLowerInvariant()
if ($UpdateSha -ne '28c30218288407e357144bdea529c0c0635aee992062bef5f419b520e34c08a0') { throw 'Baseline update hash mismatch.' }
if ($SourceSha -ne 'dda2f45a3cb40b9fb04e31286a0c5b2c100f6f5acd84fc40206b87c4b17611cd') { throw 'Baseline source hash mismatch.' }

Expand-Archive -LiteralPath $BaselineSource -DestinationPath $Source
python build/v011032/normalize_then_apply_v011032.py build/v011032/apply_v011032_delta.py (Join-Path $Source 'app/src/main.py') (Join-Path $Source 'app/src/native_updater.py')
if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3.2 delta failed.' }
'0.11.0.3.2' | Set-Content -LiteralPath (Join-Path $Source 'app/assets/VERSION.txt') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $Root 'build/v011032/release-notes.md') -Destination (Join-Path $Source 'V011032_CHANGELOG.md') -Force
Copy-Item -LiteralPath (Join-Path $Root 'build/v011032/test_v011032_contract.py') -Destination (Join-Path $Source 'tests/test_v011032_contract.py') -Force

python -m pip install --disable-pip-version-check -r (Join-Path $Source 'BUILD_DEPENDENCIES_V0100943.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependencies failed to install.' }

Push-Location $Source
try {
    $MainText = Get-Content -Raw -Encoding UTF8 'app/src/main.py'
    $NativeText = Get-Content -Raw -Encoding UTF8 'app/src/native_updater.py'
    if (-not $MainText.Contains('APP_VERSION = "0.11.0.3.2"')) { throw 'version contract failed.' }
    if (-not $MainText.Contains('uf.addRow("下载方式", update_dl_row)')) { throw 'update download selector missing.' }
    if ($MainText.Contains('bg.addRow("下载方式", mode_row)')) { throw 'selector still duplicated in Components.' }
    if (-not $MainText.Contains('allow_external_current=True')) { throw 'external current compatibility missing.' }
    if (-not $NativeText.Contains('current_was_managed')) { throw 'native updater compatibility metadata missing.' }
    if (-not $MainText.Contains('IDLE_MAX_ASSETS = 30')) { throw 'idle 30 regression.' }
    if (-not $MainText.Contains('桌面 EXE 自动生成已禁用')) { throw 'desktop EXE regression.' }
    if (-not $DesktopText.Contains("'exit_chain': '爬出屏幕后接下一支动作'")) { throw 'desktop chain regression.' }
    if (-not $MainText.Contains('convert_action_video(path,dst,max_width=420,target_fps=12)')) { throw 'transparent WebM regression.' }

    'V011032_STATIC_CONTRACT_OK' | Tee-Object -FilePath $Evidence
    python tests/test_v011032_contract.py . *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'V0.11.0.3.2 contract test failed.' }
    python tests/test_v01101_transparent_webm_runtime.py *>&1 | Tee-Object -FilePath $Evidence -Append
    if ($LASTEXITCODE -ne 0) { throw 'Transparent WebM test failed.' }

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
    if ($LASTEXITCODE -ne 0) { throw 'candidate EXE build failed.' }
} finally { Pop-Location }

$Built = Join-Path $DistRoot 'dist/XiaoMeili'
$BuiltExe = Join-Path $Built 'XiaoMeili.exe'
$BuiltFFmpeg = Join-Path $Built '_internal/imageio_ffmpeg'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) { throw 'Built XiaoMeili.exe missing.' }
if (-not (Test-Path -LiteralPath $BuiltFFmpeg -PathType Container)) { throw 'imageio_ffmpeg missing.' }

$PreSourceDir = Join-Path $Work 'pre-source'
$PreSourceZip = Join-Path $PreSourceDir 'XiaoMeili_V0.11.0.3.2_SourceProject.zip'
python build/v01101/source_zip_v01101.py --source $Source --out $PreSourceZip
if ($LASTEXITCODE -ne 0) { throw 'Source archive build failed.' }
$BuiltAssets = Join-Path $Built '_internal/assets'
if (-not (Test-Path -LiteralPath $BuiltAssets)) { New-Item -ItemType Directory -Path $BuiltAssets | Out-Null }
Copy-Item -LiteralPath $PreSourceZip -Destination (Join-Path $BuiltAssets 'XiaoMeili_V0.11.0.3.2_SourceProject.zip')

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
if ($LASTEXITCODE -ne 0) { throw 'Package assembly failed.' }
$Meta = Get-Content -Raw -Encoding UTF8 (Join-Path $Out 'build-metadata.json') | ConvertFrom-Json
if ($Meta.version -ne $Version -or -not $Meta.all_pass) { throw 'Build metadata gate rejected.' }
Copy-Item -LiteralPath (Join-Path $Out 'build-metadata.json') -Destination (Join-Path $Work 'build-metadata.json')

$UpdateName = 'XiaoMeili_' + $Version + '_update.zip'
$SourceName = 'XiaoMeili_V' + $Version + '_SourceProject.zip'
gh release create "v$Version" --repo $Repo --target $env:GITHUB_SHA --latest=false --title '小美丽 V0.11.0.3.2｜更新链路与下载方式修复' --notes-file 'build/v011032/release-notes.md' (Join-Path $Out $UpdateName) (Join-Path $Out $SourceName) (Join-Path $Out 'build-metadata.json')
if ($LASTEXITCODE -ne 0) { throw 'Release upload failed.' }

python build/v01101/public_readback_v01101.py --metadata (Join-Path $Out 'build-metadata.json') --out (Join-Path $Work 'public-readback.json')
if ($LASTEXITCODE -ne 0) { throw 'Public readback failed.' }

$Manifest = [ordered]@{
  protocol = 1
  version = $Version
  package_url = "https://github.com/$Repo/releases/download/v$Version/$UpdateName"
  sha256 = [string]$Meta.update.sha256
  package_size = [int64]$Meta.update.size
  notes = @(
    '修复当前从桌面测试副本启动时更新报“当前程序不在受保护的 versions 目录中”',
    '下载方式、NDM 测试与下载目录已迁移到“系统 → 更新”',
    '内置下载器作为推荐选项；NDM 继续保留为可选项并支持失败回退',
    '保留待机 30 支、桌面动作模板热修复、透明 WebM、美蜘蛛动作链与素材显示别名',
    '继续保留 FullSafe、受保护版本目录与旧版本回滚'
  )
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'latest_safe.json' -Encoding utf8NoBOM

git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fresh main fetch failed.' }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Main changed incompatibly.' }
git config user.name 'XiaoMeili Update Bot'
git config user.email 'actions@users.noreply.github.com'
git add latest_safe.json
git commit -m 'Promote V0.11.0.3.2 after Windows update-flow verification'
if ($LASTEXITCODE -ne 0) { throw 'Manifest commit failed.' }
git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Manifest push failed.' }
gh release edit "v$Version" --repo $Repo --latest=true
if ($LASTEXITCODE -ne 0) { throw 'Release latest marker failed.' }
Write-Host 'V011032_FORMAL_RELEASE_PROMOTED_AFTER_ALL_GATES'
