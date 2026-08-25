<#
.SYNOPSIS
    Install the eTamil IDE: the compiler, the paRY assistant, and the editor
    extensions that join them.

.DESCRIPTION
    Everything is installed for the current user. No administrator rights are
    needed and nothing is written outside the user's own profile — which is
    what makes this installable on a managed workstation without a ticket.

    It is a guest in an editor someone already uses: settings are backed up
    first and only missing keys are added, so no configuration is taken away.

.PARAMETER InstallDir
    Where to put the compiler and paRY. Defaults to
    %LOCALAPPDATA%\Programs\eTamil.

.PARAMETER Editor
    codium, code, or code-insiders. Detected when not given.

.PARAMETER InstallEditor
    Fetch VSCodium with winget when no editor is found.

.PARAMETER SkipEditor
    Install the compiler and paRY only, and leave the editor alone.

.PARAMETER Uninstall
    Remove what this script installed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install.ps1
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\eTamil",
    [ValidateSet('codium', 'code', 'code-insiders')]
    [string]$Editor,
    [switch]$InstallEditor,
    [switch]$SkipEditor,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$payload = $PSScriptRoot

function Write-Step($message) { Write-Host "  $message" }
function Write-Note($message) { Write-Host "  $message" -ForegroundColor DarkGray }

function Find-Editor {
    if ($Editor) {
        if (-not (Get-Command $Editor -ErrorAction SilentlyContinue)) {
            throw "$Editor is not on PATH"
        }
        return $Editor
    }
    foreach ($candidate in @('codium', 'code', 'code-insiders')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    return $null
}

# `code` and `codium` on PATH are .cmd shims in a bin\ directory. A shortcut
# wants the real executable beside it: the shim has no icon and flashes a
# console window on the way through.
function Resolve-EditorExe($editorName) {
    $command = Get-Command $editorName -ErrorAction SilentlyContinue
    if (-not $command) { return $null }
    $root = Split-Path (Split-Path $command.Source)
    foreach ($exe in @('VSCodium.exe', 'Code.exe', 'Code - Insiders.exe')) {
        $candidate = Join-Path $root $exe
        if (Test-Path $candidate) { return $candidate }
    }
    return $command.Source
}

function Get-EditorUserDir($editorName) {
    $folder = switch ($editorName) {
        'codium'        { 'VSCodium' }
        'code'          { 'Code' }
        'code-insiders' { 'Code - Insiders' }
    }
    return Join-Path $env:APPDATA "$folder\User"
}

# Add only the keys that are missing. A settings file someone edited by hand is
# theirs; this never overwrites a value they chose.
function Merge-JsonFile($target, $additions) {
    $existing = [ordered]@{}
    if (Test-Path $target) {
        $text = (Get-Content $target -Raw).Trim()
        if ($text) {
            try {
                $parsed = $text | ConvertFrom-Json
            } catch {
                Write-Note "$([System.IO.Path]::GetFileName($target)) is not plain JSON (comments?) - leaving it alone"
                return @()
            }
            foreach ($property in $parsed.PSObject.Properties) {
                $existing[$property.Name] = $property.Value
            }
        }
    }

    $added = @()
    foreach ($property in $additions.PSObject.Properties) {
        if (-not $existing.Contains($property.Name)) {
            $existing[$property.Name] = $property.Value
            $added += $property.Name
        }
    }
    if ($added.Count -eq 0) { return @() }

    if (Test-Path $target) {
        $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
        Copy-Item $target "$target.backup-$stamp"
    }
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    # WriteAllText rather than Out-File: 5.1's -Encoding utf8 writes a byte-order
    # mark, and settings files are read by more than one tool.
    [System.IO.File]::WriteAllText(
        $target,
        (ConvertTo-Json -InputObject $existing -Depth 20),
        (New-Object System.Text.UTF8Encoding($false))
    )
    return $added
}

# Windows PowerShell 5.1 hands a JSON array back as ONE object instead of
# enumerating it, so `@($text | ConvertFrom-Json)` produces a one-element array
# holding the whole array rather than unrolling it. Merging on top of that
# nests the file one level deeper every run, and ConvertTo-Json then writes the
# inner array as a {value, Count} wrapper that the editor cannot read. This
# function is why that cannot happen again; `foreach` does enumerate.
function Read-JsonArray($path) {
    if (-not (Test-Path $path)) { return , @() }
    $text = (Get-Content $path -Raw).Trim()
    if (-not $text) { return , @() }
    try { $parsed = ConvertFrom-Json $text } catch { return $null }
    $items = @()
    foreach ($item in $parsed) { $items += $item }
    return , $items
}

function Write-JsonArray($path, $items) {
    $json = ConvertTo-Json -InputObject @($items) -Depth 20
    # A one-element array serialises as a bare object; the editor wants a list.
    if (-not $json.TrimStart().StartsWith('[')) { $json = "[$([Environment]::NewLine)$json$([Environment]::NewLine)]" }
    New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
    [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Merge-Keybindings($target, $additions) {
    $existing = Read-JsonArray $target
    if ($null -eq $existing) {
        Write-Note "keybindings.json is not plain JSON - leaving it alone"
        return @()
    }

    $taken = @($existing | ForEach-Object { "$($_.key)|$($_.command)" })
    $fresh = @($additions | Where-Object { $taken -notcontains "$($_.key)|$($_.command)" })
    if ($fresh.Count -eq 0) { return @() }

    if (Test-Path $target) {
        $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
        Copy-Item $target "$target.backup-$stamp"
    }
    Write-JsonArray $target (@($existing) + @($fresh))
    return @($fresh | ForEach-Object { "$($_.key) -> $($_.command)" })
}

function Add-ToUserPath($directory) {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @()
    if ($current) { $entries = $current -split ';' | Where-Object { $_ } }
    if ($entries -contains $directory) { return $false }
    [Environment]::SetEnvironmentVariable('Path', (@($entries + $directory) -join ';'), 'User')
    return $true
}

function Remove-FromUserPath($directory) {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $current) { return }
    $kept = $current -split ';' | Where-Object { $_ -and $_ -ne $directory }
    [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
}

function New-Shortcut($path, $target, $arguments, $workingDirectory, $description, $iconSource) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    if ($arguments) { $link.Arguments = $arguments }
    $link.WorkingDirectory = $workingDirectory
    $link.Description = $description
    # Both shortcuts are named "eTamil ..." so that typing eTamil in the Start
    # Menu finds them — the folder name is not what Windows searches.
    if ($iconSource) { $link.IconLocation = "$iconSource,0" }
    $link.Save()
}

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\eTamil'

# ---------------------------------------------------------------- uninstall --
if ($Uninstall) {
    Write-Host "Removing the eTamil IDE"
    if (Test-Path $InstallDir) {
        Remove-Item $InstallDir -Recurse -Force
        Write-Step "deleted $InstallDir"
    }
    if (Test-Path $startMenu) {
        Remove-Item $startMenu -Recurse -Force
        Write-Step "removed the Start Menu folder"
    }
    Remove-FromUserPath (Join-Path $InstallDir 'compiler')
    [Environment]::SetEnvironmentVariable('ETAMIL_PATH', $null, 'User')
    Write-Step "cleaned PATH and ETAMIL_PATH"
    Write-Note "The editor extensions are left in place - remove them from the editor."
    exit 0
}

# ------------------------------------------------------------------ install --
Write-Host "Installing the eTamil IDE for $env:USERNAME"

foreach ($required in @('compiler', 'pary', 'extensions', 'profile')) {
    if (-not (Test-Path (Join-Path $payload $required))) {
        throw "$required is missing from this package - the download is incomplete"
    }
}

New-Item -ItemType Directory -Force $InstallDir | Out-Null
foreach ($part in @('compiler', 'pary')) {
    $destination = Join-Path $InstallDir $part
    if (Test-Path $destination) { Remove-Item $destination -Recurse -Force }
    Copy-Item (Join-Path $payload $part) $destination -Recurse
    Write-Step "$part -> $destination"
}

$compilerDir = Join-Path $InstallDir 'compiler'
if (Add-ToUserPath $compilerDir) {
    Write-Step "added the compiler to your PATH"
} else {
    Write-Note "the compiler was already on your PATH"
}

# Imports say `இறக்கு "nUlakam/paNam.qmz"`, which resolves along ETAMIL_PATH.
[Environment]::SetEnvironmentVariable('ETAMIL_PATH', $compilerDir, 'User')
Write-Step "ETAMIL_PATH = $compilerDir"

# ------------------------------------------------------------------- editor --
if ($SkipEditor) {
    Write-Note "editor left alone (-SkipEditor) - no IDE shortcut without one"
    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

$editorName = Find-Editor
if (-not $editorName -and $InstallEditor) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step "installing VSCodium with winget"
        winget install --id VSCodium.VSCodium --silent --accept-source-agreements --accept-package-agreements
        $editorName = Find-Editor
    } else {
        Write-Note "winget is not available - install VSCodium from https://vscodium.com"
    }
}

if (-not $editorName) {
    New-Item -ItemType Directory -Force $startMenu | Out-Null
    New-Shortcut (Join-Path $startMenu 'eTamil paRY server.lnk') `
        (Join-Path $InstallDir 'pary\pary-server.exe') $null (Join-Path $InstallDir 'pary') `
        'The eTamil assistant - answers from the compiler, never a hosted model' `
        $null
    Write-Note "No editor found. Install VSCodium (https://vscodium.com), then re-run this script"
    Write-Note "to get the IDE shortcut. The compiler and paRY work from a terminal already."
    exit 0
}

Write-Step "editor: $editorName"
foreach ($package in Get-ChildItem (Join-Path $payload 'extensions') -Filter *.vsix) {
    & $editorName --install-extension $package.FullName --force | Out-Null
    Write-Step "installed $($package.Name)"
}

# --------------------------------------------------------------- shortcuts --
# Written now rather than earlier, because "eTamil IDE" has to know which
# editor it is opening.
$editorExe = Resolve-EditorExe $editorName
Set-Content -Path (Join-Path $InstallDir 'editor.txt') -Value $editorExe -Encoding utf8

if (Test-Path $startMenu) { Remove-Item (Join-Path $startMenu '*.lnk') -Force }
New-Item -ItemType Directory -Force $startMenu | Out-Null
$launcher = Join-Path $InstallDir 'pary\start-ide.ps1'

# One click starts the assistant and opens the editor, in that order — an IDE
# whose assistant is not running is an editor with a broken sidebar.
New-Shortcut (Join-Path $startMenu 'eTamil IDE.lnk') `
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`"" `
    (Join-Path $InstallDir 'pary') `
    'The eTamil IDE - editor, compiler and the paRY assistant' `
    $editorExe
Write-Step "Start Menu: eTamil IDE"

New-Shortcut (Join-Path $startMenu 'eTamil paRY server.lnk') `
    (Join-Path $InstallDir 'pary\pary-server.exe') $null (Join-Path $InstallDir 'pary') `
    'The eTamil assistant on its own - answers from the compiler, never a hosted model' `
    $null
Write-Step "Start Menu: eTamil paRY server"

$userDir = Get-EditorUserDir $editorName
$settings = Get-Content (Join-Path $payload 'profile\settings.json') -Raw | ConvertFrom-Json
if ($editorName -eq 'codium') {
    # Telemetry and update settings belong to an IDE handed to a team, not to
    # the editor someone already uses every day.
    $extra = Get-Content (Join-Path $payload 'profile\settings.codium.json') -Raw | ConvertFrom-Json
    foreach ($property in $extra.PSObject.Properties) {
        $settings | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
    }
}
$settings | Add-Member -NotePropertyName 'etamil.compilerPath' `
    -NotePropertyValue (Join-Path $compilerDir 'etamil.exe') -Force

$addedSettings = Merge-JsonFile (Join-Path $userDir 'settings.json') $settings
$keybindings = Get-Content (Join-Path $payload 'profile\keybindings.json') -Raw | ConvertFrom-Json
$addedKeys = Merge-Keybindings (Join-Path $userDir 'keybindings.json') $keybindings

Write-Step "settings added: $($addedSettings.Count)"
Write-Step "keybindings added: $($addedKeys.Count)"
if ($addedSettings.Count -eq 0 -and $addedKeys.Count -eq 0) {
    Write-Note "everything was already set - nothing was overwritten"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Start Menu -> eTamil IDE. It starts paRY and opens the editor."
Write-Host "  Ctrl+Alt+I asks paRY to write code into the editor. F5 runs the file."
Write-Host "  Open a new terminal for PATH and ETAMIL_PATH to take effect."
