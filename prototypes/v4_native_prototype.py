"""功能：展示 v4 五标签原生原型，验证独立 Agentic 题集及六字段／环境预览。
实现：两个 OWASP 页共用控件组件、分别持有状态，固定演示批次全部保留内存。
输入：窗口风险、数量和语言，或 --smoke-test；输出：窗口、剪贴板或自检 JSON。
依赖：Python 标准库 Tkinter、v4_demo_data 与当前六字段校验器；无网络请求。
用法：.venv/Scripts/python.exe prototypes/v4_native_prototype.py [--smoke-test]
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from owasp_prompt_generator import PROMPT_RECORD_KEYS, validate_prompt_records
from prototypes.v4_demo_data import build_demo_batch, catalog_for


WORKSPACES = ("TC260 题库生成", "OWASP LLM 题集", "OWASP Agentic 题集", "来源管理", "设置")
COLUMNS = ("风险编号", "风险名称", "userA", "userB", "prompt", "断言")
FONT = "Microsoft YaHei UI"


def make_result_tree(parent, height=6):
    """构建统一六列表格，水平滚动可读完整列，不修改实际文本。"""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=PROMPT_RECORD_KEYS, show="headings", height=height, selectmode="browse")
    for field, title, width in zip(PROMPT_RECORD_KEYS, COLUMNS, (90, 170, 260, 260, 500, 400)):
        tree.heading(field, text=title)
        tree.column(field, width=width, minwidth=80, stretch=False)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    return tree


class PreviewWindow(tk.Toplevel):
    """展示只读 JSON 或单表六列 Excel 预览，原型不写产物文件。"""

    def __init__(self, parent, kind, payload):
        super().__init__(parent)
        self.title({"json": "六字段 JSON 预览", "excel": "Excel 预览 · 测试提示词 · 六列",
                    "environment": "独立环境说明预览"}[kind] + "｜模拟数据")
        self.geometry("1120x620")
        self.minsize(720, 400)
        self.transient(parent.winfo_toplevel())
        ttk.Label(self, text="离线原型：此窗口展示内存内容，未导出文件。", padding=12,
                  style="Muted.TLabel").pack(fill="x")
        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)
        if kind == "excel":
            self.tree = make_result_tree(body, 16)
            for index, record in enumerate(payload):
                self.tree.insert("", "end", iid=str(index), values=[record[key] for key in PROMPT_RECORD_KEYS])
        else:
            self.text = tk.Text(body, wrap="word", font=(FONT, 10), padx=12, pady=10)
            scrollbar = ttk.Scrollbar(body, command=self.text.yview)
            self.text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            self.text.pack(fill="both", expand=True)
            self.text.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2))
            self.text.configure(state="disabled")


class PromptWorkspace(ttk.Frame):
    """同一页面组件分别保存两个框架的选择、日志与结果。"""

    def __init__(self, parent, framework):
        super().__init__(parent)
        self.framework = framework
        self.catalog = catalog_for(framework)
        self.records = []
        self.environment = None
        self.previews = []
        self.risk_vars = {}
        self.total_var = tk.StringVar(self, value="10")
        self.language_var = tk.StringVar(self, value="中文")
        self.status_var = tk.StringVar(self, value="尚未生成。请选择风险后模拟生成。")
        self.selection_var = tk.StringVar(self)
        self.canvas = tk.Canvas(self, highlightthickness=0, background="#f4f6f8")
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=12)
        self.content_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.content_id, width=event.width))
        self._build()
        self.total_var.trace_add("write", self.update_summary)
        self.language_var.trace_add("write", self.update_summary)
        self.update_summary()

    def _build(self):
        """沿用正式应用的卡片与六列结果结构。"""
        agentic = self.framework == "agentic-2026"
        name = "OWASP Agentic Top 10 2026" if agentic else "OWASP LLM Top 10 2026"
        ttk.Label(self.content, text=name, style="Title.TLabel").pack(anchor="w")
        hint = ("工具、记忆和多智能体场景的输入位置与观察证据另存环境说明；最终记录仍为六字段。" if agentic else
                "单 prompt 与跨用户会话共享六字段结构；LLM02 先发送 userA，再在隔离会话只发送一次 userB 或 prompt。")
        ttk.Label(self.content, text=hint, style="Muted.TLabel", wraplength=920).pack(anchor="w", pady=(5, 10))

        risks = ttk.LabelFrame(self.content, text="1. 选择风险", padding=10)
        risks.pack(fill="x")
        toolbar = ttk.Frame(risks)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(toolbar, text="独立选择 · 编号与名称随结果导出", style="Muted.TLabel").pack(side="left")
        ttk.Button(toolbar, text="清空", width=8, command=lambda: self.select_all(False)).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="全选", width=8, command=lambda: self.select_all(True)).pack(side="right")
        for index, risk in enumerate(self.catalog):
            variable = tk.BooleanVar(self, value=False)
            self.risk_vars[risk["riskId"]] = variable
            ttk.Checkbutton(risks, text=f"{risk['riskId']} · {risk['riskName']}\n{risk['englishName']}",
                            variable=variable, command=self.update_summary).grid(
                                row=1 + index // 2, column=index % 2, sticky="w", padx=(0, 16), pady=4)
        risks.columnconfigure(0, weight=1, uniform="risks")
        risks.columnconfigure(1, weight=1, uniform="risks")

        options = ttk.LabelFrame(self.content, text="2. 本次模拟生成", padding=10)
        options.pack(fill="x", pady=8)
        ttk.Label(options, text="生成数量").grid(row=0, column=0, padx=(0, 6))
        ttk.Spinbox(options, from_=1, to=1000, textvariable=self.total_var, width=8).grid(row=0, column=1, padx=(0, 18))
        ttk.Label(options, text="输出语言").grid(row=0, column=2, padx=(0, 6))
        ttk.Combobox(options, values=("中文", "英文", "中英混合"), state="readonly",
                     textvariable=self.language_var, width=12).grid(row=0, column=3, padx=(0, 18))
        self.start_button = ttk.Button(options, text="模拟生成", style="Accent.TButton", command=self.simulate_generation)
        self.start_button.grid(row=0, column=4)
        ttk.Label(options, textvariable=self.selection_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))

        logs = ttk.LabelFrame(self.content, text="3. 运行日志", padding=8)
        logs.pack(fill="x")
        self.log_text = tk.Text(logs, height=3, wrap="word", font=(FONT, 9), state="disabled")
        log_scroll = ttk.Scrollbar(logs, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="x")

        results = ttk.LabelFrame(self.content, text="4. 运行结果 · 六字段", padding=8)
        results.pack(fill="both", expand=True, pady=(8, 0))
        actions = ttk.Frame(results)
        actions.pack(fill="x", pady=(0, 6))
        self.json_button = ttk.Button(actions, text="JSON 预览", command=lambda: self.open_preview("json"))
        self.excel_button = ttk.Button(actions, text="Excel 六列预览", command=lambda: self.open_preview("excel"))
        self.copy_button = ttk.Button(actions, text="复制所选 prompt", command=self.copy_selected_prompt)
        self.actions = [self.json_button, self.excel_button, self.copy_button]
        self.environment_button = None
        if agentic:
            self.environment_button = ttk.Button(actions, text="环境说明预览", command=lambda: self.open_preview("environment"))
            self.actions.append(self.environment_button)
        for button in self.actions:
            button.pack(side="left", padx=(0, 6))
            button.state(["disabled"])
        self.result_tree = make_result_tree(results)
        self.result_tree.bind("<Double-1>", self.copy_clicked_cell)
        ttk.Label(results, textvariable=self.status_var, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(6, 0))
        ttk.Label(results, text="演示仅用固定虚构数据，不表示模型已生成或目标存在漏洞；双击单元格可复制完整内容。",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(3, 0))

    def select_all(self, selected):
        """仅更新当前框架的勾选。"""
        for variable in self.risk_vars.values():
            variable.set(selected)
        self.update_summary()

    def update_summary(self, *_):
        """同步所选风险与参数范围，保留生成时的最终校验。"""
        count = sum(variable.get() for variable in self.risk_vars.values())
        hint = f"已选 {count}/10 项 · {self.language_var.get()}"
        try:
            valid = count > 0 and count <= int(self.total_var.get()) <= 1000
        except ValueError:
            valid = False
        self.selection_var.set(hint + (" · 可以模拟生成" if valid else " · 请选择风险，数量须在已选项数至 1000 之间"))
        self.start_button.state(["!disabled"] if valid else ["disabled"])

    def _log(self, message):
        """写入本页专属日志，不影响另一页。"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{datetime.now():%H:%M:%S} {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def simulate_generation(self):
        """先清空旧动作，再校验并展示模拟批次，异常保留本页诊断。"""
        for preview in self.previews:
            if preview.winfo_exists():
                preview.destroy()
        self.previews.clear()
        self.records = []
        self.environment = None
        self.result_tree.delete(*self.result_tree.get_children())
        for button in self.actions:
            button.state(["disabled"])
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._log(f"[{self.framework}] 开始离线模拟；未调用模型。")
        try:
            try:
                total = int(self.total_var.get())
            except ValueError:
                raise ValueError("生成数量必须是整数。") from None
            selected = [risk_id for risk_id, variable in self.risk_vars.items() if variable.get()]
            batch = build_demo_batch(self.framework, selected, total, self.language_var.get())
            errors = validate_prompt_records(batch["records"])
            if errors:
                raise ValueError("；".join(errors))
        except (ValueError, RuntimeError, TypeError, KeyError) as error:
            self.status_var.set(f"模拟生成失败：{error}")
            self._log(self.status_var.get())
            return
        self.records = batch["records"]
        self.environment = batch["environment"]
        for index, record in enumerate(self.records):
            self.result_tree.insert("", "end", iid=str(index), values=[record[key] for key in PROMPT_RECORD_KEYS])
        for button in self.actions:
            button.state(["!disabled"])
        self.status_var.set(f"模拟生成完成：{len(self.records)} 条 · 固定演示变体 · 未写入文件")
        self._log(f"六字段校验通过；{len(self.records)} 条结果进入内存。")
        if self.environment is not None:
            self._log("环境说明已逐行关联；recordIndex 从 1 开始，不计 Excel 表头。")

    def _copy(self, value):
        """复制源记录全文，不使用表格的显示截断。"""
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("已复制完整文本。")

    def copy_selected_prompt(self):
        """选择一行后复制其统一 prompt 字段。"""
        selected = self.result_tree.selection()
        if selected:
            self._copy(self.records[int(selected[0])]["prompt"])
        else:
            self.status_var.set("请先选择一条结果。")

    def copy_clicked_cell(self, event):
        """双击任意数据单元格复制实际字段，忽略标题和空白区域。"""
        row = self.result_tree.identify_row(event.y)
        column = self.result_tree.identify_column(event.x)
        if row and column and self.result_tree.identify_region(event.x, event.y) == "cell":
            self._copy(self.records[int(row)][PROMPT_RECORD_KEYS[int(column[1:]) - 1]])
            return "break"

    def open_preview(self, kind):
        """预览当前批次，不把环境元数据塞入最终六字段记录。"""
        if not self.records:
            return None
        payload = self.environment if kind == "environment" else self.records
        if payload is None:
            return None
        # 手动关闭的窗口不再持有引用；下一批开始时撤下本页全部旧预览。
        self.previews = [preview for preview in self.previews if preview.winfo_exists()]
        preview = PreviewWindow(self, kind, payload)
        self.previews.append(preview)
        return preview


class V4PrototypeApplication(tk.Tk):
    """独立原型窗口，正式业务入口与设置均不受影响。"""

    def __init__(self):
        super().__init__()
        self.title("GenerateTestQuestion v4.0.0 原生原型｜LLM / Agentic")
        self.geometry("1280x900")
        self.minsize(1020, 720)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 9))
        style.configure("Title.TLabel", font=(FONT, 15, "bold"), foreground="#17365d")
        style.configure("Muted.TLabel", foreground="#586777")
        style.configure("TLabelframe.Label", foreground="#17365d", font=(FONT, 10, "bold"))
        style.configure("Accent.TButton", padding=(12, 5))
        style.configure("Treeview", rowheight=30)
        header = ttk.Frame(self, padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="GenerateTestQuestion", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="v4.0.0 · 离线交互原型 · 固定演示数据", style="Muted.TLabel").pack(side="left", padx=16)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.tc260_page = ttk.Frame(self.notebook)
        self.llm_page = PromptWorkspace(self.notebook, "llm-2026")
        self.agentic_page = PromptWorkspace(self.notebook, "agentic-2026")
        self.sources_page = ttk.Frame(self.notebook)
        self.settings_page = ttk.Frame(self.notebook)
        pages = (self.tc260_page, self.llm_page, self.agentic_page, self.sources_page, self.settings_page)
        for index, (name, page) in enumerate(zip(WORKSPACES, pages)):
            self.notebook.add(page, text=name)
            self.bind(f"<Control-Key-{index + 1}>", lambda event, position=index: self.notebook.select(position))
        for page, title, description in (
            (self.tc260_page, "TC260 题库生成", "正式版保留：选择网站 → TC260 风险 → 模型出题。此原型仅展示工作区位置。"),
            (self.sources_page, "来源管理", "正式版保留现有来源管理；LLM 和 Agentic 题集均不需要选择或爬取网站。"),
            (self.settings_page, "设置", "正式版的 LLM 与 Agentic 共用模型配置和产物目录。本原型不读取密钥，也不修改用户设置。"),
        ):
            body = ttk.LabelFrame(page, text=title, padding=24)
            body.pack(fill="x", padx=18, pady=18)
            ttk.Label(body, text=description, wraplength=850).pack(anchor="w")
            ttk.Button(body, text="查看 Agentic 原型", command=lambda: self.notebook.select(self.agentic_page)).pack(anchor="w", pady=(18, 0))
        self.notebook.select(self.agentic_page)
        self.bind("<MouseWheel>", self._scroll_page)

    def _scroll_page(self, event):
        """表格和日志保留内部滚动，其余内容滚动所在的工作区。"""
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Treeview)):
            return
        while widget is not None:
            if isinstance(widget, PromptWorkspace):
                widget.canvas.yview_scroll(-int(event.delta / 120), "units")
                return
            widget = getattr(widget, "master", None)


def smoke_test():
    """不创建窗口地验证两个目录、六字段、跨会话和环境关联。"""
    agentic = build_demo_batch("agentic-2026", [r["riskId"] for r in catalog_for("agentic-2026")], 10, "中文")
    llm = build_demo_batch("llm-2026", ["LLM02"], 1, "中文")["records"][0]
    if len(agentic["environment"]["records"]) != 10 or llm["prompt"] != llm["userB"]:
        raise ValueError("原型自检失败：环境关联或跨会话镜像错误。")
    return {"prototypeReady": True, "mode": "prototype-demo", "version": "4.0.0-prototype",
            "workspaces": list(WORKSPACES), "catalogs": {key: len(catalog_for(key)) for key in ("llm-2026", "agentic-2026")}}


def main():
    """自检输出 ASCII 安全 JSON，默认启动独立原型窗口。"""
    if "--smoke-test" in sys.argv:
        print(json.dumps(smoke_test(), ensure_ascii=True))
    else:
        V4PrototypeApplication().mainloop()


if __name__ == "__main__":
    main()
