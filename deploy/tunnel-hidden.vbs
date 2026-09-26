' Start deploy/tunnel.sh with no console window.
'
' Windows Task Scheduler has no "hidden" option for a task that runs in the
' logged-on user's session: it runs bash, bash gets a console, and a black
' window sits on the desktop for as long as the tunnel is up. Launching through
' wscript with intWindowStyle 0 is the usual way around that.
'
' The task has to run as the user rather than as SYSTEM, because the tunnel
' authenticates with the key in that user's ~/.ssh and SYSTEM has a different
' profile with no key in it.
'
' Registered by deploy/install-task.ps1. Nothing here is specific to a machine
' except the location of Git's bash, which is looked up rather than assumed.

Option Explicit

Dim fso, shell, here, bash, candidates, candidate, command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' This script sits in deploy/, beside the tunnel it starts, so the repository
' does not have to be in any particular place.
here = fso.GetParentFolderName(WScript.ScriptFullName)

candidates = Array( _
    shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Git\bin\bash.exe", _
    shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Git\bin\bash.exe", _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Git\bin\bash.exe")

bash = ""
For Each candidate In candidates
    If bash = "" And fso.FileExists(candidate) Then bash = candidate
Next

If bash = "" Then
    ' Visible on purpose. A tunnel that silently never starts is worse than one
    ' that says why, and this runs at logon where nobody is watching a log.
    MsgBox "paRY tunnel: could not find Git's bash.exe.", 16, "paRY"
    WScript.Quit 1
End If

' Forward slashes: bash reads a backslash as an escape, not a separator.
command = """" & bash & """ """ & Replace(here, "\", "/") & "/tunnel.sh"""
' Wait, rather than launching and exiting. Fire-and-forget leaves bash running
' but lets wscript return, and Task Scheduler then records the task as
' completed - after which its restart-on-failure never fires, because as far
' as it is concerned nothing failed. Blocking here keeps the task Running for
' as long as the tunnel is, which is what makes the scheduler's supervision
' mean anything. The window stays hidden either way: that is the 0.
shell.Run command, 0, True
