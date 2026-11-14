' Nest Wifi Pro Dashboard - Headless Background Runner
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\edgarguzman\.gemini\antigravity\scratch\nest-wifi-dashboard"
WshShell.Run Chr(34) & "C:\Users\edgarguzman\.gemini\antigravity\scratch\nest-wifi-dashboard\.venv\Scripts\pythonw.exe" & Chr(34) & " run.py --no-browser", 0, False
Set WshShell = Nothing
