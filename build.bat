@echo off
rem ===========================================================================
rem  OSINT Hub - full build: venv -> tests -> tools -> PyInstaller -> self-test
rem  -> Inno Setup installer.
rem
rem    build.bat                 full build
rem    build.bat --skip-tests    skip pytest
rem    build.bat --no-installer  stop after dist\OSINTHub
rem    build.bat --update-tools  re-download bundled tools (fetch_tools --force)
rem
rem  Output:  dist\OSINTHub\OSINTHub.exe
rem           dist\installer\OSINTHub-Setup-1.0.0.exe
rem ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set SKIP_TESTS=0
set NO_INSTALLER=0
set TOOLS_FORCE=
:args
if "%~1"=="" goto args_done
if /i "%~1"=="--skip-tests" set SKIP_TESTS=1
if /i "%~1"=="--no-installer" set NO_INSTALLER=1
if /i "%~1"=="--update-tools" set TOOLS_FORCE=--force
shift
goto args
:args_done

rem ---- 1. Python 3.11+ ------------------------------------------------------
set PY=
where py >nul 2>&1 && (
  for %%V in (3.13 3.12 3.11) do if not defined PY py -%%V -c "import sys" >nul 2>&1 && set PY=py -%%V
)
if not defined PY (
  where python >nul 2>&1 && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set PY=python
)
if not defined PY (
  echo [build] ERROR: Python 3.11+ not found. Install it from https://www.python.org/downloads/
  exit /b 1
)
echo [build] Python: %PY%

rem ---- 2. virtual environment ----------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [build] Creating .venv
  %PY% -m venv .venv || goto fail
)
set VPY=.venv\Scripts\python.exe
%VPY% -m pip install --disable-pip-version-check -q --upgrade pip || goto fail
%VPY% -m pip install --disable-pip-version-check -q -r requirements-dev.txt || goto fail

rem ---- 3. tests ---------------------------------------------------------------
if "%SKIP_TESTS%"=="0" (
  echo [build] Running tests
  %VPY% -m pytest -q || goto fail
)

rem ---- 4. bundled tools ------------------------------------------------------
echo [build] Fetching bundled tools
%VPY% scripts\fetch_tools.py %TOOLS_FORCE% || goto fail

rem ---- 5. licences, icon + PyInstaller -------------------------------------------
echo [build] Collecting licences of bundled Python packages
%VPY% scripts\collect_licenses.py || goto fail
echo [build] Building application (PyInstaller)
%VPY% scripts\make_icon.py || goto fail
if exist "dist\OSINTHub" rmdir /s /q "dist\OSINTHub"
%VPY% -m PyInstaller build\osinthub.spec --noconfirm --clean --workpath build\work --distpath dist --log-level WARN || goto fail

rem ---- 6. copy tools next to the exe -----------------------------------------
echo [build] Copying tools
robocopy tools "dist\OSINTHub\tools" /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ .git test docs .github /XF *.pyc >nul
if %ERRORLEVEL% GEQ 8 goto fail
copy /y .env.example "dist\OSINTHub\.env.example" >nul
copy /y LICENSE "dist\OSINTHub\LICENSE.txt" >nul
copy /y THIRD_PARTY_NOTICES.md "dist\OSINTHub\THIRD_PARTY_NOTICES.md" >nul
robocopy licenses "dist\OSINTHub\licenses" /E /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 goto fail

rem ---- 7. self-test of the packaged build ------------------------------------
echo [build] Self-test of dist\OSINTHub
set REPORT=%CD%\build\selftest.json
if exist "%REPORT%" del "%REPORT%"
start "" /wait "dist\OSINTHub\OSINTHub.exe" --selftest "%REPORT%"
set ST=%ERRORLEVEL%
%VPY% -c "import json,sys;r=json.load(open(sys.argv[1],encoding='utf-8'));[print(('  OK  ' if x['ok'] else '  FAIL'),x['check'],'-',x['detail']) for x in r['results']]" "%REPORT%"
if not "%ST%"=="0" (
  echo [build] ERROR: self-test failed, see %REPORT%
  exit /b 1
)

rem ---- 8. installer ------------------------------------------------------------
if "%NO_INSTALLER%"=="1" goto done
set ISCC=
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%P set ISCC=%%~P
)
if not defined ISCC (
  where iscc >nul 2>&1 && set ISCC=iscc
)
if not defined ISCC (
  echo [build] Inno Setup 6 not found - installer skipped.
  echo [build] Install it:  winget install JRSoftware.InnoSetup   then run build.bat again.
  goto done
)
echo [build] Building installer
"%ISCC%" /Q build\installer.iss || goto fail

:done
echo.
echo [build] Done.
echo   App:        dist\OSINTHub\OSINTHub.exe
if exist "dist\installer" for %%F in (dist\installer\*.exe) do echo   Installer:  %%F
exit /b 0

:fail
echo [build] FAILED (exit code %ERRORLEVEL%)
exit /b 1
