param(
    [Parameter(Mandatory=$true)][string]$DataDirectory,
    [ValidateRange(1024,65535)][int]$Port = 18081,
    [switch]$Install,
    [string]$TaskName = 'CloakBrowser-Manager-Windows'
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create .venv and install backend/requirements.txt first.' }
$DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
if ($Install) {
    # InteractiveToken is essential: a Windows service in session 0 cannot show browsers.
    $arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -DataDirectory "{1}" -Port {2}' -f $PSCommandPath,$DataDirectory,$Port
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repository
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Description 'Native desktop Manager; loopback API only' -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    return
}
Set-Location -LiteralPath $repository
$env:CLOAKBROWSER_MANAGER_DATA_DIR = $DataDirectory
$env:CLOAKBROWSER_MANAGER_RUNTIME = 'native'
$logs = Join-Path $DataDirectory 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
while ($true) {
    $process = Start-Process -FilePath $python -ArgumentList '-m','backend.windows_host','--port',"$Port" -WorkingDirectory $repository -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'host.stdout.log') -RedirectStandardError (Join-Path $logs 'host.stderr.log') -PassThru
    $null = $process.Handle
    $process.WaitForExit()
    if ($process.ExitCode -eq 0) { break }
    Start-Sleep -Seconds 3
}
