"""功能:
  提供 GenerateTestQuestion 桌面端：TC260 生成、LLM 提示词、Agentic 题集、来源管理、设置五个工作区。
  TC260 以“爬取网站 → 模型出题”为主流程；OWASP 复用设置页模型生成可复制测试提示词，
  不读取网站、不调用爬虫或被测系统。TC260 题目形式仍支持文本对话题和图片生成题。
实现:
  Tkinter 构建五页；TC260 和 OWASP 使用独立后台批次及完成事件，事件经 queue.Queue 投递，
  主线程 after 轮询刷新日志；来源核验异步执行并同步网站名单/核验日志。
输入: data/sources.json、data/settings.json、data/risk_catalog.json，以及内置 OWASP 风险目录。
输出: data/output/<批次>/（TC260 题目或 OWASP 提示词 JSON / Excel、留痕）、data/reports/（名单与核验日志）、
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
import tempfile
from PIL import Image, ImageOps, ImageTk
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import BOTTOM, E, END, HORIZONTAL, LEFT, NW, RIGHT, VERTICAL, W, X, Y, filedialog, messagebox, ttk
import tkinter as tk

import crawler
import owasp_pipeline
import pipeline
import question_generator
import reporting
import storage
from agentic_workspace import AgenticWorkspace
from generation_control import GenerationCancelled, GenerationControl, seal
from prompt_widgets import configure_prompt_columns
from owasp_catalog import AGENTIC_FRAMEWORK, AGENTIC_RISKS
from owasp_prompt_generator import OWASP_RISKS, PROMPT_RECORD_KEYS, validate_prompt_records

PROJECT_ROOT = storage.PROJECT_ROOT  # 冻结为 exe 时即 exe 所在目录
WORKSPACES = ("生成", "OWASP 红队提示词", "OWASP Agentic 题集", "来源管理", "设置")
FONT = "Microsoft YaHei UI"


class DesktopApplication(tk.Tk):
    """主窗口：只在主线程更新 UI，爬取/出题/核验统一放后台线程。"""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"GenerateTestQuestion v{storage.APP_VERSION}｜TC260 / OWASP 测试提示集")
        self.geometry("1280x900")
        self.minsize(1020, 720)
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self._generation = None
        self._generation_kind = ""
        self._image_test_in_progress = False
        self.current_questions: list[dict] = []
        self.current_batch_dir = ""
        self.current_xlsx = ""
        self.owasp_records: list[dict[str, str]] = []
        self.owasp_batch_dir = ""
        self.owasp_json = ""
        self.owasp_xlsx = ""
        self.site_vars: dict[str, tk.BooleanVar] = {}
        self.site_language: dict[str, str] = {}
        self.site_group_widgets: dict[str, dict] = {}
        self.scene_vars: dict[str, tk.StringVar] = {}
        self.risk_vars: dict[str, tk.BooleanVar] = {}
        self.scene_widgets: dict[str, dict] = {}
        self._generate_widgets: list[tk.Widget] = []
        self.owasp_risk_vars: dict[str, tk.BooleanVar] = {}
        self._owasp_generate_widgets: list[tk.Widget] = []
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
        self._configure_chip_styles(style)

    @staticmethod
    def _configure_chip_styles(style: ttk.Style) -> None:
        """多选卡片样式（对齐 docs/prototype-multiselect.html 原型）：
        选中整块浅蓝高亮、指示器变蓝底白勾；大类标题条用浅灰底。"""
        accent, tint, ink, soft = "#1F5FBF", "#E8F1FD", "#14406E", "#5B6573"
        head_bg, head_active = "#F2F5F9", "#E7EDF5"
        style.configure("Chip.TCheckbutton", font=(FONT, 9), padding=(7, 4))
        style.map("Chip.TCheckbutton",
                  background=[("selected", tint), ("active", "#F2F6FB")],
                  foreground=[("selected", ink)],
                  indicatorbackground=[("selected", accent), ("pressed", accent)],
                  indicatorforeground=[("selected", "#FFFFFF")])
        style.configure("SceneHead.TFrame", background=head_bg)
        style.configure("SceneHead.TCheckbutton", font=(FONT, 9), padding=(4, 3),
                        background=head_bg)
        style.map("SceneHead.TCheckbutton",
                  background=[("selected", head_bg), ("active", head_active),
                              ("pressed", head_active)],
                  indicatorbackground=[("selected", accent), ("pressed", accent)],
                  indicatorforeground=[("selected", "#FFFFFF")])
        style.configure("SceneHead.TLabel", background=head_bg, foreground="#17365D",
                        font=(FONT, 10, "bold"))
        style.configure("SceneCount.TLabel", background=head_bg, foreground=soft, font=(FONT, 9))
        style.configure("GroupLabel.TLabel", font=(FONT, 9, "bold"), foreground=soft)

    def _create_layout(self) -> None:
        header = ttk.Frame(self, padding=(20, 14, 20, 6))
        header.pack(fill=X)
        ttk.Label(header, text="GenerateTestQuestion", style="Title.TLabel").pack(side=LEFT)
        ttk.Label(header, text="爬取网站 → 生成题目（测试提示集）", style="Subtle.TLabel").pack(side=LEFT, padx=14)
        ttk.Button(header, text="刷新数据", command=self._refresh_all).pack(side=RIGHT)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.generate_tab = ttk.Frame(self.notebook, padding=12)
        self.owasp_tab = ttk.Frame(self.notebook, padding=12)
        self.agentic_tab = ttk.Frame(self.notebook, padding=12)
        self.sources_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        for name, tab in zip(
            WORKSPACES,
            [self.generate_tab, self.owasp_tab, self.agentic_tab, self.sources_tab, self.settings_tab],
            strict=True,
        ):
            self.notebook.add(tab, text=name)
        for index in range(len(WORKSPACES)):
            self.bind(f"<Control-Key-{index + 1}>",
                      lambda event, page=index: self.notebook.select(page))
        self._build_generate_tab()
        self._build_owasp_tab()
        self.agentic_page = AgenticWorkspace(self)
        self._build_sources_tab()
        self._build_settings_tab()

        self.status_text = tk.StringVar(value="正在读取项目数据…")
        ttk.Label(self, textvariable=self.status_text, anchor=W, style="Subtle.TLabel",
                  padding=(20, 6)).pack(fill=X)

    # ------------------------------------------------------------------ 生成页
    def _make_scrollable(self, parent: tk.Widget) -> ttk.Frame:
        """把一页内容包进可垂直滚动的 Canvas：内容超出一屏时出现滚动条；
        内容高度按各区块的请求高度计算，不挤压日志和对照区。"""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vbar = ttk.Scrollbar(outer, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill="both", expand=True)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor=NW)

        def sync(_event=None) -> None:
            if canvas.winfo_width() <= 1:
                return  # 尚未完成首次布局
            canvas.itemconfigure(window_id, width=canvas.winfo_width())
            canvas.itemconfigure(window_id, height=max(inner.winfo_reqheight(), canvas.winfo_height()))
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", sync)
        canvas.bind("<Configure>", sync)
        if parent is self.owasp_tab:
            self._owasp_page_inner = inner
            self._owasp_page_canvas = canvas
        elif parent is self.agentic_tab:
            self._agentic_page_inner = inner
            self._agentic_page_canvas = canvas
        else:
            self._page_sync = sync
            self._page_inner = inner
            self._page_canvas = canvas
        return inner

    def _bind_page_wheel(self, canvas: tk.Canvas, scroll_widgets: tuple[tk.Widget, ...] | None = None) -> None:
        """页内控件优先接收滚轮，到边界后再将同方向滚轮交给整页。"""
        if scroll_widgets is None:
            scroll_widgets = (self.log_text, self.question_tree, self.detail_text)

        def on_wheel(event) -> str | None:
            if not canvas.winfo_ismapped() or event.state & 0x0001:
                return  # Shift+滚轮保持原有横向滚动语义
            if event.num in (4, 5):
                units = -1 if event.num == 4 else 1
            elif event.delta:
                units = max(1, abs(event.delta) // 120) * (-1 if event.delta > 0 else 1)
            else:
                return

            widget = event.widget
            inner_scroll = None
            while widget is not canvas:
                if widget is None or isinstance(widget, (tk.Toplevel, ttk.Spinbox)):
                    return  # 不接管其他窗口、工作区或数字输入框的滚轮
                if inner_scroll is None and isinstance(widget, (tk.Text, ttk.Treeview)):
                    inner_scroll = widget
                widget = widget.master

            if inner_scroll is not None:
                first, last = inner_scroll.yview()
                if (units < 0 and first > 0.0) or (units > 0 and last < 1.0):
                    return  # 内层还有内容，继续执行控件原生滚动绑定
            first, last = canvas.yview()
            if (units < 0 and first <= 0.0) or (units > 0 and last >= 1.0):
                return
            canvas.yview_scroll(units, "units")
            return "break"

        def on_page_wheel(event) -> str | None:
            # 内层已在原生类绑定之前检查边界，不能在 bind_all 阶段再滚一次页面。
            if event.widget not in scroll_widgets:
                return on_wheel(event)

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind_all(sequence, on_page_wheel, add=True)
            for widget in scroll_widgets:
                widget.bind(sequence, on_wheel, add=True)

    def _build_generate_tab(self) -> None:
        page = self._make_scrollable(self.generate_tab)
        site_frame = ttk.LabelFrame(page, text="1. 选择网站（已核验可爬）", style="Card.TLabelframe")
        site_frame.pack(fill=X)
        toolbar = ttk.Frame(site_frame)
        toolbar.pack(fill=X, pady=(0, 4))
        ttk.Label(toolbar, text="仅列出核验状态为“可爬”的站点；新增与核验请到“来源管理”。",
                  style="Subtle.TLabel").pack(side=LEFT)
        for text, command in (("全选", lambda: self._select_sites(None, True)),
                              ("清空", lambda: self._select_sites(None, False)),
                              ("全选中文", lambda: self._select_sites("zh", True)),
                              ("全选英文", lambda: self._select_sites("en", True))):
            ttk.Button(toolbar, text=text, width=8, command=command).pack(side=RIGHT, padx=(6, 0))
        self.site_badge = ttk.Label(toolbar, text="已选 0/0", style="Subtle.TLabel")
        self.site_badge.pack(side=RIGHT, padx=(0, 10))
        self.site_group_zh = ttk.Frame(site_frame)
        self.site_group_zh.pack(fill=X)
        self.site_group_en = ttk.Frame(site_frame)
        self.site_group_en.pack(fill=X)

        type_frame = ttk.LabelFrame(page, text="2. 题目类型（参照 TC260，大类→小类）", style="Card.TLabelframe")
        type_frame.pack(fill=X, pady=(8, 0))
        type_toolbar = ttk.Frame(type_frame)
        type_toolbar.pack(fill=X)
        ttk.Label(type_toolbar, text="点大类标题展开／收起小类；三态框整组勾选，收起时徽章仍显示已选数。",
                  style="Subtle.TLabel").pack(side=LEFT)
        ttk.Button(type_toolbar, text="全选", width=8,
                   command=self._select_all_risks).pack(side=RIGHT, padx=(6, 0))
        ttk.Button(type_toolbar, text="清空", width=8,
                   command=self._clear_all_risks).pack(side=RIGHT, padx=(6, 0))
        self.risk_badge = ttk.Label(type_toolbar, text="已选 0/0", style="Subtle.TLabel")
        self.risk_badge.pack(side=RIGHT, padx=(0, 10))
        self.scenes_area = ttk.Frame(type_frame)
        self.scenes_area.pack(fill=X)

        options = ttk.LabelFrame(page, text="3. 本次生成", style="Card.TLabelframe")
        options.pack(fill=X, pady=(8, 0))
        self.question_type_var = tk.StringVar(value=storage.load_settings().get("questionType", "text"))
        self.text_image_enabled_var = tk.BooleanVar(value=False)
        self.total_var = tk.StringVar(value="50")
        self.zh_var = tk.StringVar(value="80")
        mode_row = ttk.Frame(options)
        mode_row.grid(row=0, column=0, columnspan=7, sticky=W, pady=(4, 2))
        ttk.Label(mode_row, text="题目形式").pack(side=LEFT, padx=(0, 10))
        self.text_mode_radio = ttk.Radiobutton(
            mode_row, text="文本对话题（测文本模型）", value="text",
            variable=self.question_type_var, command=self._update_selection_summary)
        self.text_mode_radio.pack(side=LEFT)
        self.image_mode_radio = ttk.Radiobutton(
            mode_row, text="图片生成题（测文生图模型）", value="image",
            variable=self.question_type_var, command=self._update_selection_summary)
        self.image_mode_radio.pack(side=LEFT, padx=(18, 0))
        self.text_image_check = ttk.Checkbutton(mode_row, text="同时生成文字图片", variable=self.text_image_enabled_var)
        self.text_image_check.pack(side=LEFT, padx=(18, 0))
        ttk.Label(options, text="生成数量").grid(row=1, column=0, sticky=W, padx=(0, 4), pady=4)
        total_spin = ttk.Spinbox(options, from_=1, to=1000, textvariable=self.total_var, width=8)
        total_spin.grid(row=1, column=1, sticky=W, padx=(0, 14))
        ttk.Label(options, text="中文占比").grid(row=1, column=2, sticky=W, padx=(0, 4))
        zh_spin = ttk.Spinbox(options, from_=0, to=100, textvariable=self.zh_var, width=6)
        zh_spin.grid(row=1, column=3, sticky=W, padx=(0, 4))
        ttk.Label(options, text="%", style="Subtle.TLabel").grid(row=1, column=4, sticky=W)
        self.selection_summary = ttk.Label(options, text="当前：0 个网站 · 0/0 个小类",
                                           style="Subtle.TLabel")
        self.selection_summary.grid(row=1, column=5, sticky=E, padx=(8, 0))
        self.start_button = ttk.Button(options, text="开始生成", style="Accent.TButton",
                                       command=self._start_batch)
        self.start_button.grid(row=1, column=6, sticky="e", padx=(20, 0))
        self.stop_button = ttk.Button(options, text="停止生成", state="disabled",
                                      command=lambda: self._stop_generation("batch"))
        self.stop_button.grid(row=1, column=7, padx=(8, 0))
        options.columnconfigure(5, weight=1)
        self.go_hint = ttk.Label(options, text="", style="Subtle.TLabel")
        self.go_hint.grid(row=2, column=0, columnspan=7, sticky=W, pady=(0, 2))
        self._generate_widgets = [total_spin, zh_spin, self.text_mode_radio,
                                  self.image_mode_radio, self.text_image_check, self.start_button]

        # 两个区块各自保留阅读高度，让外层 Canvas 承担页面溢出，不再靠拖分隔条分配空间。
        log_frame = ttk.LabelFrame(page, text="4. 运行日志", style="Card.TLabelframe")
        log_frame.pack(fill=X, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=8, wrap="word", font=(FONT, 9), state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=LEFT, fill="both", expand=True)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.tag_configure("warn", foreground="#8a6d00")
        self.log_text.tag_configure("error", foreground="#a4262c")

        compare = ttk.LabelFrame(page, text="5. 原文 ↔ 题目对照", style="Card.TLabelframe")
        compare.pack(fill=X, pady=(8, 0))
        paned = ttk.PanedWindow(compare, orient=HORIZONTAL, height=360)
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, width=480)
        right = ttk.Frame(paned, width=720)
        # 保持初始 2:3 阅读宽度，避免题干的 1200 像素长列把右侧原文挤出可视区。
        left.pack_propagate(False)
        right.pack_propagate(False)
        paned.add(left, weight=2)
        paned.add(right, weight=3)
        self.question_tree = ttk.Treeview(left, columns=("seq", "risk", "digest"), show="headings", height=9)
        for column, title, width in (("seq", "序号", 46), ("risk", "小类", 64), ("digest", "题干摘要", 1200)):
            self.question_tree.heading(column, text=title)
            # 题干摘要列装全文：窗口不够宽时用横向滚动条查看剩余内容
            self.question_tree.column(column, width=width, minwidth=46 if column == "seq" else 64,
                                      anchor=W, stretch=column == "digest")
        self.question_tree.bind("<<TreeviewSelect>>", self._on_question_selected)
        tree_scroll = ttk.Scrollbar(left, orient=VERTICAL, command=self.question_tree.yview)
        x_scroll = ttk.Scrollbar(left, orient=HORIZONTAL, command=self.question_tree.xview)
        self.question_tree.configure(yscrollcommand=tree_scroll.set, xscrollcommand=x_scroll.set)
        x_scroll.pack(side=BOTTOM, fill=X)
        tree_scroll.pack(side=RIGHT, fill=Y)
        self.question_tree.pack(side=LEFT, fill="both", expand=True)
        self.detail_text = tk.Text(right, wrap="word", font=(FONT, 9), state="disabled")
        detail_scroll = ttk.Scrollbar(right, orient=VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side=LEFT, fill="both", expand=True)
        detail_scroll.pack(side=RIGHT, fill=Y)

        actions = ttk.Frame(page)
        actions.pack(fill=X, pady=(6, 0))
        ttk.Button(actions, text="加载历史批次", command=self._load_history_batch).pack(side=LEFT)
        self.open_xlsx_button = ttk.Button(actions, text="打开题库 Excel", state="disabled",
                                           command=lambda: self._open_path(Path(self.current_xlsx)))
        self.open_xlsx_button.pack(side=RIGHT)
        self.open_batch_button = ttk.Button(actions, text="打开批次目录", state="disabled",
                                            command=lambda: self._open_path(Path(self.current_batch_dir)))
        self.open_batch_button.pack(side=RIGHT, padx=8)
        ttk.Button(actions, text="打开来源网页",
                   command=self._open_question_url).pack(side=RIGHT)
        self.bind("<Control-l>", lambda _event: self._load_history_batch())
        self._bind_page_wheel(self._page_canvas)

    # ------------------------------------------------------------------ OWASP 红队提示词
    def _build_owasp_tab(self, view=None) -> None:
        """用相同布局构建两套 OWASP 工作区，各自保存控件和结果。"""
        view = self if view is None else view
        agentic = view is not self
        risks = AGENTIC_RISKS if agentic else OWASP_RISKS
        kind = "agentic_batch" if agentic else "owasp_batch"
        title = "OWASP Agentic Top 10 2026 题集" if agentic else "OWASP LLM Top 10 2026 红队提示词"
        page = self._make_scrollable(self.agentic_tab if agentic else self.owasp_tab)
        usage = ttk.LabelFrame(page, text=title, style="Card.TLabelframe")
        usage.pack(fill=X)
        ttk.Label(
            usage,
            text="使用设置页模型按所选风险生成可复制测试提示词；不读取网站、不启动爬虫，也不自动发送给被测系统。",
            style="Subtle.TLabel",
        ).pack(anchor=W)
        ttk.Label(
            usage,
            text="单条记录复制 prompt。若有跨会话字段，先发送 userA，再将 userB 或 prompt 发给用户 B 一次。",
            style="Subtle.TLabel",
        ).pack(anchor=W, pady=(4, 0))

        risk_frame = ttk.LabelFrame(page, text="1. 选择 OWASP 风险", style="Card.TLabelframe")
        risk_frame.pack(fill=X, pady=(8, 0))
        risk_toolbar = ttk.Frame(risk_frame)
        risk_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(risk_toolbar, text="风险编号和风险名称会作为独立列随最终提示词导出。", style="Subtle.TLabel").pack(side=LEFT)
        clear_button = ttk.Button(risk_toolbar, text="清空", width=8, command=lambda: self._clear_owasp_risks(view))
        clear_button.pack(side=RIGHT, padx=(6, 0))
        all_button = ttk.Button(risk_toolbar, text="全选", width=8, command=lambda: self._select_all_owasp_risks(view))
        all_button.pack(side=RIGHT)
        view._owasp_generate_widgets.extend([clear_button, all_button])

        for index, risk in enumerate(risks):
            risk_id = risk["riskId"]
            variable = tk.BooleanVar(value=False)
            view.owasp_risk_vars[risk_id] = variable
            checkbutton = ttk.Checkbutton(
                risk_frame,
                text=f"{risk_id} · {risk['riskName']}  ({risk['englishName']})",
                variable=variable,
                command=lambda: self._update_owasp_selection_summary(view),
            )
            checkbutton.grid(row=1 + index // 2, column=index % 2, sticky=W, padx=(0, 28), pady=3)
            view._owasp_generate_widgets.append(checkbutton)

        options = ttk.LabelFrame(page, text="2. 本次生成", style="Card.TLabelframe")
        options.pack(fill=X, pady=(8, 0))
        view.owasp_total_var = tk.StringVar(value="10")
        view.owasp_language_var = tk.StringVar(value="中文")
        view.owasp_text_image_enabled_var = tk.BooleanVar(value=False)
        ttk.Label(options, text="生成数量").grid(row=0, column=0, sticky=W, padx=(0, 5), pady=4)
        total_spin = ttk.Spinbox(options, from_=1, to=1000, textvariable=view.owasp_total_var, width=8)
        total_spin.grid(row=0, column=1, sticky=W, padx=(0, 18))
        ttk.Label(options, text="输出语言").grid(row=0, column=2, sticky=W, padx=(0, 5))
        language_box = ttk.Combobox(
            options,
            textvariable=view.owasp_language_var,
            values=("中文", "英文", "中英混合"),
            width=10,
            state="readonly",
        )
        language_box.grid(row=0, column=3, sticky=W, padx=(0, 18))
        view.owasp_text_image_check = ttk.Checkbutton(options, text="同时生成文字图片",
                                                      variable=view.owasp_text_image_enabled_var)
        view.owasp_text_image_check.grid(row=0, column=4, sticky=W)
        view.owasp_selection_summary = ttk.Label(options, style="Subtle.TLabel")
        view.owasp_selection_summary.grid(row=1, column=0, columnspan=4, sticky=W, pady=(4, 0))
        view.owasp_go_hint = ttk.Label(options, style="Subtle.TLabel")
        view.owasp_go_hint.grid(row=2, column=0, columnspan=5, sticky=W, pady=(3, 0))
        view.owasp_start_button = ttk.Button(
            options,
            text="生成可复制提示词",
            style="Accent.TButton",
            command=lambda: self._start_owasp_batch(view),
        )
        view.owasp_start_button.grid(row=1, column=5, rowspan=2, sticky="e", padx=(18, 0))
        view.owasp_stop_button = ttk.Button(options, text="停止生成", state="disabled",
                                            command=lambda: self._stop_generation(kind))
        view.owasp_stop_button.grid(row=1, column=6, rowspan=2, sticky="e", padx=(8, 0))
        options.columnconfigure(4, weight=1)
        view._owasp_generate_widgets.extend([total_spin, language_box, view.owasp_text_image_check, view.owasp_start_button])

        log_frame = ttk.LabelFrame(page, text="3. 运行日志", style="Card.TLabelframe")
        log_frame.pack(fill=X, pady=(8, 0))
        view.owasp_log_text = tk.Text(log_frame, height=6, wrap="word", font=(FONT, 9), state="disabled")
        owasp_log_scroll = ttk.Scrollbar(log_frame, orient=VERTICAL, command=view.owasp_log_text.yview)
        view.owasp_log_text.configure(yscrollcommand=owasp_log_scroll.set)
        view.owasp_log_text.pack(side=LEFT, fill="both", expand=True)
        owasp_log_scroll.pack(side=RIGHT, fill=Y)
        view.owasp_log_text.tag_configure("warn", foreground="#8a6d00")
        view.owasp_log_text.tag_configure("error", foreground="#a4262c")

        result_frame = ttk.LabelFrame(page, text="4. 运行结果", style="Card.TLabelframe")
        result_frame.pack(fill="both", expand=True, pady=(8, 0))
        view.owasp_empty_result_var = tk.StringVar(value="尚未生成可复制提示词。")
        result_header = ttk.Frame(result_frame)
        result_header.pack(fill=X, pady=(0, 6))
        ttk.Label(result_header, textvariable=view.owasp_empty_result_var, style="Subtle.TLabel").pack(side=LEFT)
        view.open_owasp_xlsx_button = ttk.Button(
            result_header,
            text="打开题库 Excel",
            state="disabled",
            command=lambda: self._open_path(Path(view.owasp_xlsx)),
        )
        view.open_owasp_xlsx_button.pack(side=RIGHT)
        table_frame = ttk.Frame(result_frame)
        table_frame.pack(fill="both", expand=True)
        view.owasp_result_tree = ttk.Treeview(table_frame, columns=PROMPT_RECORD_KEYS, show="headings", height=16)
        configure_prompt_columns(view.owasp_result_tree)
        view.owasp_result_tree.bind("<Double-1>", lambda event: self._copy_owasp_clicked_cell(event, view))
        tree_scroll = ttk.Scrollbar(table_frame, orient=VERTICAL, command=view.owasp_result_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=HORIZONTAL, command=view.owasp_result_tree.xview)
        view.owasp_result_tree.configure(yscrollcommand=tree_scroll.set, xscrollcommand=x_scroll.set)
        x_scroll.pack(side=BOTTOM, fill=X)
        tree_scroll.pack(side=RIGHT, fill=Y)
        view.owasp_result_tree.pack(side=LEFT, fill="both", expand=True)

        actions = ttk.Frame(page)
        actions.pack(fill=X, pady=(6, 0))
        ttk.Label(actions, text="双击任意单元格即可复制。", style="Subtle.TLabel").pack(side=LEFT)
        view.open_owasp_json_button = ttk.Button(
            actions,
            text="打开 JSON",
            state="disabled",
            command=lambda: self._open_path(Path(view.owasp_json)),
        )
        view.open_owasp_json_button.pack(side=RIGHT, padx=(0, 8))
        view.open_owasp_batch_button = ttk.Button(
            actions,
            text="打开批次目录",
            state="disabled",
            command=lambda: self._open_path(Path(view.owasp_batch_dir)),
        )
        view.open_owasp_batch_button.pack(side=RIGHT, padx=(0, 8))
        view.owasp_copy_prompt_button = ttk.Button(
            actions,
            text="复制选中 prompt",
            state="disabled",
            command=lambda: self._copy_selected_owasp_prompt(view),
        )
        view.owasp_copy_prompt_button.pack(side=RIGHT, padx=(0, 8))
        # 数量和语言可由键盘或下拉框直接修改，不能只依赖风险复选框的 command。
        for variable in (view.owasp_total_var, view.owasp_language_var):
            variable.trace_add("write", lambda *_args: self._update_owasp_selection_summary(view))
        self._update_owasp_selection_summary(view)
        canvas = self._agentic_page_canvas if agentic else self._owasp_page_canvas
        self._bind_page_wheel(canvas, (view.owasp_log_text, view.owasp_result_tree))

    def _selected_owasp_risk_ids(self, view=None) -> list[str]:
        """按目录顺序返回当前被选择的风险，保证提交到受控生成器的输入可重现。"""
        view = self if view is None else view
        return [risk_id for risk_id, variable in view.owasp_risk_vars.items() if variable.get()]

    def _select_all_owasp_risks(self, view=None) -> None:
        """选择所有十项 OWASP 风险，不影响 TC260 小类勾选状态。"""
        view = self if view is None else view
        for variable in view.owasp_risk_vars.values():
            variable.set(True)
        self._update_owasp_selection_summary(view)

    def _clear_owasp_risks(self, view=None) -> None:
        """清空 OWASP 风险选择，不影响 TC260 小类勾选状态。"""
        view = self if view is None else view
        for variable in view.owasp_risk_vars.values():
            variable.set(False)
        self._update_owasp_selection_summary(view)

    def _update_owasp_selection_summary(self, view=None) -> None:
        """同步 OWASP 页的独立选择状态和可开始条件。"""
        view = self if view is None else view
        selected = self._selected_owasp_risk_ids(view)
        view.owasp_selection_summary.config(text=f"当前：{len(selected)}/{len(view.owasp_risk_vars)} 项风险 · {view.owasp_language_var.get()}")
        if self.running:
            view.owasp_start_button.state(["disabled"])
            return
        try:
            total = int(view.owasp_total_var.get())
        except ValueError:
            view.owasp_start_button.state(["disabled"])
            view.owasp_go_hint.config(text="生成数量必须是整数。", foreground="#A4262C")
            return
        if not selected:
            view.owasp_start_button.state(["disabled"])
            view.owasp_go_hint.config(text="请至少选择 1 项 OWASP 风险。", foreground="#A4262C")
        elif total < len(selected) or total > 1000:
            view.owasp_start_button.state(["disabled"])
            view.owasp_go_hint.config(text=f"生成数量必须在 {len(selected)} 至 1000 之间。", foreground="#A4262C")
        else:
            view.owasp_start_button.state(["!disabled"])
            view.owasp_go_hint.config(text="就绪：使用设置页模型生成提示词；不读取网站或自动调用被测系统。", foreground="#1E7A3C")

    def _start_owasp_batch(self, view=None) -> None:
        """启动独立的 OWASP 后台批次，事件类型绝不复用 TC260 的完成处理器。"""
        view = self if view is None else view
        if self.running:
            return
        risk_ids = self._selected_owasp_risk_ids(view)
        if not risk_ids:
            messagebox.showwarning("未选择风险", "请至少选择一项 OWASP 风险。", parent=self)
            return
        try:
            total = int(view.owasp_total_var.get())
        except ValueError:
            messagebox.showwarning("参数错误", "生成数量必须是整数。", parent=self)
            return
        if not (len(risk_ids) <= total <= 1000):
            messagebox.showwarning("数量错误", f"生成数量必须在 {len(risk_ids)} 至 1000 之间。", parent=self)
            return
        params = {"riskIds": risk_ids, "total": total, "language": view.owasp_language_var.get()}
        agentic = view is not self
        if agentic:
            params["framework"] = AGENTIC_FRAMEWORK
        if view.owasp_text_image_enabled_var.get():
            params["textImageEnabled"] = True
        settings = storage.load_settings()
        if any(type(settings.get(key)) is not str or not settings[key].strip() for key in ("baseUrl", "model")):
            messagebox.showwarning("缺少模型配置", "请先到“设置”页填写接口地址与模型名。", parent=self)
            return
        # 新批次确认可启动后立即撤下旧结果，避免运行期间误用上一次的产物。
        view.owasp_records = []
        view.owasp_batch_dir = ""
        view.owasp_json = ""
        view.owasp_xlsx = ""
        view.owasp_log_text.configure(state="normal")
        view.owasp_log_text.delete("1.0", END)
        view.owasp_log_text.configure(state="disabled")
        self._populate_owasp_result_tree(view)
        view.open_owasp_batch_button.state(["disabled"])
        view.open_owasp_json_button.state(["disabled"])
        view.open_owasp_xlsx_button.state(["disabled"])
        view.owasp_copy_prompt_button.state(["disabled"])
        self._launch_generation("agentic_batch" if agentic else "owasp_batch",
                                lambda *args: owasp_pipeline.run_batch(*args), params, settings,
                                "正在调用设置页模型生成 OWASP 可复制提示词…")

    def _finish_owasp_batch(self, done: dict, view=None) -> None:
        """消费专属 OWASP 完成事件；无效或失败数据不会进入六列表。"""
        view = self if view is None else view
        self.running = False
        self._sync_generation_busy()
        for widget in view._owasp_generate_widgets:
            widget.state(["!disabled"])
        self._update_selection_summary()
        self._update_owasp_selection_summary(view)
        if not done.get("ok"):
            view.owasp_records = []
            view.owasp_batch_dir = ""
            view.owasp_json = ""
            view.owasp_xlsx = ""
            self._populate_owasp_result_tree(view)
            view.open_owasp_batch_button.state(["disabled"])
            view.open_owasp_json_button.state(["disabled"])
            view.open_owasp_xlsx_button.state(["disabled"])
            view.owasp_copy_prompt_button.state(["disabled"])
            self._set_status("OWASP 提示词生成失败")
            self._append_log({"stage": "finish", "level": "error", "message": done.get("error", "未知错误")},
                             view.owasp_log_text)
            messagebox.showerror("OWASP 生成失败", done.get("error", "未知错误"), parent=self)
            return

        summary = done["summary"]
        view.owasp_batch_dir = summary.get("batchDir", "")
        view.open_owasp_batch_button.state(["!disabled"] if view.owasp_batch_dir else ["disabled"])
        if summary.get("status") != "completed":
            view.owasp_records = []
            view.owasp_json = ""
            view.owasp_xlsx = ""
            self._populate_owasp_result_tree(view)
            view.open_owasp_json_button.state(["disabled"])
            view.open_owasp_xlsx_button.state(["disabled"])
            view.owasp_copy_prompt_button.state(["disabled"])
            self._set_status("OWASP 提示词生成失败")
            self._append_log({"stage": "finish", "level": "error", "message": summary.get("error", "未生成可用提示词。")},
                             view.owasp_log_text)
            messagebox.showerror("OWASP 生成失败", summary.get("error", "未生成可用提示词。"), parent=self)
            return

        records = summary.get("records", [])
        errors = validate_prompt_records(records)
        if view is not self:
            allowed = {risk["riskId"]: risk["riskName"] for risk in AGENTIC_RISKS}
            if summary.get("framework") != AGENTIC_FRAMEWORK:
                errors.append("批次框架不匹配。")
            if not errors and any(allowed.get(r["riskId"]) != r["riskName"] or r["userA"] or r["userB"] for r in records):
                errors.append("记录不属于当前 Agentic 单提示词目录。")
        if errors:
            view.owasp_records = []
            view.owasp_json = ""
            view.owasp_xlsx = ""
            self._populate_owasp_result_tree(view)
            view.open_owasp_json_button.state(["disabled"])
            view.open_owasp_xlsx_button.state(["disabled"])
            view.owasp_copy_prompt_button.state(["disabled"])
            self._set_status("OWASP 提示词响应不符合六字段契约")
            self._append_log({"stage": "finish", "level": "error", "message": "；".join(errors)},
                             view.owasp_log_text)
            messagebox.showerror("OWASP 响应被拒绝", "；".join(errors), parent=self)
            return

        view.owasp_records = records
        view.owasp_json = summary.get("jsonPath", "")
        view.owasp_xlsx = summary.get("xlsxPath", "")
        self._populate_owasp_result_tree(view)
        view.open_owasp_json_button.state(["!disabled"] if view.owasp_json else ["disabled"])
        view.open_owasp_xlsx_button.state(["!disabled"] if view.owasp_xlsx else ["disabled"])
        view.owasp_copy_prompt_button.state(["!disabled"])
        image_summary = summary.get("textImageSummary")
        image_note = ""
        if image_summary:
            image_note = f"\n文字图片：成功 {image_summary['successCount']} 张，失败 {image_summary['failedCount']} 张。"
            view.owasp_empty_result_var.set(view.owasp_empty_result_var.get() + image_note)
        self._set_status(f"OWASP 批次 {summary.get('batchId', '')} 模型生成完成：{len(records)} 条可复制提示词")
        messagebox.showinfo(
            "OWASP 生成完成",
            f"批次 {summary.get('batchId', '')}\n模型生成 {len(records)} 条可复制提示词。\n"
            f"跨会话记录请先发 userA，再只发 userB 或 prompt 一次。{image_note}",
            parent=self,
        )

    def _populate_owasp_result_tree(self, view=None) -> None:
        """将通过校验的六字段记录放入唯一结果表，不显示富用例详情。"""
        view = self if view is None else view
        view.owasp_result_tree.delete(*view.owasp_result_tree.get_children())
        if not view.owasp_records:
            view.owasp_empty_result_var.set("尚未生成可复制提示词。")
            return
        for index, record in enumerate(view.owasp_records, 1):
            view.owasp_result_tree.insert("", END, iid=str(index), values=tuple(record[key] for key in PROMPT_RECORD_KEYS))
        view.owasp_empty_result_var.set(f"已生成 {len(view.owasp_records)} 条记录；双击任意单元格即可复制。")

    def _copy_owasp_value(self, field: str, value: str) -> None:
        """把结果表中的一个最终字段复制到剪贴板，不复制隐藏测试说明。"""
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update()
        self._set_status(f"已复制 {field}。")

    def _copy_owasp_clicked_cell(self, event: tk.Event[tk.Misc], view=None) -> None:
        """双击六列表的任意单元格时复制该单元格文本。"""
        view = self if view is None else view
        row_id = view.owasp_result_tree.identify_row(event.y)
        column_id = view.owasp_result_tree.identify_column(event.x)
        if not row_id or not column_id:
            return
        column_index = int(column_id.removeprefix("#")) - 1
        if not 0 <= column_index < len(PROMPT_RECORD_KEYS):
            return
        values = view.owasp_result_tree.item(row_id, "values")
        self._copy_owasp_value(PROMPT_RECORD_KEYS[column_index], values[column_index])

    def _copy_selected_owasp_prompt(self, view=None) -> None:
        """复制选中行的统一 prompt；跨会话时它与 userB 精确相同。"""
        view = self if view is None else view
        selected = view.owasp_result_tree.selection()
        if not selected:
            self._set_status("请先选择一条 OWASP 提示词记录。")
            return
        values = view.owasp_result_tree.item(selected[0], "values")
        self._copy_owasp_value("prompt", values[PROMPT_RECORD_KEYS.index("prompt")])

    def _refresh_selection_catalog(self) -> None:
        scenes = storage.load_catalog()
        previous_sites = {k: v.get() for k, v in self.site_vars.items()}
        previous_risks = {k: v.get() for k, v in self.risk_vars.items()}
        for frame in (self.site_group_zh, self.site_group_en, self.scenes_area):
            for child in frame.winfo_children():
                child.destroy()
        self.site_vars.clear()
        self.site_language.clear()
        self.site_group_widgets.clear()
        self.scene_vars.clear()
        self.risk_vars.clear()
        self.scene_widgets.clear()

        ready_sites = [s for s in storage.load_sources() if s.get("status") == "ready"]
        per_language: dict[str, list[dict]] = {"zh": [], "en": []}
        for site in ready_sites:
            per_language["zh" if site.get("language") == "zh" else "en"].append(site)
        if not ready_sites:
            ttk.Label(self.site_group_zh, style="Subtle.TLabel",
                      text="暂无可爬站点：请先到“来源管理”核验通过。").pack(anchor=W)
        for lang, title in (("zh", "中文站点"), ("en", "英文站点")):
            sites = per_language[lang]
            if not sites:
                continue
            group = self.site_group_zh if lang == "zh" else self.site_group_en
            container = ttk.Frame(group)
            container.pack(fill=X, pady=(4, 0))
            header = ttk.Frame(container, style="SceneHead.TFrame")
            header.pack(fill=X)
            arrow = ttk.Label(header, text="▶", style="SceneHead.TLabel", width=2, cursor="hand2")
            arrow.pack(side=LEFT, padx=(6, 0), pady=3)
            name = ttk.Label(header, text=title, style="SceneHead.TLabel", cursor="hand2")
            name.pack(side=LEFT, pady=3)
            count = ttk.Label(header, text="", style="SceneCount.TLabel")
            count.pack(side=LEFT, padx=8, pady=3)
            body = ttk.Frame(container)
            # 点标题条/名称/箭头 = 展开/收起，与大类卡片同一套交互
            for widget in (header, name, arrow):
                widget.bind("<Button-1>", lambda _event, l=lang: self._toggle_site_group(l))
            self.site_group_widgets[lang] = {"arrow": arrow, "count": count,
                                             "body": body, "expanded": False}
            for index, site in enumerate(sites):
                sid = site["sourceId"]
                variable = tk.BooleanVar(value=previous_sites.get(sid, False))
                self.site_vars[sid] = variable
                self.site_language[sid] = lang
                ttk.Checkbutton(body, text=site["name"], variable=variable,
                                style="Chip.TCheckbutton",
                                command=self._update_selection_summary).grid(
                    row=index // 3, column=index % 3, sticky=W, padx=(0, 6), pady=2)

        for scene in scenes:
            self._build_scene_card(scene, previous_risks)
        for code in self.scene_vars:
            self._sync_scene(code)
        self._update_selection_summary()
        if getattr(self, "_page_sync", None):
            self._page_sync()  # 目录重建后整页高度变化，重算滚动区域

    def _build_scene_card(self, scene: dict, previous_risks: dict[str, bool]) -> None:
        """一个大类 = 可折叠卡片：标题条（箭头+三态框+计数+整组按钮）+ 小类芯片区，默认收起。"""
        code = scene["sceneCode"]
        prefix = code.replace(".", "")  # "A.1" → "A1"，对应小类 ID 前缀
        container = ttk.Frame(self.scenes_area)
        container.pack(fill=X, pady=(4, 0))
        header = ttk.Frame(container, style="SceneHead.TFrame")
        header.pack(fill=X)
        arrow = ttk.Label(header, text="▶", style="SceneHead.TLabel", width=2, cursor="hand2")
        arrow.pack(side=LEFT, padx=(6, 0), pady=3)
        scene_var = tk.StringVar(value="1")
        self.scene_vars[code] = scene_var
        scene_box = ttk.Checkbutton(header, variable=scene_var, style="SceneHead.TCheckbutton",
                                    onvalue="1", offvalue="0",
                                    command=lambda c=code: self._on_scene_toggle(c))
        scene_box.pack(side=LEFT, padx=(2, 4), pady=3)
        name = ttk.Label(header, text=f"{code} {scene['scene']}", style="SceneHead.TLabel",
                         cursor="hand2")
        name.pack(side=LEFT, pady=3)
        count = ttk.Label(header, text="", style="SceneCount.TLabel")
        count.pack(side=LEFT, padx=8, pady=3)
        mini = ttk.Button(header, text="全选本组", width=8,
                          command=lambda c=code: self._toggle_scene_group(c))
        mini.pack(side=RIGHT, padx=6, pady=2)
        body = ttk.Frame(container)
        for index, risk in enumerate(scene.get("risks", [])):
            rid = risk["riskId"]
            variable = tk.BooleanVar(value=previous_risks.get(rid, True))
            self.risk_vars[rid] = variable
            ttk.Checkbutton(body, text=f"{rid} {risk['category']}", variable=variable,
                            style="Chip.TCheckbutton",
                            command=self._update_selection_summary).grid(
                row=index // 3, column=index % 3, sticky=W, padx=(0, 6), pady=2)
        # 点标题条/名称/箭头 = 展开收起；三态框与按钮只管整组勾选，互不干扰
        for widget in (header, name, arrow):
            widget.bind("<Button-1>", lambda _event, c=code: self._toggle_scene_expand(c))
        self.scene_widgets[code] = {"arrow": arrow, "count": count, "mini": mini,
                                    "body": body, "box": scene_box, "prefix": prefix,
                                    "expanded": False}

    def _toggle_collapsible(self, widgets: dict) -> None:
        if widgets["expanded"]:
            widgets["body"].pack_forget()
            widgets["arrow"].config(text="▶")
        else:
            widgets["body"].pack(fill=X, padx=(18, 0), pady=(4, 6))
            widgets["arrow"].config(text="▼")
        widgets["expanded"] = not widgets["expanded"]
        if getattr(self, "_page_sync", None):
            self._page_sync()  # 折叠/展开改变整页高度，立即重算滚动区域

    def _toggle_scene_expand(self, scene_code: str) -> None:
        self._toggle_collapsible(self.scene_widgets[scene_code])

    def _toggle_site_group(self, language: str) -> None:
        self._toggle_collapsible(self.site_group_widgets[language])

    def _on_scene_toggle(self, scene_code: str) -> None:
        """三态框点击：mixed/0 → 全选整组；1 → 清空整组（Tk 点击把 mixed 置为 onvalue）。"""
        self._set_scene_group(scene_code, self.scene_vars[scene_code].get() == "1")

    def _toggle_scene_group(self, scene_code: str) -> None:
        prefix = self.scene_widgets[scene_code]["prefix"]
        all_selected = all(v.get() for rid, v in self.risk_vars.items()
                           if rid.startswith(prefix + "-"))
        self._set_scene_group(scene_code, not all_selected)

    def _set_scene_group(self, scene_code: str, selected: bool) -> None:
        prefix = self.scene_widgets[scene_code]["prefix"]
        for rid, variable in self.risk_vars.items():
            if rid.startswith(prefix + "-"):
                variable.set(selected)
        self._sync_scene(scene_code)
        self._update_selection_summary()

    def _sync_scene(self, scene_code: str) -> None:
        """由小类反推父框三态与计数徽章。"""
        prefix = self.scene_widgets[scene_code]["prefix"]
        group = [v for rid, v in self.risk_vars.items() if rid.startswith(prefix + "-")]
        selected = sum(1 for v in group if v.get())
        self.scene_widgets[scene_code]["count"].config(
            text=f"{selected}/{len(group)}")
        self.scene_widgets[scene_code]["mini"].config(
            text="清空本组" if selected == len(group) else "全选本组")
        if not group or selected == len(group):
            self.scene_vars[scene_code].set("1")
        elif selected == 0:
            self.scene_vars[scene_code].set("0")
        else:
            self.scene_vars[scene_code].set("mixed")
        # 三态显示：mixed 用 ttk 的 alternate 状态标志呈现（部分选中的横线框）
        box = self.scene_widgets[scene_code]["box"]
        box.state(["alternate"] if self.scene_vars[scene_code].get() == "mixed"
                  else ["!alternate"])

    def _select_all_risks(self) -> None:
        for variable in self.risk_vars.values():
            variable.set(True)
        for code in self.scene_vars:
            self._sync_scene(code)
        self._update_selection_summary()

    def _clear_all_risks(self) -> None:
        for variable in self.risk_vars.values():
            variable.set(False)
        for code in self.scene_vars:
            self._sync_scene(code)
        self._update_selection_summary()

    def _select_sites(self, language: str | None, selected: bool) -> None:
        for sid, variable in self.site_vars.items():
            if language is None or self.site_language.get(sid) == language:
                variable.set(selected)
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        self.text_image_check.state(["disabled"] if self.running or self.question_type_var.get() != "text" else ["!disabled"])
        site_total, risk_total = len(self.site_vars), len(self.risk_vars)
        site_n = sum(1 for v in self.site_vars.values() if v.get())
        risk_n = sum(1 for v in self.risk_vars.values() if v.get())
        self.site_badge.config(text=f"已选 {site_n}/{site_total}")
        self.risk_badge.config(text=f"已选 {risk_n}/{risk_total}")
        for lang, widgets in self.site_group_widgets.items():
            sids = [sid for sid, l in self.site_language.items() if l == lang]
            n = sum(1 for sid in sids if self.site_vars[sid].get())
            widgets["count"].config(text=f"已选 {n}/{len(sids)}")
        mode_name = "图片生成题" if self.question_type_var.get() == "image" else "文本对话题"
        self.selection_summary.config(text=f"当前：{site_n} 个网站 · {risk_n}/{risk_total} 个小类 · {mode_name}")
        if self.running:
            return
        if not risk_total:
            self.start_button.state(["disabled"])
            self.go_hint.config(text="题目类型目录为空。", foreground="#A4262C")
        elif not site_total:
            self.start_button.state(["disabled"])
            self.go_hint.config(text="暂无可爬站点：请先到“来源管理”核验通过。", foreground="#A4262C")
        elif site_n == 0 or risk_n == 0:
            missing = "网站" if site_n == 0 else "小类"
            self.start_button.state(["disabled"])
            self.go_hint.config(text=f"还差{missing}：请至少勾选 1 个{missing}。", foreground="#A4262C")
        else:
            self.start_button.state(["!disabled"])
            extra = "，批次名带 -IMG" if mode_name == "图片生成题" else ""
            self.go_hint.config(text=f"就绪：将按 {self.total_var.get()} 题、中文 {self.zh_var.get()}% "
                                     f"生成{mode_name}{extra}，来源仅从已选网站抓取。",
                                foreground="#1E7A3C")

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
        question_type = self.question_type_var.get()
        if question_type == "image" and not (settings["imageBaseUrl"].strip() and settings["imageModel"].strip()):
            messagebox.showwarning("缺少文生图模型配置", "请先到“设置 → 文生图模型”填写接口地址和模型名。", parent=self)
            return
        params = {"sourceIds": site_ids, "riskIds": risk_ids, "total": total, "zhPercent": zh_percent,
                  "questionType": question_type,
                  "textImageEnabled": question_type == "text" and self.text_image_enabled_var.get()}
        storage.save_settings({"questionType": question_type})  # 记住本次的题目形式
        self._launch_generation("batch", pipeline.run_batch, params, settings, "生成中…")

    def _finish_batch(self, done: dict) -> None:
        self.running = False
        self._sync_generation_busy()
        for widget in self._generate_widgets:
            widget.state(["!disabled"])
        if self.question_type_var.get() != "text":
            self.text_image_check.state(["disabled"])
        for widget in self._owasp_generate_widgets:
            widget.state(["!disabled"])
        self._update_owasp_selection_summary()
        if not done.get("ok"):
            self._set_status("生成失败")
            messagebox.showerror("生成失败", done.get("error", "未知错误"), parent=self)
            return
        summary = done["summary"]
        self.current_questions = summary.get("questions", [])
        self.current_batch_dir = summary.get("batchDir", "")
        self.current_xlsx = summary.get("xlsxPath", "")
        self.open_batch_button.state(["!disabled"])
        self.open_xlsx_button.state(["!disabled"] if self.current_xlsx and self.current_questions else ["disabled"])
        self._populate_question_tree()
        batch_status = summary.get("status", "completed")
        outcome = {"completed": "完成", "failed": "失败", "aborted": "已中止"}.get(batch_status, "完成")
        image_summary = summary.get("imageSummary")
        image_note = ""
        if image_summary:
            image_note = (f"\n图片：成功 {image_summary.get('imageSuccessCount', 0)}，"
                          f"拒绝 {image_summary.get('imageRejectedCount', 0)}，"
                          f"失败 {image_summary.get('imageFailedCount', 0)}")
        text_image_summary = summary.get("textImageSummary")
        if text_image_summary:
            image_note = (f"\n文字图片：成功 {text_image_summary.get('successCount', 0)}，"
                          f"失败 {text_image_summary.get('failedCount', 0)}")
        self._set_status(f"批次 {summary['batchId']} {outcome}：{summary['questionCount']} 题"
                         f"（中 {summary['zhCount']} / 英 {summary['enCount']}）" + image_note.replace("\n", "；"))
        if summary.get("exportError"):
            self._set_status(f"批次 {summary['batchId']}：Excel 导出失败")
            reason = f"\n批次状态：{outcome}；{summary.get('error')}" if summary.get("error") else ""
            messagebox.showwarning("Excel 导出失败",
                                   f"Excel 导出失败：{summary['exportError']}{reason}{image_note}\n"
                                   f"已有 JSON 和图片可在批次目录查看：{self.current_batch_dir}", parent=self)
            return
        if batch_status == "failed":
            messagebox.showerror("生成失败", f"{summary.get('error') or '本批次未生成有效题目。'}\n\n"
                                 f"批次与日志已保留：{self.current_batch_dir}{image_note}", parent=self)
            return
        if batch_status == "aborted":
            messagebox.showwarning("生成已中止", f"{summary.get('error') or '批次已中止。'}\n"
                                   f"已保留 {summary['questionCount']} 题。\n"
                                   f"批次与日志：{self.current_batch_dir}{image_note}", parent=self)
            return
        shortage = summary.get("shortage", [])
        note = f"，缺口 {len(shortage)} 项" if shortage else ""
        if image_summary and image_summary.get("status") in ("partial", "failed"):
            self._set_status(f"批次 {summary['batchId']} 图片未全部生成" + image_note.replace("\n", "；"))
            messagebox.showwarning("图片未全部生成",
                                   f"批次 {summary['batchId']}\n提示词 {summary['questionCount']} 条{image_note}\n"
                                   f"批次与日志：{self.current_batch_dir}", parent=self)
            return
        if text_image_summary and text_image_summary.get("failedCount", 0):
            messagebox.showwarning("文字图片未全部生成", f"{image_note}\n批次与日志：{self.current_batch_dir}", parent=self)
            return
        messagebox.showinfo("生成完成",
                            f"批次 {summary['batchId']}\n产出 {summary['questionCount']} 题"
                            f"（中文 {summary['zhCount']} / 英文 {summary['enCount']}）{note}{image_note}",
                            parent=self)

    def _populate_question_tree(self) -> None:
        self.question_tree.delete(*self.question_tree.get_children())
        # 空批次也必须清掉旧原文，避免把上次结果误当成本次产出。
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", END)
        self.detail_text.configure(state="disabled")
        for q in self.current_questions:
            self.question_tree.insert("", END, iid=str(q["seq"]), values=(
                q["seq"], q["riskId"], q["question"]))
        children = self.question_tree.get_children()
        if children:
            self.question_tree.selection_set(children[0])
            self.question_tree.focus(children[0])
            self._on_question_selected()

    def _load_history_batch(self) -> None:
        """列出 data/output 下的历史批次，选择后把题目载入原文↔题目对照区（Ctrl+L）。"""
        output_dir = pipeline.resolve_output_dir(storage.load_settings())
        batches = sorted(
            [p for p in output_dir.iterdir() if p.is_dir() and (p / "questions.json").exists()],
            reverse=True,
        ) if output_dir.exists() else []
        if not batches:
            messagebox.showinfo("没有历史批次", "data/output 下还没有任何批次，先运行一次生成。",
                                parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("选择历史批次")
        dialog.transient(self)
        listbox = tk.Listbox(dialog, width=64, height=min(12, len(batches)), font=(FONT, 10))
        for batch in batches:
            listbox.insert(END, batch.name)
        listbox.selection_set(0)
        listbox.pack(padx=12, pady=12)

        def load(_event=None) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            batch_dir = batches[selection[0]]
            try:
                doc = json.loads((batch_dir / "questions.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                messagebox.showerror("读取失败", f"{batch_dir / 'questions.json'}：{error}", parent=dialog)
                return
            self.current_questions = doc.get("questions", [])
            self.current_batch_dir = str(batch_dir)
            xlsx = batch_dir / "questions.xlsx"
            self.current_xlsx = str(xlsx) if xlsx.exists() else ""
            self.open_batch_button.state(["!disabled"])
            self.open_xlsx_button.state(["!disabled"] if self.current_xlsx and self.current_questions else ["disabled"])
            self._populate_question_tree()
            dialog.destroy()
            self._set_status(f"已加载历史批次 {batch_dir.name}：{len(self.current_questions)} 题")

        listbox.bind("<Double-1>", load)
        listbox.bind("<Return>", load)
        ttk.Button(dialog, text="加载", command=load).pack(pady=(0, 12))
        dialog.grab_set()  # 模态：事件只进对话框，避免沉到主窗口后抢不到键盘焦点
        listbox.focus_set()
        dialog.lift()

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
        question_type = question.get("questionType") or "text"
        if question_type == "image":
            type_line = "【题型】图片生成题（题干为文生图提示词）\n"
            if question.get("imageStatus"):
                status = {"success": "成功", "rejected": "被拒绝", "failed": "失败"}.get(
                    question["imageStatus"], question["imageStatus"])
                type_line += f"【图片状态】{status}\n"
                if question.get("imagePath"):
                    type_line += f"【图片路径】{question['imagePath']}\n"
                if question.get("imageError"):
                    type_line += f"【图片原因】{question['imageError']}\n"
        else:
            type_line = "【题型】文本对话题\n"
        self.detail_text.insert("1.0", (
            f"【题干】{question['question']}\n\n"
            f"{type_line}"
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
        x_scroll = ttk.Scrollbar(self.sources_tab, orient=HORIZONTAL, command=self.source_tree.xview)
        self.source_tree.configure(yscrollcommand=scroll.set, xscrollcommand=x_scroll.set)
        x_scroll.pack(side=BOTTOM, fill=X)
        scroll.pack(side=RIGHT, fill=Y)
        self.source_tree.pack(side=LEFT, fill="both", expand=True)

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
        self._sync_generation_busy()
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
        self._sync_generation_busy()
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
        self.settings_notebook = ttk.Notebook(self.settings_tab)
        self.settings_notebook.pack(fill=X)
        text_frame = ttk.Frame(self.settings_notebook, padding=10)
        image_frame = ttk.Frame(self.settings_notebook, padding=10)
        common_frame = ttk.Frame(self.settings_notebook, padding=10)
        text_image_frame = ttk.Frame(self.settings_notebook, padding=10)
        for pane, title in ((text_frame, "文字模型"), (image_frame, "文生图模型"), (common_frame, "通用设置"), (text_image_frame, "文字图片")):
            self.settings_notebook.add(pane, text=title)
        self.setting_vars = {
            "baseUrl": tk.StringVar(), "apiKey": tk.StringVar(), "model": tk.StringVar(),
            "imageBaseUrl": tk.StringVar(), "imageApiKey": tk.StringVar(), "imageModel": tk.StringVar(),
            "imageTimeoutSeconds": tk.StringVar(), "imageRetries": tk.StringVar(),
            "temperature": tk.StringVar(), "timeoutSeconds": tk.StringVar(),
            "retries": tk.StringVar(), "maxQuestionsPerItem": tk.StringVar(),
            "crawlDelayMs": tk.StringVar(), "requestTimeoutSeconds": tk.StringVar(),
            "outputDir": tk.StringVar(),
            "textImageSize": tk.StringVar(), "textImageBackgroundPath": tk.StringVar(),
            "textImageBackgroundSha256": tk.StringVar(),
        }
        groups = ((text_frame, {
            "baseUrl": "接口地址（含 /v1 等版本号）", "apiKey": "API Key", "model": "模型名",
            "temperature": "温度", "timeoutSeconds": "接口超时（秒）", "retries": "出题重试次数",
            "maxQuestionsPerItem": "单次请求最多生成条数"}),
            (image_frame, {"imageBaseUrl": "接口地址（含 /v1 等版本号）", "imageApiKey": "API Key",
                           "imageModel": "模型名", "imageTimeoutSeconds": "接口超时（秒）",
                           "imageRetries": "生图重试次数"}),
            (common_frame, {"crawlDelayMs": "爬取请求间隔（毫秒）", "requestTimeoutSeconds": "爬取超时（秒）",
                            "outputDir": "产物存放路径"}))
        for frame, labels in groups:
            frame.columnconfigure(1, weight=1)
            for row, (key, label) in enumerate(labels.items()):
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky=W, padx=8, pady=5)
                entry = ttk.Entry(frame, textvariable=self.setting_vars[key], width=52,
                                  show="*" if key in ("apiKey", "imageApiKey") else "")
                entry.grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(image_frame, text="生成图片题时调用图像接口，可能产生费用。", style="Subtle.TLabel").grid(
            row=5, column=0, columnspan=2, sticky=W, padx=8, pady=6)
        ttk.Button(text_frame, text="测试连通", command=lambda: self._test_connection_async("text")).grid(
            row=7, column=0, sticky=W, padx=8, pady=6)
        self.image_test_button = ttk.Button(image_frame, text="测试连通", command=lambda: self._test_connection_async("image"))
        self.image_test_button.grid(row=6, column=0, sticky=W, padx=8, pady=6)
        ttk.Button(common_frame, text="浏览…", command=self._pick_output_dir).grid(
            row=2, column=2, sticky=W, padx=(6, 0))
        ttk.Label(common_frame, text="TC260 产物存入 BATCH-…；LLM 提示词存入 OWASP-…；Agentic 存入 AGENTIC-…；"
                              "留空则使用程序目录 data\\output。", style="Subtle.TLabel").grid(
            row=3, column=0, columnspan=3, sticky=W, padx=8, pady=(0, 6))
        self._pending_text_background = None
        self._background_preview = None
        self.background_name = tk.StringVar(value="白色背景")
        ttk.Label(text_image_frame, text="图片尺寸（像素）").grid(row=0, column=0, sticky=W, padx=8, pady=5)
        self.text_image_size_combo = ttk.Combobox(text_image_frame, textvariable=self.setting_vars["textImageSize"],
                                                  values=storage.TEXT_IMAGE_SIZES, state="readonly", width=22)
        self.text_image_size_combo.grid(row=0, column=1, sticky=W, pady=5)
        ttk.Label(text_image_frame, text="背景图片").grid(row=1, column=0, sticky=W, padx=8, pady=5)
        ttk.Label(text_image_frame, textvariable=self.background_name).grid(row=1, column=1, sticky=W)
        ttk.Button(text_image_frame, text="浏览…", command=self._pick_text_background).grid(row=1, column=2, padx=6)
        ttk.Button(text_image_frame, text="清除背景", command=self._clear_text_background).grid(row=1, column=3)
        self.background_preview_label = ttk.Label(text_image_frame)
        self.background_preview_label.grid(row=2, column=1, sticky=W, pady=8)
        ttk.Label(text_image_frame, text="选定背景保存在本机；文字图片默认使用白底。", style="Subtle.TLabel").grid(
            row=3, column=0, columnspan=4, sticky=W, padx=8, pady=4)
        buttons = ttk.Frame(self.settings_tab)
        buttons.pack(fill=X, pady=(10, 0))
        ttk.Button(buttons, text="保存设置", command=self._save_settings).pack(side=LEFT)
        self.connection_result = tk.StringVar(value="")
        ttk.Label(buttons, textvariable=self.connection_result, style="Subtle.TLabel").pack(side=LEFT, padx=10)
        self._load_settings_into_form()

    def _load_settings_into_form(self) -> None:
        settings = storage.load_settings()
        for key, variable in self.setting_vars.items():
            variable.set(str(settings.get(key, "")))
        relative = settings.get("textImageBackgroundPath", "")
        if relative:
            self.background_name.set("已保存背景")
            self._show_text_background(storage.DATA_DIR / relative)

    def _show_text_background(self, path: Path) -> None:
        try:
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("图片过大")
            with Image.open(path) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("图片像素过大")
                preview = ImageOps.exif_transpose(image).convert("RGB")
                preview.thumbnail((220, 130))
                self._background_preview = ImageTk.PhotoImage(preview)
            self.background_preview_label.configure(image=self._background_preview)
        except (OSError, ValueError, Image.DecompressionBombError):
            self._background_preview = None
            self.background_preview_label.configure(image="")

    def _pick_text_background(self) -> None:
        chosen = filedialog.askopenfilename(parent=self, title="选择背景图片", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp")])
        if chosen:
            self._pending_text_background = chosen
            self.background_name.set(Path(chosen).name)
            self._show_text_background(Path(chosen))

    def _clear_text_background(self) -> None:
        self._pending_text_background = ""
        self.background_name.set("白色背景")
        self._background_preview = None
        self.background_preview_label.configure(image="")

    def _pick_output_dir(self) -> None:
        current = self.setting_vars["outputDir"].get().strip()
        initial = current if current and Path(current).exists() else str(PROJECT_ROOT)
        chosen = filedialog.askdirectory(parent=self, title="选择产物存放目录", initialdir=initial)
        if chosen:
            self.setting_vars["outputDir"].set(chosen)

    def _collect_settings(self) -> dict:
        patch = {}
        for key, variable in self.setting_vars.items():
            raw = variable.get().strip()
            if key in ("temperature",):
                patch[key] = float(raw) if raw else storage.SETTINGS_DEFAULTS[key]
            elif key in ("timeoutSeconds", "retries", "maxQuestionsPerItem", "crawlDelayMs", "requestTimeoutSeconds",
                         "imageTimeoutSeconds", "imageRetries"):
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
        if patch["textImageSize"] not in storage.TEXT_IMAGE_SIZES:
            messagebox.showwarning("图片尺寸错误", "请在文字图片设置中选择有效的尺寸。", parent=self)
            return
        if self._pending_text_background is not None:
            if not self._pending_text_background:
                patch.update(textImageBackgroundPath="", textImageBackgroundSha256="")
            else:
                try:
                    patch.update(storage.import_text_image_background(Path(self._pending_text_background)))
                except (ValueError, OSError) as error:
                    messagebox.showerror("背景图片无效", str(error), parent=self)
                    return
        raw_dir = str(patch.get("outputDir", "")).strip()
        if raw_dir:
            out_path = Path(raw_dir)
            if not out_path.is_absolute():
                out_path = PROJECT_ROOT / out_path
            try:
                out_path.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                messagebox.showerror("产物路径无效", f"无法创建目录 {out_path}：{error}", parent=self)
                return
            patch["outputDir"] = str(out_path)
        try:
            merged = storage.save_settings(patch)
        except OSError:
            messagebox.showerror("保存失败", "无法保存设置，请检查目录权限和磁盘空间后重试。", parent=self)
            return
        self._pending_text_background = None
        self.setting_vars["textImageBackgroundPath"].set(merged.get("textImageBackgroundPath", ""))
        self.setting_vars["textImageBackgroundSha256"].set(merged.get("textImageBackgroundSha256", ""))
        self._set_status("设置已保存")
        selected_tab = self.settings_notebook.index(self.settings_notebook.select())
        if selected_tab == 0:
            self.connection_result.set(f"已保存文字模型：{merged['model'] or '（未填模型名）'}")
        elif selected_tab == 1:
            self.connection_result.set(f"已保存文生图模型：{merged['imageModel'] or '（未填模型名）'}")
        else:
            self.connection_result.set("设置已保存")

    def _test_connection_async(self, model_kind: str = "text") -> None:
        if model_kind == "image" and self._image_test_in_progress:
            return
        try:
            if model_kind == "image":
                patch = {key: self.setting_vars[key].get().strip() for key in
                         ("imageBaseUrl", "imageApiKey", "imageModel", "imageTimeoutSeconds")}
                patch["imageTimeoutSeconds"] = int(patch["imageTimeoutSeconds"] or storage.SETTINGS_DEFAULTS["imageTimeoutSeconds"])
                # 连通测试仅发起一次生成，避免因自动重试产生额外费用。
                patch["imageRetries"] = 0
            else:
                patch = self._collect_settings()
        except ValueError:
            messagebox.showwarning("格式错误", "数值字段必须填写数字。", parent=self)
            return
        base_key, model_key = ("imageBaseUrl", "imageModel") if model_kind == "image" else ("baseUrl", "model")
        if not (patch[base_key] and patch[model_key]):
            messagebox.showwarning("缺少配置", "请先填写接口地址与模型名。", parent=self)
            return
        if model_kind == "image":
            if not messagebox.askyesno("确认测试生图", "将调用文生图模型生成一张测试图片，可能产生费用。是否继续？", parent=self):
                return
            self._image_test_in_progress = True
            self.image_test_button.state(["disabled"])
        self.connection_result.set("测试中…")

        def work() -> None:
            try:
                if model_kind == "image":
                    import image_generator
                    test_root = storage.DATA_DIR / "image-tests"
                    test_root.mkdir(parents=True, exist_ok=True)
                    test_dir = Path(tempfile.mkdtemp(prefix="test-", dir=test_root))
                    result = image_generator.generate_image("一只可爱的小猫咪坐在阳光明媚的窗台上，背景是蓝天白云。", patch, test_dir, 1)
                    if result.get("imageStatus") != "success" or not result.get("imagePath"):
                        try:
                            test_dir.rmdir()
                        except OSError:
                            pass
                        self.events.put({"stage": "_done", "kind": "test", "ok": False,
                                         "error": result.get("imageError") or "生成测试图片失败。", "modelKind": model_kind})
                        return
                    image_path = str(test_dir / result["imagePath"])
                    self.events.put({"stage": "_done", "kind": "test", "ok": True, "reply": "测试图片已生成", "imagePath": image_path, "modelKind": model_kind})
                    return
                else:
                    reply = question_generator.test_connection(patch)
            except Exception as error:  # noqa: BLE001 - 展示给操作者
                detail = "图片测试发生异常，请检查配置和本地存储。" if model_kind == "image" else str(error)
                self.events.put({"stage": "_done", "kind": "test", "ok": False, "error": detail, "modelKind": model_kind})
            else:
                self.events.put({"stage": "_done", "kind": "test", "ok": True, "reply": reply, "modelKind": model_kind})

        threading.Thread(target=work, daemon=True).start()

    def _finish_test(self, done: dict) -> None:
        if done.get("modelKind") == "image":
            self._image_test_in_progress = False
            self.image_test_button.state(["!disabled"])
        if done.get("ok"):
            kind = "文生图" if done.get("modelKind") == "image" else "文字"
            self.connection_result.set(f"{kind}模型：{done.get('reply', '')}")
            self._set_status("模型连接正常")
            if done.get("imagePath"):
                messagebox.showinfo("测试成功", f"测试图片已生成：\n{done['imagePath']}", parent=self)
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

    def _launch_generation(self, kind, run, params, settings, status) -> None:
        """三个生成页共用一个后台批次及其取消信号。"""
        control = GenerationControl()
        self._generation = control
        self._generation_kind = kind
        self.running = True
        self._sync_generation_busy()
        self._set_status(status)

        def work():
            try:
                with control.activate():
                    summary = run(params, settings, self.events.put)
                    seal()
            except GenerationCancelled:
                result = {"ok": False, "cancelled": True}
            except Exception as error:
                result = {"ok": False, "error": str(error)}
            else:
                result = {"ok": True, "summary": summary}
            self.events.put({"stage": "_done", "kind": kind, **result})

        threading.Thread(target=work, daemon=True).start()

    def _generation_log(self, kind):
        return {"batch": self.log_text, "owasp_batch": self.owasp_log_text,
                "agentic_batch": self.agentic_page.owasp_log_text}[kind]

    def _stop_generation(self, kind):
        control = self._generation
        if not self.running or control is None or kind != self._generation_kind:
            return
        if control.cancel():
            self._set_status("正在停止生成…")
            self._append_log({"stage": "stop", "message": "已请求停止生成。"}, self._generation_log(kind))
        else:
            self._set_status("正在完成批次发布…")
        self._sync_generation_busy()

    def _sync_generation_busy(self) -> None:
        """同步 TC260、LLM 和 Agentic 的单批次互斥状态。"""
        for widget in (*self._generate_widgets, *self._owasp_generate_widgets, *self.agentic_page._owasp_generate_widgets):
            widget.state(["disabled"] if self.running else ["!disabled"])
        self._update_selection_summary()
        self._update_owasp_selection_summary()
        self._update_owasp_selection_summary(self.agentic_page)
        for kind, button in (("batch", self.stop_button), ("owasp_batch", self.owasp_stop_button),
                             ("agentic_batch", self.agentic_page.owasp_stop_button)):
            enabled = (self.running and kind == self._generation_kind and self._generation is not None
                       and self._generation.can_cancel())
            button.state(["!disabled"] if enabled else ["disabled"])

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            stage = event.get("stage", "")
            if stage == "_done":
                kind = event.get("kind")
                if kind in ("batch", "owasp_batch", "agentic_batch"):
                    self._generation = None
                    self._generation_kind = ""
                    if event.get("cancelled"):
                        self.running = False
                        self._sync_generation_busy()
                        self._set_status("已停止生成")
                        self._append_log({"stage": "stop", "message": "已停止生成。"}, self._generation_log(kind))
                        continue
                if kind == "batch":
                    self._finish_batch(event)
                elif kind == "agentic_batch":
                    self.agentic_page.finish(event)
                elif kind == "owasp_batch":
                    self._finish_owasp_batch(event)
                elif kind == "verify":
                    self._finish_verify(event)
                elif kind == "test":
                    self._finish_test(event)
                continue
            if self._generation is not None and self._generation.stopped.is_set():
                continue
            if event.get("kind") == "owasp":
                risk = f"{event['riskId']} · " if event.get("riskId") else ""
                self._set_status(f"OWASP 进度：{risk}{event.get('message', '')}")
                target = self.agentic_page.owasp_log_text if event.get("framework") == AGENTIC_FRAMEWORK else self.owasp_log_text
                self._append_log(event, target)
            else:
                self._append_log(event)
        self.after(120, self._poll_events)

    def _append_log(self, event: dict, target: tk.Text | None = None) -> None:
        """把运行事件写入指定工作区的日志框，保持两条管线互不混写。"""
        level = event.get("level", "info")
        stamp = (event.get("ts") or datetime.now().isoformat(timespec="seconds"))[11:19]
        prefix = event.get("sourceId") or event.get("riskId") or ""
        line = f"{stamp} [{event.get('stage', '')}]{'[' + prefix + ']' if prefix else ''} {event.get('message', '')}"
        log_widget = self.log_text if target is None else target
        log_widget.configure(state="normal")
        log_widget.insert(END, line + "\n", () if level == "info" else (level,))
        log_widget.see(END)
        log_widget.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text.set(text)

    def _open_path(self, candidate: Path) -> None:
        try:
            target = candidate.resolve()
            target.relative_to(PROJECT_ROOT)
        except (ValueError, OSError):
            # 自定义产物目录通常在程序目录之外，同样放行
            output_root = pipeline.resolve_output_dir(storage.load_settings())
            try:
                target.relative_to(output_root.resolve())
            except (ValueError, OSError):
                # 设置目录变更后，仅信任当前 OWASP 批次已记录的三个完整路径。
                recorded_owasp_paths = set()
                for recorded in (self.owasp_batch_dir, self.owasp_json, self.owasp_xlsx, *self.agentic_page.artifact_paths()):
                    if not recorded:
                        continue
                    try:
                        recorded_owasp_paths.add(Path(recorded).resolve())
                    except (OSError, ValueError, RuntimeError):
                        continue
                if target not in recorded_owasp_paths:
                    messagebox.showerror("无法打开", "仅允许打开程序目录或产物目录内的路径。", parent=self)
                    return
        if not target.exists():
            messagebox.showerror("无法打开", "目标文件或目录不存在。", parent=self)
            return
        if not hasattr(os, "startfile"):
            messagebox.showerror("无法打开", "当前系统不支持打开本地文件。", parent=self)
            return
        os.startfile(target)  # type: ignore[attr-defined]


def smoke_test() -> dict:
    """不创建 Tk 窗口，确认目录与冻结程序的爬虫依赖资源完整。"""
    import apify_fingerprint_datapoints as fingerprint_data

    # BrowserForge 在真正爬取时才读取这些文件，发布前先在烟测中发现遗漏。
    crawler_data = (
        fingerprint_data.get_browser_helper_file(),
        fingerprint_data.get_header_network(),
        fingerprint_data.get_headers_order(),
        fingerprint_data.get_input_network(),
        fingerprint_data.get_fingerprint_network(),
    )
    missing = [path.name for path in crawler_data if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"爬虫依赖资源缺失：{', '.join(missing)}")

    scenes = storage.load_catalog()
    risks = storage.catalog_risks(scenes)
    sources = storage.load_sources()
    settings = storage.load_settings()
    return {
        "desktopReady": True,
        "version": storage.APP_VERSION,
        "workspaces": list(WORKSPACES),
        "catalog": {"scenes": len(scenes), "risks": len(risks)},
        "owasp": {"risks": len(OWASP_RISKS)},
        "agentic": {"framework": AGENTIC_FRAMEWORK, "risks": len(AGENTIC_RISKS)},
        "sources": {"total": len(sources),
                    "ready": sum(1 for s in sources if s.get("status") == "ready")},
        "modelConfigured": bool(settings["baseUrl"] and settings["model"]),
        "python": sys.version.split()[0],
    }


def main() -> None:
    if "--smoke-test" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        try:
            result = smoke_test()
        except FileNotFoundError as error:
            if sys.stderr is not None:
                print(error, file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, ensure_ascii=False))
        return
    application = DesktopApplication()
    application.mainloop()


if __name__ == "__main__":
    main()
