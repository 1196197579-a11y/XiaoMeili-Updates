$ErrorActionPreference='Stop'
$Repo='1196197579-a11y/XiaoMeili-Updates'
$Proof=Get-Content 'release/v0100942/release-gates.json' -Raw | ConvertFrom-Json
if (-not $Proof.all_local_gates_pass -or $Proof.normal_count -ne 3 -or $Proof.crash_count -ne 1) { throw 'Local packaged acceptance gates incomplete' }
if (@($Proof.tests | Where-Object {-not $_.pass -or $_.exit_code -ne 0}).Count -ne 0) { throw 'Failed acceptance gate' }
$ManifestBefore=Get-Content 'latest_safe.json' -Raw | ConvertFrom-Json
if ($ManifestBefore.version -ne '0.10.0.9.4.1') { throw 'Safe-channel baseline changed; promotion requires fresh review' }
$Task=Join-Path $env:RUNNER_TEMP ('xm942-public-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Task | Out-Null
$AssetDir=Join-Path $Task 'assets'
New-Item -ItemType Directory -Path $AssetDir | Out-Null
gh run download $Proof.candidate_run_id --repo $Repo --name $Proof.candidate_artifact_name --dir $AssetDir
if ($LASTEXITCODE -ne 0) { throw 'Exact accepted artifact download failed' }
$Metadata=Get-Content (Join-Path $AssetDir 'candidate.json') -Raw | ConvertFrom-Json
if ($Metadata.main_exe_sha256 -ne $Proof.main_exe_sha256 -or $Metadata.monitor_exe_sha256 -ne $Proof.monitor_exe_sha256) { throw 'Accepted executable provenance mismatch' }
$Files=@()
foreach($Prop in $Proof.assets.psobject.Properties) {
  $Path=Join-Path $AssetDir $Prop.Name
  if ((Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Prop.Value.sha256 -or (Get-Item $Path).Length -ne $Prop.Value.size) { throw 'Accepted candidate asset mismatch' }
  $Files += $Path
}
if ($Files.Count -ne 2) { throw 'Expected source and update assets' }
$Readbacks=@()
function Verify-PublicAssets([string]$Tag) {
  foreach($Prop in $Proof.assets.psobject.Properties) {
    $Verify=Join-Path $Task ($Tag+'-'+$Prop.Name)
    $Url="https://github.com/$Repo/releases/download/$Tag/$($Prop.Name)"
    Invoke-WebRequest -Uri $Url -OutFile $Verify
    $Hash=(Get-FileHash $Verify -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Hash -ne $Prop.Value.sha256 -or (Get-Item $Verify).Length -ne $Prop.Value.size) { throw "Public hash mismatch: $Url" }
    $script:Readbacks += [ordered]@{url=$Url;sha256=$Hash;size=(Get-Item $Verify).Length}
  }
}
# A prerelease is excluded from the user's safe updater. Both public candidate
# assets must pass unauthenticated downloads before the formal release exists.
$Rc='v0.10.0.9.4.2-rc1'
gh release create $Rc @Files --repo $Repo --target $env:GITHUB_SHA --prerelease --latest=false --title 'XiaoMeili V0.10.0.9.4.2 verified staging candidate' --notes 'Staging assets for public SHA-256 readback. Not in latest_safe.json. Three real packaged button runs and host-crash survival have passed.'
if ($LASTEXITCODE -ne 0) { throw 'Candidate public staging failed; existing assets are never overwritten' }
Verify-PublicAssets $Rc
$Tag='v0.10.0.9.4.2'
gh release create $Tag @Files --repo $Repo --target $env:GITHUB_SHA --latest=false --title 'XiaoMeili V0.10.0.9.4.2' --notes 'Fixes startup Path exceptions and adds bounded startup failure reports and actual UI progress acknowledgement. The final packaged main-app button chain passed three consecutive real ASR/brain/TTS runs with report ZIPs; an abnormal host exit produced an independent external-monitor crash ZIP. NDM, FullSafe and packaged runtime/settings UI self-tests passed. Full user test phases and natural TTS behavior are retained. Public source and update candidate hashes were re-downloaded before this release.'
if ($LASTEXITCODE -ne 0) { throw 'Formal release failed; safe manifest remains unchanged' }
Verify-PublicAssets $Tag
$Readbacks | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $AssetDir 'public-readback.json') -Encoding utf8
gh release upload $Tag (Join-Path $AssetDir 'public-readback.json') 'release/v0100942/release-gates.json' --repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Release evidence upload failed' }
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fresh main fetch failed' }
git switch -c ('safe942-'+[guid]::NewGuid().ToString('N')) origin/main
if ($LASTEXITCODE -ne 0) { throw 'Main staging checkout failed' }
$Fresh=Get-Content 'latest_safe.json' -Raw | ConvertFrom-Json
if ($Fresh.version -ne '0.10.0.9.4.1') { throw 'Main changed during validation; safe promotion stopped' }
$Update=$Proof.assets.'XiaoMeili_0.10.0.9.4.2_update.zip'
$Manifest=[ordered]@{protocol=1;version='0.10.0.9.4.2';package_url="https://github.com/$Repo/releases/download/$Tag/XiaoMeili_0.10.0.9.4.2_update.zip";sha256=$Update.sha256;package_size=[int64]$Update.size;notes=@('修复深度资源测试启动阶段的Path异常，完整启动链每步10秒超时生成失败报告','正式打包主程序真实按钮链路连续3次通过，完成ASR、大脑、自然TTS和诊断ZIP','宿主异常退出后外部监控器独立生成crash ZIP；NDM、FullSafe、runtime和settings UI自检通过','保留白板、动画、30轮聊天、离线识别、综合满载、90秒回落；禁止强制TTS abort和伪造闭嘴ASR','公开更新包和源码包均重新下载通过SHA-256验证；FullSafe用户文件保护规则不变')}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content 'latest_safe.json' -Encoding utf8
git config user.name 'XiaoMeili Update Bot'
git config user.email 'actions@users.noreply.github.com'
git add latest_safe.json
git commit -m 'Promote V0.10.0.9.4.2 after packaged E2E, crash survival and public SHA-256 readback'
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest commit failed' }
git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Safe manifest push failed' }
gh release edit $Tag --repo $Repo --latest
if ($LASTEXITCODE -ne 0) { throw 'Release latest marker failed; inspect manifest separately' }
Write-Host 'V0100942_ALL_GATES_PASSED_AND_PROMOTED'
