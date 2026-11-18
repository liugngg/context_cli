"""只读文本控件的写入辅助函数。"""

from __future__ import annotations

import tkinter as tk


def set_readonly_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    if text:
        widget.insert("1.0", text)
    widget.configure(state="disabled")


def append_readonly_text(
    widget: tk.Text,
    text: str,
    *,
    max_lines: int = 4000,
    keep_lines: int = 3000,
) -> None:
    if not text:
        return
    widget.configure(state="normal")
    if not text.endswith("\n"):
        text += "\n"
    widget.insert("end", text)

    line_count = int(widget.index("end-1c").split(".")[0])
    if line_count > max_lines:
        widget.delete("1.0", f"{line_count - keep_lines}.0")

    widget.see("end")
    widget.configure(state="disabled")
