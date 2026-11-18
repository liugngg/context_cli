"""YAML 配置的加载、保存、备份与导出。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

from .config import config_path
from .models import AppConfig


class ConfigError(Exception):
    """配置文件无法读取或内容无效。"""


def load_config(path: str | Path | None = None) -> AppConfig:
    target = Path(path) if path is not None else config_path()
    if not target.exists():
        return AppConfig()

    try:
        raw = target.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"读取配置失败: {target}: {exc}") from exc

    if not raw.strip():
        return AppConfig()

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 格式错误: {exc}") from exc

    if data is None:
        return AppConfig()

    try:
        return AppConfig.from_dict(data)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置内容无效: {exc}") from exc


def save_config(
    config: AppConfig,
    path: str | Path | None = None,
    *,
    backup: bool = True,
) -> Path:
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = yaml.safe_dump(
            config.to_dict(),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=1000,
        )
    except yaml.YAMLError as exc:
        raise ConfigError(f"生成 YAML 失败: {exc}") from exc

    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"写入临时配置失败: {temporary}: {exc}") from exc

    if backup and target.exists():
        try:
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        except OSError:
            pass

    try:
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ConfigError(f"替换配置文件失败: {target}: {exc}") from exc

    return target


def export_config(config: AppConfig, path: str | Path) -> Path:
    return save_config(config, path, backup=False)
