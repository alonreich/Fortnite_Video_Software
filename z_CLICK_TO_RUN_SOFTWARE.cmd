@echo off
setlocal

rem The current folder of the script.
set "CURDIR=%~dp0"

rem 1) Check if the right-click menu item already exists.
rem The "command" key is a reliable way to check for the full menu entry.
reg query "HKCU\Software\Classes\*\shell\Fortnite Video Compressor\command" >nul 2>nul
if %errorlevel% neq 0 (
    echo Right-click menu entry for "%MENU_NAME%" does not exist. Creating it now...

    rem Define variables for the command
    set "MENU_NAME=Fortnite Video Compressor"
    set "PYTHON_EXE=python.exe"
    set "SCRIPT_PATH=%CURDIR%Video.py"
    set "ICON_PATH=%CURDIR%Video_Icon_File.ico"

    rem 2) Add the right-click menu item and its display name
    reg add "HKCU\Software\Classes\*\shell\%MENU_NAME%" /ve /t REG_SZ /d "%MENU_NAME%" /f

    rem 3) Add the custom icon to the menu item
    reg add "HKCU\Software\Classes\*\shell\%MENU_NAME%" /v Icon /t REG_SZ /d "%ICON_PATH%" /f

    rem 4) Set the command that runs when the option is selected
    rem We use the `py` launcher as a more flexible way to run the script.
    reg add "HKCU\Software\Classes\*\shell\%MENU_NAME%\command" /ve /t REG_SZ /d "py \""%SCRIPT_PATH%\"" \"%%1\"" /f

    echo Right-click menu creation complete.
) else (
    echo The right-click menu already exists. Skipping creation.
)

rem Create/update the desktop shortcut.
rem The script will always attempt to create/update the shortcut to ensure it's up-to-date.
echo Creating/updating the desktop shortcut...

set "LNKFILE=%USERPROFILE%\Desktop\Video.lnk"
set "ICONFILE=%CURDIR%Video_Icon_File.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$Wsh=New-Object -ComObject WScript.Shell; $s=$Wsh.CreateShortcut('%LNKFILE%'); $s.TargetPath='py'; $s.Arguments='""%CURDIR%Video.py"""'; $s.WorkingDirectory='%CURDIR%'; $s.IconLocation='%ICONFILE%'; $s.Save()"

echo Shortcut created on your Desktop.

rem Run the Python script
echo Launching the application...
start /b py "%CURDIR%Video.py"

endlocal