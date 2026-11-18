import os
import sys
import threading
import time
from pathlib import Path

from context_cli.config import logs_dir
from context_cli.jobs import plan_jobs
from context_cli.models import Command
from context_cli.runner import run_jobs


def make_job(tmp_path: Path, code: str, **command_overrides):
    source = tmp_path / "input.txt"
    source.write_text("x", encoding="utf-8")
    data = {
        "name": "runner-test",
        "extensions": ["txt"],
        "executable": sys.executable,
        "arguments": f'-c "{code}" "{{input}}"',
        "output_name": "{input_name}.out.{input_ext}",
    }
    data.update(command_overrides)
    command = Command(**data)
    return plan_jobs(command, source)[0], source


def test_capture_output_exit_code_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    job, source = make_job(
        tmp_path,
        "import os,sys; print(os.getcwd()); print(sys.argv[1]); print('ok')",
    )
    lines: list[str] = []
    batch = run_jobs([job], capture=True, on_output=lines.append)

    result = batch.results[0]
    assert result.exit_code == 0
    assert result.succeeded
    assert result.cancelled is False

    output = "\n".join(lines)
    assert str(Path(sys.executable).resolve().parent) in output
    assert str(source) in output
    assert "ok" in lines

    assert batch.log_path is not None
    assert batch.log_path.exists()
    log_text = batch.log_path.read_text(encoding="utf-8")
    assert "命令行" in log_text
    assert str(source) in log_text


def test_nonzero_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    job, _ = make_job(tmp_path, "import sys; sys.exit(3)")
    batch = run_jobs([job], capture=True)
    assert batch.results[0].exit_code == 3
    assert not batch.results[0].succeeded
    assert batch.failed == 1


def test_job_start_callback(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    job, _ = make_job(tmp_path, "print('hello')")
    starts: list[tuple[int, int, str]] = []
    run_jobs(
        [job],
        capture=True,
        on_job_start=lambda index, total, current: starts.append(
            (index, total, current.input_path.name)
        ),
    )
    assert starts == [(1, 1, "input.txt")]


def test_output_directory_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    target = tmp_path / "new" / "nested"
    job, _ = make_job(tmp_path, "print('x')", output_dir=str(target))
    run_jobs([job], capture=True)
    assert target.is_dir()


def test_cleanup_expired_logs_before_run(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    logs = logs_dir()
    old_log = logs / "old.log"
    old_log.write_text("old", encoding="utf-8")
    recent_log = logs / "recent.log"
    recent_log.write_text("recent", encoding="utf-8")
    old_time = time.time() - 2 * 86400
    os.utime(old_log, (old_time, old_time))
    recent_time = time.time() - 3600
    os.utime(recent_log, (recent_time, recent_time))

    probe = f"import os; print('OLD_EXISTS', os.path.exists({str(old_log)!r}))"
    job, _ = make_job(tmp_path, probe)
    lines: list[str] = []
    batch = run_jobs([job], capture=True, on_output=lines.append)

    assert "OLD_EXISTS False" in lines
    assert not old_log.exists()
    assert recent_log.exists()
    assert batch.log_path is not None and batch.log_path.exists()


def test_stop_event_cancels_process(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_CLI_HOME", str(tmp_path / "home"))
    job, _ = make_job(tmp_path, "import time; time.sleep(30)")
    stop = threading.Event()
    timer = threading.Timer(0.4, stop.set)
    timer.start()
    try:
        batch = run_jobs([job], capture=True, stop_event=stop)
    finally:
        timer.cancel()

    assert batch.cancelled
    assert batch.results[0].cancelled
    assert not batch.results[0].succeeded
