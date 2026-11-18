"""实验：验证控制台模式 bat 包装的机制（不含 pause，避免挂起）。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 实验1：直接跑 .bat，CREATE_NEW_CONSOLE，能否拿到退出码
bat1 = Path(tempfile.mkstemp(suffix=".bat")[1])
bat1.write_text("@echo off\r\ncmd /c exit /b 7\r\nset RC=%errorlevel%\r\nexit /b %RC%\r\n")
r1 = subprocess.run([str(bat1)], creationflags=subprocess.CREATE_NEW_CONSOLE, capture_output=False)
print("实验1 bat 直接执行 returncode =", r1.returncode, "(期望 7)")
bat1.unlink()

# 实验2：命令行通过环境变量传入 bat（避免中文路径写进 bat 的编码问题）
#   bat 内容纯 ASCII；命令行从 env 取；退出码写入 result 文件
result_file = Path(tempfile.mkstemp(suffix=".txt")[1])
result_file.unlink()  # 让 bat 自己创建
bat2 = Path(tempfile.mkstemp(suffix=".bat")[1])
bat2.write_text(
    "@echo off\r\n"
    "chcp 65001 >nul 2>&1\r\n"
    "%CONTEXT_CLI_CMD_0%\r\n"
    'echo %errorlevel%>>>"%CONTEXT_CLI_RESULT%"' + "\r\n"
    "%CONTEXT_CLI_CMD_1%\r\n"
    'echo %errorlevel%>>>"%CONTEXT_CLI_RESULT%"' + "\r\n"
)
env = os.environ.copy()
env["CONTEXT_CLI_CMD_0"] = 'cmd /c exit /b 3'
env["CONTEXT_CLI_CMD_1"] = 'cmd /c exit /b 0'
env["CONTEXT_CLI_RESULT"] = str(result_file)
r2 = subprocess.run([str(bat2)], creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
print("实验2 bat returncode =", r2.returncode)
print("实验2 result 文件存在:", result_file.exists())
if result_file.exists():
    lines = result_file.read_text().splitlines()
    print("实验2 退出码列表:", lines, "(期望 ['3','0'])")
bat2.unlink()
if result_file.exists():
    result_file.unlink()

# 实验3：命令行含中文路径，经 env 传入，验证 CreateProcessW 不丢 Unicode
bat3 = Path(tempfile.mkstemp(suffix=".bat")[1])
# 用 python 自身打印 argv，验证中文路径完整传递
py = sys.executable
bat3.write_text(
    "@echo off\r\n"
    "chcp 65001 >nul 2>&1\r\n"
    "%CONTEXT_CLI_CMD_0%\r\n"
)
env3 = os.environ.copy()
# 用一个含中文的虚拟路径（不存在，但能验证传递）
env3["CONTEXT_CLI_CMD_0"] = f'"{py}" -c "import sys; print(repr(sys.argv)); print(sys.argv)" "D:\\test\\test - 副本.srt"'
r3 = subprocess.run([str(bat3)], creationflags=subprocess.CREATE_NEW_CONSOLE, env=env3, capture_output=True, text=True, encoding="utf-8")
print("实验3 stdout:", r3.stdout.strip().replace(os.linesep, " | "))
print("实验3 含中文路径:", "副本" in r3.stdout)
bat3.unlink()
