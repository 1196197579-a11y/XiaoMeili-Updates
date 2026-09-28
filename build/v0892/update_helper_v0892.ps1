param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][Alias('DesktopLog')][string]$LogPath,
    [Parameter(Mandatory=$true)][string]$DiagnosticDir
)
$ErrorActionPreference = 'Stop'

function Ensure-Parent([string]$PathValue) {
    $parent = Split-Path -Parent $PathValue
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Log([string]$Text) {
    Ensure-Parent $LogPath
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $LogPath -Value ("[$stamp] $Text") -Encoding UTF8
}

function Write-Diagnostic([string]$Message, $ErrorRecord) {
    try {
        New-Item -ItemType Directory -Force -Path $DiagnosticDir | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $diag = Join-Path $DiagnosticDir ("update_failure_" + $stamp + ".txt")
        $lines = @(
            "小美丽 V0.8.9.2 更新诊断",
            "时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
            "说明: $Message",
            "更新包: $Package",
            "目标目录: $Target",
            "常规更新日志: $LogPath",
            "",
            "异常详情:",
            ($ErrorRecord | Out-String)
        )
        Set-Content -LiteralPath $diag -Value $lines -Encoding UTF8
        return $diag
    }
    catch {
        return $null
    }
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
    $diag = Write-Diagnostic $_.Exception.Message $_
    if ($diag) {
        try { Start-Process notepad.exe -ArgumentList $diag } catch {}
    }
    exit 1
}
exit 0
