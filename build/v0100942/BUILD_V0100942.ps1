param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$BaselineUpdateZip,
  [Parameter(Mandatory=$true)][string]$NewOutputDirectory
)
$ErrorActionPreference='Stop'
$SourceRoot=$PSScriptRoot
$BaselineExpected='d45cf82691335317fa33e4c5bf635ce869da298787b91249bec3fa414bd73722'
if ((Get-FileHash -LiteralPath $BaselineUpdateZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $BaselineExpected) { throw 'V0.10.0.9.4.1 runtime baseline SHA-256 mismatch' }
if (Test-Path -LiteralPath $NewOutputDirectory) { throw 'Output directory must be new; existing directories are never replaced' }
$Output=[System.IO.Path]::GetFullPath($NewOutputDirectory)
New-Item -ItemType Directory -Path $Output | Out-Null
$Build=Join-Path $Output 'build'
$Bundle=Join-Path $Output 'XiaoMeili'
$Src=Join-Path $SourceRoot 'app/src'
$Assets=Join-Path $SourceRoot 'app/assets'
$Icon=Join-Path $Assets 'xiaomeili_icon.ico'
& $Python -m PyInstaller --noconfirm --windowed --name XiaoMeili --icon $Icon --distpath (Join-Path $Build 'dist') --workpath (Join-Path $Build 'work') --specpath (Join-Path $Build 'spec') --collect-all rapidocr --collect-all onnxruntime --collect-all soundfile --collect-all sounddevice --collect-all dxcam --collect-all dashscope --collect-all websocket --hidden-import pynvml --hidden-import resource_e2e --add-data "$Assets;assets" (Join-Path $Src 'main.py')
if ($LASTEXITCODE -ne 0) { throw 'Main EXE build failed' }
& $Python -m PyInstaller --noconfirm --noconsole --name XiaoMeiliResourceMonitor --distpath (Join-Path $Build 'monitor-dist') --workpath (Join-Path $Build 'monitor-work') --specpath (Join-Path $Build 'monitor-spec') --hidden-import pynvml (Join-Path $Src 'resource_monitor_v0100941.py')
if ($LASTEXITCODE -ne 0) { throw 'Monitor EXE build failed' }
# Keep exact verified baseline runtime DLLs. Local PyInstaller discovery selected
# system CRT/API shim DLLs that failed Qt initialization on this machine.
# Only newly extracted staging files are updated; no installed files are touched.
Expand-Archive -LiteralPath $BaselineUpdateZip -DestinationPath $Bundle
Copy-Item -LiteralPath (Join-Path $Build 'dist/XiaoMeili/XiaoMeili.exe') -Destination (Join-Path $Bundle 'XiaoMeili.exe')
Copy-Item -LiteralPath (Join-Path $Build 'monitor-dist/XiaoMeiliResourceMonitor/XiaoMeiliResourceMonitor.exe') -Destination (Join-Path $Bundle 'ResourceMonitor/XiaoMeiliResourceMonitor.exe')
Copy-Item -LiteralPath (Join-Path $Assets 'VERSION.txt') -Destination (Join-Path $Bundle '_internal/assets/VERSION.txt')
Write-Host "Local candidate built: $Bundle"
Write-Host 'This command does not upload, publish, install, change active.json, or update latest_safe.json.'
