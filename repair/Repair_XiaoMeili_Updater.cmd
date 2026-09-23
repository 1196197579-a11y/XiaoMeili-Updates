@echo off
setlocal
title XiaoMeili Updater Repair
echo ===============================================
echo XiaoMeili updater one-time bootstrap repair
echo ===============================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=Join-Path $env:PUBLIC 'XiaoMeili'; $helper=Join-Path $root 'DesktopApp\XiaoMeili\_internal\assets\update_helper.ps1'; if(-not(Test-Path -LiteralPath $helper)){ $item=Get-ChildItem -LiteralPath $root -Recurse -Filter 'update_helper.ps1' -ErrorAction SilentlyContinue ^| Where-Object { $_.FullName -like '*\_internal\assets\update_helper.ps1' } ^| Select-Object -First 1; if(-not $item){ throw 'update_helper.ps1 not found under Public\XiaoMeili' }; $helper=$item.FullName }; $backup=$helper+'.before_repair'; Copy-Item -LiteralPath $helper -Destination $backup -Force; $s=Get-Content -LiteralPath $helper -Raw; if($s -notlike '*[int]$Pid*' -and $s -like '*$ParentPid*'){ Write-Host 'Updater is already repaired.' } else { $s=$s.Replace('[Parameter(Mandatory=$true)][int]$Pid,','[Parameter(Mandatory=$true)][Alias(''Pid'')][int]$ParentPid,'); $s=$s.Replace('$Pid','$ParentPid'); Set-Content -LiteralPath $helper -Value $s -Encoding UTF8; $check=Get-Content -LiteralPath $helper -Raw; if($check -notlike '*$ParentPid*'){ throw 'Repair verification failed' }; Write-Host 'Updater helper repaired successfully.' }; $exe=Join-Path $root 'DesktopApp\XiaoMeili\XiaoMeili.exe'; if(-not(Test-Path -LiteralPath $exe)){ $ex=Get-ChildItem -LiteralPath $root -Recurse -Filter 'XiaoMeili.exe' -ErrorAction SilentlyContinue ^| Select-Object -First 1; if($ex){ $exe=$ex.FullName } }; if(Test-Path -LiteralPath $exe){ Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe); Write-Host 'XiaoMeili restarted.' } else { Write-Host 'Repair complete. Please start XiaoMeili manually.' }"
if errorlevel 1 (
  echo.
  echo Repair failed. Please take a screenshot of this window.
  pause
  exit /b 1
)
echo.
echo Repair complete. Reopen Settings - Update and install the newest version.
timeout /t 3 /nobreak >nul
exit /b 0
