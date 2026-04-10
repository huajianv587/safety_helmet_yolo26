param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ConfigPath = "configs/runtime.json",
    [int]$DashboardPort = 8501,
    [string]$DashboardTaskName = "SafetyHelmetDashboard",
    [string]$MonitorTaskName = "SafetyHelmetMonitor"
)

$repoRootResolved = (Resolve-Path $RepoRoot).Path
$dashboardCommand = "/c cd /d `"$repoRootResolved`" && set HELMET_CONFIG_PATH=$ConfigPath && set HELMET_DASHBOARD_PORT=$DashboardPort && call `"$repoRootResolved\start_dashboard_service.cmd`""
$monitorCommand = "/c cd /d `"$repoRootResolved`" && set HELMET_CONFIG_PATH=$ConfigPath && call `"$repoRootResolved\start_monitor_service.cmd`""

$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

$dashboardAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $dashboardCommand
$monitorAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $monitorCommand

Register-ScheduledTask -TaskName $DashboardTaskName -Action $dashboardAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $MonitorTaskName -Action $monitorAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "dashboard_task=$DashboardTaskName"
Write-Host "monitor_task=$MonitorTaskName"
Write-Host "startup_mode=AtLogOn"
Write-Host "repo_root=$repoRootResolved"
