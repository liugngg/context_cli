import pytest

from context_cli.models import (
    AppConfig,
    Command,
    new_command_id,
    normalize_extensions,
)


def valid_command(**overrides):
    data = {
        "name": "测试命令",
        "extensions": ["mp4"],
        "executable": "python.exe",
        "arguments": '-c "print(1)" "{input}"',
        "output_name": "{input_name}_out{input_ext}",
    }
    data.update(overrides)
    return Command(**data)


def test_normalize_extensions_from_string():
    assert normalize_extensions(".MP4, mkv；mov") == ["mp4", "mkv", "mov"]


def test_normalize_extensions_deduplicates():
    assert normalize_extensions(["mp4", ".MP4", " mp4 "]) == ["mp4"]


def test_normalize_extensions_rejects_compound_suffix():
    with pytest.raises(ValueError, match="最终后缀"):
        normalize_extensions("tar.gz")


def test_normalize_extensions_rejects_invalid_characters():
    with pytest.raises(ValueError, match="非法字符"):
        normalize_extensions("m*p4")


def test_matches_is_case_insensitive():
    command = valid_command(extensions=["mp4", "mkv"])
    assert command.matches(r"D:\a.MP4")
    assert command.matches(r"D:\a.mkv")
    assert not command.matches(r"D:\a.txt")


def test_matches_empty_extensions_matches_all_files():
    command = valid_command(extensions=[])
    assert command.matches("a.mp4")
    assert command.matches("a.txt")
    assert command.matches("no_extension")


def test_empty_extensions_and_arguments_are_allowed():
    command = valid_command(extensions=[], arguments="")
    assert command.validate() == []


def test_valid_command_has_no_errors():
    assert valid_command().validate() == []


def test_validate_requires_fields():
    errors = valid_command(name=" ", executable="").validate()
    assert any("名称" in error for error in errors)
    assert any("执行程序" in error for error in errors)


def test_directories_only_roundtrip():
    command = valid_command(directories_only=True)
    restored = Command.from_dict(command.to_dict())
    assert restored.directories_only is True


def test_validate_requires_input_variable():
    errors = valid_command(arguments="-y -i fixed.mp4").validate()
    assert any("{input}" in error for error in errors)


def test_validate_rejects_unknown_variable():
    errors = valid_command(arguments='-i "{input}" "{nope}"').validate()
    assert any("未知变量" in error and "nope" in error for error in errors)


def test_validate_output_variables_require_template():
    errors = valid_command(arguments='-i "{input}" "{output}"', output_name="").validate()
    assert any("输出文件名模板" in error for error in errors)


def test_validate_rejects_invalid_output_name_template():
    errors = valid_command(output_name="{input_name}/out.mp4").validate()
    assert any("输出文件名模板" in error for error in errors)


def test_config_roundtrip():
    config = AppConfig(commands=[valid_command()])
    restored = AppConfig.from_dict(config.to_dict())
    assert restored.menu_title == config.menu_title
    assert len(restored.commands) == 1
    assert restored.commands[0].to_dict() == config.commands[0].to_dict()


def test_config_regenerates_duplicate_ids():
    first = valid_command()
    second = valid_command()
    second.id = first.id
    config = AppConfig.from_dict(
        {
            "commands": [
                first.to_dict(),
                second.to_dict(),
            ]
        }
    )
    assert len({command.id for command in config.commands}) == 2


def test_config_accepts_string_extensions_and_bool_strings():
    config = AppConfig.from_dict(
        {
            "settings": {"menu_title": ""},
            "commands": [
                {
                    "name": "x",
                    "extensions": "mp4, mkv",
                    "executable": "cmd.exe",
                    "arguments": '"{input}"',
                    "recurse": "false",
                    "show_console": "no",
                    "directories_only": "yes",
                }
            ],
        }
    )
    assert config.menu_title == "快捷执行"
    assert config.commands[0].extensions == ["mp4", "mkv"]
    assert config.commands[0].recurse is False
    assert config.commands[0].show_console is False
    assert config.commands[0].directories_only is True


def test_new_command_id_is_unique():
    assert new_command_id() != new_command_id()
