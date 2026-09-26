param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$DesktopLog,
    [Parameter(Mandatory=$true)][string]$ReadyFile
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'XiaoMeili - Moving data to D drive'

function Log([string]$Text) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$stamp] $Text"
    Write-Host $line
    try { Add-Content -LiteralPath $DesktopLog -Value $line -Encoding UTF8 } catch {}
}

function Get-FolderStats([string]$Path) {
    $count = 0L
    $bytes = 0L
    if (Test-Path -LiteralPath $Path) {
        Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue | ForEach-Object {
            $count++
            $bytes += $_.Length
        }
    }
    return @{ Count=$count; Bytes=$bytes }
}

function Verify-SourceInTarget([string]$Src, [string]$Dst) {
    $bad = New-Object System.Collections.Generic.List[string]
    $srcRoot = [System.IO.Path]::GetFullPath($Src).TrimEnd('\')
    Get-ChildItem -LiteralPath $Src -Recurse -Force -File -ErrorAction Stop | ForEach-Object {
        $rel = $_.FullName.Substring($srcRoot.Length).TrimStart('\')
        $other = Join-Path $Dst $rel
        if (-not (Test-Path -LiteralPath $other -PathType Leaf)) {
            $bad.Add("MISSING: $rel")
        } else {
            try {
                if ((Get-Item -LiteralPath $other -Force).Length -ne $_.Length) {
                    $bad.Add("SIZE_MISMATCH: $rel")
                }
            } catch {
                $bad.Add("VERIFY_FAILED: $rel")
            }
        }
    }
    if ($bad.Count -gt 0) {
        $sample = ($bad | Select-Object -First 20) -join [Environment]::NewLine
        throw ("File verification failed:" + [Environment]::NewLine + $sample)
    }
}

function Restart-XiaoMeili {
    if (Test-Path -LiteralPath $ExePath) {
        Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
    }
}

try {
    try { Remove-Item -LiteralPath $DesktopLog -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue } catch {}

    # V0.7.7.2: write READY as the first real action. Reaching this line already proves
    # Windows PowerShell parsed the helper. Slow cold starts / antivirus scanning no longer
    # race the GUI's handshake.
    "READY" | Set-Content -LiteralPath $ReadyFile -Encoding ASCII

    Log "XiaoMeili D-drive migration helper started."
    Log "Source: $Source"
    Log "Target: $Target"

    if (-not $Target.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Target must be on D: drive. Current target: $Target"
    }
    if (-not (Test-Path -LiteralPath 'D:\')) {
        throw "D: drive was not found."
    }
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source data folder was not found: $Source"
    }

    Log "READY handshake completed. Waiting for XiaoMeili to exit cleanly."

    for ($i=0; $i -lt 240; $i++) {
        $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        throw "XiaoMeili did not exit within 60 seconds. Migration was cancelled."
    }
    Start-Sleep -Seconds 2

    $sourceItem = Get-Item -LiteralPath $Source -Force
    if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Log "Source is already a reparse point/junction. No migration is required."
        Restart-XiaoMeili
        exit 0
    }

    $srcStats = Get-FolderStats $Source
    $drive = Get-PSDrive -Name D -ErrorAction Stop
    $need = [int64]($srcStats.Bytes + 1073741824)
    Log ("Current data size: {0:N2} GB in {1} files." -f ($srcStats.Bytes / 1GB), $srcStats.Count)
    Log ("D: free space: {0:N2} GB." -f ($drive.Free / 1GB))
    if ($drive.Free -lt $need) {
        throw ("Not enough free space on D:. Required approximately {0:N2} GB including safety margin." -f ($need / 1GB))
    }

    New-Item -ItemType Directory -Path $Target -Force | Out-Null

    Log "Copying XiaoMeili data to D: ..."
    & robocopy.exe $Source $Target /E /COPY:DAT /DCOPY:DAT /R:3 /W:2 /XJ /FFT /NFL /NDL /NP
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        throw "robocopy failed with exit code $rc. The original C: data is still intact."
    }

    Log "Copy completed. Verifying every source file by relative path and file size ..."
    Verify-SourceInTarget $Source $Target
    Log "Verification passed."

    $backup = $Source + '.__C_BACKUP__.' + [Guid]::NewGuid().ToString('N')
    Log "Switching the logical data path to a D: junction."
    Move-Item -LiteralPath $Source -Destination $backup -Force

    try {
        New-Item -ItemType Junction -Path $Source -Target $Target -ErrorAction Stop | Out-Null

        if (-not (Test-Path -LiteralPath $Source)) {
            throw "Junction creation failed."
        }
        $link = Get-Item -LiteralPath $Source -Force
        if (($link.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
            throw "The compatibility path is not a reparse point."
        }

        $critical = @('config.json','brain','voice','assets')
        foreach ($name in $critical) {
            $oldView = Join-Path $Source $name
            $newView = Join-Path $Target $name
            if ((Test-Path -LiteralPath $newView) -and -not (Test-Path -LiteralPath $oldView)) {
                throw "Compatibility path verification failed for: $name"
            }
        }

        Log "Junction verification passed. Removing the old C: copy to reclaim space."
        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
        Log "Old C: copy removed successfully."
    }
    catch {
        Log ("Switch failed. Rolling back automatically: " + $_.Exception.Message)
        try {
            if (Test-Path -LiteralPath $Source) {
                $item = Get-Item -LiteralPath $Source -Force
                if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    Remove-Item -LiteralPath $Source -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {}
        if (Test-Path -LiteralPath $backup) {
            Move-Item -LiteralPath $backup -Destination $Source -Force
        }
        throw
    }

    Log "Migration completed successfully."
    Log "Physical data location: $Target"
    Log "Logical compatibility path remains: $Source"
    Log "Restarting XiaoMeili ..."
    Restart-XiaoMeili
    Start-Sleep -Seconds 2
    Log "Migration helper finished."
    exit 0
}
catch {
    Log ("ERROR: " + $_.Exception.Message)
    Log ($_ | Out-String)
    try { Restart-XiaoMeili } catch {}
    try { Start-Process notepad.exe -ArgumentList $DesktopLog } catch {}
    exit 1
}
