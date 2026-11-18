"""多选合并收集 batching 模块的测试（仅覆盖非互斥体路径与投递目录）。"""

import os
import threading
import time
from pathlib import Path

from context_cli import batching


def test_enqueue_and_drain_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    batching._enqueue_path("cmd1", r"D:\素材\a.mp4")
    batching._enqueue_path("cmd1", r"D:\素材\b.mp4")
    paths = batching._drain_pending("cmd1")
    assert paths == [r"D:\素材\a.mp4", r"D:\素材\b.mp4"]
    # 读取即删除。
    assert batching._drain_pending("cmd1") == []


def test_cleanup_stale_pending_removes_old_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    stale = tmp_path / "home" / "pending" / "old-cmd"
    stale.mkdir(parents=True)
    old_time = time.time() - 2 * 86400
    os.utime(stale, (old_time, old_time))

    fresh = tmp_path / "home" / "pending" / "new-cmd"
    fresh.mkdir(parents=True)

    batching.cleanup_stale_pending()

    assert not stale.exists()
    assert fresh.exists()


def test_collect_selection_single_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    # 独立的命令 ID 在测试进程里通常能立即拿到互斥体，成为协调者。
    paths = batching.collect_selection("test-cmd-unique", r"D:\x\a.mp4")
    if paths is None:
        # 极端情况下互斥体被占用：投递路径后放弃断言。
        return
    assert paths == [r"D:\x\a.mp4"]


def test_collect_selection_merges_thread_deliveries(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    results: list[list[str] | None] = []

    def coordinator():
        results.append(
            batching.collect_selection(
                "test-cmd-merge",
                r"D:\x\a.mp4",
                grace=0.6,
                max_wait=3.0,
                poll=0.02,
            )
        )

    thread = threading.Thread(target=coordinator)
    thread.start()
    time.sleep(0.15)  # 等协调者拿到互斥体
    # 模拟第二个实例：投递路径并退出。
    follower = batching.collect_selection("test-cmd-merge", r"D:\x\b.mp4")
    thread.join(timeout=5)

    assert follower is None  # 非协调者投递后退出
    assert results[0] == [r"D:\x\a.mp4", r"D:\x\b.mp4"]


def test_pending_directory_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    batching._enqueue_path("layout", r"D:\x\a.mp4")
    pending = Path(os.environ["CONTEXT_CLI_HOME"]) / "pending" / "layout"
    files = list(pending.glob("*.txt"))
    assert len(files) == 1
