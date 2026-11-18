"""资源管理器右键菜单的注册、卸载与状态检测。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import winreg

from .config import MENU_KEY_NAME
from .jobs import JobError, resolve_executable
from .models import AppConfig, Command

FILE_EXTENSIONS_ROOT = r"Software\Classes\SystemFileAssociations"
DIRECTORY_SHELL_ROOT = r"Software\Classes\Directory\shell"
BACKGROUND_SHELL_ROOT = r"Software\Classes\Directory\Background\shell"
STAR_SHELL_ROOT = r"Software\Classes\*\shell"


class RegistryError(Exception):
    """注册表操作失败或命令无法注册。"""


@dataclass
class RegistryStats:
    extension_count: int = 0
    command_count: int = 0
    folder_command_count: int = 0
    all_files_command_count: int = 0


@dataclass
class RegistryStatus:
    state: str
    extension_count: int = 0
    problems: list[str] = field(default_factory=list)
    all_files: bool = False

    @property
    def label(self) -> str:
        if self.state == "registered":
            parts: list[str] = []
            if self.extension_count:
                parts.append(f"{self.extension_count} 个扩展名")
            if self.all_files:
                parts.append("所有文件")
            detail = " + ".join(parts) or "无文件菜单"
            return f"已注册（{detail}）"
        if self.state == "stale":
            return "已过期，需要重新注册"
        return "未注册"


def escape_menu_text(text: str) -> str:
    """Windows 菜单中 & 是快捷键前缀，字面量需要写成 &&。"""
    return (text or "").replace("&", "&&")


def registry_extension(extension: str) -> str:
    return (extension or "").strip().lower().lstrip(".").rsplit(".", 1)[-1]


def build_launch_prefix() -> list[str]:
    """返回写入注册表的启动前缀。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]

    executable = Path(sys.executable)
    pythonw = executable.parent / "pythonw.exe"
    launcher = pythonw if pythonw.exists() else executable
    return [str(launcher), "-m", "context_cli"]


def build_extension_map(config: AppConfig) -> dict[str, dict[str, Command]]:
    """按注册表扩展名分组，值为 {command_id: Command}。

    仅目录命令不出现在文件菜单；扩展名为空的命令注册到「所有文件」菜单。
    """
    mapping: dict[str, dict[str, Command]] = {}
    for command in config.enabled_commands():
        if command.directories_only:
            continue
        for extension in command.extensions:
            key = registry_extension(extension)
            if not key:
                continue
            mapping.setdefault(key, {})[command.id] = command
    return mapping


def build_all_files_commands(config: AppConfig) -> list[Command]:
    """扩展名为空且不限制目录的启用命令，注册到「所有文件」菜单。"""
    return [
        command
        for command in config.enabled_commands()
        if not command.directories_only and not command.extensions
    ]


def ordered_menu_key(index: int, command_id: str) -> str:
    """注册表子键按名称排序，用数字前缀锁定命令列表中的顺序。"""
    return f"{index:04d}_{command_id}"


def build_command_string(
    prefix: list[str],
    command_id: str,
    path_token: str = "%1",
) -> str:
    parts = [*prefix, "--run", command_id]
    return subprocess.list2cmdline(parts) + f' "{path_token}"'


def _open_key(path: str, access: int = winreg.KEY_READ):
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, access)


def _key_exists(path: str) -> bool:
    try:
        key = _open_key(path)
    except (FileNotFoundError, OSError):
        return False
    key.Close()
    return True


def _get_value(path: str, name: str = "") -> str | None:
    try:
        with _open_key(path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return value
    except (FileNotFoundError, OSError):
        return None


def _list_subkeys(path: str) -> list[str]:
    try:
        with _open_key(path) as key:
            names: list[str] = []
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
            return names
    except (FileNotFoundError, OSError):
        return []


def _create_key(path: str):
    return winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        path,
        0,
        winreg.KEY_WRITE,
    )


def _set_sz(key, name: str, value: str) -> None:
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _delete_tree(path: str) -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_ALL_ACCESS,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RegistryError(f"打开注册表项失败: HKCU\\{path}: {exc}") from exc

    children: list[str] = []
    index = 0
    try:
        while True:
            try:
                children.append(winreg.EnumKey(key, index))
            except OSError:
                break
            index += 1
    finally:
        key.Close()

    for child in children:
        _delete_tree(f"{path}\\{child}")

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RegistryError(f"删除注册表项失败: HKCU\\{path}: {exc}") from exc


def _notify_shell() -> None:
    try:
        # SHCNE_ASSOCCHANGED, SHCNF_IDLIST
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def notify_shell() -> None:
    _notify_shell()


def _validate_commands(commands: list[Command]) -> None:
    problems: list[str] = []
    for command in commands:
        errors = command.validate()
        if errors:
            problems.append(f"{command.name or command.id}: " + "；".join(errors))
            continue
        try:
            resolve_executable(command.executable)
        except JobError as exc:
            problems.append(f"{command.name or command.id}: {exc}")
    if problems:
        raise RegistryError("以下命令无法注册：\n" + "\n".join(problems))


def _write_menu(
    parent_path: str,
    title: str,
    commands: list[Command],
    prefix: list[str],
) -> None:
    _delete_tree(parent_path)

    with _create_key(parent_path) as key:
        _set_sz(key, "MUIVerb", escape_menu_text(title))
        _set_sz(key, "SubCommands", "")
        _set_sz(key, "MultiSelectModel", "Single")

    shell_path = f"{parent_path}\\shell"
    for index, command in enumerate(commands):
        command_path = f"{shell_path}\\{ordered_menu_key(index, command.id)}"
        with _create_key(command_path) as key:
            _set_sz(key, "MUIVerb", escape_menu_text(command.name))
            _set_sz(key, "MultiSelectModel", "Single")
        with _create_key(f"{command_path}\\command") as key:
            _set_sz(key, "", build_command_string(prefix, command.id, "%1"))


def register(
    config: AppConfig,
    prefix: list[str] | None = None,
) -> RegistryStats:
    launch_prefix = list(prefix) if prefix else build_launch_prefix()
    if not launch_prefix:
        raise RegistryError("注册表启动命令为空")

    enabled = config.enabled_commands()
    if not enabled:
        unregister()
        return RegistryStats()

    _validate_commands(enabled)
    extension_map = build_extension_map(config)
    all_files_commands = build_all_files_commands(config)

    try:
        _remove_all_our_keys(notify=False)
        for extension, commands in extension_map.items():
            parent = (
                f"{FILE_EXTENSIONS_ROOT}\\.{extension}\\shell\\{MENU_KEY_NAME}"
            )
            _write_menu(parent, config.menu_title, list(commands.values()), launch_prefix)

        if all_files_commands:
            wildcard_parent = f"{STAR_SHELL_ROOT}\\{MENU_KEY_NAME}"
            _write_menu(
                wildcard_parent,
                config.menu_title,
                all_files_commands,
                launch_prefix,
            )

        folder_parent = f"{DIRECTORY_SHELL_ROOT}\\{MENU_KEY_NAME}"
        _write_menu(folder_parent, config.menu_title, enabled, launch_prefix)
    except OSError as exc:
        try:
            _remove_all_our_keys(notify=False)
        except Exception:
            pass
        raise RegistryError(f"写入右键菜单失败: {exc}") from exc

    _notify_shell()
    return RegistryStats(
        extension_count=len(extension_map),
        command_count=sum(len(commands) for commands in extension_map.values()),
        folder_command_count=len(enabled),
        all_files_command_count=len(all_files_commands),
    )


def unregister() -> int:
    removed = _remove_all_our_keys(notify=False)
    if removed:
        _notify_shell()
    return removed


def _remove_all_our_keys(*, notify: bool = True) -> int:
    removed = 0
    for extension_key in _list_subkeys(FILE_EXTENSIONS_ROOT):
        path = f"{FILE_EXTENSIONS_ROOT}\\{extension_key}\\shell\\{MENU_KEY_NAME}"
        if _delete_tree(path):
            removed += 1
    for root in (DIRECTORY_SHELL_ROOT, BACKGROUND_SHELL_ROOT, STAR_SHELL_ROOT):
        path = f"{root}\\{MENU_KEY_NAME}"
        if _delete_tree(path):
            removed += 1
    if notify and removed:
        _notify_shell()
    return removed


def _check_menu(
    path: str,
    title: str,
    commands: list[Command],
    prefix: list[str],
    problems: list[str],
    label: str,
) -> None:
    if _get_value(path, "MUIVerb") != escape_menu_text(title):
        problems.append(f"{label}: 菜单标题不匹配")
    if _get_value(path, "SubCommands") != "":
        problems.append(f"{label}: SubCommands 设置不正确")
    if _get_value(path, "MultiSelectModel") != "Single":
        problems.append(f"{label}: MultiSelectModel 设置不正确")

    shell_path = f"{path}\\shell"
    actual = set(_list_subkeys(shell_path))
    expected = {
        ordered_menu_key(index, command.id)
        for index, command in enumerate(commands)
    }
    for missing in sorted(expected - actual):
        problems.append(f"{label}: 缺少命令 {missing}")
    for extra in sorted(actual - expected):
        problems.append(f"{label}: 存在多余命令 {extra}")

    for index, command in enumerate(commands):
        command_path = f"{shell_path}\\{ordered_menu_key(index, command.id)}"
        if _get_value(command_path, "MUIVerb") != escape_menu_text(command.name):
            problems.append(f"{label}: 命令名称不匹配（{command.name}）")
        expected_command = build_command_string(prefix, command.id, "%1")
        actual_command = _get_value(f"{command_path}\\command", "")
        if actual_command != expected_command:
            problems.append(f"{label}: 启动命令不匹配（{command.name}）")


def get_status(
    config: AppConfig,
    prefix: list[str] | None = None,
) -> RegistryStatus:
    launch_prefix = list(prefix) if prefix else build_launch_prefix()
    enabled = config.enabled_commands()
    extension_map = build_extension_map(config)
    all_files_commands = build_all_files_commands(config)
    expected_extensions = set(extension_map)

    current_extensions: set[str] = set()
    for extension_key in _list_subkeys(FILE_EXTENSIONS_ROOT):
        path = f"{FILE_EXTENSIONS_ROOT}\\{extension_key}\\shell\\{MENU_KEY_NAME}"
        if _key_exists(path):
            current_extensions.add(extension_key.lstrip(".").lower())

    wildcard_path = f"{STAR_SHELL_ROOT}\\{MENU_KEY_NAME}"
    wildcard_exists = _key_exists(wildcard_path)
    folder_path = f"{DIRECTORY_SHELL_ROOT}\\{MENU_KEY_NAME}"
    folder_exists = _key_exists(folder_path)
    any_keys = bool(current_extensions) or wildcard_exists or folder_exists

    if not enabled:
        problems: list[str] = []
        if any_keys:
            problems.append("存在已启用命令之外的右键菜单")
        return RegistryStatus(
            "stale" if any_keys else "not_registered",
            0,
            problems,
        )

    problems = []
    for extra in sorted(current_extensions - expected_extensions):
        problems.append(f"存在多余的扩展名菜单: {extra}")
    for missing in sorted(expected_extensions - current_extensions):
        problems.append(f"缺少扩展名菜单: {missing}")

    for extension in sorted(expected_extensions & current_extensions):
        path = f"{FILE_EXTENSIONS_ROOT}\\.{extension}\\shell\\{MENU_KEY_NAME}"
        _check_menu(
            path,
            config.menu_title,
            list(extension_map[extension].values()),
            launch_prefix,
            problems,
            f"扩展名 .{extension}",
        )

    if not folder_exists:
        problems.append("缺少文件夹菜单")
    else:
        _check_menu(
            folder_path,
            config.menu_title,
            enabled,
            launch_prefix,
            problems,
            "文件夹",
        )

    if all_files_commands:
        if not wildcard_exists:
            problems.append("缺少所有文件菜单")
        else:
            _check_menu(
                wildcard_path,
                config.menu_title,
                all_files_commands,
                launch_prefix,
                problems,
                "所有文件",
            )
    elif wildcard_exists:
        problems.append("存在多余的菜单: 所有文件")

    all_files = bool(all_files_commands)
    if not any_keys:
        return RegistryStatus(
            "not_registered",
            len(expected_extensions),
            [],
            all_files=all_files,
        )

    if problems:
        return RegistryStatus(
            "stale",
            len(expected_extensions),
            problems,
            all_files=all_files,
        )

    return RegistryStatus(
        "registered",
        len(expected_extensions),
        [],
        all_files=all_files,
    )
