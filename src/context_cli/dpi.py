"""Windows DPI 感知与 Tk 缩放辅助。"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk


def set_process_dpi_awareness() -> None:
    """在创建 Tk 窗口前声明 DPI 感知，避免系统位图拉伸导致模糊/缩小。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_system_dpi(root: tk.Misc | None = None) -> int:
    if sys.platform == "win32":
        try:
            return int(ctypes.windll.user32.GetDpiForSystem())
        except Exception:
            pass
    if root is not None:
        try:
            return int(root.winfo_fpixels("1i"))
        except Exception:
            pass
    return 96


def configure_tk_scaling(root: tk.Misc) -> float:
    """设置 Tk 的点/像素换算，返回相对 100%（96 DPI）的缩放系数。"""
    dpi = max(get_system_dpi(root), 96)
    root.tk.call("tk", "scaling", dpi / 72.0)
    return dpi / 96.0
