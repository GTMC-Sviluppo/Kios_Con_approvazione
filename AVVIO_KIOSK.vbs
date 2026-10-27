' ============================================================
' AVVIO_KIOSK.vbs - Avvio nascosto del supervisore kiosk HR
' ------------------------------------------------------------
' Lanciato al logon di Windows da:
'   - chiave HKCU\...\Run (INSTALLA_AUTOSTART.bat)
'   - VBS generato nella cartella "Esecuzione automatica" (dall'installer)
' Non richiede privilegi di amministratore e non mostra finestre console.
'
' Risolve da solo la cartella del progetto (funziona anche se spostata)
' e usa il pythonw del venv. Se il venv manca NON ripiega su un pythonw
' globale (potrebbe non avere Flask: loop di crash silenzioso) ma lascia
' una riga in logs\autostart_error.log ed esce.
' ============================================================
Option Explicit

Dim fso, sh, dir, py, scriptFile
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

' Cartella del progetto = cartella dove si trova questo .vbs
dir = fso.GetParentFolderName(WScript.ScriptFullName)

' Il supervisore deve esistere, altrimenti esci in silenzio
scriptFile = dir & "\kiosk_supervisor.py"
If Not fso.FileExists(scriptFile) Then
    WScript.Quit 1
End If

' Python senza console: solo quello del venv del progetto
py = dir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then
    On Error Resume Next
    If Not fso.FolderExists(dir & "\logs") Then fso.CreateFolder(dir & "\logs")
    Dim ts
    Set ts = fso.OpenTextFile(dir & "\logs\autostart_error.log", 8, True)
    ts.WriteLine Now & " - venv\Scripts\pythonw.exe non trovato in " & dir & ": avvio annullato (creare il venv con INSTALLA.bat o SETUP_PYTHON311.bat)"
    ts.Close
    On Error Goto 0
    WScript.Quit 2
End If

sh.CurrentDirectory = dir
' 0 = finestra nascosta, False = non attendere la fine
sh.Run """" & py & """ """ & scriptFile & """", 0, False
