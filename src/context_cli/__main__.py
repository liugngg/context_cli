"""程序入口：GUI 管理端与右键菜单 Runner。"""

from __future__ import annotations

import argparse
import ctypes
import sys

from . import __version__
from .config import config_path
from .dpi import set_process_dpi_awareness
from .jobs import JobError, plan_jobs, plan_jobs_multi
from .runner import run_jobs, run_jobs_console_window
from .storage import ConfigError, load_config


def _message(title: str, text: str, flags: int = 0x10) -> None:
    """使用 Win32 MessageBox，避免 Runner 依赖 Tk 初始化。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), flags)
        return
    except Exception:
        pass
    try:
        print(f"{title}: {text}", file=sys.stderr)
    except Exception:
        pass


def _print(text: str) -> None:
    try:
        print(text)
    except Exception:
        pass


def _load(config_file: str | None):
    try:
        return load_config(config_file)
    except ConfigError as exc:
        _message("配置读取失败", str(exc))
        return None


def _run_command(args: argparse.Namespace) -> int:
    config = _load(args.config)
    if config is None:
        return 2

    command = config.find(args.run)
    if command is None:
        _message(
            "命令不存在",
            f"配置中找不到命令 ID：{args.run}\n\n配置：{args.config or config_path()}",
        )
        return 2

    if not command.enabled:
        _message("命令已停用", f"命令「{command.name}」当前处于停用状态。")
        return 2

    # 参数为空：不匹配扩展名、不展开变量，用系统默认方式直接启动程序。
    if not command.arguments.strip():
        from .jobs import start_direct

        try:
            start_direct(command.executable)
        except JobError as exc:
            _message("无法执行", str(exc))
            return 2
        return 0

    # 多选合并：资源管理器对多选按文件逐个启动本程序，
    # 首个实例等待并收集同一批的所有路径后统一执行。
    from .batching import cleanup_stale_pending, collect_selection

    cleanup_stale_pending()
    paths = collect_selection(command.id, args.path)
    if paths is None:
        return 0  # 已投递给协调者实例，本进程直接退出

    try:
        if len(paths) == 1:
            jobs = plan_jobs(command, paths[0])
        else:
            jobs = plan_jobs_multi(command, paths)
    except JobError as exc:
        _message("无法执行", str(exc))
        return 2

    if not jobs:
        _message(
            "没有匹配文件",
            "所选位置没有匹配扩展名的文件。\n\n" + "\n".join(paths),
            0x40,
        )
        return 1

    # 执行前列出待处理文件的数量与文件名，让用户确认后再开始。
    names = [job.input_path.name for job in jobs]
    preview = "、".join(names[:12])
    if len(names) > 12:
        preview += f" … 等共 {len(names)} 个"
    summary = f"共 {len(jobs)} 个待处理文件：\n{preview}"

    if not _confirm_run(command.name, summary):
        return 1

    # show_console=True：单/多文件统一走控制台窗口（subprocess.run + bat 包装），
    # 不经管道捕获，彻底回避子程序编码问题；结束后 pause 等待用户按键。
    # show_console=False：单文件静默捕获；多文件走 Tk 进度窗口。
    if command.show_console:
        batch = run_jobs_console_window(jobs)
        # 控制台模式不弹失败弹窗（用户已在控制台窗口看到输出），仅记录日志。
        return 0

    if len(jobs) == 1:
        batch = run_jobs(jobs, capture=True)
        result = batch.results[0]
        if not result.succeeded:
            details = [f"退出码：{result.exit_code}"]
            if result.error:
                details.append(f"错误：{result.error}")
            if result.cancelled:
                details.append("状态：已取消")
            if batch.log_path:
                details.append(f"日志：{batch.log_path}")
            _message("命令执行失败", "\n".join(details))
            return 1
        return 0

    # 多文件静默模式：Tk 进度窗口
    from .ui.progress_window import ProgressWindow

    window = ProgressWindow(jobs)
    batch = window.run()
    if batch is None:
        _message("执行未完成", "批量任务窗口已关闭，任务可能被取消。")
        return 1
    if batch.failed:
        _message(
            "批量执行完成（有失败）",
            f"成功 {batch.succeeded}，失败/取消 {batch.failed}\n"
            f"日志：{batch.log_path}",
            0x30,
        )
        return 1
    return 0


def _confirm_run(command_name: str, summary: str) -> bool:
    """执行前列出待处理文件数量与文件名，返回用户是否确认。"""
    try:
        text = (
            f"命令：{command_name}\n\n{summary}\n\n是否开始执行？"
        )
        flags = 0x40 | 0x04  # MB_ICONINFORMATION | MB_YESNO
        return ctypes.windll.user32.MessageBoxW(
            None, text, "快捷执行", flags
        ) == 6  # IDYES
    except Exception:
        return True  # 无法弹窗时直接执行，保持可用性


def _run_registry(args: argparse.Namespace) -> int:
    from . import registry

    try:
        if args.unregister:
            removed = registry.unregister()
            _print(f"已移除 {removed} 个右键菜单项。")
            return 0

        config = _load(args.config)
        if config is None:
            return 2
        stats = registry.register(config)
        _print(
            f"已注册：{stats.extension_count} 个扩展名，"
            f"文件菜单项 {stats.command_count} 个，"
            f"所有文件菜单项 {stats.all_files_command_count} 个，"
            f"文件夹菜单项 {stats.folder_command_count} 个。"
        )
        return 0
    except registry.RegistryError as exc:
        _message("注册表操作失败", str(exc))
        return 1
    except Exception as exc:
        _message("注册表操作失败", f"{type(exc).__name__}: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="context-cli",
        description="Windows 资源管理器「快捷执行」右键菜单 CLI 管理器",
    )
    parser.add_argument(
        "--run",
        metavar="COMMAND_ID",
        help="由右键菜单调用：执行指定命令",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="选中的文件或文件夹（配合 --run 使用；多选时资源管理器"
        "会按文件逐个启动本程序，由程序自动合并为一批执行）",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="注册右键菜单后退出",
    )
    parser.add_argument(
        "--unregister",
        action="store_true",
        help="移除右键菜单后退出",
    )
    parser.add_argument(
        "--config",
        metavar="YAML",
        help="使用指定配置文件（默认 %%APPDATA%%\\ContextCLI\\commands.yaml）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.run and (args.register or args.unregister):
        parser.error("--run 不能与 --register/--unregister 同时使用")
    if args.register and args.unregister:
        parser.error("--register 与 --unregister 不能同时使用")
    if args.run and not args.path:
        parser.error("--run 需要提供文件或文件夹路径")
    if (args.register or args.unregister) and args.path:
        parser.error("--register/--unregister 不接受路径参数")

    set_process_dpi_awareness()

    if args.run:
        return _run_command(args)
    if args.register or args.unregister:
        return _run_registry(args)

    from .ui.main_window import MainWindow

    window = MainWindow(config_file=args.config)
    window.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
