from pathlib import Path

import pytest

from context_cli.models import AppConfig, Command
from context_cli.storage import ConfigError, export_config, load_config, save_config


def sample_config() -> AppConfig:
    return AppConfig(
        commands=[
            Command(
                name="测试",
                extensions=["mp4"],
                executable="cmd.exe",
                arguments='"{input}"',
            )
        ]
    )


def test_missing_file_returns_empty_config(tmp_path):
    config = load_config(tmp_path / "missing.yaml")
    assert config.commands == []


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "commands.yaml"
    original = sample_config()
    save_config(original, path)
    loaded = load_config(path)
    assert loaded.to_dict() == original.to_dict()
    assert path.read_text(encoding="utf-8").startswith("version:")


def test_save_creates_backup(tmp_path):
    path = tmp_path / "commands.yaml"
    save_config(sample_config(), path)
    save_config(sample_config(), path)
    assert (tmp_path / "commands.yaml.bak").exists()


def test_export_does_not_create_backup(tmp_path):
    source = tmp_path / "commands.yaml"
    target = tmp_path / "export.yaml"
    save_config(sample_config(), source)
    export_config(sample_config(), target)
    export_config(sample_config(), target)
    assert target.exists()
    assert not (tmp_path / "export.yaml.bak").exists()


def test_invalid_yaml_raises(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("commands: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(path)


def test_invalid_structure_raises(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("commands: not-a-list", encoding="utf-8")
    with pytest.raises(ConfigError, match="commands"):
        load_config(path)


def test_invalid_command_raises_with_index(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(
        "commands:\n  - name: ok\n  - 123\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"commands\[1\]"):
        load_config(path)


def test_empty_file_returns_empty_config(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("", encoding="utf-8")
    assert load_config(path).commands == []


def test_bom_is_accepted(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("﻿version: 1\ncommands: []\n", encoding="utf-8")
    assert load_config(path).commands == []
