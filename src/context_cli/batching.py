"""多选文件时的跨进程合并收集。

资源管理器对静态注册表菜单的多次选中会按文件逐个启动本程序，
因此用「互斥体 + 待处理目录」把同一批启动合并给首个实例：

- 首个拿到互斥体的实例作为协调者，等待其余实例投递路径；
- 其余实例把路径写入 pending 目录后直接退出；
- 协调者收集到静默期（无新路径）后统一返回全部路径。
"""

from __future__ import annotations

import ctypes
import os
import shutil
import time
import uuid
from pathlib import Path

from .config import app_data_dir

GRACE_SECONDS = 0.5  # 无新路径到达的静默期，超过即认为收集完成
MAX_WAIT_SECONDS = 8.0  # 收集总时长上限，防止极端情况下一直等待
POLL_SECONDS = 0.05
STALE_PENDING_SECONDS = 86400  # pending 目录残留的最长保留时间

_WAIT_TIMEOUT = 0x00000102
_WAIT_ABANDONED = 0x00000080


def _pending_dir(command_id: str) -> Path:
    return app_data_dir(create=False) / "pending" / command_id


_ENQUEUE_SEQ = __import__("itertools").count()


def _enqueue_path(command_id: str, path: str) -> None:
    """把路径投递给当前协调者。文件名带序号+时间戳，保证读取顺序。"""
    directory = _pending_dir(command_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        seq = next(_ENQUEUE_SEQ)
        target = (
            directory
            / f"{seq:06d}-{time.time_ns():019d}-{os.getpid()}-{uuid.uuid4().hex}.txt"
        )
        target.write_text(path, encoding="utf-8")
    except OSError:
        pass


def _drain_pending(command_id: str) -> list[str]:
    """读取并删除 pending 目录中的全部路径（按投递顺序）。"""
    directory = _pending_dir(command_id)
    paths: list[str] = []
    try:
        entries = sorted(directory.glob("*.txt"))
    except OSError:
        return paths
    for entry in entries:
        try:
            text = entry.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        try:
            entry.unlink()
        except OSError:
            continue
        if text:
            paths.append(text)
    return paths


def cleanup_stale_pending(max_age_seconds: int = STALE_PENDING_SECONDS) -> None:
    """清理异常退出残留的 pending 目录。"""
    root = app_data_dir(create=False) / "pending"
    try:
        if not root.is_dir():
            return
        now = time.time()
        for child in root.iterdir():
            try:
                if child.is_dir() and now - child.stat().st_mtime > max_age_seconds:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def collect_selection(
    command_id: str,
    own_path: str,
    *,
    grace: float = GRACE_SECONDS,
    max_wait: float = MAX_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
) -> list[str] | None:
    """返回本批全部输入路径；若自己不是协调者，投递后返回 None。"""
    if os.name != "nt":
        return [own_path]

    kernel32 = ctypes.windll.kernel32
    mutex_name = "Local\\ContextCLI.batch." + command_id
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        # 无法创建互斥体时退化为直接执行自己的路径。
        return [own_path]

    wait_result = kernel32.WaitForSingleObject(handle, 0)
    if wait_result == _WAIT_TIMEOUT:
        # 已有协调者在收集，投递自己的路径后退出。
        kernel32.CloseHandle(handle)
        _enqueue_path(command_id, own_path)
        return None

    # WAIT_OBJECT_0 / WAIT_ABANDONED（上个协调者异常退出）：自己当协调者。
    try:
        # 刚拿到互斥体，清掉上次异常退出残留的投递文件是安全的。
        shutil.rmtree(_pending_dir(command_id), ignore_errors=True)
        paths = [own_path]
        seen = {os.path.normcase(os.path.abspath(own_path))}
        start = last_arrival = time.monotonic()
        while True:
            time.sleep(poll)
            for path in _drain_pending(command_id):
                key = os.path.normcase(os.path.abspath(path))
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
            now = time.monotonic()
            if now - start >= max_wait:
                break
            if now - last_arrival >= grace:
                break
        return paths
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
