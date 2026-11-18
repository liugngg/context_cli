"""GUI 主窗口。"""

from __future__ import annotations

import copy
import os
import re
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import registry
from ..config import DEFAULT_OUTPUT_NAME, app_data_dir
from ..dpi import configure_tk_scaling, set_process_dpi_awareness
from ..models import AppConfig, Command, new_command_id
from ..runner import cleanup_old_logs
from ..storage import ConfigError, export_config, load_config, save_config
from .command_form import CommandForm, FormError
from .scrollable_frame import ScrollableFrame
from .test_panel import TestPanel


def _set_window_icon(window: tk.Misc) -> None:
    """窗口与任务栏使用应用图标；打包版取 exe 内嵌图标。"""
    try:
        if getattr(sys, "frozen", False):
            window.iconbitmap(sys.executable)
            return
        icon = Path(__file__).resolve().parents[2] / "packaging" / "context_cli.ico"
        if icon.is_file():
            window.iconbitmap(str(icon))
    except tk.TclError:
        pass


class MainWindow:
    def __init__(self, config_file: str | Path | None = None) -> None:
        self.config_file = Path(config_file) if config_file else None
        self.config = AppConfig()
        self.current_index: int | None = None
        self.structure_dirty = False
        self._last_status: registry.RegistryStatus | None = None

        self._build_root()
        self._build_ui()
        self._load_initial_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        cleanup_old_logs()

    # ------------------------------------------------------------- window
    def _build_root(self) -> None:
        set_process_dpi_awareness()
        self.root = tk.Tk()
        self.ui_scale = configure_tk_scaling(self.root)
        self.root.title("快捷执行 CLI 管理器")

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = max(
            min(int(1180 * self.ui_scale), screen_width - int(80 * self.ui_scale)),
            720,
        )
        height = max(
            min(int(820 * self.ui_scale), screen_height - int(120 * self.ui_scale)),
            540,
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(
            min(int(980 * self.ui_scale), width),
            min(int(680 * self.ui_scale), height),
        )
        _set_window_icon(self.root)

        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        # Treeview 的默认行高是固定像素，不随 DPI/字体缩放，高 DPI 下会把
        # 中文和 ✓ 裁成上半截，因此按实际字体行高重新设置。
        line_height = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        style.configure(
            "Treeview",
            rowheight=max(
                line_height + int(8 * self.ui_scale),
                int(22 * self.ui_scale),
            ),
        )
        style.configure(
            "Treeview.Heading",
            padding=(int(4 * self.ui_scale), int(2 * self.ui_scale)),
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        scale = self.ui_scale
        toolbar = ttk.Frame(
            self.root,
            padding=(
                int(10 * scale),
                int(8 * scale),
                int(10 * scale),
                int(4 * scale),
            ),
        )
        toolbar.grid(row=0, column=0, sticky="ew")

        ttk.Button(toolbar, text="新建", command=self.new_command).pack(side="left")
        self.copy_button = ttk.Button(
            toolbar, text="复制", command=self.duplicate_command
        )
        self.copy_button.pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="删除", command=self.delete_command).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(toolbar, text="上移", command=lambda: self.move_command(-1)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(toolbar, text="下移", command=lambda: self.move_command(1)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=int(10 * scale), pady=int(2 * scale)
        )
        ttk.Button(toolbar, text="导入 YAML", command=self.import_yaml).pack(side="left")
        ttk.Button(toolbar, text="导出 YAML", command=self.export_yaml).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(toolbar, text="打开配置目录", command=self.open_config_dir).pack(
            side="left", padx=(6, 0)
        )

        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=int(10 * scale),
            pady=(0, int(6 * scale)),
        )

        left = ttk.LabelFrame(paned, text="命令列表", padding=6)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            left,
            columns=("enabled", "name", "extensions", "scope"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("enabled", text="启用")
        self.tree.heading("name", text="名称")
        self.tree.heading("extensions", text="扩展名")
        self.tree.heading("scope", text="范围")
        self.tree.column(
            "enabled",
            width=int(48 * scale),
            anchor="center",
            stretch=False,
        )
        self.tree.column("name", width=int(190 * scale), anchor="w")
        self.tree.column("extensions", width=int(150 * scale), anchor="w")
        self.tree.column(
            "scope",
            width=int(64 * scale),
            anchor="center",
            stretch=False,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.tag_configure("disabled", foreground="#888888")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        right = ttk.Frame(paned)
        self.right_panel = right
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(2, weight=0)

        self.form_scroll = ScrollableFrame(right)
        self.form_scroll.grid(row=0, column=0, sticky="nsew")
        self.form = CommandForm(self.form_scroll.inner)
        self.form.pack(fill="both", expand=True)

        test_header = ttk.Frame(right)
        test_header.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(int(6 * scale), 0),
        )
        self.test_toggle = ttk.Button(
            test_header,
            text="▶ 测试验证",
            width=16,
            command=self.toggle_test_panel,
        )
        self.test_toggle.pack(side="left")
        ttk.Separator(test_header, orient="horizontal").pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        self.test_panel = TestPanel(right, command_provider=self._command_for_test)
        self._test_expanded = False

        paned.add(left, weight=1)
        paned.add(right, weight=3)

        status = ttk.Frame(
            self.root,
            padding=(
                int(10 * scale),
                int(4 * scale),
                int(10 * scale),
                int(8 * scale),
            ),
        )
        self.status_bar = status
        status.grid(row=2, column=0, sticky="ew")
        self.message_label = ttk.Label(status, text="就绪")
        self.message_label.pack(side="left")

        ttk.Button(status, text="移除右键菜单", command=self.unregister_menu).pack(
            side="right"
        )
        ttk.Button(status, text="注册右键菜单", command=self.register_menu).pack(
            side="right", padx=(0, 6)
        )
        ttk.Button(status, text="保存", command=self.save_current).pack(
            side="right", padx=(0, 12)
        )
        self.registry_label = ttk.Label(status, text="")
        self.registry_label.pack(side="right", padx=(0, 18))

    # ------------------------------------------------------------- startup
    def _load_initial_config(self) -> None:
        try:
            self.config = load_config(self.config_file)
        except ConfigError as exc:
            messagebox.showwarning(
                "配置加载失败",
                f"{exc}\n\n将使用空配置启动。",
                parent=self.root,
            )
            self.config = AppConfig()

        self.refresh_tree()
        if self.config.commands:
            self.current_index = 0
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._load_current()
        else:
            self.current_index = None
            self.form.set_command(None)
            self._set_status("命令列表为空，请先点击「新建」创建命令")
        self._update_registry_status()

    def run(self) -> None:
        self.root.mainloop()

    # -------------------------------------------------------------- tree
    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, command in enumerate(self.config.commands):
            values = (
                "✓" if command.enabled else "",
                command.name or "（未命名）",
                ", ".join(command.extensions) or "所有文件",
                "仅目录" if command.directories_only else "",
            )
            tags = () if command.enabled else ("disabled",)
            self.tree.insert("", "end", iid=str(index), values=values, tags=tags)

        if (
            self.current_index is not None
            and 0 <= self.current_index < len(self.config.commands)
        ):
            item = str(self.current_index)
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.see(item)

    def _select(self, index: int) -> None:
        if 0 <= index < len(self.config.commands):
            item = str(index)
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.see(item)

    def _restore_selection(self) -> None:
        if self.current_index is None:
            self.tree.selection_remove(self.tree.selection())
        elif 0 <= self.current_index < len(self.config.commands):
            self._select(self.current_index)

    def _load_current(self) -> None:
        if (
            self.current_index is None
            or not (0 <= self.current_index < len(self.config.commands))
        ):
            self.form.set_command(None)
            return
        self.form.set_command(self.config.commands[self.current_index])

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        try:
            new_index = int(selection[0])
        except ValueError:
            return
        if new_index == self.current_index:
            return
        if not self._leave_current():
            self._restore_selection()
            return
        self.current_index = new_index
        self._load_current()

    def _on_tree_double_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        # 若切换选择时用户取消了未保存修改，则不要继续切换该行
        if self.tree.selection() != (item,):
            return
        index = int(item)
        command = self.config.commands[index]
        command.enabled = not command.enabled
        if index == self.current_index:
            self.form.enabled_var.set(command.enabled)
        self.structure_dirty = True
        self.refresh_tree()
        self._set_status("启用状态已修改（尚未保存）")
        self._update_registry_status()

    # ---------------------------------------------------------- dirty state
    def _form_differs(self) -> bool:
        if (
            self.current_index is None
            or not (0 <= self.current_index < len(self.config.commands))
        ):
            return False
        try:
            candidate = self.form.get_command(
                self.config.commands[self.current_index]
            )
        except FormError:
            return True
        return candidate.to_dict() != self.config.commands[self.current_index].to_dict()

    def _leave_current(self) -> bool:
        if not self._form_differs():
            return True
        answer = messagebox.askyesnocancel(
            "未保存的修改",
            "当前命令有未保存的修改，是否保存？",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self.save_current(silent=True)
        return True

    def _confirm_close(self) -> bool:
        if not self.structure_dirty and not self._form_differs():
            return True
        answer = messagebox.askyesnocancel(
            "未保存的修改",
            "配置有未保存的修改，是否保存后退出？",
            parent=self.root,
        )
        if answer is None:
            return False
        if not answer:
            return True
        if self.current_index is not None:
            return self.save_current(silent=True)
        try:
            save_config(self.config, self.config_file)
        except ConfigError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        return True

    # ------------------------------------------------------------- actions
    def save_current(self, silent: bool = False) -> bool:
        if self.current_index is None:
            if not silent:
                messagebox.showinfo(
                    "没有选中命令",
                    "请先新建或选择一个命令。",
                    parent=self.root,
                )
            return False

        try:
            command = self.form.get_command(
                self.config.commands[self.current_index]
            )
        except FormError as exc:
            messagebox.showerror("表单有误", str(exc), parent=self.root)
            return False

        errors = command.validate()
        if errors:
            messagebox.showerror(
                "命令配置不完整",
                "\n".join("• " + error for error in errors),
                parent=self.root,
            )
            return False

        self.config.commands[self.current_index] = command
        try:
            save_config(self.config, self.config_file)
        except ConfigError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False

        self.structure_dirty = False
        self.refresh_tree()
        self._load_current()
        if not silent:
            self._set_status("已保存")
        self._maybe_reregister()
        self._update_registry_status()
        return True

    def new_command(self) -> None:
        if not self._leave_current():
            return
        command = Command(
            name=f"新命令 {len(self.config.commands) + 1}",
            extensions=[],
            executable="",
            arguments='"{input}"',
            output_name=DEFAULT_OUTPUT_NAME,
        )
        self.config.commands.append(command)
        self.current_index = len(self.config.commands) - 1
        self.structure_dirty = True
        self.refresh_tree()
        self._load_current()
        self.form.focus_name()
        self._set_status("新建命令：请填写执行程序后保存")
        self._update_registry_status()

    def duplicate_command(self) -> None:
        if self.current_index is None:
            messagebox.showinfo(
                "没有选中命令",
                "请先选择要复制的命令。",
                parent=self.root,
            )
            return

        try:
            source = self.form.get_command(
                self.config.commands[self.current_index]
            )
        except FormError as exc:
            messagebox.showerror("表单有误", str(exc), parent=self.root)
            return

        clone = copy.deepcopy(source)
        clone.id = new_command_id()
        clone.name = self._copy_name(source.name)
        # 插到原命令后面，便于紧接着修改；复制后不会自动保存。
        self.config.commands.insert(self.current_index + 1, clone)
        self.current_index += 1
        self.structure_dirty = True
        self.refresh_tree()
        self._load_current()
        self.form.focus_name()
        self._set_status("已复制命令（尚未保存），请修改名称等字段后保存")
        self._update_registry_status()

    def _copy_name(self, name: str) -> str:
        # 连续复制时去掉已有的「副本」后缀，避免出现「xx 副本 副本」。
        original = re.sub(r"\s*副本(?:\s+\d+)?$", "", name or "").strip()
        base = f"{original or '未命名'} 副本"
        existing = {command.name for command in self.config.commands}
        if base not in existing:
            return base
        index = 2
        while f"{base} {index}" in existing:
            index += 1
        return f"{base} {index}"

    def delete_command(self) -> None:
        if self.current_index is None:
            return
        command = self.config.commands[self.current_index]
        if not messagebox.askyesno(
            "删除命令",
            f"确定删除「{command.name or '未命名'}」吗？",
            parent=self.root,
        ):
            return

        del self.config.commands[self.current_index]
        if self.config.commands:
            self.current_index = min(
                self.current_index, len(self.config.commands) - 1
            )
        else:
            self.current_index = None
        self.structure_dirty = True
        self.refresh_tree()
        self._load_current()
        if self.config.commands:
            self._set_status("已删除（尚未保存）")
        else:
            self._set_status("已删除（尚未保存）；列表为空，请先新建命令")
        self._update_registry_status()

    def move_command(self, delta: int) -> None:
        if self.current_index is None:
            return
        target = self.current_index + delta
        if not (0 <= target < len(self.config.commands)):
            return
        if not self._leave_current():
            return

        commands = self.config.commands
        commands[self.current_index], commands[target] = (
            commands[target],
            commands[self.current_index],
        )
        self.current_index = target
        self.structure_dirty = True
        self.refresh_tree()
        self._load_current()
        self._set_status("顺序已调整（尚未保存）")
        self._update_registry_status()

    def _maybe_reregister(self) -> None:
        if self._last_status is None:
            return
        if self._last_status.state not in ("registered", "stale"):
            return
        try:
            registry.register(self.config)
        except Exception as exc:
            messagebox.showwarning(
                "右键菜单未更新",
                str(exc),
                parent=self.root,
            )

    # ------------------------------------------------------------ yaml i/o
    def import_yaml(self) -> None:
        if not self._leave_current():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入 YAML",
            filetypes=[
                ("YAML 文件", "*.yaml *.yml"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return

        try:
            imported = load_config(path)
        except ConfigError as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return

        if imported.commands:
            prompt = (
                f"将用 {len(imported.commands)} 条命令替换当前列表。\n\n"
                "配置中的命令在保存并注册后会被执行，请确认文件来源可信。\n\n"
                "是否继续？"
            )
        else:
            prompt = "该文件没有任何命令，是否用空配置替换当前列表？"
        if not messagebox.askyesno("导入配置", prompt, parent=self.root):
            return

        self.config = imported
        self.current_index = 0 if imported.commands else None
        self.structure_dirty = True
        self.refresh_tree()
        self._load_current()
        self._set_status("已导入（尚未保存）")
        self._update_registry_status()

    def export_yaml(self) -> None:
        snapshot = copy.deepcopy(self.config)
        if self.current_index is not None:
            try:
                snapshot.commands[self.current_index] = self.form.get_command(
                    self.config.commands[self.current_index]
                )
            except FormError as exc:
                messagebox.showerror("表单有误", str(exc), parent=self.root)
                return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出 YAML",
            defaultextension=".yaml",
            filetypes=[
                ("YAML 文件", "*.yaml"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return

        try:
            export_config(snapshot, path)
        except ConfigError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        messagebox.showinfo("导出成功", f"已导出到：\n{path}", parent=self.root)

    def open_config_dir(self) -> None:
        directory = (
            self.config_file.parent if self.config_file else app_data_dir()
        )
        try:
            os.startfile(str(directory))
        except OSError as exc:
            messagebox.showerror(
                "无法打开目录", f"{directory}\n\n{exc}", parent=self.root
            )

    # ------------------------------------------------------------ registry
    def register_menu(self) -> None:
        if self.current_index is not None:
            if not self.save_current(silent=True):
                return
        else:
            try:
                save_config(self.config, self.config_file)
            except ConfigError as exc:
                messagebox.showerror("保存失败", str(exc), parent=self.root)
                return

        try:
            stats = registry.register(self.config)
        except registry.RegistryError as exc:
            messagebox.showerror("注册失败", str(exc), parent=self.root)
            return
        except Exception as exc:
            messagebox.showerror(
                "注册失败",
                f"{type(exc).__name__}: {exc}",
                parent=self.root,
            )
            return

        if stats.folder_command_count == 0:
            messagebox.showinfo(
                "已移除菜单",
                "当前没有启用命令，已移除「快捷执行」右键菜单。",
                parent=self.root,
            )
        else:
            lines = ["已注册："]
            if stats.extension_count:
                lines.append(
                    f"• {stats.extension_count} 个扩展名菜单"
                    f"（文件菜单项 {stats.command_count} 个）"
                )
            if stats.all_files_command_count:
                lines.append(
                    f"• 所有文件菜单 {stats.all_files_command_count} 项"
                )
            lines.append(f"• 文件夹菜单项 {stats.folder_command_count} 个")
            messagebox.showinfo(
                "注册成功",
                "\n".join(lines),
                parent=self.root,
            )
        self._update_registry_status()

    def unregister_menu(self) -> None:
        if not messagebox.askyesno(
            "移除右键菜单",
            "确定移除「快捷执行」右键菜单吗？\n配置文件不会被删除。",
            parent=self.root,
        ):
            return
        try:
            removed = registry.unregister()
        except Exception as exc:
            messagebox.showerror(
                "移除失败",
                f"{type(exc).__name__}: {exc}",
                parent=self.root,
            )
            return
        messagebox.showinfo(
            "已移除",
            f"已移除 {removed} 个菜单项。",
            parent=self.root,
        )
        self._update_registry_status()

    def _update_registry_status(self) -> None:
        try:
            status = registry.get_status(self.config)
        except Exception as exc:
            self._last_status = None
            self.registry_label.configure(text=f"注册状态检测失败：{exc}")
            return

        self._last_status = status
        mode = "打包模式" if getattr(sys, "frozen", False) else "开发模式"
        text = f"右键菜单：{status.label}    [{mode}]"
        if status.problems:
            text += f"（{len(status.problems)} 项待更新）"
        self.registry_label.configure(text=text)

    # ------------------------------------------------------------- helpers
    def toggle_test_panel(self) -> None:
        if self.test_panel.is_running():
            messagebox.showinfo(
                "测试运行中",
                "测试正在运行，暂不能收起测试区域。",
                parent=self.root,
            )
            return

        if self._test_expanded:
            self.test_panel.grid_remove()
            self._test_expanded = False
            self.test_toggle.configure(text="▶ 测试验证")
            self.right_panel.rowconfigure(0, weight=1)
            self.right_panel.rowconfigure(2, weight=0)
        else:
            self.test_panel.grid(
                row=2,
                column=0,
                sticky="nsew",
                pady=(int(6 * self.ui_scale), 0),
            )
            self._test_expanded = True
            self.test_toggle.configure(text="▼ 收起测试验证")
            self.right_panel.rowconfigure(0, weight=3)
            self.right_panel.rowconfigure(2, weight=2)

        self.root.update_idletasks()

    def _command_for_test(self) -> Command:
        base = (
            self.config.commands[self.current_index]
            if self.current_index is not None
            and 0 <= self.current_index < len(self.config.commands)
            else None
        )
        return self.form.get_command(base)

    def _set_status(self, text: str) -> None:
        self.message_label.configure(text=text)

    def _on_close(self) -> None:
        if self.test_panel.is_running():
            if not messagebox.askyesno(
                "测试仍在运行",
                "测试正在运行，是否停止并退出？",
                parent=self.root,
            ):
                return
            self.test_panel.shutdown()

        if not self._confirm_close():
            return
        self.root.destroy()
