param(
  [Parameter(Mandatory=$true)][int]$ParentPid,
  [Parameter(Mandatory=$true)][string]$SessionDir,
  [Parameter(Mandatory=$true)][string]$DesktopDir,
  [Parameter(Mandatory=$true)][string]$AppVersion,
  [Parameter(Mandatory=$false)][string]$StartedUtc = ""
)

$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function New-UniquePath([string]$Dir,[string]$Stem,[string]$Ext) {
  if(-not (Test-Path -LiteralPath $Dir)) { [IO.Directory]::CreateDirectory($Dir) | Out-Null }
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $p = Join-Path $Dir ($Stem + "_" + $stamp + $Ext)
  $n = 1
  while(Test-Path -LiteralPath $p) {
    $p = Join-Path $Dir ($Stem + "_" + $stamp + "_" + $n + $Ext)
    $n++
  }
  return $p
}

function Redact([string]$Text) {
  $v = [string]$Text
  if($env:USERPROFILE) { $v = $v.Replace($env:USERPROFILE, "<USERPROFILE>") }
  if($env:USERNAME) { $v = $v.Replace($env:USERNAME, "<USER>") }
  return $v
}

$session = [IO.Path]::GetFullPath($SessionDir)
$desktop = [IO.Path]::GetFullPath($DesktopDir)
if(-not (Test-Path -LiteralPath $session -PathType Container)) { exit 0 }

$finalFlag = Join-Path $session "finalized.flag"
$startedMarker = Join-Path $session "watchdog_started.json"
if(-not (Test-Path -LiteralPath $startedMarker)) {
  $obj = [ordered]@{
    watchdog = "v0100934"
    parent_pid = $ParentPid
    app_version = $AppVersion
    started_utc = $(if($StartedUtc){$StartedUtc}else{(Get-Date).ToUniversalTime().ToString("o")})
    safety = "append/copy only; no delete, no move, no overwrite"
  }
  $json = $obj | ConvertTo-Json -Depth 4
  try {
    $fs=[IO.File]::Open($startedMarker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
    try { $sw=New-Object IO.StreamWriter($fs,[Text.UTF8Encoding]::new($false)); $sw.Write($json); $sw.Flush(); $sw.Dispose() } finally { if($fs){$fs.Dispose()} }
  } catch {}
}

while($true) {
  if(Test-Path -LiteralPath $finalFlag) { exit 0 }
  $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
  if(-not $p) { break }
  Start-Sleep -Milliseconds 700
}

Start-Sleep -Seconds 2
if(Test-Path -LiteralPath $finalFlag) { exit 0 }

$evidence = New-UniquePath $session "watchdog_exit_evidence" ".txt"
$eventEvidence = New-UniquePath $session "windows_event_crash_evidence" ".txt"

$lastStatus = ""
$statusFile = Join-Path $session "live_status.jsonl"
if(Test-Path -LiteralPath $statusFile) {
  try { $lastStatus = (Get-Content -LiteralPath $statusFile -Tail 1 -Encoding UTF8) } catch {}
}
$lastEvents = ""
$eventsFile = Join-Path $session "live_events.jsonl"
if(Test-Path -LiteralPath $eventsFile) {
  try { $lastEvents = ((Get-Content -LiteralPath $eventsFile -Tail 12 -Encoding UTF8) -join [Environment]::NewLine) } catch {}
}

$procLines = @()
foreach($name in @("crashrpt","XiaoMeili","SogouCloud","SogouImeBroker")) {
  try {
    Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
      $procLines += ("name={0} pid={1} path={2}" -f $_.ProcessName,$_.Id,(Redact $_.Path))
    }
  } catch {}
}

$body = @"
watchdog=v0100934
app_version=$AppVersion
parent_pid=$ParentPid
observed_parent_exit_utc=$((Get-Date).ToUniversalTime().ToString("o"))
last_status=$lastStatus
last_events:
$lastEvents
related_processes:
$($procLines -join [Environment]::NewLine)
safety=Evidence copied/created only. No user file was deleted, moved, cleaned or overwritten.
"@
try {
  $fs=[IO.File]::Open($evidence,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  try { $sw=New-Object IO.StreamWriter($fs,[Text.UTF8Encoding]::new($false)); $sw.Write((Redact $body)); $sw.Flush(); $sw.Dispose() } finally { if($fs){$fs.Dispose()} }
} catch {}

try {
  $start = (Get-Date).AddMinutes(-5)
  $rows = Get-WinEvent -FilterHashtable @{LogName="Application"; StartTime=$start} -ErrorAction SilentlyContinue |
    Where-Object {
      ($_.Id -in 1000,1001,1026) -and
      ($_.Message -match "XiaoMeili|crashrpt|Sogou|Qt6|onnxruntime|torch|nvml|nvcuda")
    } |
    Select-Object -First 30
  $txt = New-Object System.Text.StringBuilder
  foreach($e in $rows) {
    [void]$txt.AppendLine(("TIME={0:o} ID={1} PROVIDER={2}" -f $e.TimeCreated,$e.Id,$e.ProviderName))
    [void]$txt.AppendLine((Redact ([string]$e.Message)))
    [void]$txt.AppendLine("---")
  }
  if($txt.Length -eq 0) { [void]$txt.AppendLine("No matching Windows Application Error/WER event was readable in the previous 5 minutes.") }
  $fs=[IO.File]::Open($eventEvidence,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  try { $sw=New-Object IO.StreamWriter($fs,[Text.UTF8Encoding]::new($false)); $sw.Write($txt.ToString()); $sw.Flush(); $sw.Dispose() } finally { if($fs){$fs.Dispose()} }
} catch {}

$zipPath = New-UniquePath $desktop "小美丽_资源测试_独立看门狗崩溃报告" ".zip"
$safeNames = @(
  "live_timeline.jsonl","live_events.jsonl","live_rounds.jsonl","live_status.jsonl",
  "speech_diagnostic_worker.log","diagnostic_input.wav","events.json","summary.json",
  "stage_summary.csv","round_ledger.csv","timeline_250ms.csv","vram_jump_events.csv",
  "process_tree.csv","watchdog_started.json"
)

try {
  $fs=[IO.File]::Open($zipPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  $za=New-Object IO.Compression.ZipArchive($fs,[IO.Compression.ZipArchiveMode]::Create,$false)
  try {
    foreach($n in $safeNames) {
      $f=Join-Path $session $n
      if(Test-Path -LiteralPath $f -PathType Leaf) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($za,$f,$n,[IO.Compression.CompressionLevel]::Optimal) | Out-Null
      }
    }
    foreach($f in @($evidence,$eventEvidence)) {
      if(Test-Path -LiteralPath $f -PathType Leaf) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($za,$f,[IO.Path]::GetFileName($f),[IO.Compression.CompressionLevel]::Optimal) | Out-Null
      }
    }
    $entry=$za.CreateEntry("watchdog_summary.json")
    $writer=New-Object IO.StreamWriter($entry.Open(),[Text.UTF8Encoding]::new($false))
    $summary=[ordered]@{
      watchdog="v0100934"
      app_version=$AppVersion
      parent_pid=$ParentPid
      observed_parent_exit_utc=(Get-Date).ToUniversalTime().ToString("o")
      report_path=(Redact $zipPath)
      last_status=$lastStatus
      safety="append/copy only; no delete, no move, no overwrite"
    } | ConvertTo-Json -Depth 5
    $writer.Write($summary); $writer.Dispose()
  } finally {
    if($za){$za.Dispose()}
    if($fs){$fs.Dispose()}
  }
} catch {}

exit 0
