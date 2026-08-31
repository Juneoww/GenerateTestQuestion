"""功能:
  提供 GenerateTestQuestion 桌面端（纯 Python 单栈）：生成、来源管理、设置三个工作区，
  以"爬取网站 → 生成题目（测试提示集）"为唯一主流程，实时日志与原文↔题目对照。
实现:
  Tkinter 构建三页；爬取与出题由 pipeline 在后台线程执行，事件经 queue.Queue 投递，
  主线程 after 轮询刷新日志；来源核验异步执行并同步网站名单/核验日志。
输入: data/sources.json、data/settings.json、data/risk_catalog.json。
输出: data/output/<批次>/（题目 Excel/JSON、留痕）、data/reports/（名单与核验日志）、
      data/sources.json（核验状态回写）、data/settings.json。
依赖: Python 3.10+ 标准库、scrapling[fetchers]、openpyxl（见 requirements.txt）。
用法:
  .venv/Scripts/python app.py
  .venv/Scripts/python app.py --smoke-test
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import END, HORIZONTAL, LEFT, RIGHT, VERTICAL, W, X, Y, messagebox, ttk
import tkinter as tk

import crawler
import pipeline
import question_generator
import reporting
import storage

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACES = ("生成", "来源管理", "设置")
FONT = "Microsoft YaHei UI"


class DesktopApplication(tk.Tk):
    """主窗口：只在主线程更新 UI，爬取/出题/核验统一放后台线程。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("GenerateTestQuestion｜爬取网站 → 生成题目")
        self.geometry("1280x860")
        self.minsize(1020, 680)
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self.current_questions: list[dict] = []
        self.current_batch_dir = ""
        self.current_xlsx = ""
        self.site_vars: dict[str, tk.BooleanVar] = {}
        self.scene_vars: dict[str, tk.BooleanVar] = {}
        self.risk_vars: dict[str, tk.BooleanVar] = {}
        self._generate_widgets: list[tk.Widget] = []
        self._configure_style()
        self._create_layout()
        self._refresh_all()
        self.after(120, self._poll_events)

    # ------------------------------------------------------------------ 样式
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=(FONT, 16, "bold"), foreground="#17365D")
        style.configure("Subtle.TLabel", foreground="#5B6573")
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Card.TLabelframe.Label", font=(FONT, 10, "bold"), foreground="#17365D")
        style.configure("Accent.TButton", padding=(10, 6))

    def _create_layout(self) -> None:
        header = ttk.Frame(self, padding=(20, 14, 20, 6))
        header.pack(fill=X)
        ttk.Label(header, text="GenerateTestQuestion", style="Title.TLabel").pack(side=LEFT)
        ttk.Label(header, text="爬取网站 → 生成题目（测试提示集）", style="Subtle.TLabel").pack(side=LEFT, padx=14)
        ttk.Button(header, text="刷新数据", command=self._refresh_all).pack(side=RIGHT)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.generate_tab = ttk.Frame(notebook, padding=12)
        self.sources_tab = ttk.Frame(notebook, padding=12)
        self.settings_tab = ttk.Frame(notebook, padding=12)
        for name, tab in zip(WORKSPACES, [self.generate_tab, self.sources_tab, self.settings_tab], strict=True):
            notebook.add(tab, text=name)
        for index in range(len(WORKSPACES)):
            self.bind(f"<Control-Key-{index + 1}>",
                      lambda event, page=index: notebook.select(page))
        self._build_generate_tab()
        self._build_sources_tab()
        self._build_settings_tab()

        self.status_text = tk.StringVar(value="正在读取项目数据…")
        ttk.Label(self, textvariable=self.status_text, anchor=W, style="Subtle.TLabel",
                  padding=(20, 6)).pack(fill=X)

    # ------------------------------------------------------------------ 生成页
    def _build_generate_tab(self) -> None:
        site_frame = ttk.LabelFrame(self.generate_tab, text="1. 选择网站（已核验可爬）", style="Card.TLabelframe")
        site_frame.pack(fill=X)
        toolbar = ttk.Frame(site_frame)
        toolbar.pack(fill=X, pady=(0, 4))
        ttk.Label(toolbar, text="仅列出核验状态为“可爬”的站点；新增与核验请到“来源管理”。",
                  style="Subtle.TLabel").pack(side=LEFT)
        self.site_cards = ttk.Frame(site_frame)
        self.site_cards.pack(fill=X)

        type_frame = ttk.LabelFrame(self.generate_tab, text="2. 题目类型（参照 TC260，大类→小类）", style="Card.TLabelframe")
        type_frame.pack(fill=X, pady=(8, 0))
        self.scene_row = ttk.Frame(type_frame)
        self.scene_row.pack(fill=X)
        ttk.Label(type_frame, text="小类（勾选大类默认全选，可单独增减）：",
                  style="Subtle.TLabel").pack(anchor=W, pady=(6, 2))
        self.risk_frame = ttk.Frame(type_frame)
        self.risk_frame.pack(fill=X)

        options = ttk.LabelFrame(self.generate_tab, text="3. 本次生成", style="Card.TLabelframe")
        options.pack(fill=X, pady=(8, 0))
        self.total_var = tk.StringVar(value="50")
        self.zh_var = tk.StringVar(value="80")
        ttk.Label(options, text="生成数量").grid(row=0, column=0, sticky=W, padx=(0, 4), pady=4)
        total_spin = ttk.Spinbox(options, from_=1, to=1000, textvariable=self.total_var, width=8)
        total_spin.grid(row=0, column=1, sticky=W, padx=(0, 14))
        ttk.Label(options, text="中文占比").grid(row=0, column=2, sticky=W, padx=(0, 4))
        zh_spin = ttk.Spinbox(options, from_=0, to=100, textvariable=self.zh_var, width=6)
        zh_spin.grid(row=0, column=3, sticky=W, padx=(0, 4))
        ttk.Label(options, text="%", style="Subtle.TLabel").grid(row=0, column=4, sticky=W)
        self.start_button = ttk.Button(options, text="开始生成", style="Accent.TButton",
                                       command=self._start_batch)
        self.start_button.grid(row=0, column=5, sticky="e", padx=(20, 0))
        options.columnconfigure(5, weight=1)
        self._generate_widgets = [total_spin, zh_spin, self.start_button]

        log_frame = ttk.LabelFrame(self.generate_tab, text="4. 运行日志", style="Card.TLabelframe")
        log_frame.pack(fill=X, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=8, wrap="word", font=(FONT, 9), state="disabled")
        self.log_text.pack(fill=X)
        self.log_text.tag_configure("warn", foreground="#8a6d00")
        self.log_text.tag_configure("error", foreground="#a4262c")

        compare = ttk.LabelFrame(self.generate_tab, text="5. 原文 ↔ 题目对照", style="Card.TLabelframe")
        compare.pack(fill="both", expand=True, pady=(8, 0))
        paned = ttk.PanedWindow(compare, orient=HORIZONTAL)
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=2)
        paned.add(right, weight=3)
        self.question_tree = ttk.Treeview(left, columns=("seq", "risk", "digest"), show="headings", height=9)
        for column, title, width in (("seq", "序号", 46), ("risk", "小类", 64), ("digest", "题干摘要", 340)):
            self.question_tree.heading(column, text=title)
            self.question_tree.column(column, width=width, anchor=W)
        self.question_tree.bind("<<TreeviewSelect>>", self._on_question_selected)
        tree_scroll = ttk.Scrollbar(left, orient=VERTICAL, command=self.question_tree.yview)
        self.question_tree.configure(yscrollcommand=tree_scroll.set)
        self.question_tree.pack(side=LEFT, fill="both", expand=True)
        tree_scroll.pack(side=RIGHT, fill=Y)
        self.detail_text = tk.Text(right, wrap="word", font=(FONT, 9), state="disabled")
        detail_scroll = ttk.Scrollbar(right, orient=VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side=LEFT, fill="both", expand=True)
        detail_scroll.pack(side=RIGHT, fill=Y)

        actions = ttk.Frame(self.generate_tab)
        actions.pack(fill=X, pady=(6, 0))
        self.open_xlsx_button = ttk.Button(actions, text="打开题库 Excel", state="disabled",
                                           command=lambda: self._open_path(Path(self.current_xlsx)))
        self.open_xlsx_button.pack(side=RIGHT)
        self.open_batch_button = ttk.Button(actions, text="打开批次目录", state="disabled",
                                            command=lambda: self._open_path(Path(self.current_batch_dir)))
        self.open_batch_button.pack(side=RIGHT, padx=8)
        ttk.Button(actions, text="打开来源网页",
                   command=self._open_question_url).pack(side=RIGHT)

    def _refresh_selection_catalog(self) -> None:
        scenes = storage.load_catalog()
        for child in self.site_cards.winfo_children():
            child.destroy()
        for child in self.scene_row.winfo_children():
            child.destroy()
        for child in self.risk_frame.winfo_children():
            child.destroy()
        self.site_vars.clear()
        self.scene_vars.clear()
        self.risk_vars.clear()

        previous_sites = {k: v.get() for k, v in self.site_vars.items()}
        ready_sites = [s for s in storage.load_sources() if s.get("status") == "ready"]
        if not ready_sites:
            ttk.Label(self.site_cards, style="Subtle.TLabel",
                      text="暂无可爬站点：请先到“来源管理”核验通过。").pack(anchor=W)
        for index, site in enumerate(ready_sites):
            variable = tk.BooleanVar(value=previous_sites.get(site["sourceId"], False))
            self.site_vars[site["sourceId"]] = variable
            label = f"{site['name']}（{'中文' if site.get('language') == 'zh' else '英文'}）"
            ttk.Checkbutton(self.site_cards, text=label, variable=variable).grid(
                row=index // 3, column=index % 3, sticky=W, padx=(0, 14), pady=2)

        previous_risks = {k: v.get() for k, v in self.risk_vars.items()}
        for index, scene in enumerate(scenes):
            code = scene["sceneCode"]
            variable = tk.BooleanVar(value=True)
            self.scene_vars[code] = variable
            box = ttk.Checkbutton(self.scene_row, text=f"{code} {scene['scene']}", variable=variable,
                                  command=lambda c=code: self._on_scene_toggle(c))
            box.grid(row=0, column=index, sticky=W, padx=(0, 12))
            for risk in scene.get("risks", []):
                rid = risk["riskId"]
                risk_var = tk.BooleanVar(value=previous_risks.get(rid, True))
                self.risk_vars[rid] = risk_var
                ttk.Checkbutton(self.risk_frame, text=f"{rid} {risk['category'][:12]}",
                                variable=risk_var).grid(
                    row=(len(self.risk_vars) - 1) // 5, column=(len(self.risk_vars) - 1) % 5,
                    sticky=W, padx=(0, 8), pady=1)

    def _on_scene_toggle(self, scene_code: str) -> None:
        value = self.scene_vars[scene_code].get()
        prefix = scene_code.replace(".", "")  # "A.1" → "A1"，对应小类 ID 前缀
        for rid, variable in self.risk_vars.items():
            if rid.startswith(prefix + "-"):
                variable.set(value)

    def _selected_site_ids(self) -> list[str]:
        return sorted(sid for sid, v in self.site_vars.items() if v.get())

    def _selected_risk_ids(self) -> list[str]:
        return sorted(rid for rid, v in self.risk_vars.items() if v.get())

    def _start_batch(self) -> None:
        if self.running:
            return
        site_ids = self._selected_site_ids()
        risk_ids = self._selected_risk_ids()
        if not site_ids:
            messagebox.showwarning("未选择网站", "请至少选择一个可爬站点。", parent=self)
            return
        if not risk_ids:
            messagebox.showwarning("未选择题型", "请至少勾选一个小类。", parent=self)
            return
        try:
            total = int(self.total_var.get())
            zh_percent = int(self.zh_var.get())
        except ValueError:
            messagebox.showwarning("参数错误", "生成数量与中文占比必须是整数。", parent=self)
            return
        if not (len(risk_ids) <= total <= 1000):
            messagebox.showwarning("数量错误", f"生成数量必须在 {len(risk_ids)} 至 1000 之间。", parent=self)
            return
        if not (0 <= zh_percent <= 100):
            messagebox.showwarning("比例错误", "中文占比必须在 0 至 100 之间。", parent=self)
            return
        settings = storage.load_settings()
        if not (settings["baseUrl"] and settings["model"]):
            messagebox.showwarning("缺少模型配置", "请先到“设置”页配置接口地址、API Key 与模型名。", parent=self)
            return
        params = {"sourceIds": site_ids, "riskIds": risk_ids, "total": total, "zhPercent": zh_percent}
        self.running = True
        for widget in self._generate_widgets:
            widget.state(["disabled"])
        self._set_status("生成中…")

        def work() -> None:
            try:
                summary = pipeline.run_batch(params, settings, self.events.put)
            except Exception as error:  # noqa: BLE001 - 后端错误原样呈现
                self.events.put({"stage": "_done", "kind": "batch", "ok": False, "error": str(error)})
            else:
                self.events.put({"stage": "_done", "kind": "batch", "ok": True, "summary": summary})

        threading.Thread(target=work, daemon=True).start()

    def _finish_batch(self, done: dict) -> None:
        self.running = False
        for widget in self._generate_widgets:
            widget.state(["!disabled"])
        if not done.get("ok"):
            self._set_status("生成失败")
            messagebox.showerror("生成失败", done.get("error", "未知错误"), parent=self)
            return
        summary = done["summary"]
        self.current_questions = summary.get("questions", [])
        self.current_batch_dir = summary.get("batchDir", "")
        self.current_xlsx = summary.get("xlsxPath", "")
        self.open_batch_button.state(["!disabled"])
        self.open_xlsx_button.state(["!disabled"] if self.current_xlsx else ["disabled"])
        self.question_tree.delete(*self.question_tree.get_children())
        for q in self.current_questions:
            self.question_tree.insert("", END, iid=str(q["seq"]), values=(
                q["seq"], q["riskId"], q["question"][:48]))
        self._set_status(f"批次 {summary['batchId']} 完成：{summary['questionCount']} 题"
                         f"（中 {summary['zhCount']} / 英 {summary['enCount']}）")
        shortage = summary.get("shortage", [])
        note = f"，缺口 {len(shortage)} 项" if shortage else ""
        messagebox.showinfo("生成完成",
                            f"批次 {summary['batchId']}\n产出 {summary['questionCount']} 题"
                            f"（中文 {summary['zhCount']} / 英文 {summary['enCount']}）{note}",
                            parent=self)

    def _on_question_selected(self, _event=None) -> None:
        selection = self.question_tree.selection()
        if not selection:
            return
        seq = int(selection[0])
        question = next((q for q in self.current_questions if q["seq"] == seq), None)
        if not question:
            return
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", END)
        self.detail_text.insert("1.0", (
            f"【题干】{question['question']}\n\n"
            f"【类型】{question['sceneCode']} {question['riskId']} {question['category']}"
            f"（{question['language']}）\n"
            f"【来源】{question['sourceName']}　{question['sourceUrl']}\n\n"
            f"【依据原文】\n{question['evidenceText'][:2000]}"
        ))
        self.detail_text.configure(state="disabled")

    def _open_question_url(self) -> None:
        selection = self.question_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先在左侧选择一道题。", parent=self)
            return
        question = next((q for q in self.current_questions if q["seq"] == int(selection[0])), None)
        if question and question.get("sourceUrl"):
            webbrowser.open(question["sourceUrl"])

    # ------------------------------------------------------------------ 来源管理
    def _build_sources_tab(self) -> None:
        toolbar = ttk.Frame(self.sources_tab)
        toolbar.pack(fill=X, pady=(0, 6))
        ttk.Button(toolbar, text="核验选中", command=lambda: self._verify_async(selected_only=True)).pack(side=LEFT)
        ttk.Button(toolbar, text="核验全部", command=lambda: self._verify_async(selected_only=False)).pack(side=LEFT, padx=6)
        ttk.Button(toolbar, text="停用/启用", command=self._toggle_disabled).pack(side=LEFT)
        ttk.Button(toolbar, text="新增站点", command=self._add_source_dialog).pack(side=LEFT, padx=6)
        ttk.Button(toolbar, text="打开网站名单", command=self._open_site_list).pack(side=RIGHT)

        columns = ("sourceId", "name", "language", "method", "engine", "status", "checked", "note")
        self.source_tree = ttk.Treeview(self.sources_tab, columns=columns, show="headings", height=20)
        labels = {"sourceId": "来源ID", "name": "名称", "language": "语言", "method": "方式",
                  "engine": "引擎", "status": "状态", "checked": "最近核验", "note": "备注"}
        widths = {"sourceId": 150, "name": 240, "language": 60, "method": 70,
                  "engine": 80, "status": 90, "checked": 100, "note": 260}
        for column in columns:
            self.source_tree.heading(column, text=labels[column])
            self.source_tree.column(column, width=widths[column], minwidth=50, anchor=W)
        scroll = ttk.Scrollbar(self.sources_tab, orient=VERTICAL, command=self.source_tree.yview)
        self.source_tree.configure(yscrollcommand=scroll.set)
        self.source_tree.pack(side=LEFT, fill="both", expand=True)
        scroll.pack(side=RIGHT, fill=Y)

    def _refresh_sources_table(self) -> None:
        if not hasattr(self, "source_tree"):
            return
        self.source_tree.delete(*self.source_tree.get_children())
        for source in storage.load_sources():
            status = storage.STATUS_LABELS.get(source.get("status", ""), source.get("status", ""))
            self.source_tree.insert("", END, iid=source["sourceId"], values=(
                source["sourceId"], source.get("name", ""), source.get("language", ""),
                source.get("method", ""), source.get("engine", ""), status,
                source.get("lastCheckedAt") or "—", source.get("note") or ""))

    def _verify_async(self, selected_only: bool) -> None:
        if self.running:
            messagebox.showinfo("提示", "当前有任务运行中，请稍后再核验。", parent=self)
            return
        selection = set(self.source_tree.selection())
        targets = [s for s in storage.load_sources()
                   if s.get("status") != "disabled" and (not selected_only or s["sourceId"] in selection)]
        if not targets:
            messagebox.showwarning("未选择站点", "请先在表格中选中要核验的站点。", parent=self)
            return
        self.running = True
        self._set_status(f"核验 {len(targets)} 个站点…")

        def work() -> None:
            results = []
            sources = storage.load_sources()
            for source in targets:
                result = crawler.verify_source(source, storage.load_settings())
                results.append(result)
                for item in sources:
                    if item["sourceId"] == source["sourceId"]:
                        item["status"] = "ready" if result["passed"] else "failed"
                        item["lastCheckedAt"] = str(__import__("datetime").date.today())
                        item["note"] = result["reason"] if not result["passed"] else "自动核验通过"
                        break
            storage.save_sources(sources)
            reporting.append_verify_log(results)
            reporting.write_site_list(sources)
            self.events.put({"stage": "_done", "kind": "verify", "ok": True,
                             "passed": sum(1 for r in results if r["passed"]), "total": len(results)})

        threading.Thread(target=work, daemon=True).start()

    def _finish_verify(self, done: dict) -> None:
        self.running = False
        self._refresh_all()
        self._set_status(f"核验完成：通过 {done.get('passed', 0)} / {done.get('total', 0)}")
        messagebox.showinfo("核验完成",
                            f"通过 {done.get('passed', 0)} / {done.get('total', 0)}\n"
                            "网站名单与核验日志已更新，通过的站点已进入生成页。",
                            parent=self)

    def _toggle_disabled(self) -> None:
        selection = set(self.source_tree.selection())
        if not selection:
            messagebox.showwarning("未选择站点", "请先选中要停用/启用的站点。", parent=self)
            return
        sources = storage.load_sources()
        for source in sources:
            if source["sourceId"] in selection:
                source["status"] = "pending" if source["status"] == "disabled" else "disabled"
        storage.save_sources(sources)
        self._refresh_sources_table()

    def _add_source_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("新增站点")
        dialog.transient(self)
        fields = [("来源ID", "sourceId"), ("名称", "name"), ("入口 URL（HTTPS）", "url"),
                  ("列表 URL 模板（含 {num}，可空）", "listUrlTemplate"),
                  ("条目正则（含一个捕获组）", "itemPattern"),
                  ("URL 前缀（拼接详情链接，可空）", "itemUrlBase")]
        variables = {key: tk.StringVar() for _, key in fields}
        for row, (label, key) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky=W, padx=8, pady=4)
            ttk.Entry(dialog, textvariable=variables[key], width=58).grid(row=row, column=1, pady=4)
        language = tk.StringVar(value="zh")
        method = tk.StringVar(value="html")
        engine = tk.StringVar(value="fetcher")
        for row, (label, var, values) in enumerate([
            ("语言", language, ("zh", "en")), ("方式", method, ("html", "json")),
            ("引擎", engine, ("fetcher", "stealthy")),
        ], start=len(fields)):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky=W, padx=8, pady=4)
            ttk.Combobox(dialog, textvariable=var, values=values, state="readonly", width=12).grid(row=row, column=1, sticky=W, pady=4)

        def save() -> None:
            new_source = {key: var.get().strip() for key, var in variables.items()}
            new_source.update({"language": language.get(), "method": method.get(), "engine": engine.get()})
            if not new_source["sourceId"] or not new_source["name"] or not new_source["url"]:
                messagebox.showwarning("缺少必填项", "来源ID、名称、入口 URL 必填。", parent=dialog)
                return
            if not crawler.is_safe_url(new_source["url"]) or (
                new_source["listUrlTemplate"] and not crawler.is_safe_url(new_source["listUrlTemplate"].replace("{num}", "1"))
            ):
                messagebox.showwarning("URL 不合规", "入口与列表 URL 必须是 HTTPS（443、无凭据）。", parent=dialog)
                return
            sources = storage.load_sources()
            if any(s["sourceId"] == new_source["sourceId"] for s in sources):
                messagebox.showwarning("ID 重复", "来源 ID 已存在。", parent=dialog)
                return
            sources.append(new_source)
            storage.save_sources(sources)
            reporting.write_site_list(sources)
            dialog.destroy()
            self._refresh_all()

        ttk.Button(dialog, text="保存（待核验）", command=save).grid(
            row=len(fields) + 3, column=1, sticky="e", padx=8, pady=10)

    def _open_site_list(self) -> None:
        path = storage.DATA_DIR / "reports" / "网站名单.md"
        if path.exists():
            self._open_path(path)
        else:
            messagebox.showinfo("尚未生成", "还没有网站名单：先执行一次核验。", parent=self)

    # ------------------------------------------------------------------ 设置页
    def _build_settings_tab(self) -> None:
        frame = ttk.LabelFrame(self.settings_tab, text="模型配置（OpenAI 兼容接口）", style="Card.TLabelframe")
        frame.pack(fill=X)
        self.setting_vars = {
            "baseUrl": tk.StringVar(), "apiKey": tk.StringVar(), "model": tk.StringVar(),
            "temperature": tk.StringVar(), "timeoutSeconds": tk.StringVar(),
            "retries": tk.StringVar(), "maxQuestionsPerItem": tk.StringVar(),
            "crawlDelayMs": tk.StringVar(), "requestTimeoutSeconds": tk.StringVar(),
        }
        labels = {
            "baseUrl": "接口地址（含 /v1 等版本号）", "apiKey": "API Key", "model": "模型名",
            "temperature": "温度", "timeoutSeconds": "接口超时（秒）", "retries": "出题重试次数",
            "maxQuestionsPerItem": "单条原文最多出题数", "crawlDelayMs": "爬取请求间隔（毫秒）",
            "requestTimeoutSeconds": "爬取超时（秒）",
        }
        for row, (key, label) in enumerate(labels.items()):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=W, padx=8, pady=5)
            entry = ttk.Entry(frame, textvariable=self.setting_vars[key], width=52,
                              show="*" if key == "apiKey" else "")
            entry.grid(row=row, column=1, sticky=W, pady=5)
        buttons = ttk.Frame(self.settings_tab)
        buttons.pack(fill=X, pady=(10, 0))
        ttk.Button(buttons, text="保存设置", command=self._save_settings).pack(side=LEFT)
        ttk.Button(buttons, text="测试连接", command=self._test_connection_async).pack(side=LEFT, padx=8)
        self.connection_result = tk.StringVar(value="")
        ttk.Label(buttons, textvariable=self.connection_result, style="Subtle.TLabel").pack(side=LEFT, padx=10)
        self._load_settings_into_form()

    def _load_settings_into_form(self) -> None:
        settings = storage.load_settings()
        for key, variable in self.setting_vars.items():
            variable.set(str(settings.get(key, "")))

    def _collect_settings(self) -> dict:
        patch = {}
        for key, variable in self.setting_vars.items():
            raw = variable.get().strip()
            if key in ("temperature",):
                patch[key] = float(raw) if raw else storage.SETTINGS_DEFAULTS[key]
            elif key in ("timeoutSeconds", "retries", "maxQuestionsPerItem", "crawlDelayMs", "requestTimeoutSeconds"):
                patch[key] = int(raw) if raw else storage.SETTINGS_DEFAULTS[key]
            else:
                patch[key] = raw
        return patch

    def _save_settings(self) -> None:
        try:
            patch = self._collect_settings()
        except ValueError:
            messagebox.showwarning("格式错误", "数值字段必须填写数字。", parent=self)
            return
        merged = storage.save_settings(patch)
        self._set_status("设置已保存")
        self.connection_result.set(f"已保存：{merged['model'] or '（未填模型名）'}")

    def _test_connection_async(self) -> None:
        try:
            patch = self._collect_settings()
        except ValueError:
            messagebox.showwarning("格式错误", "数值字段必须填写数字。", parent=self)
            return
        if not (patch["baseUrl"] and patch["model"]):
            messagebox.showwarning("缺少配置", "请先填写接口地址与模型名。", parent=self)
            return
        self.connection_result.set("测试中…")

        def work() -> None:
            try:
                reply = question_generator.test_connection(patch)
            except Exception as error:  # noqa: BLE001 - 展示给操作者
                self.events.put({"stage": "_done", "kind": "test", "ok": False, "error": str(error)})
            else:
                self.events.put({"stage": "_done", "kind": "test", "ok": True, "reply": reply})

        threading.Thread(target=work, daemon=True).start()

    def _finish_test(self, done: dict) -> None:
        if done.get("ok"):
            self.connection_result.set(f"连接成功：{done.get('reply', '')}")
            self._set_status("模型连接正常")
        else:
            self.connection_result.set("连接失败")
            messagebox.showerror("连接失败", done.get("error", ""), parent=self)

    # ------------------------------------------------------------------ 公共
    def _refresh_all(self) -> None:
        try:
            self._refresh_selection_catalog()
            self._refresh_sources_table()
            self._set_status("项目数据已刷新")
        except Exception as error:  # noqa: BLE001 - 数据文件异常直接呈现
            self._set_status(f"数据加载失败：{error}")

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            stage = event.get("stage", "")
            if stage == "_done":
                kind = event.get("kind")
                if kind == "batch":
                    self._finish_batch(event)
                elif kind == "verify":
                    self._finish_verify(event)
                elif kind == "test":
                    self._finish_test(event)
                continue
            self._append_log(event)
        self.after(120, self._poll_events)

    def _append_log(self, event: dict) -> None:
        level = event.get("level", "info")
        stamp = (event.get("ts") or "")[11:19] or "--:--:--"
        prefix = event.get("sourceId") or event.get("riskId") or ""
        line = f"{stamp} [{event.get('stage', '')}]{'[' + prefix + ']' if prefix else ''} {event.get('message', '')}"
        self.log_text.configure(state="normal")
        self.log_text.insert(END, line + "\n", () if level == "info" else (level,))
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text.set(text)

    def _open_path(self, candidate: Path) -> None:
        try:
            target = candidate.resolve()
            target.relative_to(PROJECT_ROOT)
        except (ValueError, OSError):
            messagebox.showerror("无法打开", "仅允许打开项目目录内的路径。", parent=self)
            return
        if not target.exists():
            messagebox.showerror("无法打开", "目标文件或目录不存在。", parent=self)
            return
        if not hasattr(os, "startfile"):
            messagebox.showerror("无法打开", "当前系统不支持打开本地文件。", parent=self)
            return
        os.startfile(target)  # type: ignore[attr-defined]


def smoke_test() -> dict:
    """不创建 Tk 窗口，供自动测试确认数据桥与目录完整性。"""
    scenes = storage.load_catalog()
    risks = storage.catalog_risks(scenes)
    sources = storage.load_sources()
    settings = storage.load_settings()
    return {
        "desktopReady": True,
        "workspaces": list(WORKSPACES),
        "catalog": {"scenes": len(scenes), "risks": len(risks)},
        "sources": {"total": len(sources),
                    "ready": sum(1 for s in sources if s.get("status") == "ready")},
        "modelConfigured": bool(settings["baseUrl"] and settings["model"]),
        "python": sys.version.split()[0],
    }


def main() -> None:
    if "--smoke-test" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(smoke_test(), ensure_ascii=False))
        return
    application = DesktopApplication()
    application.mainloop()


if __name__ == "__main__":
    main()
