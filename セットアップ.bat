@echo off
chcp 65001 > nul
title Shorts Generator セットアップ

echo.
echo  =============================================
echo    YouTube Shorts Generator  セットアップ
echo  =============================================
echo.

:: ── Python 確認 ─────────────────────────────────
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [エラー] Python が見つかりません。
    echo.
    echo  以下の手順でインストールしてください：
    echo    1. https://www.python.org/downloads/ を開く
    echo    2. 「Download Python」をクリック
    echo    3. インストーラーを実行し、
    echo       「Add Python to PATH」に必ずチェックを入れる
    echo    4. インストール完了後、このファイルをもう一度実行
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PY_VER=%%i
echo  [OK] %PY_VER% を検出しました
echo.

:: ── パッケージインストール ───────────────────────
echo  [1/2] 必要なパッケージをインストール中...
echo        初回は数分かかります。しばらくお待ちください。
echo.
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo  [エラー] パッケージのインストールに失敗しました。
    echo  インターネット接続を確認してから再実行してください。
    pause
    exit /b 1
)
echo  [OK] パッケージのインストール完了
echo.

:: ── デスクトップショートカット作成 ──────────────
echo  [2/2] デスクトップにショートカットを作成中...

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

powershell -ExecutionPolicy Bypass -Command ^
  "$py = (Get-Command python).Source -replace 'python.exe','pythonw.exe';" ^
  "$dir = '%SCRIPT_DIR%';" ^
  "$desk = [Environment]::GetFolderPath('Desktop');" ^
  "$sh = New-Object -ComObject WScript.Shell;" ^
  "$sc = $sh.CreateShortcut(\"$desk\Shorts Generator.lnk\");" ^
  "$sc.TargetPath = $py;" ^
  "$sc.Arguments = \"`\"$dir\app.py`\"\";" ^
  "$sc.WorkingDirectory = $dir;" ^
  "$sc.Description = 'YouTube Shorts Generator';" ^
  "$sc.IconLocation = $py;" ^
  "$sc.Save();" ^
  "Write-Host '  [OK] ショートカットを作成しました'"

echo.
echo  =============================================
echo    セットアップ完了！
echo  =============================================
echo.
echo  デスクトップに「Shorts Generator」が作成されました。
echo.
echo  起動前に VOICEVOX を立ち上げておいてください。
echo.
pause
