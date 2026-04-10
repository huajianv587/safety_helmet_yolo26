param(
    [string]$DashboardTaskName = "SafetyHelmetDashboard",
    [string]$MonitorTaskName = "SafetyHelmetMonitor"
)

foreach ($taskName in @($DashboardTaskName, $MonitorTaskName)) {
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
        Write-Host "removed_task=$taskName"
    } catch {
        Write-Host "missing_task=$taskName"
    }
}
