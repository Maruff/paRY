# Register the paRY tunnel as a logon task, so the editor's server survives
# closing the terminal it was started from.
#
#   powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1 -Remove
#
# Runs as the logged-on user, not SYSTEM: the tunnel authenticates with the key
# in that user's ~/.ssh, and SYSTEM has a different profile with no key in it.
# That also means no stored password, which a "run whether logged on or not"
# task would require.

[CmdletBinding()]
param(
    [string]$TaskName = "paRY tunnel",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $here "tunnel-hidden.vbs"

if ($Remove) {
    schtasks /delete /tn $TaskName /f | Out-Null
    Write-Output "  removed '$TaskName'"
    return
}

if (-not (Test-Path $launcher)) { throw "missing $launcher" }

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# The defaults are written for batch jobs and all three fight a long-lived
# tunnel: it is stopped on battery, never restarted after a failure, and killed
# after three days.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# tunnel.sh reconnects on its own; this is the layer above that, for the cases
# the script cannot see — a laptop resuming from sleep, or the process being
# killed outright.
Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Keeps local 8901 forwarded to paRY on the droplet. See deploy/tunnel.sh." `
    -Force | Out-Null

Write-Output "  registered '$TaskName' (at logon, as $env:USERNAME)"
