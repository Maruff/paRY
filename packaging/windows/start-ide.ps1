<#
    Start the eTamil IDE.

    The assistant is a server, and an IDE whose assistant is not running is an
    editor with a broken sidebar. So this starts paRY first if nothing is
    already listening, then opens the editor — which is what someone clicking
    "eTamil IDE" means, rather than two shortcuts and an instruction to click
    them in the right order.

    Run hidden by the Start Menu shortcut; nothing here needs a console.
#>

[CmdletBinding()]
param(
    [string]$Editor,
    [int]$Port = 8900
)

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot          # ...\eTamil\pary -> ...\eTamil
$server = Join-Path $PSScriptRoot 'pary-server.exe'

function Test-Listening($port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $port)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# Already running is the common case on a second launch, and starting a second
# copy would only fail on the port and confuse whoever reads the log.
if (-not (Test-Listening $Port) -and (Test-Path $server)) {
    Start-Process -FilePath $server -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    # The editor's paRY panel asks for /health as it activates, so give the
    # server the couple of seconds it needs to be there when that happens.
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-Listening $Port) { break }
        Start-Sleep -Milliseconds 250
    }
}

if (-not $Editor) {
    $marker = Join-Path $root 'editor.txt'
    if (Test-Path $marker) { $Editor = (Get-Content $marker -Raw).Trim() }
}

if ($Editor -and (Test-Path $Editor)) {
    Start-Process -FilePath $Editor
} else {
    foreach ($candidate in @('codium', 'code', 'code-insiders')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { Start-Process -FilePath $found.Source -WindowStyle Hidden; break }
    }
}
