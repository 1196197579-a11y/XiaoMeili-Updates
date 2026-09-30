param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion,
    [Parameter(Mandatory=$true)][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$LogPath,
    [Parameter(Mandatory=$true)][string]$DiagnosticDir
)

$ErrorActionPreference = 'Stop'
$XIAOMEILI_INSTALL_ROOT_MARKER = '.xiaomeili-install.json'
$PROTECTED_USER_PATHS = @()

function Log([string]$Text) {
    $parent = Split-Path -Parent $LogPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Add-Content -LiteralPath $LogPath -Value ("[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Text") -Encoding UTF8
}
function Full([string]$PathValue) { return [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\') }
function Add-Protected([string]$PathValue) {
    if (-not [string]::IsNullOrWhiteSpace($PathValue)) {
        try { $script:PROTECTED_USER_PATHS += (Full $PathValue) } catch {}
    }
}
function Fail([string]$Message) { throw $Message }

try {
    Log "SAFE updater start. package=$Package root=$InstallRoot version=$ExpectedVersion"

    $expectedRoot = Full (Join-Path $env:LOCALAPPDATA 'XiaoMeiliApp')
    $actualRoot = Full $InstallRoot
    if (-not $actualRoot.Equals($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "Unsafe install root rejected. expected=$expectedRoot actual=$actualRoot"
    }

    Add-Protected $env:USERPROFILE
    Add-Protected ([Environment]::GetFolderPath('Desktop'))
    Add-Protected ([Environment]::GetFolderPath('MyDocuments'))
    Add-Protected (Join-Path $env:USERPROFILE 'Downloads')
    Add-Protected $env:OneDrive
    Add-Protected $env:WINDIR
    Add-Protected $env:ProgramFiles
    Add-Protected ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)'))
    Add-Protected $env:ProgramData
    Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue | ForEach-Object { Add-Protected $_.Root }

    foreach ($protected in $PROTECTED_USER_PATHS | Select-Object -Unique) {
        if ($actualRoot.Equals($protected, [System.StringComparison]::OrdinalIgnoreCase)) {
            Fail "Protected user/system path rejected: $actualRoot"
        }
    }

    $markerPath = Join-Path $actualRoot $XIAOMEILI_INSTALL_ROOT_MARKER
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { Fail "Install marker missing: $markerPath" }
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ([string]$marker.product -ne 'XiaoMeili' -or [int]$marker.schema -lt 2 -or [string]::IsNullOrWhiteSpace([string]$marker.install_id)) {
        Fail "Install marker invalid."
    }

    if (-not (Test-Path -LiteralPath $Package -PathType Leaf)) { Fail "Update package missing: $Package" }
    $actualSha = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedSha = ([string]$ExpectedSha256).Trim().ToLowerInvariant()
    if ($expectedSha -and $actualSha -ne $expectedSha) { Fail "SHA-256 mismatch. expected=$expectedSha actual=$actualSha" }

    $versionsRoot = Join-Path $actualRoot 'versions'
    New-Item -ItemType Directory -Force -Path $versionsRoot | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $versionDir = Join-Path $versionsRoot ("v" + $ExpectedVersion + "_" + $stamp + "_" + $PID)
    if (Test-Path -LiteralPath $versionDir) { Fail "Fresh version directory unexpectedly exists: $versionDir" }
    New-Item -ItemType Directory -Path $versionDir | Out-Null

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Package)
    try {
        $base = (Full $versionDir) + '\'
        foreach ($entry in $archive.Entries) {
            if ([string]::IsNullOrWhiteSpace($entry.FullName)) { continue }
            $candidate = Full (Join-Path $versionDir $entry.FullName)
            if (-not $candidate.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase) -and
                -not $candidate.Equals((Full $versionDir), [System.StringComparison]::OrdinalIgnoreCase)) {
                Fail "ZIP path traversal rejected: $($entry.FullName)"
            }
        }
    } finally { $archive.Dispose() }

    Expand-Archive -LiteralPath $Package -DestinationPath $versionDir

    $newExe = Join-Path $versionDir 'XiaoMeili.exe'
    if (-not (Test-Path -LiteralPath $newExe -PathType Leaf)) { Fail "Updated XiaoMeili.exe missing." }
    $versionFile = $null
    foreach ($candidate in @(
        (Join-Path $versionDir '_internal\assets\VERSION.txt'),
        (Join-Path $versionDir 'assets\VERSION.txt')
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $versionFile = $candidate; break }
    }
    if (-not $versionFile) { Fail "VERSION.txt missing from extracted build." }
    $actualVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    if ($actualVersion -ne $ExpectedVersion) { Fail "Version mismatch. expected=$ExpectedVersion actual=$actualVersion" }

    $launcher = Join-Path $actualRoot 'XiaoMeiliLauncher.exe'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { Fail "Stable launcher missing: $launcher" }

    $relativeExe = [System.IO.Path]::GetRelativePath($actualRoot, $newExe).Replace('\','/')
    $active = [ordered]@{
        schema = 1
        product = 'XiaoMeili'
        version = $ExpectedVersion
        relative_exe = $relativeExe
        activated_at = (Get-Date).ToString('o')
    }
    $active | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $actualRoot 'active.json') -Encoding UTF8

    try {
        $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        if (Test-Path $runKey) {
            $props = Get-ItemProperty -Path $runKey
            foreach ($p in $props.PSObject.Properties) {
                if ($p.Name -match '^PS') { continue }
                $value = [string]$p.Value
                if ($value -and $value.Contains($actualRoot) -and $value -match 'XiaoMeili\.exe') {
                    Set-ItemProperty -Path $runKey -Name $p.Name -Value ('"' + $launcher + '"') -Force
                    Log "Existing managed startup entry repointed to stable launcher: $($p.Name)"
                }
            }
        }
    } catch { Log "Startup migration warning: $($_.Exception.Message)" }

    for ($i=0; $i -lt 120; $i++) {
        if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }

    Log "Activated V$ExpectedVersion at $versionDir. No existing version or user file was deleted."
    Start-Process -FilePath $launcher -WorkingDirectory $actualRoot
    exit 0
}
catch {
    try {
        Log ("ERROR: " + $_.Exception.Message)
        New-Item -ItemType Directory -Force -Path $DiagnosticDir | Out-Null
        $diag = Join-Path $DiagnosticDir ("safe_update_failure_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".txt")
        @(
            "小美丽安全更新诊断",
            "时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
            "版本: $ExpectedVersion",
            "安装根目录: $InstallRoot",
            "说明: $($_.Exception.Message)",
            "",
            ($_ | Out-String)
        ) | Set-Content -LiteralPath $diag -Encoding UTF8
    } catch {}
    exit 1
}
