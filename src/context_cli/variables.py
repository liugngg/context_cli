"""命令参数中的变量解析与展开。"""

from __future__ import annotations

import re
from collections.abc import Mapping

VAR_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

INPUT_VARIABLES = frozenset({"input", "input_name", "input_ext", "input_dir"})
OUTPUT_VARIABLES = frozenset({"output", "output_dir", "output_name"})
KNOWN_VARIABLES = INPUT_VARIABLES | OUTPUT_VARIABLES


class VariableError(ValueError):
    """模板中包含未知变量。"""


def find_variables(template: str) -> set[str]:
    return set(VAR_PATTERN.findall(template or ""))


def expand(template: str, values: Mapping[str, str]) -> str:
    """单次替换模板变量。

    替换结果不会被再次扫描，避免路径中的花括号被递归展开。
    遇到未知变量时抛出 VariableError，而不是留下原文继续执行。
    """
    unknown: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        unknown.append(key)
        return match.group(0)

    result = VAR_PATTERN.sub(_replace, template or "")
    if unknown:
        names = ", ".join(sorted(set(unknown)))
        raise VariableError(f"未知变量: {names}")
    return result
