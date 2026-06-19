@echo off
echo 开始执行启动流程...

:: 获取当前脚本所在目录（即存放脚本的路径）
set "script_dir=%~dp0"
echo 脚本所在目录：%script_dir%

:: 步骤2：从脚本目录切换到虚拟环境所在的根目录（../代表一级目录）
cd /d "%script_dir%" || (
    echo 错误：无法切换到虚拟环境根目录，请检查路径是否正确
    pause
    exit /b 1
)
echo 已切换到虚拟环境根目录：%cd%

:: 步骤3：激活虚拟环境
if not exist ".venv\Scripts\activate.bat" (
    echo 错误：未找到虚拟环境激活文件，请确认.venv目录存在
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat || (
    echo 错误：虚拟环境激活失败
    pause
    exit /b 1
)
echo 虚拟环境激活成功

:: 步骤4：切换回脚本所在目录（程序运行目录）
cd /d "%script_dir%" || (
    echo 错误：无法切换回程序运行目录，请检查路径是否正确
    pause
    exit /b 1
)
echo 已切换到脚本所在目录：%cd%

:: 提示用户可以进行手动操作
echo.
echo ==============================================
echo 虚拟环境已激活，当前可正常使用命令行
echo 输入 py 启动Python，或直接运行其他命令
echo 或输入其他命令（切换盘符、目录等）
echo 输入 exit 退出当前环境
echo ==============================================
echo.

:: 启动命令行
cmd /k 