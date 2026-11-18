import pytest

from context_cli.variables import VariableError, expand, find_variables


def test_expand_all_variables():
    values = {
        "input": r"D:\素材\a.mkv",
        "input_name": "a",
        "input_ext": "mkv",
        "input_dir": r"D:\素材",
        "output_dir": r"D:\输出",
        "output_name": "a.mp4",
        "output": r"D:\输出\a.mp4",
    }
    template = '"{input}" -> "{output}" ({input_name}.{input_ext}, {input_dir}, {output_dir}, {output_name})'
    result = expand(template, values)
    assert result == (
        '"D:\\素材\\a.mkv" -> "D:\\输出\\a.mp4" '
        "(a.mkv, D:\\素材, D:\\输出, a.mp4)"
    )


def test_unknown_variable_raises():
    with pytest.raises(VariableError, match="missing"):
        expand("{input} {missing}", {"input": "x"})


def test_expansion_is_single_pass():
    values = {"input": "{input_name}", "input_name": "a"}
    assert expand("{input}", values) == "{input_name}"


def test_find_variables():
    assert find_variables("{input} {input_name} {unknown}") == {
        "input",
        "input_name",
        "unknown",
    }


def test_non_variable_braces_are_left_alone():
    assert expand("{} {123} {a-b}", {}) == "{} {123} {a-b}"
