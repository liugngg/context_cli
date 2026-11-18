import sys

import pytest

from context_cli import registry
from context_cli.models import AppConfig, Command


def make_command(**overrides) -> Command:
    data = {
        "name": "测试",
        "extensions": ["mp4"],
        "executable": sys.executable,
        "arguments": '"{input}"',
    }
    data.update(overrides)
    return Command(**data)


def test_escape_menu_text():
    assert registry.escape_menu_text("A&B") == "A&&B"
    assert registry.escape_menu_text("普通菜单") == "普通菜单"


def test_registry_extension():
    assert registry.registry_extension(".MP4") == "mp4"
    assert registry.registry_extension(" mkv ") == "mkv"
    assert registry.registry_extension("Tar.Gz") == "gz"


def test_build_extension_map_only_enabled_files():
    first = make_command(id="a", extensions=["mp4"])
    second = make_command(id="b", extensions=["mp4", "mkv"])
    disabled = make_command(id="c", extensions=["mov"], enabled=False)
    folder_only = make_command(id="d", extensions=["mp4"], directories_only=True)
    all_files = make_command(id="e", extensions=[])
    config = AppConfig(commands=[first, second, disabled, folder_only, all_files])

    mapping = registry.build_extension_map(config)
    assert set(mapping) == {"mp4", "mkv"}
    assert set(mapping["mp4"]) == {"a", "b"}
    assert set(mapping["mkv"]) == {"b"}
    assert [command.id for command in registry.build_all_files_commands(config)] == [
        "e"
    ]


def test_ordered_menu_key_follows_list_order():
    keys = [
        registry.ordered_menu_key(index, command_id)
        for index, command_id in enumerate(["bbb", "aaa", "ccc"])
    ]
    assert keys == ["0000_bbb", "0001_aaa", "0002_ccc"]
    assert keys == sorted(keys)


def test_build_command_string():
    result = registry.build_command_string(
        [r"C:\Program Files\App\app.exe"],
        "abc",
    )
    assert result == r'"C:\Program Files\App\app.exe" --run abc "%1"'


def test_build_launch_prefix_dev_mode():
    prefix = registry.build_launch_prefix()
    assert prefix[-2:] == ["-m", "context_cli"]
    assert prefix[0].lower().endswith(("python.exe", "pythonw.exe"))


def test_validate_commands_rejects_missing_executable():
    command = make_command(executable="no-such-executable-xyz")
    with pytest.raises(registry.RegistryError, match="找不到执行程序"):
        registry._validate_commands([command])


def test_validate_commands_accepts_empty_extensions_and_arguments():
    command = make_command(extensions=[], arguments="")
    registry._validate_commands([command])
