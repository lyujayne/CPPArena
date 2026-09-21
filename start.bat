@echo off
setlocal
cd /d "%~dp0"

set "PY="

if exist "E:\anaconda\python.exe" set "PY=E:\anaconda\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [错误] 未找到 Python，请安装 Python 3.10+ 后重试。
    pause
    exit /b 1
)

echo [CPPBench] Python: %PY%

"%PY%" -c "import PySide6, shapely, pyproj, matplotlib, numpy, pandas, lxml" >nul 2>nul
if errorlevel 1 (
    echo [CPPBench] 正在安装依赖，请稍候...
    "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [CPPBench] 清华镜像不可用，改用官方 PyPI...
        "%PY%" -m pip install -r requirements.txt
    )
    "%PY%" -c "import PySide6, shapely, pyproj, matplotlib, numpy, pandas, lxml" >nul 2>nul
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行：
        echo   %PY% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo [CPPBench] 正在启动 CPPBench...
"%PY%" main.py
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出，请查看上方错误信息。
    pause
)
endlocal