# Register the Finance OS morning job in Windows Task Scheduler.
#   Runs `python -m finance_os.daily` every day at 7:00. If the laptop is off or asleep at 7:00, it runs as
#   soon as it is available (StartWhenAvailable), e.g. 9:00 when you open it. It never wakes the machine.
#   Runs as you, only while you are logged on (Claude Code and gcloud sign-ins live in your profile).
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1            # create or update
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1 -Remove    # delete the task
param([switch]$Remove, [string]$At = "07:00")

$TaskName = "FinanceOS Daily"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed '$TaskName'."
    exit 0
}

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python venv not found at $Python" }

$Action = New-ScheduledTaskAction -Execute $Python -Argument "-m finance_os.daily" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal `
    -Description "Finance OS: simulate the live company to today, sync Stripe, load the warehouse, run dbt. Logs: data\live\logs" -Force | Out-Null
$t = Get-ScheduledTask -TaskName $TaskName
Write-Output "Scheduled '$TaskName' daily at $At (runs late if missed). State: $($t.State)"
