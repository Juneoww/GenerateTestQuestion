"""功能：在同一窗口对当前批次原题生成规则变种和模型改写变种。

实现：Tk 窗口仅在主线程更新，变换及文件导出在后台执行，原题不原地修改。
输入：原题记录、题集类型、批次目录；输出：独立变种 Excel 和可选图片。
依赖：规则引擎、模型改写服务、导出模块和共享文字图片设置。
"""
from __future__ import annotations

import queue
import json
import os
from copy import deepcopy
from functools import partial
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
import tkinter as tk
from tkinter import messagebox, ttk

_MODEL_GROUP = "模型改写变种"
_MODEL_STATUS_LABELS = {"basic": "原题", "generated": "已生成", "skipped": "跳过", "failed": "失败"}


def make_variant_rows(records, selected, strategy_ids, framework, transform, checkpoint=None, planned_surfaces=None,
                      *, model_strategy_ids=(), progress=None):
    """根据现有原题构造基线和状态行，不修改输入记录。"""
    if not selected or not strategy_ids:
        raise ValueError("请至少选择一道原题和一种策略。")
    rows = []
    completed = 0
    for index in selected:
        item = records[index]
        original = item.get("question", "") if framework == "tc" else item.get("prompt", "")
        risk_id = item.get("riskId", "")
        source_index = item.get("seq", index + 1)
        base = {"sourceIndex": source_index, "riskId": risk_id,
                "riskName": item.get("category", item.get("riskName", "")),
                "originalText": original, "sourceName": item.get("sourceName", ""),
                "sourceUrl": item.get("sourceUrl", ""), "originalAssertion": item.get("assertion", ""),
                "questionType": item.get("questionType", ""), "originalUserA": item.get("userA", ""),
                "originalUserB": item.get("userB", ""),
                "plannedInputSurface": planned_surfaces[index] if planned_surfaces is not None else "",
                "sourceRecord": deepcopy(item)}
        rows.append({**base, "strategyId": "basic", "strategyName": "basic 原题",
                     "variantText": original, "status": "basic", "reason": "",
                     "reviewStatus": "not_applicable"})
        language = item.get("language")
        if language not in ("zh", "en"):
            language = "zh" if any("\u4e00" <= c <= "\u9fff" for c in original) else "en"
        for strategy in strategy_ids:
            is_model = strategy in model_strategy_ids
            if checkpoint:
                checkpoint()
            try:
                outcome = transform(strategy, original, language=language)
            except InterruptedError:
                raise
            except Exception as error:
                reason = "模型变种生成失败" if is_model else str(error)
                outcome = {"status": "failed", "text": "", "reason": reason}
            if is_model and checkpoint:
                checkpoint()
            status = outcome.get("status", "failed")
            variant = outcome.get("text", "")
            reason = outcome.get("reason", "")
            row = {**base, "strategyId": strategy, "strategyName": strategy,
                   "variantText": variant, "status": status, "reason": reason,
                   "reviewStatus": "" if is_model else ("needs_review" if status == "generated" else "not_applicable")}
            if is_model and "modelMeta" in outcome:
                row["modelMeta"] = outcome["modelMeta"]
            rows.append(row)
            if progress and is_model:
                completed += 1
                progress(completed)
    return rows


class StrategyWindow(tk.Toplevel):
    """在独立窗口选择原题与规则，使用后台线程生成及导出。"""

    def __init__(self, parent, records, framework, batch_dir):
        super().__init__(parent)
        import storage
        from strategy_engine import STRATEGIES
        from strategy_model import MODEL_STRATEGIES
        from strategy_scenario import load_planned_surfaces

        self.records = [dict(record) for record in records]
        self.framework, self.batch_dir = framework, Path(batch_dir)
        self.model_strategy_ids = {item["id"] for item in MODEL_STRATEGIES}
        self.specs = [*STRATEGIES, *({**item, "group": _MODEL_GROUP} for item in MODEL_STRATEGIES)]
        self.planned_surfaces = load_planned_surfaces(self.records, framework, batch_dir)
        self.model_settings = dict(storage.load_settings())
        for key in ("baseUrl", "model"):
            value = self.model_settings.get(key)
            self.model_settings[key] = value.strip() if isinstance(value, str) else ""
        try:
            service = urlsplit(self.model_settings["baseUrl"])
            self.model_ready = bool(service.scheme in ("http", "https") and service.hostname
                                    and self.model_settings["model"])
        except ValueError:
            self.model_ready = False
        self.names = {item["id"]: item["name"] for item in self.specs}
        self.rows = []
        self.tasks = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self._rendering = False
        self._render_after = None
        self.last_export = None
        self.title("攻击方式变种｜当前批次")
        self.geometry("1100x820")
        self.minsize(900, 650)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._parent_destroy_binding = parent.bind("<Destroy>", self._parent_destroyed, add="+")
        self.bind("<Destroy>", self._window_destroyed, add="+")
        self._build()
        self._poll_after = self.after(100, self._poll)

    def _parent_destroyed(self, event):
        """主窗口关闭时通知后台结束，并允许工作线程清理暂存目录。"""
        if event.widget is self.master:
            self.cancel.set()

    def _window_destroyed(self, event):
        if event.widget is self:
            self.cancel.set()
            if getattr(self, "_poll_after", None):
                try:
                    self.after_cancel(self._poll_after)
                except tk.TclError:
                    pass
            if self._render_after is not None:
                try:
                    self.after_cancel(self._render_after)
                except tk.TclError:
                    pass
                self._render_after = None
            if self._parent_destroy_binding:
                try:
                    self.master.unbind("<Destroy>", self._parent_destroy_binding)
                except tk.TclError:
                    pass
                self._parent_destroy_binding = None

    def _build(self):
        ttk.Label(self, text="基于当前批次的原题生成变种。", padding=10).pack(anchor="w")
        source = ttk.LabelFrame(self, text="1. 选择原题", padding=8)
        source.pack(fill="x", padx=10)
        batch_sources = ttk.Frame(source)
        batch_sources.pack(fill="x")
        toolbar = ttk.Frame(batch_sources)
        toolbar.pack(fill="x")
        self.select_all_button = ttk.Button(toolbar, text="全选", command=lambda: self._select_sources(True))
        self.select_all_button.pack(side="left")
        self.clear_button = ttk.Button(toolbar, text="清空", command=lambda: self._select_sources(False))
        self.clear_button.pack(side="left", padx=6)
        self.source = tk.Canvas(batch_sources, height=105, highlightthickness=0)
        from strategy_tooltip import SourceTooltip
        self.source_tooltip = SourceTooltip(self)
        bar = ttk.Scrollbar(batch_sources, orient="vertical", command=self.source.yview)
        self.source_scrollbar = bar
        bar.bind("<Button-1>", lambda _event: self.source_tooltip.hide_hover(), add="+")
        self.source.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.source.pack(fill="x", expand=True, pady=(6, 0))
        source_inner = ttk.Frame(self.source)
        self.source.create_window((0, 0), window=source_inner, anchor="nw")
        source_inner.bind("<Configure>", lambda _event: self.source.configure(scrollregion=self.source.bbox("all")))
        self.source_vars = []
        self.source_checks = []
        self.source_preview_buttons = []
        for index, item in enumerate(self.records):
            text = item.get("question", "") if self.framework == "tc" else item.get("prompt", "")
            summary = " ".join(text.split())[:160]
            var = tk.BooleanVar(value=True)
            row = ttk.Frame(source_inner)
            row.pack(anchor="w")
            preview = ttk.Button(row, text="查看全文", command=lambda value=text: self.source_tooltip.show_persistent(value))
            preview.pack(side="left", padx=(0, 4))
            self.source_preview_buttons.append(preview)
            source_label = item.get("riskId", "")
            check = ttk.Checkbutton(row, text=f"{index + 1:03d}  {source_label}  {summary}",
                                    variable=var, command=self._selection_changed)
            check.pack(side="left")
            self.source_vars.append(var)
            self.source_checks.append(check)
            self.source_tooltip.attach(check, text)
            check.bind("<MouseWheel>", self._scroll_sources)
            preview.bind("<MouseWheel>", self._scroll_sources)
            row.bind("<MouseWheel>", self._scroll_sources)
        source_inner.bind("<MouseWheel>", self._scroll_sources)
        self.source.bind("<MouseWheel>", self._scroll_sources)

        select = ttk.LabelFrame(self, text="2. 选择攻击方式", padding=8)
        select.pack(fill="x", padx=10, pady=8)
        self.strategy_select = select
        self.open_strategy_group = None
        self.strategy_group_buttons = {}
        self.strategy_group_panels = {}
        self.strategy_group_canvases = {}
        self.selected_strategies = {}
        self.strategy_checks = []
        self.group_buttons = []
        groups = ("基础规则", "直接指令", _MODEL_GROUP)
        for column, group in enumerate(groups):
            group_button = ttk.Button(select, text=f"{group}（已选 0） ▾",
                                      command=lambda g=group: self._toggle_strategy_dropdown(g))
            select.columnconfigure(column, weight=1, uniform="strategies")
            group_button.grid(row=0, column=column, sticky="ew", padx=4)
            self.strategy_group_buttons[group] = group_button
            self.group_buttons.append(group_button)
            inline = group == _MODEL_GROUP
            panel = ttk.Frame(self, relief="solid", borderwidth=1, padding=4 if inline else 0)
            self.strategy_group_panels[group] = panel
            if inline:
                # 模型策略只有三项，横向排在参数上方，展开时仍保留结果区的空间。
                section = panel
            else:
                # 规则选项较多，继续用带滚动的浮层展示。
                canvas = tk.Canvas(panel, height=170, highlightthickness=0)
                self.strategy_group_canvases[group] = canvas
                scroll = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
                canvas.configure(yscrollcommand=scroll.set)
                scroll.pack(side="right", fill="y")
                canvas.pack(side="left", fill="both", expand=True)
                inner = ttk.Frame(canvas)
                canvas.create_window((0, 0), window=inner, anchor="nw")
                inner.bind("<Configure>", lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")))
                section = ttk.LabelFrame(inner, text=group, padding=4)
                section.pack(fill="x", pady=3)
            items = [item for item in self.specs if item.get("group") == group]
            toolbar = ttk.Frame(section)
            toolbar.grid(row=0, column=0, columnspan=1 if inline else 3, sticky="w")
            for title, selected in (("全选", True), ("清空", False)):
                button = ttk.Button(toolbar, text=title, command=lambda g=group, value=selected: self._set_group(g, value))
                button.pack(side="left", padx=3)
                self.group_buttons.append(button)
            for i, item in enumerate(items):
                var = tk.BooleanVar(value=False)
                self.selected_strategies[item["id"]] = var
                var.trace_add("write", self._update_strategy_dropdown_label)
                check = ttk.Checkbutton(section, text=f"{item['id']}  {item['name']}", variable=var,
                                        command=self._selection_changed)
                row, check_column = (0, i + 1) if inline else (i // 3 + 1, i % 3)
                check.grid(row=row, column=check_column, sticky="w", padx=8, pady=2)
                self.strategy_checks.append(check)
        def bind_scroll(widget, canvas):
            widget.bind("<MouseWheel>", lambda event, c=canvas: self._scroll_strategies(event, c))
            for child in widget.winfo_children():
                bind_scroll(child, canvas)
        for group, canvas in self.strategy_group_canvases.items():
            bind_scroll(self.strategy_group_panels[group], canvas)
        self.bind("<Button-1>", self._dismiss_strategy_dropdown, add="+")
        self.bind("<Configure>", self._position_strategy_dropdown, add="+")
        tools = ttk.Frame(self, padding=(10, 0))
        tools.pack(fill="x")
        self.strategy_tools = tools
        tools.bind("<Configure>", lambda _event: self._position_strategy_dropdown())
        self.estimate = tk.StringVar()
        ttk.Label(tools, textvariable=self.estimate).pack(side="left")
        self.generate_button = ttk.Button(tools, text="生成变种", command=self._generate)
        self.generate_button.pack(side="right")
        self.model_cancel_button = ttk.Button(tools, text="取消生成", command=self._cancel_model_generation,
                                               state="disabled")

        result = ttk.LabelFrame(self, text="3. 变种结果（选择一行查看完整内容）", padding=8)
        result.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree = ttk.Treeview(result, columns=("source", "strategy", "status", "reason"), show="headings", height=6)
        for name, title, width in (("source", "原题序号", 85), ("strategy", "策略", 200),
                                   ("status", "状态", 85), ("reason", "原因", 400)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, stretch=name == "reason")
        yscroll = ttk.Scrollbar(result, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        self.detail = tk.Text(result, height=5, wrap="word", state="disabled")
        self.detail.pack(side="bottom", fill="x", pady=(6, 0))
        self.tree.pack(fill="both", expand=True)
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(before=result, side="bottom", fill="x")
        self.with_images = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="同时生成文字图片", variable=self.with_images).pack(side="left")
        ttk.Label(bottom, text="R09、R19 不可见字符不生成图片，Excel 保留完整文本").pack(side="left", padx=8)
        self.copy_button = ttk.Button(bottom, text="复制选中变种", command=self._copy, state="disabled")
        self.copy_button.pack(side="right")
        self.export_button = ttk.Button(bottom, text="导出原题与变种 Excel", command=self._export, state="disabled")
        self.export_button.pack(side="right", padx=8)
        self.open_button = ttk.Button(bottom, text="打开变种 Excel", command=self._open_export, state="disabled")
        self.open_button.pack(side="right")
        self._update_estimate()

    def _selected(self):
        return [index for index, var in enumerate(self.source_vars) if var.get()], [key for key, var in self.selected_strategies.items() if var.get()]

    def _generation_selection(self):
        sources, strategies = self._selected()
        rule_strategies = [key for key in strategies if key not in self.model_strategy_ids]
        model_strategies = [key for key in strategies if key in self.model_strategy_ids]
        return sources, rule_strategies, model_strategies

    def _can_generate(self, sources, rules, models):
        return not self.busy and bool(sources) and bool(rules or models) and (not models or self.model_ready)

    def _scroll_sources(self, event):
        self.source_tooltip.hide_hover()
        self.source.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _select_sources(self, select):
        for var in self.source_vars:
            var.set(select)
        self._selection_changed()

    def _update_strategy_dropdown_label(self, *_args):
        for group, button in self.strategy_group_buttons.items():
            count = sum(self.selected_strategies[item["id"]].get() for item in self.specs
                        if item["group"] == group and item["id"] in self.selected_strategies)
            button.configure(text=f"{group}（已选 {count}） ▾")

    def _toggle_strategy_dropdown(self, group):
        if self.busy:
            return
        previous = self.open_strategy_group
        self._close_strategy_dropdown()
        if previous == group:
            return
        self.open_strategy_group = group
        panel = self.strategy_group_panels[group]
        if group == _MODEL_GROUP:
            panel.pack(after=self.strategy_select, fill="x", padx=10, pady=(0, 6))
        else:
            self.update_idletasks()
            self._position_strategy_dropdown()
            panel.lift()

    def _position_strategy_dropdown(self, event=None):
        if self.open_strategy_group in self.strategy_group_canvases and (event is None or event.widget is self):
            tools_bottom = self.strategy_tools.winfo_rooty() + self.strategy_tools.winfo_height()
            y = tools_bottom - self.winfo_rooty()
            height = 175
            if self.export_button.winfo_ismapped():
                height = min(height, max(1, self.export_button.winfo_rooty() - tools_bottom - 2))
            self.strategy_group_panels[self.open_strategy_group].place(
                x=10, y=y, width=max(1, self.winfo_width() - 20), height=height)

    def _scroll_strategies(self, event, canvas):
        canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _close_strategy_dropdown(self):
        if self.open_strategy_group:
            panel = self.strategy_group_panels[self.open_strategy_group]
            if self.open_strategy_group == _MODEL_GROUP:
                panel.pack_forget()
            else:
                panel.place_forget()
        self.open_strategy_group = None

    def _dismiss_strategy_dropdown(self, event):
        if not self.open_strategy_group:
            return
        widget = str(event.widget)
        section_widgets = (self.strategy_select, self.strategy_group_panels[self.open_strategy_group])
        if not any(widget.startswith(str(section)) for section in section_widgets):
            self._close_strategy_dropdown()

    def _set_group(self, group, selected):
        for item in self.specs:
            if item.get("group") == group:
                self.selected_strategies[item["id"]].set(selected)
        self._selection_changed()

    def _selection_changed(self):
        """保留上次结果，并提示它不一定对应当前选择。"""
        if hasattr(self, "tree") and self.rows:
            self.tree.master.configure(text="3. 上次生成结果（选择已更改，点击生成变种更新）")
        if hasattr(self, "generate_button"):
            self._update_estimate()

    def _update_estimate(self):
        sources, rules, models = self._generation_selection()
        total = len(sources) * (len(rules) + len(models))
        estimate = f"已选 {len(sources)} 道原题、{len(rules) + len(models)} 种策略，最多 {total} 条变种"
        if models:
            if not self.model_cancel_button.winfo_manager():
                self.model_cancel_button.pack(side="right", padx=(0, 8))
            if self.model_ready:
                estimate += f"，最多 {len(sources) * len(models)} 次模型请求"
            else:
                estimate += "。请先在设置中配置文本模型，再重新打开此窗口"
        else:
            self.model_cancel_button.pack_forget()
        self.estimate.set(estimate)
        self.generate_button.state(["!disabled"] if self._can_generate(sources, rules, models) else ["disabled"])

    def _checkpoint(self):
        if self.cancel.is_set():
            raise InterruptedError("用户取消")

    def _set_selection_enabled(self, enabled):
        state = "!disabled" if enabled else "disabled"
        for control in (self.select_all_button, self.clear_button, *self.source_checks, *self.group_buttons,
                        *self.strategy_checks):
            control.state([state])

    def _run(self, task):
        self.busy = True
        self.cancel.clear()
        if hasattr(self, "_close_strategy_dropdown"):
            self._close_strategy_dropdown()
        self._set_selection_enabled(False)
        self.generate_button.state(["disabled"])
        self.export_button.state(["disabled"])
        def runner():
            try:
                self.tasks.put(("ok", task()))
            except Exception as error:
                self.tasks.put(("error", str(error)))
        # 非 daemon 线程允许进程关闭时完成 finally 中的暂存目录清理。
        threading.Thread(target=runner, daemon=False).start()

    def _generate(self):
        from strategy_engine import apply_strategy

        sources, rules, models = self._generation_selection()
        if not self._can_generate(sources, rules, models):
            return
        records = [dict(item) for item in self.records]
        planned_surfaces = list(self.planned_surfaces)
        self.generate_button.configure(text="正在生成变种…")
        if self.rows:
            self.tree.master.configure(text="3. 上次生成结果（正在生成新结果）")
        else:
            self.tree.master.configure(text="3. 正在生成变种…")
        transform = None
        if models:
            from strategy_model import apply_model_strategy

            transform = partial(apply_model_strategy, settings=dict(self.model_settings),
                                checkpoint=self._checkpoint)
            self.model_cancel_button.state(["!disabled"])

        def progress(completed):
            self.tasks.put(("progress", (completed, len(sources) * len(models))))

        def task():
            if not models:
                rows = make_variant_rows(records, sources, rules, self.framework, apply_strategy,
                                         self._checkpoint, planned_surfaces)
                self._checkpoint()
                return "generated", rows

            def convert(strategy, text, *, language):
                if strategy in self.model_strategy_ids:
                    return transform(strategy, text, language=language)
                return apply_strategy(strategy, text, language=language)

            rows = make_variant_rows(records, sources, [*rules, *models], self.framework, convert,
                                     self._checkpoint, planned_surfaces,
                                     model_strategy_ids=self.model_strategy_ids, progress=progress)
            self._checkpoint()
            return "generated", rows

        self._run(task)

    def _cancel_model_generation(self):
        self.cancel.set()
        self.model_cancel_button.state(["disabled"])
        self.generate_button.configure(text="正在取消…")

    def _show_detail(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        row = self.rows[int(selection[0])]
        status = self._status_label(row)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", f"【原题】{row['originalText']}\n\n【变种】{row['variantText']}\n\n【状态】{status} {row['reason']}")
        self.detail.configure(state="disabled")
        self.copy_button.state(["!disabled"] if row["variantText"] else ["disabled"])

    def _copy(self):
        selection = self.tree.selection()
        if selection:
            value = self.rows[int(selection[0])]["variantText"]
            self.clipboard_clear()
            self.clipboard_append(value)

    def _export(self):
        import storage
        import text_image_renderer
        from strategy_export import export_strategy_xlsx
        try:
            config = text_image_renderer.load_text_image_config(storage.load_settings()) if self.with_images.get() else None
        except Exception as error:
            messagebox.showerror("图片设置不可用", str(error), parent=self)
            return
        rows = [dict(row) for row in self.rows]
        specs = {item["id"]: dict(item) for item in self.specs}
        def task():
            self._checkpoint()
            staging = Path(tempfile.mkdtemp(prefix=".strategy-", dir=self.batch_dir))
            final = self.batch_dir / ("strategy-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            try:
                summary = export_strategy_xlsx(staging / "strategy_variants.xlsx", rows,
                                               text_image_config=config, output_dir=final, checkpoint=self._checkpoint)
                self._checkpoint()
                manifest = {"schemaVersion": 1, "batchId": self.batch_dir.name, "framework": self.framework,
                            "strategies": [specs[key] for key in dict.fromkeys(
                                row["strategyId"] for row in rows if row["strategyId"] != "basic")],
                            "counts": {status: sum(row["status"] == status for row in rows)
                                       for status in ("basic", "generated", "skipped", "failed")},
                            "images": summary,
                            "results": rows}
                (staging / "strategy_variants.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self._checkpoint()
                staging.rename(final)
                return "exported", (str(final / "strategy_variants.xlsx"), summary)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        self._run(task)

    def _open_export(self):
        """只打开本窗口成功发布且仍位于当前批次下的 Excel。"""
        try:
            path = Path(self.last_export).resolve(strict=True)
            path.relative_to(self.batch_dir.resolve(strict=True))
            if not path.is_file() or not hasattr(os, "startfile"):
                raise OSError("当前系统无法打开该 Excel。")
            os.startfile(path)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("无法打开", str(error), parent=self)

    def _poll(self):
        self._poll_after = None
        try:
            status, value = self.tasks.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self._poll_after = self.after(100, self._poll)
            return
        if status == "progress":
            if not self.cancel.is_set():
                completed, total = value
                self.generate_button.configure(text=f"正在生成变种（{completed}/{total}）…")
            self._poll_after = self.after(100, self._poll)
            return
        if status == "ok" and value[0] == "generated" and self.cancel.is_set():
            status, value = "error", "用户取消"
        self.model_cancel_button.state(["disabled"])
        if status == "error":
            if self.rows:
                self.tree.master.configure(text="3. 上次生成结果（本次生成未完成）")
            else:
                self.tree.master.configure(text="3. 变种结果（本次生成未完成）")
            if value != "用户取消":
                messagebox.showerror("变种操作失败", value, parent=self)
        elif value[0] == "generated":
            self.rows = value[1]
            self.last_export = None
            self.open_button.state(["disabled"])
            self.tree.master.configure(text="3. 正在显示变种结果…")
            self.tree.delete(*self.tree.get_children())
            self.detail.configure(state="normal")
            self.detail.delete("1.0", tk.END)
            self.detail.configure(state="disabled")
            self.copy_button.state(["disabled"])
            self._rendering = True
            self.generate_button.configure(text="正在显示结果…")
            self._render_rows(0)
            return
        else:
            path, summary = value[1]
            self.last_export = path
            self.open_button.state(["!disabled"])
            image_note = (f"文字图片：成功 {summary.get('imagesSucceeded', 0)}，"
                          f"失败 {summary.get('imagesFailed', 0)}，"
                          f"未生成 {summary.get('imagesSkipped', 0)}")
            messagebox.showinfo("导出完成", f"已保存：\n{path}\n\n{image_note}", parent=self)
        self._finish_task()

    def _render_rows(self, start):
        """分批向表格写入结果，让界面在大量原题时保持响应。"""
        self._render_after = None
        end = min(start + 200, len(self.rows))
        for index in range(start, end):
            row = self.rows[index]
            row["strategyName"] = self.names.get(row["strategyId"], row["strategyName"])
            status = self._status_label(row)
            self.tree.insert("", "end", iid=str(index), values=(row["sourceIndex"], row["strategyName"], status, row["reason"]))
        if end < len(self.rows):
            self.tree.master.configure(text=f"3. 正在显示变种结果（{end}/{len(self.rows)}）")
            self._render_after = self.after(1, lambda: self._render_rows(end))
        else:
            self._rendering = False
            self.tree.master.configure(text="3. 变种结果（选择一行查看完整内容）")
            self._finish_task()

    def _finish_task(self):
        self.busy = False
        self.generate_button.configure(text="生成变种")
        self._set_selection_enabled(True)
        self._update_estimate()
        if self.rows:
            self.export_button.state(["!disabled"])
        if self.winfo_exists():
            self._poll_after = self.after(100, self._poll)

    def _status_label(self, row):
        status = row["status"]
        return _MODEL_STATUS_LABELS.get(status, status) if row.get("reviewStatus") == "" else status

    def _close(self):
        if self._rendering:
            self.destroy()
            return
        if self.busy:
            self.cancel.set()
            messagebox.showinfo("正在停止", "已请求停止，请稍候操作结束。", parent=self)
            return
        self.destroy()
