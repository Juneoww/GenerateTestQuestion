"""功能：实现正式 Agentic 题集页的选择、后台模型生成、日志和产物操作。
实现：各页独立状态；通过主窗口队列消费进度／完成事件，复用模型批次与六列控件。
输入：风险、数量、语言、共享设置和受控完成事件。
输出：六字段结果展示、剪贴板及本批次 JSON／Excel／环境说明的打开操作。
依赖：Tkinter、threading、storage、OWASP 目录／生成／批次模块。
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import owasp_pipeline
import storage
from owasp_catalog import AGENTIC_FRAMEWORK, AGENTIC_RISKS
from owasp_prompt_generator import PROMPT_RECORD_KEYS, validate_prompt_records
from prompt_widgets import configure_prompt_columns


class AgenticWorkspace:
    """保存单个 Agentic 页状态，绝不复用 LLM 的记录、路径或日志。"""

    def __init__(self, host, parent):
        self.host = host
        self.records = []
        self.batch_dir = self.json_path = self.xlsx_path = ""
        self.environment_path = self.environment_markdown_path = ""
        self.risk_vars = {}
        self.generate_widgets = []
        self.total_var = tk.StringVar(host, value="10")
        self.language_var = tk.StringVar(host, value="中文")
        self.summary_var = tk.StringVar(host)
        self.result_var = tk.StringVar(host, value="尚未生成 Agentic 提示词。")
        self.inner = host._make_scrollable(parent)
        self._build()

    def _build(self):
        """构建与 LLM 页一致的风险、参数、日志和结果层级。"""
        usage = ttk.LabelFrame(self.inner, text="OWASP Agentic Top 10 2026", style="Card.TLabelframe")
        usage.pack(fill="x")
        ttk.Label(usage, text="使用设置页模型生成 ASI01–ASI10 提示词；环境信息独立导出，不读取网站或执行被测 Agent。",
                  style="Subtle.TLabel", wraplength=930).pack(anchor="w")
        ttk.Label(usage, text="prompt 应投放到环境说明指定的位置；工具返回、记忆与智能体消息不等同于普通用户消息。",
                  style="Subtle.TLabel", wraplength=930).pack(anchor="w", pady=(4, 0))
        risk_frame = ttk.LabelFrame(self.inner, text="1. 选择 Agentic 风险", style="Card.TLabelframe")
        risk_frame.pack(fill="x", pady=(8, 0))
        toolbar = ttk.Frame(risk_frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(toolbar, text="六字段输出 · 环境文件按结果行关联", style="Subtle.TLabel").pack(side="left")
        for label, selected in (("清空", False), ("全选", True)):
            button = ttk.Button(toolbar, text=label, command=lambda value=selected: self.select_all(value))
            button.pack(side="right", padx=(6, 0))
            self.generate_widgets.append(button)
        for index, risk in enumerate(AGENTIC_RISKS):
            variable = tk.BooleanVar(self.host, value=False)
            self.risk_vars[risk["riskId"]] = variable
            control = ttk.Checkbutton(risk_frame, text=f"{risk['riskId']} · {risk['riskName']}\n{risk['englishName']}",
                                      variable=variable, command=self.update_summary)
            control.grid(row=1 + index // 2, column=index % 2, sticky="w", pady=3, padx=(0, 20))
            self.generate_widgets.append(control)
        risk_frame.columnconfigure(0, weight=1)
        risk_frame.columnconfigure(1, weight=1)
        options = ttk.LabelFrame(self.inner, text="2. 本次生成", style="Card.TLabelframe")
        options.pack(fill="x", pady=(8, 0))
        ttk.Label(options, text="生成数量").grid(row=0, column=0, padx=(0, 6))
        total = ttk.Spinbox(options, from_=1, to=1000, textvariable=self.total_var, width=8)
        total.grid(row=0, column=1, padx=(0, 18))
        ttk.Label(options, text="输出语言").grid(row=0, column=2, padx=(0, 6))
        language = ttk.Combobox(options, values=("中文", "英文", "中英混合"), state="readonly", textvariable=self.language_var, width=10)
        language.grid(row=0, column=3, padx=(0, 18))
        self.start_button = ttk.Button(options, text="生成可复制提示词", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=4)
        self.generate_widgets.extend((total, language, self.start_button))
        ttk.Label(options, textvariable=self.summary_var, style="Subtle.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        logs = ttk.LabelFrame(self.inner, text="3. 运行日志", style="Card.TLabelframe")
        logs.pack(fill="x", pady=(8, 0))
        self.log_text = tk.Text(logs, height=6, wrap="word", state="disabled", font=("Microsoft YaHei UI", 9))
        log_scroll = ttk.Scrollbar(logs, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        for level, color in (("warn", "#8a6d00"), ("error", "#a4262c")):
            self.log_text.tag_configure(level, foreground=color)
        results = ttk.LabelFrame(self.inner, text="4. 运行结果", style="Card.TLabelframe")
        results.pack(fill="both", expand=True, pady=(8, 0))
        actions = ttk.Frame(results)
        actions.pack(fill="x", pady=(0, 6))
        self.output_buttons = []
        for label, attribute in (("打开题库 Excel", "xlsx_path"), ("打开 JSON", "json_path"),
                                 ("打开环境说明", "environment_markdown_path"), ("打开批次目录", "batch_dir")):
            button = ttk.Button(actions, text=label, state="disabled",
                                command=lambda name=attribute: self.host._open_path(Path(getattr(self, name))))
            button.pack(side="left", padx=(0, 6))
            self.output_buttons.append((button, attribute))
            if attribute == "environment_markdown_path":
                self.environment_button = button
        self.copy_button = ttk.Button(actions, text="复制选中 prompt", state="disabled", command=self.copy_prompt)
        self.copy_button.pack(side="left")
        table = ttk.Frame(results)
        table.pack(fill="both", expand=True)
        self.result_tree = ttk.Treeview(table, columns=PROMPT_RECORD_KEYS, show="headings", height=16, selectmode="browse")
        configure_prompt_columns(self.result_tree, compact=True)
        vertical = ttk.Scrollbar(table, command=self.result_tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side="bottom", fill="x")
        vertical.pack(side="right", fill="y")
        self.result_tree.pack(fill="both", expand=True)
        self.result_tree.bind("<Double-1>", self.copy_cell)
        ttk.Label(results, textvariable=self.result_var, style="Subtle.TLabel", wraplength=920).pack(anchor="w", pady=(6, 0))
        for variable in (self.total_var, self.language_var):
            variable.trace_add("write", self.update_summary)
        self.update_summary()
        self.host._bind_page_wheel(self.host._agentic_page_canvas, (self.log_text, self.result_tree))

    def select_all(self, selected):
        """只修改本页风险选择。"""
        for variable in self.risk_vars.values():
            variable.set(selected)
        self.update_summary()

    def update_summary(self, *_):
        """参数变化实时控制可开始状态，主窗口忙时不能并发启动。"""
        count = sum(variable.get() for variable in self.risk_vars.values())
        try:
            valid = count > 0 and count <= int(self.total_var.get()) <= 1000
        except ValueError:
            valid = False
        self.summary_var.set(f"已选 {count}/10 项 · {self.language_var.get()} · " + ("就绪" if valid else "请选择风险，数量须在已选项数至 1000 之间"))
        self.start_button.state(["!disabled"] if valid and not self.host.running else ["disabled"])

    def set_busy(self, busy):
        """保持下拉框只读，并恢复本页自身的参数校验。"""
        for control in self.generate_widgets:
            control.state(["disabled"] if busy else ["!disabled"])
        self.update_summary()

    def artifact_paths(self):
        """输出目录切换后，仅允许打开本批记录的准确产物路径。"""
        return (self.batch_dir, self.json_path, self.xlsx_path, self.environment_path, self.environment_markdown_path)

    def _clear(self):
        """新批开始或失败时撤下旧交付动作，不清理另一页面。"""
        self.records = []
        self.batch_dir = self.json_path = self.xlsx_path = ""
        self.environment_path = self.environment_markdown_path = ""
        self.result_tree.delete(*self.result_tree.get_children())
        self.result_var.set("尚未生成 Agentic 提示词。")
        for button, _ in self.output_buttons:
            button.state(["disabled"])
        self.copy_button.state(["disabled"])

    def start(self):
        """校验输入后使用后台线程运行共享正式管线。"""
        if self.host.running:
            return
        selected = [risk_id for risk_id, variable in self.risk_vars.items() if variable.get()]
        try:
            total = int(self.total_var.get())
            if not selected or not len(selected) <= total <= 1000:
                raise ValueError("请选择风险，生成数量须在已选项数至 1000 之间。")
        except ValueError:
            messagebox.showwarning("参数错误", "请选择风险，生成数量须为已选项数至 1000 的整数。", parent=self.host)
            return
        settings = storage.load_settings()
        if any(type(settings.get(key)) is not str or not settings[key].strip() for key in ("baseUrl", "model")):
            messagebox.showwarning("缺少模型配置", "请先到设置页填写接口地址与模型名。", parent=self.host)
            return
        params = {"framework": AGENTIC_FRAMEWORK, "riskIds": selected, "total": total, "language": self.language_var.get()}
        self._clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.host.running = True
        self.host._sync_generation_busy()
        self.host._set_status("正在调用设置页模型生成 Agentic 提示词…")

        def work():
            try:
                summary = owasp_pipeline.run_batch(params, settings, self.host.events.put)
            except Exception as error:  # 后台任何异常均通过主线程消费，禁止线程操作 Tk。
                event = {"ok": False, "error": str(error)}
            else:
                event = {"ok": True, "summary": summary}
            self.host.events.put({"stage": "_done", "kind": "agentic_batch", "framework": AGENTIC_FRAMEWORK, **event})

        threading.Thread(target=work, daemon=True).start()

    def finish(self, done):
        """仅接受本框架的六字段记录，失败清空交付，诊断目录仍可打开。"""
        self.host.running = False
        self.host._sync_generation_busy()
        self._clear()
        summary = done.get("summary", {})
        error = done.get("error", "生成失败") if not done.get("ok") else summary.get("error", "")
        if done.get("ok"):
            self.batch_dir = summary.get("batchDir", "")
            if summary.get("status") != "completed":
                error = error or "未生成可用 Agentic 提示词。"
            else:
                records = summary.get("records", [])
                errors = validate_prompt_records(records)
                names = {risk["riskId"]: risk["riskName"] for risk in AGENTIC_RISKS}
                if not errors and any(names.get(r["riskId"]) != r["riskName"] or r["userA"] or r["userB"] for r in records):
                    errors.append("记录不属于当前 Agentic 单提示词目录。")
                if summary.get("framework") != AGENTIC_FRAMEWORK:
                    errors.append("批次框架不匹配。")
                if not summary.get("environmentPath") or not summary.get("environmentMarkdownPath"):
                    errors.append("缺少本批次的环境文件。")
                error = "；".join(errors)
                if not error:
                    self.records = records
                    self.json_path = summary.get("jsonPath", "")
                    self.xlsx_path = summary.get("xlsxPath", "")
                    self.environment_path = summary["environmentPath"]
                    self.environment_markdown_path = summary["environmentMarkdownPath"]
        for button, attribute in self.output_buttons:
            button.state(["!disabled"] if getattr(self, attribute) else ["disabled"])
        if error:
            self.host._append_log({"stage": "finish", "level": "error", "message": error}, self.log_text)
            self.host._set_status("Agentic 提示词生成失败")
            messagebox.showerror("Agentic 生成失败", error, parent=self.host)
            return
        for index, record in enumerate(self.records, 1):
            self.result_tree.insert("", "end", iid=str(index), values=[record[key] for key in PROMPT_RECORD_KEYS])
        self.copy_button.state(["!disabled"])
        self.result_var.set(f"已生成 {len(self.records)} 条；请按环境说明投放 prompt 并检查实际行为。")
        self.host._set_status(f"Agentic 批次完成：{len(self.records)} 条可复制提示词")
        messagebox.showinfo("Agentic 生成完成", f"模型生成 {len(self.records)} 条提示词，环境信息已另存。", parent=self.host)

    def copy_prompt(self):
        """复制选中行的完整输入。"""
        selected = self.result_tree.selection()
        if selected:
            self.host._copy_owasp_value("prompt", self.records[int(selected[0]) - 1]["prompt"])

    def copy_cell(self, event):
        """双击数据单元格时复制源记录，忽略标题和空白区域。"""
        row = self.result_tree.identify_row(event.y)
        column = self.result_tree.identify_column(event.x)
        if row and column and self.result_tree.identify_region(event.x, event.y) == "cell":
            key = PROMPT_RECORD_KEYS[int(column[1:]) - 1]
            self.host._copy_owasp_value(key, self.records[int(row) - 1][key])
