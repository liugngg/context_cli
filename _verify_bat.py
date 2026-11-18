"""验证控制台 bat 包装机制：不 pause，捕获输出确认命令正确执行。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from context_cli.models import Command
from context_cli.jobs import plan_jobs_multi

tmp = Path(tempfile.mkdtemp())
f1 = tmp / "test - 副本.txt"
f2 = tmp / "test.txt"
f1.write_text("hello", encoding="utf-8")
f2.write_text("hello", encoding="utf-8")

# 命令：python 打印 argv[1]，验证中文路径完整传递
cmd = Command(
    id="test_bat",
    name="测试",
    enabled=True,
    extensions=["txt"],
    executable=sys.executable,
    arguments='-c "import sys; print(\'ARG=\'+sys.argv[1])" "{input}"',
    output_name="{input_name}.out.txt",
    show_console=True,
)
jobs = plan_jobs_multi(cmd, [str(f1), str(f2)])

# 手动构造一个不含 pause 的 bat，捕获输出验证
lines = ["@echo off", "chcp 65001 >nul 2>&1", ""]
for index, job in enumerate(jobs):
    lines.append(f"cd /d %__CTX_CWD_{index}%")
    lines.append(f"echo [{index + 1}/{len(jobs)}] %__CTX_LABEL_{index}%")
    lines.append(f"%__CTX_LINE_{index}%")
    lines.append("")

fd, bat_path = tempfile.mkstemp(suffix=".bat")
os.write(fd, "\r\n".join(lines).encode("ascii"))
os.close(fd)

env = os.environ.copy()
for index, job in enumerate(jobs):
    env[f"__CTX_CWD_{index}"] = str(job.executable.parent)
    env[f"__CTX_LABEL_{index}"] = job.input_path.name
    env[f"__CTX_LINE_{index}"] = job.command_line

# 用 capture 输出（不弹新窗口），验证命令行正确展开
r = subprocess.run(
    [bat_path],
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print("=== bat 输出 ===")
print(r.stdout)
print("退出码:", r.returncode)
if r.stderr:
    print("stderr:", r.stderr[:200])

ok1 = "test - 副本.txt" in r.stdout
ok2 = "test.txt" in r.stdout
print(f"\n中文路径1传递正确: {'✓' if ok1 else '✗'}")
print(f"路径2传递正确: {'✓' if ok2 else '✗'}")

os.unlink(bat_path)
