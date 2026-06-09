' Launch the live-scores poll with NO visible window (style 0). The scheduled
' task runs this via wscript (a windowless host) instead of the .bat directly,
' so the cmd console no longer flashes every minute. The .bat -- and its log
' redirect -- is preserved.
Dim sBat
sBat = "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_live_scores.bat"
CreateObject("WScript.Shell").Run """" & sBat & """", 0, False
