"""批量执行的进度窗口。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..dpi import configure_tk_scaling, set_process_dpi_awareness
from ..jobs import Job
from ..runner import BatchResult, run_jobs
from .text_utils import append_readonly_text


class ProgressWindow:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        self.batch: BatchResult | None = None
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._total = len(jobs)
        self._build()

    def _build(self) -> None:
        set_process_dpi_awareness()
        self.root = tk.Tk()
        self.ui_scale = configure_tk_scaling(self.root)
        self.root.title("快捷执行 - 正在处理")

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = max(
            min(int(880 * self.ui_scale), screen_width - int(80 * self.ui_scale)),
            640,
        )
        height = max(
            min(int(560 * self.ui_scale), screen_height - int(120 * self.ui_scale)),
            420,
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(
            min(int(720 * self.ui_scale), width),
            min(int(440 * self.ui_scale), height),
        )
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            ttk.Style(self.root).theme_use("vista")
        except tk.TclError:
            pass

        scale = self.ui_scale
        command_name = self.jobs[0].command.name if self.jobs else ""
        header = ttk.Frame(
            self.root,
            padding=(
                int(12 * scale),
                int(10 * scale),
                int(12 * scale),
                int(4 * scale),
            ),
        )
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        self.header_var = tk.StringVar(
            value=f"{command_name}：0/{self._total}"
        )
        ttk.Label(
            header,
            textvariable=self.header_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(
            header,
            orient="horizontal",
            mode="determinate",
            maximum=max(self._total, 1),
            value=0,
        )
        self.progress.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(int(6 * scale), 0),
        )

        output_frame = ttk.Frame(
            self.root,
            padding=(
                int(12 * scale),
                int(6 * scale),
                int(12 * scale),
                int(6 * scale),
            ),
        )
        output_frame.grid(row=2, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(
            output_frame,
            height=16,
            wrap="none",
            state="disabled",
            font=("Consolas", 9),
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(
            output_frame, orient="vertical", command=self.output_text.yview
        )
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(
            output_frame, orient="horizontal", command=self.output_text.xview
        )
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.output_text.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )

        footer = ttk.Frame(
            self.root,
            padding=(
                int(12 * scale),
                int(4 * scale),
                int(12 * scale),
                int(12 * scale),
            ),
        )
        footer.grid(row=3, column=0, sticky="ew")
        self.status_label = ttk.Label(footer, text="准备运行…")
        self.status_label.pack(side="left")

        self.close_button = ttk.Button(
            footer, text="关闭", command=self._on_close, state="disabled"
        )
        self.close_button.pack(side="right")
        self.stop_button = ttk.Button(footer, text="停止", command=self.stop)
        self.stop_button.pack(side="right", padx=(0, int(6 * scale)))

    def run(self) -> BatchResult | None:
        if not self.jobs:
            self.batch = BatchResult()
            return self.batch

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self.root.after(80, self._poll)
        self.root.mainloop()
        return self.batch

    def _worker(self) -> None:
        try:
            batch = run_jobs(
                self.jobs,
                capture=True,
                on_output=lambda text: self._queue.put(("output", text)),
                on_job_start=lambda index, total, job: self._queue.put(
                    ("job", (index, total, job))
                ),
                stop_event=self._stop_event,
            )
            self._queue.put(("done", batch))
        except Exception as exc:  # pragma: no cover - 防御性兜底
            self._queue.put(("error", str(exc)))

    def _poll(self) -> None:
        if not self.root.winfo_exists():
            return

        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "output":
                    append_readonly_text(self.output_text, payload)
                elif kind == "job":
                    index, total, job = payload
                    self.header_var.set(
                        f"{job.command.name}：{index}/{total}  {job.input_path.name}"
                    )
                    self.progress.configure(value=index - 1)
                    append_readonly_text(
                        self.output_text,
                        f"\n=== [{index}/{total}] {job.input_path} ===",
                    )
                elif kind == "done":
                    self._finish(payload)
                    return
                elif kind == "error":
                    self._finish_error(payload)
                    return
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(80, self._poll)

    def _finish(self, batch: BatchResult) -> None:
        self.batch = batch
        self._thread = None
        self.progress.configure(value=self._total)
        self.header_var.set(f"处理结束：{self._total} 个文件")
        self.stop_button.state(["disabled"])
        self.close_button.state(["!disabled"])

        if batch.cancelled:
            self.status_label.configure(
                text=f"已取消：成功 {batch.succeeded}，失败/取消 {batch.failed}"
            )
        else:
            self.status_label.configure(
                text=f"完成：成功 {batch.succeeded}，失败 {batch.failed}"
            )

        append_readonly_text(
            self.output_text,
            f"\n完成：成功 {batch.succeeded}，失败/取消 {batch.failed}，"
            f"共 {len(batch.results)} 个。",
        )
        if batch.log_path:
            append_readonly_text(self.output_text, f"日志：{batch.log_path}")

        failures = [result for result in batch.results if not result.succeeded]
        if failures:
            append_readonly_text(self.output_text, "\n失败项：")
            for result in failures[:10]:
                detail = result.error or f"退出码 {result.exit_code}"
                if result.cancelled:
                    detail = "已取消"
                append_readonly_text(
                    self.output_text,
                    f"  {result.job.input_path.name}: {detail}",
                )
            if len(failures) > 10:
                append_readonly_text(
                    self.output_text,
                    f"  … 其余 {len(failures) - 10} 个",
                )

        if self._closing:
            self.root.destroy()
            return

        if not batch.cancelled and batch.failed == 0:
            append_readonly_text(
                self.output_text,
                "\n全部成功，窗口将在 3 秒后自动关闭。",
            )
            self.root.after(3000, self._auto_close)

    def _finish_error(self, message: str) -> None:
        self.batch = None
        self._thread = None
        self.stop_button.state(["disabled"])
        self.close_button.state(["!disabled"])
        self.status_label.configure(text="执行出错")
        messagebox.showerror("执行出错", message, parent=self.root)
        if self._closing:
            self.root.destroy()

    def _auto_close(self) -> None:
        if self.root.winfo_exists():
            self.root.destroy()

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._stop_event.set()
            self.stop_button.state(["disabled"])
            self.status_label.configure(text="正在停止…")

    def _on_close(self) -> None:
        running = self._thread is not None and self._thread.is_alive()
        if running:
            if not messagebox.askyesno(
                "确认关闭",
                "任务仍在运行，是否停止并关闭窗口？",
                parent=self.root,
            ):
                return
            self._closing = True
            self._stop_event.set()
            self.stop_button.state(["disabled"])
            self.status_label.configure(text="正在停止…")
            return
        if self.root.winfo_exists():
            self.root.destroy()
