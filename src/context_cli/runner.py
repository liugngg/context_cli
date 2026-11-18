"""子进程执行、输出捕获与运行日志。"""

from __future__ import annotations

import locale
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from .config import LOG_RETENTION_DAYS, logs_dir
from .jobs import Job

OutputCallback = Callable[[str], None]
JobStartCallback = Callable[[int, int, Job], None]


@dataclass
class RunResult:
    job: Job
    exit_code: int | None = None
    duration: float = 0.0
    cancelled: bool = False
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.cancelled and self.exit_code == 0


@dataclass
class BatchResult:
    results: list[RunResult] = field(default_factory=list)
    log_path: Path | None = None
    cancelled: bool = False

    @property
    def succeeded(self) -> int:
        return sum(1 for result in self.results if result.succeeded)

    @property
    def failed(self) -> int:
        return len(self.results) - self.succeeded


def create_log_path(command_name: str, command_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^0-9A-Za-z_\-一-鿿]+", "_", command_name).strip("_")[:40]
    safe_name = safe_name or "run"
    directory = logs_dir()
    path = directory / f"{stamp}-{safe_name}-{command_id}.log"
    index = 1
    while path.exists():
        path = directory / f"{stamp}-{safe_name}-{command_id}-{index}.log"
        index += 1
    return path


def cleanup_old_logs(days: int = LOG_RETENTION_DAYS) -> int:
    cutoff = time.time() - days * 86400
    removed = 0
    try:
        directory = logs_dir(create=False)
        if not directory.exists():
            return 0
        for entry in directory.iterdir():
            try:
                if (
                    entry.is_file()
                    and entry.suffix.lower() == ".log"
                    and entry.stat().st_mtime < cutoff
                ):
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    return removed


def _decode_bytes(data: bytes) -> str:
    encodings = ["utf-8"]
    preferred = locale.getpreferredencoding(False)
    if preferred:
        encodings.append(preferred)
    if os.name == "nt":
        encodings.append("mbcs")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _stream_reader(pipe, emit: Callable[[str], None]) -> None:
    pending = b""
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            pending += chunk
            while True:
                indexes = [
                    index
                    for index in (pending.find(b"\n"), pending.find(b"\r"))
                    if index >= 0
                ]
                if not indexes:
                    break
                index = min(indexes)
                line = pending[:index]
                pending = pending[index + 1 :]
                if line:
                    emit(_decode_bytes(line))
        if pending:
            emit(_decode_bytes(pending))
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _kill_process_tree(pid: int) -> None:
    if os.name != "nt":
        try:
            import signal

            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except OSError:
        pass


def _write_log(handle: TextIO | None, text: str) -> None:
    if handle is None:
        return
    try:
        handle.write(text + "\n")
        handle.flush()
    except (OSError, ValueError):
        pass


def _build_console_bat(jobs: list[Job]) -> Path:
    """生成临时 .bat，逐个执行 jobs，末尾 pause 等待用户按键关闭。

    命令行与中文提示均通过 env var 注入，bat 文件本身纯 ASCII，
    彻底回避系统 GBK/UTF-8 编码问题。
    """
    lines = ["@echo off", "chcp 65001 >nul 2>&1", ""]
    for index, job in enumerate(jobs):
        lines.append(f"cd /d %__CTX_CWD_{index}%")
        lines.append(f"echo [{index + 1}/{len(jobs)}] %__CTX_LABEL_{index}%")
        lines.append(f"%__CTX_LINE_{index}%")
        lines.append("")
    lines += [
        "echo.",
        "echo %__CTX_DONE_MSG%",
        "pause >nul",
        "exit /b 0",
    ]
    fd, path = tempfile.mkstemp(suffix=".bat", prefix="ctx_run_")
    try:
        os.write(fd, "\r\n".join(lines).encode("ascii"))
    finally:
        os.close(fd)
    return Path(path)


def run_jobs_console_window(jobs: list[Job]) -> BatchResult:
    """以新控制台窗口运行所有 jobs，结束后 pause 等待用户按键。

    不捕获输出（回避管道编码问题）；log_path 写元数据供事后排查。
    """
    cleanup_old_logs()
    log_path = create_log_path(jobs[0].command.name, jobs[0].command.id) if jobs else None
    batch = BatchResult(log_path=log_path)
    if not jobs:
        return batch

    if log_path:
        with open(log_path, "a", encoding="utf-8") as lh:
            _write_log(lh, "=" * 64)
            _write_log(lh, f"运行开始: {datetime.now():%Y-%m-%d %H:%M:%S}")
            _write_log(lh, f"命令: {jobs[0].command.name} ({jobs[0].command.id})")
            _write_log(lh, f"任务数: {len(jobs)}  模式: 控制台（新窗口）")
            _write_log(lh, "=" * 64)
            for index, job in enumerate(jobs, start=1):
                _write_log(lh, f"[{index}/{len(jobs)}] {job.input_path}")
                _write_log(lh, f"  命令行: {job.command_line}")

    if os.name != "nt":
        for job in jobs:
            result = run_job(job, capture=False)
            batch.results.append(result)
        return batch

    bat = _build_console_bat(jobs)
    env = os.environ.copy()
    for index, job in enumerate(jobs):
        env[f"__CTX_CWD_{index}"] = str(job.executable.parent)
        env[f"__CTX_LABEL_{index}"] = job.input_path.name
        env[f"__CTX_LINE_{index}"] = job.command_line
    env["__CTX_DONE_MSG"] = "全部完成，按任意键关闭此窗口…"

    started = time.monotonic()
    try:
        subprocess.run(
            [str(bat)],
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            check=False,
        )
    except (OSError, ValueError) as exc:
        for job in jobs:
            batch.results.append(
                RunResult(job=job, error=f"启动失败: {exc}",
                          duration=time.monotonic() - started)
            )
        return batch
    finally:
        try:
            bat.unlink()
        except OSError:
            pass

    # bat 整体阻塞运行完后返回；无法拿到每个 job 的退出码，
    # 用户已在控制台窗口看到输出，统一标记 exit_code=0。
    duration = time.monotonic() - started
    for job in jobs:
        batch.results.append(RunResult(job=job, exit_code=0, duration=duration))
    return batch


def run_job(
    job: Job,
    *,
    capture: bool = True,
    on_output: OutputCallback | None = None,
    stop_event: threading.Event | None = None,
    log_handle: TextIO | None = None,
) -> RunResult:
    started = time.monotonic()
    result = RunResult(job=job)

    try:
        job.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.error = f"创建输出目录失败: {exc}"
        result.duration = time.monotonic() - started
        return result

    # 控制台模式：subprocess.run() 阻塞运行，子进程输出直接实时显示在
    # 新开的控制台窗口里，不经过管道，兼容任意编码的子进程输出。
    # 通过 _build_console_bat / run_jobs_console_window 调用时不走此分支；
    # 此处保留用于 GUI 测试面板手动触发的单文件控制台路径。
    if not capture and stop_event is None:
        try:
            completed = subprocess.run(
                job.command_line,
                cwd=str(job.executable.parent),
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    if os.name == "nt"
                    else 0
                ),
                check=False,
            )
        except (OSError, ValueError) as exc:
            result.error = f"启动进程失败: {exc}"
            result.duration = time.monotonic() - started
            return result
        result.exit_code = completed.returncode
        result.duration = time.monotonic() - started
        return result

    # 捕获模式（测试面板 / 批量进度窗口）：Popen 管道流式读取并支持停止。
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if capture
            else getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        )

    try:
        process = subprocess.Popen(
            job.command_line,
            cwd=str(job.executable.parent),
            stdin=subprocess.DEVNULL if capture else None,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            creationflags=creationflags,
            bufsize=0,
        )
    except (OSError, ValueError) as exc:
        result.error = f"启动进程失败: {exc}"
        result.duration = time.monotonic() - started
        return result

    reader: threading.Thread | None = None
    if capture and process.stdout is not None:

        def emit(text: str) -> None:
            _write_log(log_handle, text)
            if on_output is not None:
                try:
                    on_output(text)
                except Exception:
                    pass

        reader = threading.Thread(
            target=_stream_reader,
            args=(process.stdout, emit),
            daemon=True,
        )
        reader.start()

    cancelled = False
    while process.poll() is None:
        if stop_event is not None and stop_event.is_set():
            cancelled = True
            _kill_process_tree(process.pid)
            break
        time.sleep(0.05)

    try:
        exit_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process.pid)
        exit_code = process.wait()
        result.error = "进程未在预期时间内退出，已强制结束"

    if reader is not None:
        reader.join(timeout=5)

    result.exit_code = exit_code
    result.cancelled = cancelled
    result.duration = time.monotonic() - started
    return result


def run_jobs(
    jobs: list[Job],
    *,
    capture: bool = True,
    on_output: OutputCallback | None = None,
    on_job_start: JobStartCallback | None = None,
    stop_event: threading.Event | None = None,
) -> BatchResult:
    batch = BatchResult()
    if not jobs:
        return batch

    # 运行前清理超过保留期的日志，避免历史日志无限增长。
    cleanup_old_logs()

    log_path = create_log_path(jobs[0].command.name, jobs[0].command.id)
    batch.log_path = log_path
    total = len(jobs)

    with open(log_path, "a", encoding="utf-8") as log_handle:
        _write_log(log_handle, "=" * 64)
        _write_log(log_handle, f"运行开始: {datetime.now():%Y-%m-%d %H:%M:%S}")
        _write_log(
            log_handle,
            f"命令: {jobs[0].command.name} ({jobs[0].command.id})",
        )
        _write_log(
            log_handle,
            f"任务数: {total}  模式: {'捕获输出' if capture else '控制台'}",
        )
        _write_log(log_handle, "=" * 64)

        for index, job in enumerate(jobs, start=1):
            if stop_event is not None and stop_event.is_set():
                batch.cancelled = True
                break

            if on_job_start is not None:
                try:
                    on_job_start(index, total, job)
                except Exception:
                    pass

            _write_log(log_handle, "")
            _write_log(log_handle, f"[{index}/{total}] {job.input_path}")
            _write_log(log_handle, f"  输出: {job.output_path}")
            _write_log(log_handle, f"  工作目录: {job.executable.parent}")
            _write_log(log_handle, f"  命令行: {job.command_line}")

            result = run_job(
                job,
                capture=capture,
                on_output=on_output,
                stop_event=stop_event,
                log_handle=log_handle,
            )
            batch.results.append(result)

            if result.error:
                _write_log(log_handle, f"  错误: {result.error}")
            _write_log(
                log_handle,
                f"  退出码: {result.exit_code}  耗时: {result.duration:.2f}s  "
                f"取消: {result.cancelled}",
            )

            if result.cancelled:
                batch.cancelled = True
                break

        _write_log(log_handle, "")
        _write_log(log_handle, "=" * 64)
        _write_log(
            log_handle,
            f"运行结束: 成功 {batch.succeeded}, 失败/取消 {batch.failed}, "
            f"已执行 {len(batch.results)}/{total}",
        )
        _write_log(log_handle, f"日志: {log_path}")

    return batch
