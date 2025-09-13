@echo off
setlocal

rem 1) current script folder (no trailing backslash)
set "CURDIR=%~dp0"
if "%CURDIR:~-1%"=="\" set "CURDIR=%CURDIR:~0,-1%"

rem 2) where to place/update the shortcut (Desktop). Change if you want local folder.
set "LNKFILE=%USERPROFILE%\Desktop\Video.lnk"
set "ICONFILE=%CURDIR%\Video_Icon_File.ico"

rem 3) create/update shortcut (single-line PowerShell to avoid line-continuation issues)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$Wsh=New-Object -ComObject WScript.Shell; $s=$Wsh.CreateShortcut('%LNKFILE%'); $s.TargetPath='py'; $s.Arguments='""%CURDIR%\Video.py"""'; $s.WorkingDirectory='%CURDIR%'; $s.IconLocation='%ICONFILE%'; $s.Save()"


rem 4) run the Python script (uses py launcher)
py "%CURDIR%\Video.py"

endlocal
