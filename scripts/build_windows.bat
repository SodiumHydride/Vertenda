@echo off
REM -----------------------------------------------------------------------------
REM Salt Converter - Windows packaging script
REM
REM Usage:
REM   scripts\build_windows.bat [options]
REM
REM Options:
REM   --download-ffmpeg   Download a static ffmpeg build (gyan.dev, includes libass)
REM   --clean             Remove and recreate the build virtualenv
REM   -h | --help         Show this help
REM
REM Encoding notes:
REM   - This file is saved as UTF-8 (no BOM). We switch to code page 65001 on
REM     line 1 so any Chinese text in ECHO lines renders correctly on Win10+.
REM   - Avoid editing this file with Notepad, which tends to save as ANSI/GBK
REM     and corrupts the UTF-8 bytes. Use VS Code / Cursor and keep it UTF-8.
REM -----------------------------------------------------------------------------
chcp 65001 >nul
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
pushd "%PROJECT_ROOT%" >nul
set "PROJECT_ROOT=%CD%"

set DOWNLOAD_FFMPEG=0
set CLEAN_VENV=0

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--download-ffmpeg" ( set DOWNLOAD_FFMPEG=1 & shift & goto parse_args )
if /I "%~1"=="--clean"           ( set CLEAN_VENV=1     & shift & goto parse_args )
if /I "%~1"=="-h"                ( goto show_help )
if /I "%~1"=="--help"            ( goto show_help )
echo [error] Unknown argument: %~1
echo Use --help for usage.
popd >nul
exit /b 1

:show_help
echo.
echo Salt Converter - Windows packaging
echo.
echo Usage:
echo   scripts\build_windows.bat [--download-ffmpeg] [--clean]
echo.
echo Options:
echo   --download-ffmpeg   Download a static ffmpeg build (gyan.dev, includes libass)
echo   --clean             Remove and recreate the build virtualenv
echo.
popd >nul
exit /b 0

:args_done
echo [build] 工作目录: %PROJECT_ROOT%

REM --- Locate Python -----------------------------------------------------------
set "PYTHON="
where py >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON (
    where python >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    echo [error] Cannot find Python. Install from https://www.python.org/ and tick "Add to PATH".
    popd >nul
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON% -c "import sys;print(\"{}.{}\".format(*sys.version_info[:2]))"') do set "PY_VERSION=%%v"
echo [build] 使用 Python %PY_VERSION% (%PYTHON%)

%PYTHON% -c "import sys;assert sys.version_info[:2] >= (3,9)" 2>nul
if errorlevel 1 (
    echo [error] Python ^>= 3.9 required, got %PY_VERSION%.
    popd >nul
    exit /b 1
)

REM --- Virtual environment -----------------------------------------------------
set "VENV_DIR=%PROJECT_ROOT%\.venv-build"
if "%CLEAN_VENV%"=="1" if exist "%VENV_DIR%" (
    echo [build] 清理旧 venv: %VENV_DIR%
    rmdir /s /q "%VENV_DIR%"
)

if not exist "%VENV_DIR%" (
    echo [build] 创建虚拟环境: %VENV_DIR%
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [error] venv creation failed.
        popd >nul
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] activate.bat failed.
    popd >nul
    exit /b 1
)

echo [build] 升级 pip / setuptools / wheel
python -m pip install --quiet --upgrade pip setuptools wheel

echo [build] 安装运行依赖
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [error] pip install requirements failed.
    popd >nul
    exit /b 1
)

echo [build] 安装 PyInstaller
python -m pip install --quiet pyinstaller
if errorlevel 1 (
    echo [error] pip install pyinstaller failed.
    popd >nul
    exit /b 1
)

REM --- Optional: download static ffmpeg ----------------------------------------
if "%DOWNLOAD_FFMPEG%"=="1" (
    echo [build] 下载静态 ffmpeg ^(gyan.dev, Windows build 含 libass^)
    set "FF_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    set "FF_TMP=%TEMP%\convert_ffmpeg.zip"
    set "FF_EXTRACT=%TEMP%\convert_ffmpeg_extract"
    if exist "%FF_TMP%" del "%FF_TMP%"
    if exist "%FF_EXTRACT%" rmdir /s /q "%FF_EXTRACT%"

    where curl >nul 2>nul
    if not errorlevel 1 (
        curl -fsSL -o "%FF_TMP%" "%FF_URL%"
    ) else (
        echo [build] curl 不可用，改用 PowerShell 下载
        powershell -NoProfile -Command "Invoke-WebRequest -Uri '%FF_URL%' -OutFile '%FF_TMP%'"
    )
    if errorlevel 1 (
        echo [error] ffmpeg download failed.
        popd >nul
        exit /b 1
    )

    mkdir "%FF_EXTRACT%" >nul 2>nul
    powershell -NoProfile -Command "Expand-Archive -Path '%FF_TMP%' -DestinationPath '%FF_EXTRACT%' -Force"
    if errorlevel 1 (
        echo [error] Expand-Archive failed.
        popd >nul
        exit /b 1
    )

    REM The gyan.dev zip places exe files under <version>/bin/
    if not exist resources mkdir resources
    for /f "delims=" %%f in ('dir /s /b "%FF_EXTRACT%\ffmpeg.exe"') do copy /Y "%%f" "resources\ffmpeg.exe" >nul
    for /f "delims=" %%f in ('dir /s /b "%FF_EXTRACT%\ffprobe.exe"') do copy /Y "%%f" "resources\ffprobe.exe" >nul

    if not exist "resources\ffmpeg.exe" (
        echo [error] ffmpeg.exe not found in extracted archive.
        popd >nul
        exit /b 1
    )
    echo [build] resources\ffmpeg.exe 已更新
    rmdir /s /q "%FF_EXTRACT%" >nul 2>nul
    del "%FF_TMP%" >nul 2>nul
)

if exist resources\ffmpeg.exe (
    resources\ffmpeg.exe -version >nul 2>nul
    if errorlevel 1 (
        echo [warn] resources\ffmpeg.exe 无法运行，运行时会回退到 PATH 上的 ffmpeg。
        echo [warn] 建议加 --download-ffmpeg 重新打包。
    )
) else if exist resources\ffmpeg (
    REM Mach-O binary from macOS copy won't run on Windows.
    echo [warn] resources\ffmpeg 看起来不是 Windows 可执行文件。
    echo [warn] 建议加 --download-ffmpeg 下载 Windows 版本。
)

REM --- Clean previous artifacts ------------------------------------------------
echo [build] 清理旧的 build\ dist\
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM --- Run PyInstaller ---------------------------------------------------------
echo [build] 开始 PyInstaller 打包
pyinstaller Main.spec --clean --noconfirm
if errorlevel 1 (
    echo [error] PyInstaller failed.
    popd >nul
    exit /b 1
)

if exist "dist\Main\Main.exe" (
    echo [build] 打包完成: dist\Main\Main.exe
) else if exist "dist\Main.exe" (
    echo [build] 打包完成: dist\Main.exe
) else (
    echo [error] 未找到 Main.exe。请检查 PyInstaller 输出。
    popd >nul
    exit /b 1
)

echo.
echo [build] ✓ 全部完成。
echo [build]   可以运行:  dist\Main\Main.exe
echo.
popd >nul
endlocal
exit /b 0
