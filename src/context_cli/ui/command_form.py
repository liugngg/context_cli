"""命令编辑表单。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from ..config import DEFAULT_OUTPUT_NAME
from ..models import Command, new_command_id, normalize_extensions

VARIABLE_NAMES = (
    "input",
    "input_name",
    "input_ext",
    "input_dir",
    "output_dir",
    "output_name",
    "output",
)


class FormError(ValueError):
    """表单内容无法转换为命令。"""


class CommandForm(ttk.LabelFrame):
    def __init__(self, master) -> None:
        super().__init__(master, text="命令编辑", padding=10)
        self._build_widgets()
        self.set_command(None)

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        self.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar()
        self.enabled_var = tk.BooleanVar(value=True)
        self.directories_only_var = tk.BooleanVar(value=False)
        self.extensions_var = tk.StringVar()
        self.executable_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value=DEFAULT_OUTPUT_NAME)
        self.recurse_var = tk.BooleanVar(value=False)
        self.keep_structure_var = tk.BooleanVar(value=True)
        self.show_console_var = tk.BooleanVar(value=True)

        ttk.Label(self, text="名称").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.name_entry = ttk.Entry(self, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(self, text="启用", variable=self.enabled_var).grid(
            row=0, column=2, sticky="w", padx=(10, 0), pady=4
        )

        ttk.Label(self, text="注释").grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=4)
        self.comment_text = tk.Text(self, height=3, wrap="word", undo=True)
        self.comment_text.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(self, text="扩展名").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self, textvariable=self.extensions_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Label(
            self,
            text="多个用逗号分隔；留空 = 所有文件；只填最终后缀（如 mp4），不支持 tar.gz",
            foreground="#666666",
        ).grid(row=3, column=1, columnspan=2, sticky="w")

        ttk.Label(self, text="执行程序").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self, textvariable=self.executable_var).grid(
            row=4, column=1, sticky="ew", pady=4
        )
        ttk.Button(self, text="浏览…", width=8, command=self._browse_executable).grid(
            row=4, column=2, sticky="w", padx=(10, 0), pady=4
        )

        ttk.Label(self, text="参数").grid(row=5, column=0, sticky="nw", padx=(0, 8), pady=4)
        self.arguments_text = tk.Text(
            self,
            height=5,
            wrap="word",
            undo=True,
            font=("Consolas", 9),
        )
        self.arguments_text.grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)

        variable_frame = ttk.Frame(self)
        variable_frame.grid(row=6, column=1, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(variable_frame, text="插入变量：").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 2)
        )
        # 高 DPI 下按钮会随字体变宽，固定 4 列换行，避免横向溢出被裁切。
        for index, name in enumerate(VARIABLE_NAMES):
            ttk.Button(
                variable_frame,
                text="{" + name + "}",
                width=len(name) + 2,
                command=lambda item=name: self._insert_variable(item),
            ).grid(
                row=1 + index // 4,
                column=index % 4,
                sticky="w",
                padx=(0, 2),
                pady=1,
            )

        ttk.Label(self, text="输出目录").grid(row=7, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self, textvariable=self.output_dir_var).grid(
            row=7, column=1, sticky="ew", pady=4
        )
        ttk.Button(self, text="浏览…", width=8, command=self._browse_output_dir).grid(
            row=7, column=2, sticky="w", padx=(10, 0), pady=4
        )
        ttk.Label(
            self,
            text="留空 = 源文件所在目录；相对路径相对于选中的根目录",
            foreground="#666666",
        ).grid(row=8, column=1, columnspan=2, sticky="w")

        ttk.Label(self, text="文件名模板").grid(
            row=9, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(self, textvariable=self.output_name_var).grid(
            row=9, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Label(
            self,
            text='模板只决定 {output} 的文件名；参数中需写 "{output}" 才会生效',
            foreground="#666666",
        ).grid(row=10, column=1, columnspan=2, sticky="w")

        options = ttk.Frame(self)
        options.grid(row=11, column=1, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text="遍历子文件夹", variable=self.recurse_var).pack(
            side="left", padx=(0, 14)
        )
        ttk.Checkbutton(options, text="保留目录结构", variable=self.keep_structure_var).pack(
            side="left", padx=(0, 14)
        )
        ttk.Checkbutton(options, text="显示控制台", variable=self.show_console_var).pack(
            side="left", padx=(0, 14)
        )
        ttk.Checkbutton(
            options, text="仅目录", variable=self.directories_only_var
        ).pack(side="left")
        ttk.Label(
            self,
            text="勾选「仅目录」后，该命令只出现在文件夹右键菜单，不处理单个文件",
            foreground="#666666",
        ).grid(row=13, column=1, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(
            self,
            text='路径变量建议用双引号包裹，例如：-i "{input}" "{output}"',
            foreground="#666666",
        ).grid(row=12, column=1, columnspan=2, sticky="w", pady=(6, 0))

    # ------------------------------------------------------------- dialogs
    def _browse_executable(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择执行程序",
            filetypes=[
                ("可执行文件", "*.exe"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.executable_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(parent=self, title="选择输出目录")
        if path:
            self.output_dir_var.set(path)

    def _insert_variable(self, name: str) -> None:
        self.arguments_text.focus_set()
        self.arguments_text.insert("insert", "{" + name + "}")
        self.arguments_text.see("insert")

    # ------------------------------------------------------------- content
    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)

    def set_editable(self, editable: bool) -> None:
        """整表启用/禁用；没有选中命令时避免用户误以为可以编辑。"""
        self._apply_editable(self, editable)

    def _apply_editable(self, parent: tk.Misc, editable: bool) -> None:
        for child in parent.winfo_children():
            if isinstance(child, tk.Text):
                child.configure(state="normal" if editable else "disabled")
            elif isinstance(child, ttk.Widget):
                if editable:
                    child.state(["!disabled"])
                else:
                    child.state(["disabled"])
            self._apply_editable(child, editable)

    def set_command(self, command: Command | None) -> None:
        # 先启用，保证 Text 控件可以写入内容；最后再按有无命令设置状态。
        self.set_editable(True)
        self.name_var.set(command.name if command else "")
        self.enabled_var.set(command.enabled if command else True)
        self.directories_only_var.set(
            command.directories_only if command else False
        )
        self.extensions_var.set(", ".join(command.extensions) if command else "")
        self.executable_var.set(command.executable if command else "")
        self.output_dir_var.set(command.output_dir if command else "")
        self.output_name_var.set(
            command.output_name if command else DEFAULT_OUTPUT_NAME
        )
        self.recurse_var.set(command.recurse if command else False)
        self.keep_structure_var.set(command.keep_structure if command else True)
        self.show_console_var.set(command.show_console if command else True)
        self._set_text(self.comment_text, command.comment if command else "")
        self._set_text(self.arguments_text, command.arguments if command else "")
        self.set_editable(command is not None)

    def get_command(self, base: Command | None = None) -> Command:
        try:
            extensions = normalize_extensions(self.extensions_var.get())
        except ValueError as exc:
            raise FormError(str(exc)) from exc

        return Command(
            id=base.id if base else new_command_id(),
            name=self.name_var.get().strip(),
            enabled=self.enabled_var.get(),
            directories_only=self.directories_only_var.get(),
            comment=self.comment_text.get("1.0", "end-1c").strip(),
            extensions=extensions,
            executable=self.executable_var.get().strip(),
            arguments=self.arguments_text.get("1.0", "end-1c").strip(),
            recurse=self.recurse_var.get(),
            output_dir=self.output_dir_var.get().strip(),
            output_name=self.output_name_var.get().strip(),
            keep_structure=self.keep_structure_var.get(),
            show_console=self.show_console_var.get(),
        )

    def focus_name(self) -> None:
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, "end")
