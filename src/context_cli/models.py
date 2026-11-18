"""命令与配置的数据模型。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import DEFAULT_MENU_TITLE, DEFAULT_OUTPUT_NAME
from .variables import (
    INPUT_VARIABLES,
    KNOWN_VARIABLES,
    OUTPUT_VARIABLES,
    find_variables,
)

_EXT_SPLIT = re.compile(r"[,;，；\s]+")
_EXT_INVALID_CHARS = set('\\/:*?"<>|')


def new_command_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_extensions(value: Any) -> list[str]:
    """把字符串/列表归一化为小写、无前导点、去重的最终后缀列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        raw_items: list[str] = _EXT_SPLIT.split(value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(_EXT_SPLIT.split(str(item)))
    else:
        raw_items = _EXT_SPLIT.split(str(value))

    result: list[str] = []
    for item in raw_items:
        extension = item.strip().lower().lstrip(".")
        if not extension:
            continue
        if "." in extension:
            raise ValueError(
                f"扩展名只支持最终后缀（不能包含点）: {item}；如需 tar.gz 请填写 gz"
            )
        if any(ch in _EXT_INVALID_CHARS for ch in extension):
            raise ValueError(f"扩展名包含非法字符: {item}")
        if extension not in result:
            result.append(extension)
    return result


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "y"}:
            return True
        if text in {"0", "false", "no", "off", "n", ""}:
            return False
    return bool(value)


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


@dataclass
class Command:
    id: str = field(default_factory=new_command_id)
    name: str = ""
    enabled: bool = True
    directories_only: bool = False
    comment: str = ""
    extensions: list[str] = field(default_factory=list)
    executable: str = ""
    arguments: str = ""
    recurse: bool = False
    output_dir: str = ""
    output_name: str = DEFAULT_OUTPUT_NAME
    keep_structure: bool = True
    show_console: bool = True

    def matches(self, path: str | Path) -> bool:
        # 扩展名留空表示匹配所有文件。
        if not self.extensions:
            return True
        filename = Path(path).name.lower()
        return any(filename.endswith(f".{extension}") for extension in self.extensions)

    def uses_input_variables(self) -> bool:
        return bool(find_variables(self.arguments) & INPUT_VARIABLES)

    def uses_output_variables(self) -> bool:
        return bool(find_variables(self.arguments) & OUTPUT_VARIABLES)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("命令名称不能为空")
        if not self.executable.strip():
            errors.append("执行程序不能为空")
        for extension in self.extensions:
            if (
                not extension
                or "." in extension
                or any(ch in _EXT_INVALID_CHARS for ch in extension)
            ):
                errors.append(f"扩展名格式无效: {extension}")
        arguments = self.arguments.strip()
        if arguments:
            used = find_variables(arguments)
            if not (used & INPUT_VARIABLES):
                errors.append("命令参数必须包含至少一个输入变量，例如 {input}")
            unknown = used - KNOWN_VARIABLES
            if unknown:
                errors.append("参数中包含未知变量: " + ", ".join(sorted(unknown)))
            if used & OUTPUT_VARIABLES and not self.output_name.strip():
                errors.append("参数使用了输出变量，但输出文件名模板为空")
        if any(ch in self.output_name for ch in '<>:"/\\|?*'):
            errors.append("输出文件名模板包含路径分隔符或非法字符")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "directories_only": self.directories_only,
            "comment": self.comment,
            "extensions": list(self.extensions),
            "executable": self.executable,
            "arguments": self.arguments,
            "recurse": self.recurse,
            "output_dir": self.output_dir,
            "output_name": self.output_name,
            "keep_structure": self.keep_structure,
            "show_console": self.show_console,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Command":
        if not isinstance(data, dict):
            raise ValueError("命令项必须是映射结构")
        command_id = _as_text(data.get("id")).strip() or new_command_id()
        return cls(
            id=command_id,
            name=_as_text(data.get("name")),
            enabled=_as_bool(data.get("enabled"), True),
            directories_only=_as_bool(data.get("directories_only"), False),
            comment=_as_text(data.get("comment")),
            extensions=normalize_extensions(data.get("extensions", [])),
            executable=_as_text(data.get("executable")),
            arguments=_as_text(data.get("arguments")),
            recurse=_as_bool(data.get("recurse"), False),
            output_dir=_as_text(data.get("output_dir")),
            output_name=_as_text(data.get("output_name"), DEFAULT_OUTPUT_NAME)
            or DEFAULT_OUTPUT_NAME,
            keep_structure=_as_bool(data.get("keep_structure"), True),
            show_console=_as_bool(data.get("show_console"), True),
        )


@dataclass
class AppConfig:
    version: int = 1
    menu_title: str = DEFAULT_MENU_TITLE
    commands: list[Command] = field(default_factory=list)

    def find(self, command_id: str) -> Command | None:
        for command in self.commands:
            if command.id == command_id:
                return command
        return None

    def enabled_commands(self) -> list[Command]:
        return [command for command in self.commands if command.enabled]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "settings": {"menu_title": self.menu_title},
            "commands": [command.to_dict() for command in self.commands],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        if not isinstance(data, dict):
            raise ValueError("配置文件顶层必须是映射结构")

        try:
            version = int(data.get("version", 1) or 1)
        except (TypeError, ValueError):
            version = 1

        settings = data.get("settings") or {}
        if not isinstance(settings, dict):
            raise ValueError("settings 必须是映射结构")
        menu_title = _as_text(settings.get("menu_title")).strip() or DEFAULT_MENU_TITLE

        raw_commands = data.get("commands") or []
        if not isinstance(raw_commands, list):
            raise ValueError("commands 必须是列表")

        commands: list[Command] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw_commands):
            if not isinstance(item, dict):
                raise ValueError(f"commands[{index}] 必须是映射结构")
            try:
                command = Command.from_dict(item)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"commands[{index}] 无效: {exc}") from exc
            if command.id in seen_ids:
                command.id = new_command_id()
            seen_ids.add(command.id)
            commands.append(command)

        return cls(version=version, menu_title=menu_title, commands=commands)
