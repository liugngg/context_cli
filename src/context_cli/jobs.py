"""输入收集、输出路径规划与最终命令行构造。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_OUTPUT_NAME
from .models import Command
from .variables import VariableError, expand


class JobError(Exception):
    """无法为命令生成可执行任务。"""


@dataclass
class Job:
    command: Command
    input_path: Path
    output_dir: Path
    output_name: str
    output_path: Path
    variables: dict[str, str]
    executable: Path
    command_line: str
    relative_dir: Path | None = None


def resolve_executable(value: str) -> Path:
    """支持完整路径或 PATH 中的命令名。"""
    raw = (value or "").strip().strip('"')
    if not raw:
        raise JobError("未设置执行程序")

    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    found = shutil.which(raw)
    if found:
        return Path(found).resolve()

    raise JobError(f"找不到执行程序: {raw}")


def start_direct(executable: str) -> None:
    """参数为空时用系统默认方式直接启动程序（不传参、不匹配扩展名）。"""
    raw = (executable or "").strip().strip('"')
    if not raw:
        raise JobError("未设置执行程序")

    candidate = Path(raw).expanduser()
    if candidate.is_file():
        target = str(candidate.resolve())
    else:
        found = shutil.which(raw)
        if not found:
            raise JobError(f"找不到执行程序: {raw}")
        target = found

    try:
        os.startfile(target)  # noqa: S606 - 预期行为：交给 shell 打开
    except OSError as exc:
        raise JobError(f"启动程序失败: {exc}") from exc


def collect_inputs(command: Command, input_path: str | Path) -> tuple[list[Path], Path]:
    """返回待处理文件列表与选中的根路径。"""
    root = Path(os.path.abspath(os.path.expanduser(str(input_path))))
    if not root.exists():
        raise JobError(f"输入路径不存在: {root}")

    if root.is_file():
        if command.directories_only:
            raise JobError(f"该命令仅处理文件夹，不能用于文件: {root.name}")
        if not command.matches(root):
            raise JobError(f"文件扩展名不在命令列表中: {root.name}")
        return [root], root.parent

    if root.is_dir():
        return _scan_directory(command, root)

    raise JobError(f"不支持的输入类型: {root}")


def collect_inputs_multi(command: Command, paths: list[str]) -> list[Path]:
    """多选输入：文件按扩展名过滤，目录展开为其中匹配的文件。

    不支持仅目录命令；结果按输入顺序去重，目录内部文件按路径排序。
    """
    if command.directories_only:
        raise JobError("多选执行不支持仅目录命令，请单个选择文件夹")

    files: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        root = Path(os.path.abspath(os.path.expanduser(raw)))
        if not root.exists():
            continue
        if root.is_file():
            if command.matches(root):
                key = os.path.normcase(str(root))
                if key not in seen:
                    seen.add(key)
                    files.append(root)
            continue
        if root.is_dir():
            matched, _source_root = _scan_directory(command, root)
            for item in matched:
                key = os.path.normcase(str(item))
                if key not in seen:
                    seen.add(key)
                    files.append(item)

    if not files:
        raise JobError("所选文件均不匹配命令的扩展名")
    return files


def _scan_directory(command: Command, root: Path) -> tuple[list[Path], Path]:
    """扫描单个目录中匹配扩展名的文件，返回 (文件列表, 目录)。"""
    files: list[Path] = []
    if command.recurse:
        for directory, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                candidate = Path(directory) / filename
                if command.matches(candidate):
                    files.append(candidate)
    else:
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.is_file() and command.matches(entry.path):
                        files.append(Path(entry.path))
        except OSError as exc:
            raise JobError(f"读取文件夹失败: {root}: {exc}") from exc
    files.sort(key=lambda item: str(item).lower())
    return files, root


def _validate_output_name(name: str) -> None:
    if not name or not name.strip():
        raise JobError("输出文件名展开后为空")
    if name in {".", ".."}:
        raise JobError(f"输出文件名无效: {name}")
    if any(ch in name for ch in '<>:"/\\|?*'):
        raise JobError(f"输出文件名包含非法字符: {name}")
    if any(ord(ch) < 32 for ch in name):
        raise JobError("输出文件名包含控制字符")
    if name != name.rstrip(" ."):
        raise JobError("输出文件名不能以空格或点结尾")


def _expand_output(
    command: Command,
    input_file: Path,
    source_root: Path,
) -> tuple[dict[str, str], Path, str, Path, Path | None]:
    base_variables = {
        "input": str(input_file),
        "input_name": input_file.stem,
        "input_ext": input_file.suffix[1:],
        "input_dir": str(input_file.parent),
    }

    relative_dir: Path | None = None
    output_dir_setting = command.output_dir.strip()

    if output_dir_setting:
        try:
            output_value = expand(output_dir_setting, base_variables).strip().strip('"')
        except VariableError as exc:
            raise JobError(f"输出目录变量错误: {exc}") from exc
        if not output_value:
            raise JobError("输出目录展开后为空")

        output_base = Path(output_value).expanduser()
        if not output_base.is_absolute():
            output_base = source_root / output_base

        if command.keep_structure:
            try:
                relative = input_file.parent.relative_to(source_root)
            except ValueError:
                relative = Path(".")
            if relative.parts:
                relative_dir = relative
                output_dir = output_base / relative
            else:
                output_dir = output_base
        else:
            output_dir = output_base
    else:
        output_dir = input_file.parent

    template = command.output_name.strip() or DEFAULT_OUTPUT_NAME
    try:
        output_name = expand(template, base_variables)
    except VariableError as exc:
        raise JobError(f"输出文件名变量错误: {exc}") from exc

    _validate_output_name(output_name)
    output_path = output_dir / output_name

    variables = dict(base_variables)
    variables.update(
        {
            "output_dir": str(output_dir),
            "output_name": output_name,
            "output": str(output_path),
        }
    )
    return variables, output_dir, output_name, output_path, relative_dir


def plan_jobs(command: Command, input_path: str | Path) -> list[Job]:
    """根据命令配置与输入路径生成任务列表，不创建输出目录。"""
    errors = command.validate()
    if errors:
        raise JobError("；".join(errors))

    executable = resolve_executable(command.executable)
    files, source_root = collect_inputs(command, input_path)

    jobs: list[Job] = []
    for input_file in files:
        variables, output_dir, output_name, output_path, relative_dir = _expand_output(
            command, input_file, source_root
        )
        try:
            arguments = expand(command.arguments, variables).strip()
        except VariableError as exc:
            raise JobError(f"参数变量错误: {exc}") from exc

        command_line = subprocess.list2cmdline([str(executable)])
        if arguments:
            command_line = f"{command_line} {arguments}"

        jobs.append(
            Job(
                command=command,
                input_path=input_file,
                output_dir=output_dir,
                output_name=output_name,
                output_path=output_path,
                variables=variables,
                executable=executable,
                command_line=command_line,
                relative_dir=relative_dir,
            )
        )

    return jobs


def plan_jobs_multi(command: Command, paths: list[str]) -> list[Job]:
    """多选文件的任务规划：每个文件一个任务，目录展开为匹配文件。

    source_root 取每个输入文件各自的父目录/所在目录，与单选行为一致。
    """
    errors = command.validate()
    if errors:
        raise JobError("；".join(errors))

    executable = resolve_executable(command.executable)
    files = collect_inputs_multi(command, paths)

    jobs: list[Job] = []
    for input_file in files:
        variables, output_dir, output_name, output_path, relative_dir = (
            _expand_output(command, input_file, input_file.parent)
        )
        try:
            arguments = expand(command.arguments, variables).strip()
        except VariableError as exc:
            raise JobError(f"参数变量错误: {exc}") from exc

        command_line = subprocess.list2cmdline([str(executable)])
        if arguments:
            command_line = f"{command_line} {arguments}"

        jobs.append(
            Job(
                command=command,
                input_path=input_file,
                output_dir=output_dir,
                output_name=output_name,
                output_path=output_path,
                variables=variables,
                executable=executable,
                command_line=command_line,
                relative_dir=relative_dir,
            )
        )

    return jobs
