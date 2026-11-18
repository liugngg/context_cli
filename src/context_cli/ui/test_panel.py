"""命令测试与实时输出面板。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from ..jobs import JobError, plan_jobs
from ..models import Command
from ..runner import BatchResult, run_jobs
from .command_form import FormError
from .text_utils import append_readonly_text, set_readonly_text


class TestPanel(ttk.LabelFrame):
    def __init__(
        self,
        master,
        command_provider: Callable[[], Command],
    ) -> None:
        super().__init__(master, text="测试验证", padding=10)
        self.command_provider = command_provider
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_id: str | None = None
        self._build_widgets()

    def _build_widgets(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        self.sample_var = tk.StringVar()
        ttk.Label(self, text="样本").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(self, textvariable=self.sample_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(self, text="选文件…", width=9, command=self._pick_file).grid(
            row=0, column=2, padx=(0, 4)
        )
        ttk.Button(self, text="选文件夹…", width=10, command=self._pick_folder).grid(
            row=0, column=3
        )

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, columnspan=4, sticky="ew", pady=6)
        self.preview_button = ttk.Button(controls, text="预览", command=self.preview)
        self.preview_button.pack(side="left")
        self.run_button = ttk.Button(controls, text="运行测试", command=self.run_test)
        self.run_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(
            controls, text="停止", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(6, 0))
        self.clear_button = ttk.Button(
            controls, text="清空", command=self.clear_display
        )
        self.clear_button.pack(side="left", padx=(6, 0))
        self.status_label = ttk.Label(controls, text="就绪")
        self.status_label.pack(side="left", padx=(16, 0))

        # 预览与输出放在可拖动分隔条的垂直面板中，预览高度可随时调整。
        self.split = ttk.Panedwindow(self, orient="vertical")
        self.split.grid(row=2, column=0, columnspan=4, sticky="nsew")

        self.preview_frame = ttk.Frame(self.split)
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)

        self.preview_text = tk.Text(
            self.preview_frame,
            height=4,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        preview_scroll = ttk.Scrollbar(
            self.preview_frame, orient="vertical", command=self.preview_text.yview
        )
        preview_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=preview_scroll.set)

        self.output_frame = ttk.Frame(self.split)
        self.output_frame.rowconfigure(0, weight=1)
        self.output_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(
            self.output_frame,
            height=10,
            wrap="none",
            state="disabled",
            font=("Consolas", 9),
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(
            self.output_frame, orient="vertical", command=self.output_text.yview
        )
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(
            self.output_frame, orient="horizontal", command=self.output_text.xview
        )
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.output_text.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )

        self.split.add(self.preview_frame, weight=1)
        self.split.add(self.output_frame, weight=3)

    # ------------------------------------------------------------- dialogs
    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择测试文件")
        if path:
            self.sample_var.set(path)

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="选择测试文件夹")
        if path:
            self.sample_var.set(path)

    # -------------------------------------------------------------- helpers
    def _plan(self) -> tuple[Command, list]:
        sample = self.sample_var.get().strip()
        if not sample:
            raise JobError("请先选择样例文件或文件夹")
        path = Path(sample)
        if not path.exists():
            raise JobError(f"样例路径不存在: {sample}")
        command = self.command_provider()
        return command, plan_jobs(command, path)

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _set_preview(self, text: str) -> None:
        set_readonly_text(self.preview_text, text)

    def _append_output(self, text: str) -> None:
        append_readonly_text(self.output_text, text)

    def _clear_output(self) -> None:
        set_readonly_text(self.output_text, "")

    # -------------------------------------------------------------- actions
    def clear_display(self) -> None:
        """清空预览与输出，便于排除上次运行结果后重新调试。"""
        self._set_preview("")
        self._clear_output()
        if not self.is_running():
            self._set_status("就绪")

    def preview(self) -> None:
        try:
            command, jobs = self._plan()
        except (FormError, JobError, ValueError) as exc:
            messagebox.showerror("无法预览", str(exc), parent=self)
            return

        if not jobs:
            self._set_preview("未找到匹配扩展名的文件。")
            messagebox.showinfo("没有匹配文件", "所选位置没有匹配扩展名的文件。", parent=self)
            return

        lines = [
            f"命令：{command.name}",
            f"匹配文件：{len(jobs)} 个",
            f"工作目录：{jobs[0].executable.parent}",
            "",
        ]
        for index, job in enumerate(jobs[:3], start=1):
            lines.append(f"[{index}] {job.input_path.name} -> {job.output_path}")
        if len(jobs) > 3:
            lines.append(f"… 其余 {len(jobs) - 3} 个")
        lines.extend(["", "命令行示例：", jobs[0].command_line])
        self._set_preview("\n".join(lines))

    def run_test(self) -> None:
        if self.is_running():
            return
        try:
            command, jobs = self._plan()
        except (FormError, JobError, ValueError) as exc:
            messagebox.showerror("无法测试", str(exc), parent=self)
            return

        if not jobs:
            messagebox.showinfo("没有匹配文件", "所选位置没有匹配扩展名的文件。", parent=self)
            return

        if len(jobs) > 50 and not messagebox.askyesno(
            "确认测试",
            f"本次将处理 {len(jobs)} 个文件，是否继续？",
            parent=self,
        ):
            return

        self._stop_event.clear()
        self._clear_output()
        self._append_output(
            f"命令：{command.name}\n匹配文件：{len(jobs)} 个\n"
            f"工作目录：{jobs[0].executable.parent}\n"
        )
        self.preview_button.state(["disabled"])
        self.run_button.state(["disabled"])
        self.stop_button.state(["!disabled"])
        self._set_status("运行中…")

        self._thread = threading.Thread(target=self._worker, args=(jobs,), daemon=True)
        self._thread.start()
        self._schedule_poll()

    def stop(self) -> None:
        if self.is_running():
            self._stop_event.set()
            self.stop_button.state(["disabled"])
            self._set_status("正在停止…")

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --------------------------------------------------------------- worker
    def _worker(self, jobs) -> None:
        try:
            batch = run_jobs(
                jobs,
                capture=True,
                on_output=lambda text: self._queue.put(("output", text)),
                on_job_start=lambda index, total, job: self._queue.put(
                    ("job", (index, total, job.input_path))
                ),
                stop_event=self._stop_event,
            )
            self._queue.put(("done", batch))
        except Exception as exc:  # pragma: no cover - 防御性兜底
            self._queue.put(("error", str(exc)))

    def _schedule_poll(self) -> None:
        if self._poll_id is None:
            self._poll_id = self.after(80, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "output":
                    self._append_output(payload)
                elif kind == "job":
                    index, total, path = payload
                    self._append_output(f"\n=== [{index}/{total}] {path.name} ===")
                elif kind == "done":
                    self._finish_run(payload)
                    return
                elif kind == "error":
                    self._finish_error(payload)
                    return
        except queue.Empty:
            pass

        if self._thread is not None:
            self._schedule_poll()

    def _finish_run(self, batch: BatchResult) -> None:
        self._thread = None
        self.preview_button.state(["!disabled"])
        self.run_button.state(["!disabled"])
        self.stop_button.state(["disabled"])

        if batch.cancelled:
            self._set_status(f"已取消：成功 {batch.succeeded}，失败/取消 {batch.failed}")
        else:
            self._set_status(f"完成：成功 {batch.succeeded}，失败 {batch.failed}")

        self._append_output(
            f"\n完成：成功 {batch.succeeded}，失败/取消 {batch.failed}，"
            f"共 {len(batch.results)} 个。"
        )
        if batch.log_path:
            self._append_output(f"日志：{batch.log_path}")

        failures = [result for result in batch.results if not result.succeeded]
        if failures:
            self._append_output("\n失败项：")
            for result in failures[:8]:
                detail = result.error or f"退出码 {result.exit_code}"
                if result.cancelled:
                    detail = "已取消"
                self._append_output(f"  {result.job.input_path.name}: {detail}")
            if len(failures) > 8:
                self._append_output(f"  … 其余 {len(failures) - 8} 个")

    def _finish_error(self, message: str) -> None:
        self._thread = None
        self.preview_button.state(["!disabled"])
        self.run_button.state(["!disabled"])
        self.stop_button.state(["disabled"])
        self._set_status("测试出错")
        messagebox.showerror("测试出错", message, parent=self)
