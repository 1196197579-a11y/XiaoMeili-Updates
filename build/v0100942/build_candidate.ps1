$ErrorActionPreference='Stop'
$Repo='1196197579-a11y/XiaoMeili-Updates'
$Task=Join-Path $env:RUNNER_TEMP ('xm942-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Task | Out-Null
$Source=Join-Path $Task 'source'
$SourceZip=Join-Path $Task 'baseline-source.zip'
$UpdateZip=Join-Path $Task 'baseline-update.zip'
Invoke-WebRequest -Uri "https://github.com/$Repo/releases/download/v0.10.0.9.4.1/XiaoMeili_V0.10.0.9.4.1_SourceProject.zip" -OutFile $SourceZip
Invoke-WebRequest -Uri "https://github.com/$Repo/releases/download/v0.10.0.9.4.1/XiaoMeili_0.10.0.9.4.1_update.zip" -OutFile $UpdateZip
if ((Get-FileHash $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'a45f2ead718df50d3042c08d17760f4af5ea4e3261e6b1c7afc902cc0fac1cf0') { throw 'Baseline source mismatch' }
if ((Get-FileHash $UpdateZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'd45cf82691335317fa33e4c5bf635ce869da298787b91249bec3fa414bd73722') { throw 'Baseline update mismatch' }
Expand-Archive -LiteralPath $SourceZip -DestinationPath $Source
$BuildFiles=Join-Path (Get-Location).Path 'build/v0100942'
python (Join-Path $BuildFiles 'normalize_patch.py') $Source $BuildFiles
if ($LASTEXITCODE -ne 0) { throw 'Line ending normalization failed' }
Push-Location $Source
try { git apply (Join-Path $BuildFiles 'changes.diff'); if ($LASTEXITCODE -ne 0) { throw 'Patch apply failed' } } finally { Pop-Location }
foreach($Name in @('BUILD_V0100942.ps1','BUILD_DEPENDENCIES_V0100942.txt','V0100942_ACCEPTANCE.md')) {
  Copy-Item -LiteralPath (Join-Path $BuildFiles $Name) -Destination (Join-Path $Source $Name)
}
New-Item -ItemType Directory -Path (Join-Path $Source 'acceptance') | Out-Null
foreach($Name in @('run_acceptance942.py','run_selftests942.py','test_startup942.py')) {
  Copy-Item -LiteralPath (Join-Path $BuildFiles $Name) -Destination (Join-Path $Source "acceptance/$Name")
}
python -m pip install -r (Join-Path $Source 'BUILD_DEPENDENCIES_V0100942.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed' }
python (Join-Path $BuildFiles 'verify_source.py') $Source (Join-Path $BuildFiles 'expected-source.json')
if ($LASTEXITCODE -ne 0) { throw 'Source differs from locally tested repair' }
$Output=Join-Path $Task 'output'
& (Join-Path $Source 'BUILD_V0100942.ps1') -Python (Get-Command python).Source -BaselineUpdateZip $UpdateZip -NewOutputDirectory $Output
$Bundle=Join-Path $Output 'XiaoMeili'
$Artifacts=Join-Path (Get-Location).Path 'candidate-artifacts942'
New-Item -ItemType Directory -Path $Artifacts | Out-Null
python (Join-Path $BuildFiles 'package_candidate.py') $Source $Bundle $Artifacts
if ($LASTEXITCODE -ne 0) { throw 'Candidate packaging failed' }
python 'build/v010092/test_ndm_fast_fallback_v010092.py' $Source
if ($LASTEXITCODE -ne 0) { throw 'NDM failed' }
python 'build/v010092/test_fullsafe_no_delete_v010092.py' $Source
if ($LASTEXITCODE -ne 0) { throw 'FullSafe failed' }
python (Join-Path $BuildFiles 'run_selftests942.py') (Join-Path $Bundle 'XiaoMeili.exe')
if ($LASTEXITCODE -ne 0) { throw 'Packaged self-tests failed' }
Write-Host 'CANDIDATE_BUILD_PASS; NOT RELEASED; latest_safe.json UNCHANGED'
