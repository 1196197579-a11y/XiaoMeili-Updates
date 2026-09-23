param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$DesktopLog
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = '小美丽｜正在迁移数据到 D 盘'

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
            $bad.Add("缺失: $rel")
        } else {
            try {
                if ((Get-Item -LiteralPath $other -Force).Length -ne $_.Length) {
                    $bad.Add("大小不同: $rel")
                }
            } catch {
                $bad.Add("无法检查: $rel")
            }
        }
    }
    if ($bad.Count -gt 0) {
        throw ("迁移校验失败：" + [Environment]::NewLine + ($bad | Select-Object -First 20) -join [Environment]::NewLine)
    }
}

try {
    try { Remove-Item -LiteralPath $DesktopLog -Force -ErrorAction SilentlyContinue } catch {}
    Log "小美丽 D 盘迁移助手启动。"
    Log "源目录: $Source"
    Log "目标目录: $Target"

    if (-not $Target.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "目标必须位于 D: 盘。当前目标: $Target"
    }
    if (-not (Test-Path -LiteralPath 'D:\')) {
        throw "没有检测到 D: 盘。"
    }

    Log "等待小美丽安全退出..."
    for ($i=0; $i -lt 240; $i++) {
        $p = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        throw "小美丽主进程 60 秒内没有退出，迁移已取消，原数据未动。"
    }
    Start-Sleep -Seconds 2

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "源数据目录不存在: $Source"
    }

    $sourceItem = Get-Item -LiteralPath $Source -Force
    if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Log "检测到 C 盘 XiaoMeiliData 已经是链接目录，无需再次搬运。"
        Log "当前链接目标: $($sourceItem.Target)"
        if (Test-Path -LiteralPath $ExePath) {
            Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
        }
        exit 0
    }

    $srcStats = Get-FolderStats $Source
    $drive = Get-PSDrive -Name D -ErrorAction Stop
    $need = [int64]($srcStats.Bytes + 1073741824)
    Log ("当前 XiaoMeiliData: {0:N2} GB, {1} 个文件" -f ($srcStats.Bytes / 1GB), $srcStats.Count)
    Log ("D 盘可用空间: {0:N2} GB" -f ($drive.Free / 1GB))
    if ($drive.Free -lt $need) {
        throw ("D 盘空间不足。至少需要约 {0:N2} GB 可用空间。" -f ($need / 1GB))
    }

    New-Item -ItemType Directory -Path $Target -Force | Out-Null

    Log "正在复制模型、语音运行环境、大脑、动作素材、更新缓存和养成数据到 D 盘..."
    & robocopy.exe $Source $Target /E /COPY:DAT /DCOPY:DAT /R:3 /W:2 /XJ /FFT /NFL /NDL /NP
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        throw "robocopy 复制失败，退出码 $rc。原 C 盘数据仍保留。"
    }

    Log "复制完成，正在逐文件校验..."
    Verify-SourceInTarget $Source $Target
    Log "文件校验通过。"

    $backup = $Source + '.__C_BACKUP__'
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
    }

    Log "切换数据入口..."
    Move-Item -LiteralPath $Source -Destination $backup -Force

    try {
        New-Item -ItemType Junction -Path $Source -Target $Target -ErrorAction Stop | Out-Null
        if (-not (Test-Path -LiteralPath $Source)) {
            throw "创建兼容链接失败。"
        }
        $link = Get-Item -LiteralPath $Source -Force
        if (($link.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
            throw "兼容入口不是 Junction/ReparsePoint。"
        }

        $critical = @('config.json','brain','voice','assets')
        foreach ($name in $critical) {
            $oldView = Join-Path $Source $name
            $newView = Join-Path $Target $name
            if ((Test-Path -LiteralPath $newView) -and -not (Test-Path -LiteralPath $oldView)) {
                throw "兼容入口校验失败: $name"
            }
        }

        Log "D 盘数据入口验证通过。正在删除 C 盘旧副本以释放空间..."
        for ($try=0; $try -lt 3; $try++) {
            try {
                Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
                break
            } catch {
                if ($try -eq 2) { throw }
                Start-Sleep -Seconds 2
            }
        }
        Log "C 盘旧副本已删除。实际数据现位于: $Target"
    }
    catch {
        Log ("切换失败，正在自动回滚: " + $_.Exception.Message)
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

    Log "迁移成功。以后大模型、Qwen3-TTS、llama.cpp、动作素材、养成库、日志和更新缓存都会实际写入 D 盘。"
    Log "C:\Users\Public\XiaoMeiliData 只保留一个几乎不占空间的兼容入口。"
    Log "正在重新启动小美丽..."
    Start-Sleep -Seconds 1
    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "小美丽 EXE 不存在，无法自动重启: $ExePath"
    }
    Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
    Start-Sleep -Seconds 2
    Log "迁移助手完成。此窗口可以关闭。"
    exit 0
}
catch {
    Log ("ERROR: " + $_.Exception.Message)
    Log ($_ | Out-String)
    Write-Host ""
    Write-Host "迁移没有完成。为保护现有功能，程序不会主动删除未验证的数据。" -ForegroundColor Yellow
    Write-Host "错误日志已经保存到桌面，请上传给 ChatGPT。" -ForegroundColor Yellow
    try {
        if (Test-Path -LiteralPath $ExePath) {
            Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
        }
    } catch {}
    try { Start-Process notepad.exe -ArgumentList $DesktopLog } catch {}
    Read-Host "按 Enter 关闭"
    exit 1
}
