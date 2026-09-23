param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$DesktopLog
)
$ErrorActionPreference = 'Stop'
function Log([string]$Text) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $DesktopLog -Value ("[$stamp] $Text") -Encoding UTF8
}
try {
    Log "XiaoMeili updater started. package=$Package target=$Target parentPid=$ParentPid"
    for ($i=0; $i -lt 120; $i++) {
        $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        throw "Old XiaoMeili process did not exit in time."
    }
    if (-not (Test-Path -LiteralPath $Package)) { throw "Update package not found: $Package" }
    if (-not (Test-Path -LiteralPath $Target)) { throw "Target folder not found: $Target" }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $updateRoot = Split-Path -Parent $Package
    $work = Join-Path $updateRoot ("update_work_" + [Guid]::NewGuid().ToString('N'))
    $backup = Join-Path $updateRoot ("program_backup_" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Expand-Archive -LiteralPath $Package -DestinationPath $work -Force

    $payload = $null
    $directExe = Join-Path $work $ExeName
    $nested = Get-ChildItem -LiteralPath $work -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName $ExeName) } | Select-Object -First 1
    if (Test-Path -LiteralPath $directExe) { $payload = $work }
    elseif ($nested) { $payload = $nested.FullName }
    else { throw "Update package does not contain $ExeName" }

    try {
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        & robocopy.exe $Target $backup /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        $brc = $LASTEXITCODE
        if ($brc -ge 8) { throw "program backup failed with exit code $brc" }

        & robocopy.exe $payload $Target /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        $rc = $LASTEXITCODE
        if ($rc -ge 8) { throw "robocopy failed with exit code $rc" }
        $newExe = Join-Path $Target $ExeName
        if (-not (Test-Path -LiteralPath $newExe)) { throw "Updated EXE missing: $newExe" }

        Log "Update copied successfully. Starting new version."
        Start-Process -FilePath $newExe -WorkingDirectory $Target
        Start-Sleep -Milliseconds 800
        $started = Get-Process | Where-Object { $_.Path -eq $newExe } | Select-Object -First 1
        if (-not $started) { Log "Warning: could not confirm relaunched process; Start-Process returned without exception." }

        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    catch {
        Log ("Update apply failed. Restoring D-staged backup. " + $_.Exception.Message)
        if (Test-Path -LiteralPath $backup) {
            & robocopy.exe $backup $Target /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        }
        throw
    }

    Log "Updater finished successfully."
}
catch {
    try {
        Log ("ERROR: " + $_.Exception.Message)
        Log ($_ | Out-String)
    } catch {}
    try { Start-Process notepad.exe -ArgumentList $DesktopLog } catch {}
    exit 1
}
exit 0
