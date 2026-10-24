# Registers the laptop relay as a Windows scheduled task.
# It fetches the sites that block GitHub's servers and pushes them to data/inbox/.
#
#   powershell -ExecutionPolicy Bypass -File tools\install_relay_task.ps1
#
# Runs every 2 hours while you're logged in, and at logon; missed runs (laptop asleep)
# run as soon as it wakes. Remove with:  Unregister-ScheduledTask -TaskName JobRadarRelay

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$log = Join-Path $repo "data\relay.log"

# cmd wrapper so each run's output is appended to data\relay.log for troubleshooting.
$cmd = "/c cd /d `"$repo`" && `"$python`" -m radar.main relay --push >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $repo

$every2h = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 2)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable

Register-ScheduledTask -TaskName "JobRadarRelay" -Action $action -Trigger $every2h, $atLogon `
    -Settings $settings -Description "Job Radar: relay sites that block GitHub (CG Vyapam, CGPSC, UPSC...)" `
    -Force | Out-Null

Write-Host "Installed scheduled task 'JobRadarRelay' (every 2 hours + at logon)."
Write-Host "First run in about 2 minutes. Log: $log"
Write-Host "Run it now:   Start-ScheduledTask -TaskName JobRadarRelay"
