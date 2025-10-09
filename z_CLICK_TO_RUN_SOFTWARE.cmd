@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem --- Setup environment and logging for robust failure reporting ---
set "SCRIPT_DIR=%~dp0"
set "EXIT_CODE=0"

rem --- Get timestamp for logs ---
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')" 2^>nul') do set "TS=%%i"
if not defined TS (
echo ------------------------------------------------------------------
echo [CRITICAL ERROR] FAILED at Line 10 (Timestamp): Powershell not found or access denied.
echo This script relies on Powershell. Ensure powershell.exe is in your PATH.
echo ------------------------------------------------------------------
goto :FAIL_EXIT_NOSUMMARY
)
set "LOG=%TEMP%\Video_Setup_%TS%.log"
set "SUM_I=%TEMP%\Video_Sum_installed_%TS%.txt"
set "SUM_S=%TEMP%\Video_Sum_skipped_%TS%.txt"
set "SUM_O=%TEMP%\Video_Sum_overwritten_%TS%.txt"
set "SUM_F=%TEMP%\Video_Sum_writefail_%TS%.txt"
if exist "%SUM_I%" del /q "%SUM_I%"
if exist "%SUM_S%" del /q "%SUM_S%"
if exist "%SUM_O%" del /q "%SUM_O%"
if exist "%SUM_F%" del /q "%SUM_F%"

rem --- Function to track line numbers for precise failure reporting ---
call :GetLineNumber

rem --- 1. ADMIN CHECK ---
echo [STEP 1/5] Checking Administrator privileges...
NET SESSION >nul 2>&1
if NOT %ERRORLEVEL% EQU 0 (
echo ------------------------------------------------------------------
echo [CRITICAL ERROR] FAILED at Line !LINENUM! (Admin Check): Script requires Administrator rights.
echo ------------------------------------------------------------------
set "EXIT_CODE=1"
goto :FAIL_EXIT
)
pushd "%SCRIPT_DIR%"
echo [OK 1/5] This Admin Check ran successfully


rem --- 2. PYTHON DETECTION AND INSTALLATION ---
set "PYTHON="
set "USE_PYLAUNCHER="

:install_python
call :GetLineNumber
if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
set "PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"
set "USE_PYLAUNCHER="
call :AddSummary SKIPPED "Python (venv present)"
goto :skip_python_install
)

if not defined PYTHON (
if exist "%SystemRoot%\py.exe" (
"%SystemRoot%\py.exe" -3 -V >nul 2>&1
call :CheckForFailure 0 "Check py.exe launcher"
if %ERRORLEVEL% EQU 0 (set "PYTHON=%SystemRoot%\py.exe" & set "USE_PYLAUNCHER=1" & goto :skip_python_install)
)

for /f "delims=" %%P in ('where py 2^>nul') do (
"%%P" -3 -V >nul 2>&1
call :CheckForFailure 0 "Check py.exe via PATH"
if %ERRORLEVEL% EQU 0 (set "PYTHON=%%P" & set "USE_PYLAUNCHER=1" & goto :skip_python_install)
)

if exist "%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\python.exe" (
"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\python.exe" -V >nul 2>&1
call :CheckForFailure 0 "Check MS Store Python"
if %ERRORLEVEL% EQU 0 (set "PYTHON=%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\python.exe" & goto :skip_python_install)
)

for /f "delims=" %%P in ('where python 2^>nul') do (
"%%P" -V >nul 2>&1
call :CheckForFailure 0 "Check python.exe via PATH"
if %ERRORLEVEL% EQU 0 (set "PYTHON=%%P" & goto :skip_python_install)
)

echo [INFO] Python not found. Attempting to download and install Python 3.12...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; " ^
"$u='https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe'; " ^
"$o="$env:TEMP\python-3.12.3-amd64.exe"; Invoke-WebRequest -Uri $u -OutFile $o -UseBasicParsing"
call :CheckForFailure 1 "Python 3.12 Installer Download"

if not exist "%TEMP%\python-3.12.3-amd64.exe" (
call :AddSummary WRITEFAIL "Python 3.12.3 installer download"
) else (
echo [INFO] Installing Python. This may take a moment.
start /wait "" "%TEMP%\python-3.12.3-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1
if %ERRORLEVEL% EQU 0 (
call :AddSummary INSTALLED "Python 3.12.3 (x64)"
) else (
call :AddSummary WRITEFAIL "Python 3.12.3 installation"
)
del "%TEMP%\python-3.12.3-amd64.exe"
)
echo [INFO] Installation complete. Retrying Python detection.
goto :install_python
)

:skip_python_install
echo [INFO] Python detected: "%PYTHON%"
echo [OK 2/5] This Python detection/installation ran successfully

rem --- 3. VLC DETECTION AND INSTALLATION ---
echo [STEP 2/5] Detecting latest VLC x64 and checking for existing installation...
call :GetLineNumber
for /f "usebackq delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=\"https://download.videolan.org/pub/videolan/vlc/last/win64/\";$p=Invoke-WebRequest -UseBasicParsing -Uri $u;$m=($p.Links ^| Where-Object href -Match \"vlc-.*-win64\.exe$\" ^| Select-Object -First 1 -ExpandProperty href);if($m){if($m -notmatch \"^https?://\"){Write-Output ($u+$m)} else {Write-Output $m}}" 2^>nul') do set "VLC_INSTALLER_URL=%%I"
call :CheckForFailure 0 "VLC Latest URL Detection"

if not defined VLC_INSTALLER_URL goto VLC_FALLBACK

for %%I in ("%VLC_INSTALLER_URL%") do set "VLC_INSTALLER_NAME=%%~nxI"
echo [INFO] Resolved VLC URL: %VLC_INSTALLER_URL%
goto VLC_DETECT_DONE

:VLC_FALLBACK
echo [WARNING] Could not resolve VLC latest. Falling back to 3.0.21.
set "VLC_VERSION=3.0.21"
set "VLC_ARCH=win64"
set "VLC_INSTALLER_NAME=vlc-%VLC_VERSION%-%VLC_ARCH%.exe"
set "VLC_INSTALLER_URL=https://download.videolan.org/pub/videolan/vlc/%VLC_VERSION%/%VLC_ARCH%/%VLC_INSTALLER_NAME%"

:VLC_DETECT_DONE

set "VLC_REG_KEY=HKLM\SOFTWARE\VideoLAN\VLC"
set "UNINSTALL_REG_KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

set "VLC_FOUND="
set "VLC_64BIT_FOUND="

call :GetLineNumber
for /f "tokens=2*" %%a in ('reg query "%VLC_REG_KEY%" /v "InstallDir" 2^>nul') do set "VLC_FOUND=%%b"

if defined VLC_FOUND (
echo [INFO] VLC Media Player detected at: %VLC_FOUND%
reg query "%UNINSTALL_REG_KEY%\VLC media player" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
set "VLC_64BIT_FOUND=1"
echo [INFO] Detected VLC 64-bit. Skipping reinstall.
call :AddSummary SKIPPED "VLC Media Player 64-bit (already present)"
) else (
echo [WARNING] Detected non-64-bit or non-standard VLC installation.
echo [WARNING] Searching for VLC 32-bit uninstaller...
set "UNINSTALL_STRING="
call :GetLineNumber
for /f "usebackq tokens=" %%A in ('powershell -NoProfile -Command "Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall*' | Where-Object { $_.DisplayName -like 'VLC media player' } | Select-Object -ExpandProperty UninstallString -First 1" 2^>nul') do set "UNINSTALL_STRING=%%A"

if defined UNINSTALL_STRING (
echo [INFO] Found 32-bit uninstaller. Attempting silent removal...
start /wait "" "%UNINSTALL_STRING%" /S
call :CheckForFailure 0 "VLC 32-bit Uninstallation"
echo [INFO] VLC 32-bit uninstallation process finished.
) else (
echo [WARNING] Could not find VLC 32-bit uninstaller string. Skipping uninstall.
)
)
)

if not defined VLC_64BIT_FOUND (
echo [INFO] Downloading VLC 64-bit installer: %VLC_INSTALLER_NAME%...
call :GetLineNumber
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; " ^
"Invoke-WebRequest -Uri '%VLC_INSTALLER_URL%' -OutFile "$env:TEMP%VLC_INSTALLER_NAME%" -UseBasicParsing"
call :CheckForFailure 1 "VLC 64-bit Download"

if exist "%TEMP%%VLC_INSTALLER_NAME%" (
echo [INFO] Installing VLC 64-bit (silent)...
start /wait "" "%TEMP%%VLC_INSTALLER_NAME%" /L=1033 /S
if %ERRORLEVEL% EQU 0 (
call :AddSummary INSTALLED "VLC Media Player 64-bit"
) else (
call :AddSummary WRITEFAIL "VLC installation"
)
del "%TEMP%%VLC_INSTALLER_NAME%"
) else (
call :AddSummary WRITEFAIL "VLC download (file not found after download)"
)
)

rem --- 4. INSTALL PYTHON DEPENDENCIES ---
echo [STEP 3/5] Installing required Python packages: PyQt5 and python-vlc...
call :GetLineNumber
"%PYTHON%" -m pip install PyQt5 python-vlc --upgrade --break-system-packages >nul 2>&1

if %ERRORLEVEL% NEQ 0 (
echo [ERROR] Failed to install Python dependencies.
set "PIP_OK=0"
call :AddSummary WRITEFAIL "Python deps (PyQt5, python-vlc)"
) else (
set "PIP_OK=1"
call :AddSummary INSTALLED "Python deps (PyQt5, python-vlc)"
)

echo [OK 3/5] This VLC detection/installation ran successfully
rem --- 5. CREATE DESKTOP SHORTCUT ---
echo [STEP 4/5] Creating/refreshing Desktop shortcut...
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Video.lnk"
if exist "%SHORTCUT_PATH%" (set "SC_EXISTED=1") else set "SC_EXISTED="
call :GetLineNumber
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop');" ^
"$lnk=Join-Path $desktop 'Video.lnk'; $s=$ws.CreateShortcut($lnk);" ^
"$s.TargetPath='%SCRIPT_DIR%z_CLICK_TO_RUN_SOFTWARE.cmd';" ^
"$s.WorkingDirectory='%SCRIPT_DIR%'; $s.Description='Run Python Video Application';" ^
"if (Test-Path '%SCRIPT_DIR%Video_Icon_File.ico') {$s.IconLocation='%SCRIPT_DIR%Video_Icon_File.ico'} else {$s.IconLocation='shell32.dll,3'};" ^
"$s.Save()"
call :CheckForFailure 1 "Desktop Shortcut Creation"

if exist "%SHORTCUT_PATH%" (
if defined SC_EXISTED (call :AddSummary OVERWRITTEN "Desktop shortcut: Video.lnk") else (call :AddSummary INSTALLED "Desktop shortcut: Video.lnk")
) else (
call :AddSummary WRITEFAIL "Desktop shortcut: Video.lnk"
)
echo [OK 4/5] This Desktop Shortcut creation ran successfully
rem --- 6. EXECUTE PYTHON SCRIPT ---
echo [STEP 5/5] Launching application...
if "%PIP_OK%"=="1" (
echo [INFO] Launching Python application: Video.py
call :GetLineNumber
"%PYTHON%" Video.py
call :CheckForFailure 0 "Python Application Execution"
) else (
echo [WARNING] Skipping launch due to missing Python dependencies.
)
echo [OK 5/5] This Application launch stage ran successfully
call :PrintSummary

:SUCCESS_EXIT
popd
endlocal & exit /b 0

:FAIL_EXIT
popd
call :PrintSummary
endlocal & exit /b 1

:FAIL_EXIT_NOSUMMARY
endlocal & exit /b 1

rem --- Subroutines start here ---

:CheckForFailure
rem %1 = 1 to exit on failure, 0 to continue
rem %2 = Description of the failed step
if %ERRORLEVEL% NEQ 0 (
if "%~1"=="1" (
echo ------------------------------------------------------------------
echo [CRITICAL FAILURE] STOPPED at Line !LINENUM! (Failure Check)
echo Reason: Failed to perform '%~2'. ErrorLevel: %ERRORLEVEL%
echo ------------------------------------------------------------------
set "EXIT_CODE=1"
goto :FAIL_EXIT
) else (
call :Log "[NON-CRITICAL FAILURE] Step '%~2' failed with ErrorLevel: %ERRORLEVEL%"
)
)
exit /b 0

:GetLineNumber
rem This command needs to be executed right before the operation you want to check.
rem It determines the current line number for failure reporting.
for /F "tokens=1 delims=:" %%n in ('findstr /n /c:":GetLineNumber" "%~f0"') do set "LINENUM=%%n"
set /a "LINENUM=!LINENUM!-1"
exit /b 0

:Log
echo [LOG] %~1
>>"%LOG%" echo [LOG] %~1
exit /b 0

:AddSummary
set "CAT=%~1"
set "ITEM=%~2"
if /I "%CAT%"=="INSTALLED" (>>"%SUM_I%" echo %ITEM% & call :Log "[SUMMARY][INSTALLED] %ITEM%")
if /I "%CAT%"=="SKIPPED" (>>"%SUM_S%" echo %ITEM% & call :Log "[SUMMARY][SKIPPED] %ITEM%")
if /I "%CAT%"=="OVERWRITTEN"(>>"%SUM_O%" echo %ITEM% & call :Log "[SUMMARY][OVERWRITTEN] %ITEM%")
if /I "%CAT%"=="WRITEFAIL" (>>"%SUM_F%" echo %ITEM% & call :Log "[SUMMARY][WRITEFAIL] %ITEM%")
exit /b 0

:PrintSummary
echo.
echo ===================== SETUP SUMMARY =====================
echo [INFO] Log file: %LOG%
echo.
if exist "%SUM_I%" (echo Installed: & type "%SUM_I%") else echo Installed: none
echo.
if exist "%SUM_S%" (echo Already present (skipped): & type "%SUM_S%") else echo Already present (skipped): none
echo.
if exist "%SUM_O%" (echo Overwritten files: & type "%SUM_O%") else echo Overwritten files: none
echo.
if exist "%SUM_F%" (echo Write failures: & type "%SUM_F%") else echo Write failures: none
echo =========================================================
exit /b 0