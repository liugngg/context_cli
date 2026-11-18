"""`__main__` Runner 入口的回归测试（重点：多选分支的名称解析）。

回归背景：`__main__.py` 曾漏导入 `plan_jobs_multi`，打包版多选执行时
报 NameError；单元测试都直接测 jobs 模块，未覆盖该分支。
"""

import sys
from pathlib import Path

from context_cli import __main__ as cli
from context_cli.models import AppConfig, Command
from context_cli.runner import BatchResult, RunResult
from context_cli.storage import save_config


def make_config(tmp_path: Path) -> Command:
    command = Command(
        id="abcd1234ef",
        name="回归",
        extensions=["txt"],
        executable=sys.executable,
        arguments='-c "print(1)" "{input}"',
        output_name="{input_name}.out.{input_ext}",
        show_console=False,
    )
    save_config(AppConfig(commands=[command]), tmp_path / "commands.yaml")
    return command


class _StubWindow:
    """替代 ProgressWindow：直接返回全部成功的批量结果。"""

    def __init__(self, jobs) -> None:
        self.jobs = jobs

    def run(self):
        return BatchResult(
            results=[RunResult(job=job, exit_code=0) for job in self.jobs]
        )


def test_run_multi_paths_executes_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    a = tmp_path / "a.txt"
    a.write_text("1", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("2", encoding="utf-8")
    command = make_config(tmp_path)

    # 模拟合并收集：协调者直接拿到两个路径。
    monkeypatch.setattr(
        "context_cli.batching.cleanup_stale_pending", lambda: None
    )
    monkeypatch.setattr(
        "context_cli.batching.collect_selection",
        lambda command_id, own_path, **kwargs: [str(a), str(b)],
    )
    monkeypatch.setattr(cli, "_confirm_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "context_cli.ui.progress_window.ProgressWindow", _StubWindow
    )

    exit_code = cli.main(
        ["--run", command.id, str(a), "--config", str(tmp_path / "commands.yaml")]
    )
    assert exit_code == 0


def test_run_single_path_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    a = tmp_path / "a.txt"
    a.write_text("1", encoding="utf-8")
    command = make_config(tmp_path)

    monkeypatch.setattr(
        "context_cli.batching.cleanup_stale_pending", lambda: None
    )
    monkeypatch.setattr(
        "context_cli.batching.collect_selection",
        lambda command_id, own_path, **kwargs: [str(a)],
    )
    monkeypatch.setattr(cli, "_confirm_run", lambda *args, **kwargs: True)

    exit_code = cli.main(
        ["--run", command.id, str(a), "--config", str(tmp_path / "commands.yaml")]
    )
    assert exit_code == 0
