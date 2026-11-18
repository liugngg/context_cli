"""应用常量与本地路径。"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "ContextCLI"
MENU_KEY_NAME = "ContextCLI"
DEFAULT_MENU_TITLE = "快捷执行"
DEFAULT_OUTPUT_NAME = "{input_name}_out.{input_ext}"
LOG_RETENTION_DAYS = 1
ENV_HOME = "CONTEXT_CLI_HOME"


def app_data_dir(create: bool = True) -> Path:
    """返回应用数据目录，可用 CONTEXT_CLI_HOME 覆盖（便于测试）。"""
    override = os.environ.get(ENV_HOME)
    if override:
        path = Path(override).expanduser()
    else:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        path = base / APP_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "commands.yaml"


def state_path() -> Path:
    return app_data_dir() / "state.yaml"


def logs_dir(create: bool = True) -> Path:
    path = app_data_dir(create=create) / "logs"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
