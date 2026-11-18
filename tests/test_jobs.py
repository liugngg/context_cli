import subprocess
import sys
from pathlib import Path

import pytest

from context_cli.jobs import (
    JobError,
    plan_jobs,
    plan_jobs_multi,
    resolve_executable,
)
from context_cli.models import Command


def make_command(**overrides) -> Command:
    data = {
        "name": "测试",
        "extensions": ["mp4"],
        "executable": sys.executable,
        "arguments": '-c "print(1)" "{input}"',
        "output_name": "{input_name}_out.{input_ext}",
        "recurse": False,
        "output_dir": "",
        "keep_structure": True,
    }
    data.update(overrides)
    return Command(**data)


def make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "素材"
    root.mkdir()
    (root / "a.mp4").write_text("a", encoding="utf-8")
    (root / "b.MP4").write_text("b", encoding="utf-8")
    (root / "c.txt").write_text("c", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "d.mp4").write_text("d", encoding="utf-8")
    return root


def test_resolve_executable_full_path():
    resolved = resolve_executable(sys.executable)
    assert resolved == Path(sys.executable).resolve()


def test_resolve_executable_missing():
    with pytest.raises(JobError, match="找不到"):
        resolve_executable("definitely-not-a-real-command-xyz")


def test_single_file_plan(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(), root / "a.mp4")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.input_path == root / "a.mp4"
    assert job.output_dir == root
    assert job.output_name == "a_out.mp4"
    assert job.output_path == root / "a_out.mp4"
    assert job.variables["input"] == str(root / "a.mp4")
    assert job.variables["input_ext"] == "mp4"
    assert job.variables["output"] == str(root / "a_out.mp4")
    assert job.executable == Path(sys.executable).resolve()
    assert job.command_line.startswith(subprocess.list2cmdline([str(job.executable)]))


def test_mismatched_extension_raises(tmp_path):
    root = make_tree(tmp_path)
    with pytest.raises(JobError, match="扩展名不在命令列表中"):
        plan_jobs(make_command(), root / "c.txt")


def test_folder_non_recursive(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(recurse=False), root)
    assert [job.input_path.name for job in jobs] == ["a.mp4", "b.MP4"]
    assert all(job.output_dir == root for job in jobs)


def test_folder_recursive(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(recurse=True), root)
    assert [job.input_path.name for job in jobs] == ["a.mp4", "b.MP4", "d.mp4"]


def test_custom_absolute_output_with_structure(tmp_path):
    root = make_tree(tmp_path)
    output = tmp_path / "out"
    jobs = plan_jobs(
        make_command(recurse=True, output_dir=str(output), keep_structure=True),
        root,
    )
    by_name = {job.input_path.name: job for job in jobs}
    assert by_name["a.mp4"].output_dir == output
    assert by_name["b.MP4"].output_dir == output
    assert by_name["d.mp4"].output_dir == output / "sub"
    assert by_name["d.mp4"].output_path == output / "sub" / "d_out.mp4"


def test_custom_relative_output(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(
        make_command(recurse=False, output_dir="out", keep_structure=True),
        root,
    )
    assert all(job.output_dir == root / "out" for job in jobs)


def test_flatten_output_without_structure(tmp_path):
    root = make_tree(tmp_path)
    output = tmp_path / "out"
    jobs = plan_jobs(
        make_command(recurse=True, output_dir=str(output), keep_structure=False),
        root,
    )
    assert all(job.output_dir == output for job in jobs)


def test_unknown_output_directory_variable(tmp_path):
    root = make_tree(tmp_path)
    with pytest.raises(JobError, match="未知变量"):
        plan_jobs(make_command(output_dir="{nope}"), root / "a.mp4")


def test_empty_match_returns_no_jobs(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "only.txt").write_text("x", encoding="utf-8")
    assert plan_jobs(make_command(recurse=True), root) == []


def test_input_variables_preserve_case(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(), root / "b.MP4")
    assert jobs[0].variables["input_ext"] == "MP4"
    assert jobs[0].variables["input_name"] == "b"


def test_empty_extensions_matches_all_files(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(extensions=[], recurse=True), root)
    assert [job.input_path.name for job in jobs] == ["a.mp4", "b.MP4", "c.txt", "d.mp4"]
    assert plan_jobs(make_command(extensions=[]), root / "c.txt")[0].input_path == (
        root / "c.txt"
    )


def test_directories_only_rejects_file_input(tmp_path):
    root = make_tree(tmp_path)
    with pytest.raises(JobError, match="仅处理文件夹"):
        plan_jobs(make_command(directories_only=True), root / "a.mp4")


def test_directories_only_processes_folder(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(directories_only=True), root)
    assert [job.input_path.name for job in jobs] == ["a.mp4", "b.MP4"]


def test_empty_arguments_allowed(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs(make_command(arguments=""), root / "a.mp4")
    assert jobs[0].command_line == subprocess.list2cmdline([str(jobs[0].executable)])


def test_plan_jobs_multi_filters_and_deduplicates(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs_multi(
        make_command(),
        [str(root / "a.mp4"), str(root / "c.txt"), str(root / "a.mp4")],
    )
    # c.txt 不匹配扩展名被过滤；a.mp4 重复选择只保留一个。
    assert [job.input_path.name for job in jobs] == ["a.mp4"]


def test_plan_jobs_multi_expands_directories(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs_multi(make_command(recurse=True), [str(root)])
    # 目录输入展开为其中匹配的文件；不支持仅目录。
    assert [job.input_path.name for job in jobs] == ["a.mp4", "b.MP4", "d.mp4"]


def test_plan_jobs_multi_rejects_directories_only(tmp_path):
    root = make_tree(tmp_path)
    with pytest.raises(JobError, match="仅目录"):
        plan_jobs_multi(make_command(directories_only=True), [str(root / "a.mp4")])


def test_plan_jobs_multi_all_mismatched_raises(tmp_path):
    root = make_tree(tmp_path)
    with pytest.raises(JobError, match="不匹配"):
        plan_jobs_multi(make_command(), [str(root / "c.txt")])


def test_plan_jobs_multi_order_follows_input(tmp_path):
    root = make_tree(tmp_path)
    jobs = plan_jobs_multi(
        make_command(extensions=[]),
        [str(root / "c.txt"), str(root / "a.mp4")],
    )
    assert [job.input_path.name for job in jobs] == ["c.txt", "a.mp4"]


def test_start_direct_launches_executable(monkeypatch):
    launched = {}
    monkeypatch.setattr(
        "context_cli.jobs.os.startfile", lambda target: launched.update(target=target)
    )
    from context_cli.jobs import start_direct

    start_direct(sys.executable)
    assert launched["target"].lower().endswith("python.exe")
