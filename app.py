"""功能:
  提供 GenerateTestQuestion 的独立 Windows 桌面端，以网站与五大类选择为默认的一键出题流程，
  并将人工素材维护保留在高级维护页。
实现:
  使用 Python 标准库 Tkinter 构建一键生成、来源配置和高级维护三个工作区；通过本项目内 Node
  服务执行受控采集与 Excel 生成，复杂操作在后台线程运行，界面只操作 GenerateTestQuestion 目录。
输入:
  data/source_registry.xlsx、data/source_items.xlsx，以及用户在界面中填写的人工素材信息。
输出:
  项目内素材档案、data/raw/ 和 data/question_bank/；--smoke-test 输出 JSON 摘要。
依赖:
  Python 3.13+ 标准库、Node.js、@oai/artifact-tool（通过本项目 Node 服务调用）。
用法:
  python app.py
  python app.py --smoke-test
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import date
from pathlib import Path
from tkinter import END, LEFT, RIGHT, VERTICAL, W, X, Y, filedialog, messagebox, ttk
import tkinter as tk


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_NAMES = ["一键生成", "语料采集", "来源配置", "高级维护"]


class DesktopBackend:
    """封装所有本地 Node 调用，并限制请求文件和打开路径在项目目录内。"""

    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        self.project_root = project_root.resolve()
        self.node_command = shutil.which("node")
        if not self.node_command:
            raise RuntimeError("未找到 Node.js；请安装 Node.js 后再启动桌面端。")
        self.data_service = self.project_root / "tools" / "desktop_data_service.mjs"
        self.one_click_service = self.project_root / "tools" / "one_click_run_service.mjs"
        self.corpus_service = self.project_root / "tools" / "corpus_collector_service.mjs"

    def _inside_project(self, candidate: Path) -> Path:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as error:
            raise RuntimeError("桌面端拒绝操作项目目录以外的路径。") from error
        return resolved

    @staticmethod
    def _json_from_output(stdout: str, stderr: str) -> dict:
        for line in reversed([line.strip() for line in stdout.splitlines() if line.strip()]):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        for line in reversed([line.strip() for line in stderr.splitlines() if line.strip()]):
            try:
                payload = json.loads(line)
                if "error" in payload:
                    raise RuntimeError(payload["error"])
            except json.JSONDecodeError:
                continue
        raise RuntimeError(stderr.strip() or stdout.strip() or "本地数据服务没有返回可读取结果。")

    def _run_node(self, script: Path, arguments: list[str], payload: dict | None = None) -> dict:
        request_path: Path | None = None
        try:
            # --use-env-proxy：让 Node 内置 fetch 读取系统 HTTP(S)_PROXY，保证采集服务能联网。
            command = [self.node_command, "--use-env-proxy", str(self._inside_project(script)), *arguments]
            if payload is not None:
                request_dir = self.project_root / "data" / ".ui_requests"
                request_dir.mkdir(parents=True, exist_ok=True)
                request_path = self._inside_project(request_dir / f"request-{uuid.uuid4().hex}.json")
                request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                command.extend(["--payload-file", request_path.relative_to(self.project_root).as_posix()])
            result = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            response = self._json_from_output(result.stdout, result.stderr)
            if result.returncode != 0:
                raise RuntimeError(response.get("error", "本地服务执行失败。"))
            return response
        finally:
            if request_path and request_path.exists():
                request_path.unlink()

    def snapshot(self) -> dict:
        return self._run_node(self.data_service, ["--action", "snapshot"])

    def stage_intake(self, payload: dict) -> dict:
        return self._run_node(self.data_service, ["--action", "stage-intake"], payload)

    def update_material(self, payload: dict) -> dict:
        return self._run_node(self.data_service, ["--action", "update-material"], payload)

    def run_one_click(self, payload: dict) -> dict:
        return self._run_node(self.one_click_service, [], payload)

    def run_corpus_collection(self, payload: dict) -> dict:
        return self._run_node(self.corpus_service, [], payload)

    def open_project_path(self, candidate: Path) -> None:
        target = self._inside_project(candidate)
        if not target.exists():
            raise RuntimeError("目标文件或目录尚未生成。")
        if not hasattr(os, "startfile"):
            raise RuntimeError("当前系统不支持打开本地文件。")
        os.startfile(target)  # type: ignore[attr-defined]


class DesktopApplication(tk.Tk):
    """主窗口：只在主线程更新 UI，耗时 Node 调用统一放入后台线程。"""

    def __init__(self, backend: DesktopBackend) -> None:
        super().__init__()
        self.backend = backend
        self.snapshot_data: dict = {}
        self.routes_by_id: dict[str, dict] = {}
        self.materials_by_id: dict[str, dict] = {}
        self.status_text = tk.StringVar(value="正在读取项目数据…")
        self.title("GenerateTestQuestion｜风险测试题库桌面端")
        self.geometry("1440x920")
        self.minsize(1120, 720)
        self._configure_style()
        self._create_layout()
        self._refresh_async()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 17, "bold"), foreground="#17365D")
        style.configure("Subtle.TLabel", foreground="#5B6573")
        style.configure("Card.TLabelframe", padding=12)
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"), foreground="#17365D")
        style.configure("Accent.TButton", padding=(10, 6))
        style.map("Accent.TButton", background=[("active", "#245A93")])

    def _create_layout(self) -> None:
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(fill=X)
        ttk.Label(header, text="GenerateTestQuestion", style="Title.TLabel").pack(side=LEFT)
        ttk.Label(header, text="独立 · 手动启动 · 中英文风险测试题库", style="Subtle.TLabel").pack(side=LEFT, padx=14)
        ttk.Button(header, text="刷新数据", command=self._refresh_async).pack(side=RIGHT)
        ttk.Button(header, text="打开项目数据", command=lambda: self._open_path(self.backend.project_root / "data")).pack(side=RIGHT, padx=8)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.one_click_tab = ttk.Frame(notebook, padding=16)
        self.corpus_tab = ttk.Frame(notebook, padding=16)
        self.sources_tab = ttk.Frame(notebook, padding=16)
        self.materials_tab = ttk.Frame(notebook, padding=16)
        for name, tab in zip(WORKSPACE_NAMES, [self.one_click_tab, self.corpus_tab, self.sources_tab, self.materials_tab], strict=True):
            notebook.add(tab, text=name)

        self._build_one_click_tab()
        self._build_corpus_tab()
        self._build_sources_tab()
        self._build_materials_tab()

        footer = ttk.Label(self, textvariable=self.status_text, anchor=W, style="Subtle.TLabel", padding=(20, 8))
        footer.pack(fill=X)

    def _build_one_click_tab(self) -> None:
        """构建默认的一键页面：用户只选择网站、五大类、数量、比例和批次。"""
        ttk.Label(self.one_click_tab, text="一键生成测试题库", style="Title.TLabel").pack(anchor=W)
        ttk.Label(
            self.one_click_tab,
            text="选择可运行网站和要覆盖的一级风险类别，设置题量与中英文比例后，点击一次即可完成受控采集与题库输出。",
            style="Subtle.TLabel",
        ).pack(anchor=W, pady=(2, 14))

        source_frame = ttk.LabelFrame(self.one_click_tab, text="1. 选择网站", style="Card.TLabelframe")
        source_frame.pack(fill=X)
        source_toolbar = ttk.Frame(source_frame)
        source_toolbar.pack(fill=X, pady=(0, 6))
        ttk.Label(source_toolbar, text="仅展示当前可运行的网站；其他登记来源可在“来源配置”查看。", style="Subtle.TLabel").pack(side=LEFT)
        ttk.Button(source_toolbar, text="全选可用网站", command=lambda: self._set_all_site_selection(True)).pack(side=RIGHT)
        ttk.Button(source_toolbar, text="清空", command=lambda: self._set_all_site_selection(False)).pack(side=RIGHT, padx=6)
        self.site_cards_frame = ttk.Frame(source_frame)
        self.site_cards_frame.pack(fill=X)
        self.site_note = tk.StringVar(value="正在读取可运行网站…")
        ttk.Label(source_frame, textvariable=self.site_note, style="Subtle.TLabel").pack(anchor=W, pady=(8, 0))

        scene_frame = ttk.LabelFrame(self.one_click_tab, text="2. 选择要生成的五大类风险（可多选）", style="Card.TLabelframe")
        scene_frame.pack(fill=X, pady=(12, 0))
        scene_toolbar = ttk.Frame(scene_frame)
        scene_toolbar.pack(fill=X, pady=(0, 6))
        ttk.Label(scene_toolbar, text="默认全选；题量不能低于已勾选类别所含的风险数。", style="Subtle.TLabel").pack(side=LEFT)
        ttk.Button(scene_toolbar, text="全选五大类", command=lambda: self._set_all_scene_selection(True)).pack(side=RIGHT)
        ttk.Button(scene_toolbar, text="清空", command=lambda: self._set_all_scene_selection(False)).pack(side=RIGHT, padx=6)
        self.scene_cards_frame = ttk.Frame(scene_frame)
        self.scene_cards_frame.pack(fill=X)

        options = ttk.LabelFrame(self.one_click_tab, text="3. 本次输出", style="Card.TLabelframe")
        options.pack(fill=X, pady=(12, 0))
        self.one_click_date = tk.StringVar(value=date.today().isoformat())
        self.one_click_batch = tk.StringVar(value=f"RUN-{date.today():%Y%m%d}")
        self.one_click_total = tk.StringVar(value="155")
        self.one_click_chinese_percent = tk.StringVar(value="80")
        ttk.Label(options, text="运行日期").grid(row=0, column=0, sticky=W, padx=(0, 6), pady=5)
        ttk.Entry(options, textvariable=self.one_click_date, width=15).grid(row=0, column=1, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="批次 ID").grid(row=0, column=2, sticky=W, padx=(0, 6), pady=5)
        ttk.Entry(options, textvariable=self.one_click_batch, width=24).grid(row=0, column=3, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="生成数量").grid(row=0, column=4, sticky=W, padx=(0, 6), pady=5)
        self.total_spinbox = ttk.Spinbox(options, from_=1, to=1000, textvariable=self.one_click_total, width=10)
        self.total_spinbox.grid(row=0, column=5, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="中文占比").grid(row=0, column=6, sticky=W, padx=(0, 6), pady=5)
        ttk.Spinbox(options, from_=0, to=100, textvariable=self.one_click_chinese_percent, width=8).grid(row=0, column=7, sticky=W, padx=(0, 10), pady=5)
        ttk.Label(options, text="%", style="Subtle.TLabel").grid(row=0, column=8, sticky=W, pady=5)
        self.one_click_button = ttk.Button(options, text="开始采集并生成题库", style="Accent.TButton", command=self._run_one_click)
        self.one_click_button.grid(row=0, column=9, sticky="e", pady=5)
        options.columnconfigure(9, weight=1)

        results = ttk.LabelFrame(self.one_click_tab, text="本次结果", style="Card.TLabelframe")
        results.pack(fill="both", expand=True, pady=(12, 0))
        self.one_click_result_text = tk.Text(results, height=13, wrap="word", font=("Microsoft YaHei UI", 10), state="disabled")
        self.one_click_result_text.pack(fill="both", expand=True)
        result_actions = ttk.Frame(results)
        result_actions.pack(fill=X, pady=(10, 0))
        self.open_incremental_button = ttk.Button(result_actions, text="打开本次题库", state="disabled", command=lambda: self._open_last_output("incrementalPath"))
        self.open_incremental_button.pack(side=RIGHT)
        self.open_master_button = ttk.Button(result_actions, text="打开汇总题库", state="disabled", command=lambda: self._open_last_output("masterPath"))
        self.open_master_button.pack(side=RIGHT, padx=8)
        ttk.Button(result_actions, text="打开题库目录", command=lambda: self._open_path(self.backend.project_root / "data" / "question_bank")).pack(side=RIGHT)
        self.site_selection_vars: dict[str, tk.BooleanVar] = {}
        self.scene_selection_vars: dict[str, tk.BooleanVar] = {}
        self.scene_risk_counts: dict[str, int] = {}
        self.last_output_paths: dict[str, str] = {}

    def _build_corpus_tab(self) -> None:
        """构建语料采集页：选择网站与五大类，设置中英文比例与目标量，一键采集新批次语料。"""
        ttk.Label(self.corpus_tab, text="语料采集（合格率语料集）", style="Title.TLabel").pack(anchor=W)
        ttk.Label(
            self.corpus_tab,
            text="选择来源网站与风险类别，设置中英文比例（默认中文 70%）与目标量，点击一次即可采集一批新的正负样本语料；重复内容按内容哈希自动去重。",
            style="Subtle.TLabel",
        ).pack(anchor=W, pady=(2, 14))

        source_frame = ttk.LabelFrame(self.corpus_tab, text="1. 选择网站", style="Card.TLabelframe")
        source_frame.pack(fill=X)
        source_toolbar = ttk.Frame(source_frame)
        source_toolbar.pack(fill=X, pady=(0, 6))
        ttk.Label(source_toolbar, text="仅展示当前可运行的网站；未参与语料采集的来源可在“来源配置”查看。", style="Subtle.TLabel").pack(side=LEFT)
        ttk.Button(source_toolbar, text="全选可用网站", command=lambda: self._set_all_corpus_site_selection(True)).pack(side=RIGHT)
        ttk.Button(source_toolbar, text="清空", command=lambda: self._set_all_corpus_site_selection(False)).pack(side=RIGHT, padx=6)
        self.corpus_site_cards_frame = ttk.Frame(source_frame)
        self.corpus_site_cards_frame.pack(fill=X)
        self.corpus_site_note = tk.StringVar(value="正在读取可运行网站…")
        ttk.Label(source_frame, textvariable=self.corpus_site_note, style="Subtle.TLabel").pack(anchor=W, pady=(8, 0))

        scene_frame = ttk.LabelFrame(self.corpus_tab, text="2. 选择要覆盖的五大类风险（可多选）", style="Card.TLabelframe")
        scene_frame.pack(fill=X, pady=(12, 0))
        scene_toolbar = ttk.Frame(scene_frame)
        scene_toolbar.pack(fill=X, pady=(0, 6))
        ttk.Label(scene_toolbar, text="默认全选；正样本按每类风险的目标量采集。", style="Subtle.TLabel").pack(side=LEFT)
        ttk.Button(scene_toolbar, text="全选五大类", command=lambda: self._set_all_corpus_scene_selection(True)).pack(side=RIGHT)
        ttk.Button(scene_toolbar, text="清空", command=lambda: self._set_all_corpus_scene_selection(False)).pack(side=RIGHT, padx=6)
        self.corpus_scene_cards_frame = ttk.Frame(scene_frame)
        self.corpus_scene_cards_frame.pack(fill=X)

        options = ttk.LabelFrame(self.corpus_tab, text="3. 本次采集", style="Card.TLabelframe")
        options.pack(fill=X, pady=(12, 0))
        self.corpus_batch = tk.StringVar(value=f"CORPUS-{date.today():%Y%m%d}")
        self.corpus_target_per_risk = tk.StringVar(value="200")
        self.corpus_negative_target = tk.StringVar(value="4000")
        self.corpus_zh_percent = tk.StringVar(value="70")
        ttk.Label(options, text="批次 ID").grid(row=0, column=0, sticky=W, padx=(0, 6), pady=5)
        ttk.Entry(options, textvariable=self.corpus_batch, width=28).grid(row=0, column=1, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="每类正样本目标量").grid(row=0, column=2, sticky=W, padx=(0, 6), pady=5)
        ttk.Spinbox(options, from_=1, to=500, textvariable=self.corpus_target_per_risk, width=10).grid(row=0, column=3, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="负样本目标量").grid(row=0, column=4, sticky=W, padx=(0, 6), pady=5)
        ttk.Spinbox(options, from_=0, to=100000, textvariable=self.corpus_negative_target, width=10).grid(row=0, column=5, sticky=W, padx=(0, 16), pady=5)
        ttk.Label(options, text="中文占比").grid(row=0, column=6, sticky=W, padx=(0, 6), pady=5)
        ttk.Spinbox(options, from_=0, to=100, textvariable=self.corpus_zh_percent, width=8).grid(row=0, column=7, sticky=W, padx=(0, 10), pady=5)
        ttk.Label(options, text="%（默认 70）", style="Subtle.TLabel").grid(row=0, column=8, sticky=W, pady=5)
        self.corpus_button = ttk.Button(options, text="开始采集语料", style="Accent.TButton", command=self._run_corpus_collection)
        self.corpus_button.grid(row=0, column=9, sticky="e", pady=5)
        options.columnconfigure(9, weight=1)

        results = ttk.LabelFrame(self.corpus_tab, text="本次结果", style="Card.TLabelframe")
        results.pack(fill="both", expand=True, pady=(12, 0))
        self.corpus_result_text = tk.Text(results, height=13, wrap="word", font=("Microsoft YaHei UI", 10), state="disabled")
        self.corpus_result_text.pack(fill="both", expand=True)
        result_actions = ttk.Frame(results)
        result_actions.pack(fill=X, pady=(10, 0))
        self.open_corpus_batch_button = ttk.Button(result_actions, text="打开本次语料批次", state="disabled", command=self._open_last_corpus_batch)
        self.open_corpus_batch_button.pack(side=RIGHT)
        ttk.Button(result_actions, text="打开语料目录", command=lambda: self._open_path(self.backend.project_root / "data" / "corpus")).pack(side=RIGHT, padx=8)
        self.corpus_site_selection_vars: dict[str, tk.BooleanVar] = {}
        self.corpus_scene_selection_vars: dict[str, tk.BooleanVar] = {}
        self.corpus_scene_risk_counts: dict[str, int] = {}
        self.last_corpus_batch_path: str = ""

    def _build_sources_tab(self) -> None:
        toolbar = ttk.Frame(self.sources_tab)
        toolbar.pack(fill=X, pady=(0, 8))
        ttk.Label(toolbar, text="来源路由", style="Title.TLabel").pack(side=LEFT)
        self.source_filter = tk.StringVar(value="全部")
        self.source_filter.trace_add("write", lambda *_: self._refresh_route_tree())
        self.source_filter_box = ttk.Combobox(toolbar, state="readonly", textvariable=self.source_filter, width=22)
        self.source_filter_box.pack(side=RIGHT)
        ttk.Button(toolbar, text="打开来源登记表", command=lambda: self._open_path(self.backend.project_root / "data" / "source_registry.xlsx")).pack(side=RIGHT, padx=8)
        ttk.Label(toolbar, text="状态筛选：").pack(side=RIGHT)

        columns = ("routeId", "riskId", "siteName", "outputLanguage", "enableStatus", "verificationLevel", "runGate")
        self.route_tree = ttk.Treeview(self.sources_tab, columns=columns, show="headings", height=25)
        labels = {
            "routeId": "路由ID", "riskId": "风险ID", "siteName": "爬取网站", "outputLanguage": "输出语言",
            "enableStatus": "启用状态", "verificationLevel": "核验等级", "runGate": "运行门禁",
        }
        widths = {"routeId": 200, "riskId": 90, "siteName": 260, "outputLanguage": 90, "enableStatus": 165, "verificationLevel": 95, "runGate": 360}
        for column in columns:
            self.route_tree.heading(column, text=labels[column])
            self.route_tree.column(column, width=widths[column], minwidth=75, anchor=W)
        route_scroll = ttk.Scrollbar(self.sources_tab, orient=VERTICAL, command=self.route_tree.yview)
        self.route_tree.configure(yscrollcommand=route_scroll.set)
        self.route_tree.pack(side=LEFT, fill="both", expand=True)
        route_scroll.pack(side=RIGHT, fill=Y)

    def _build_materials_tab(self) -> None:
        top = ttk.LabelFrame(self.materials_tab, text="人工素材入库", style="Card.TLabelframe")
        top.pack(fill=X)
        self.intake_vars = {
            "routeId": tk.StringVar(), "sourceUrl": tk.StringVar(), "title": tk.StringVar(), "publicationDate": tk.StringVar(value=date.today().isoformat()),
            "materialType": tk.StringVar(value="案例摘要"), "authorization": tk.StringVar(value="人工确认-已获授权"),
            "evidenceId": tk.StringVar(), "evidenceUrl": tk.StringVar(), "urlPrefix": tk.StringVar(), "scope": tk.StringVar(value="允许保留全文；允许生成去标识化场景。"),
            "confirmer": tk.StringVar(), "confirmationDate": tk.StringVar(value=date.today().isoformat()), "expiryDate": tk.StringVar(),
            "batchId": tk.StringVar(value=f"MANUAL-{date.today():%Y%m%d}-001"), "sidecarPath": tk.StringVar(),
        }
        self.route_selector = ttk.Combobox(top, state="readonly", textvariable=self.intake_vars["routeId"], width=34)
        self.route_selector.bind("<<ComboboxSelected>>", lambda _event: self._apply_selected_route())
        self._labeled_widget(top, "来源路由", self.route_selector, 0, 0)
        self._labeled_entry(top, "来源链接", "sourceUrl", 0, 2, width=62)
        self._labeled_entry(top, "标题", "title", 1, 0, width=35)
        self._labeled_entry(top, "发布时间", "publicationDate", 1, 2, width=18)
        self.material_type_box = ttk.Combobox(top, state="readonly", textvariable=self.intake_vars["materialType"], width=18)
        self._labeled_widget(top, "素材类型", self.material_type_box, 1, 4)
        self.authorization_box = ttk.Combobox(top, state="readonly", textvariable=self.intake_vars["authorization"], width=20)
        self._labeled_widget(top, "授权确认", self.authorization_box, 2, 0)
        self._labeled_entry(top, "授权证据ID", "evidenceId", 2, 2, width=24)
        self._labeled_entry(top, "授权证据URL", "evidenceUrl", 2, 4, width=42)
        self._labeled_entry(top, "授权URL前缀", "urlPrefix", 3, 0, width=44)
        self._labeled_entry(top, "确认人", "confirmer", 3, 2, width=24)
        self._labeled_entry(top, "确认日期", "confirmationDate", 3, 4, width=18)
        self._labeled_entry(top, "有效期", "expiryDate", 4, 0, width=18)
        self._labeled_entry(top, "授权范围", "scope", 4, 2, width=62)
        self._labeled_entry(top, "导入批次ID", "batchId", 4, 4, width=25)
        self._labeled_entry(top, "旁车原文路径", "sidecarPath", 5, 0, width=44)
        ttk.Button(top, text="选择项目内旁车", command=self._choose_sidecar).grid(row=5, column=2, sticky=W, padx=(6, 12), pady=5)
        ttk.Label(top, text="原始正文与旁车路径二选一", style="Subtle.TLabel").grid(row=5, column=4, columnspan=2, sticky=W)
        ttk.Label(top, text="原始正文").grid(row=6, column=0, sticky="nw", padx=(0, 6), pady=5)
        self.body_text = tk.Text(top, height=6, wrap="word", font=("Microsoft YaHei UI", 10))
        self.body_text.grid(row=6, column=1, columnspan=5, sticky="ew", pady=5)
        ttk.Button(top, text="提交并入库", style="Accent.TButton", command=self._submit_intake).grid(row=7, column=5, sticky="e", pady=(8, 0))
        for column in (1, 3, 5):
            top.columnconfigure(column, weight=1)

        bottom = ttk.PanedWindow(self.materials_tab, orient="horizontal")
        bottom.pack(fill="both", expand=True, pady=(16, 0))
        archive_frame = ttk.LabelFrame(bottom, text="素材档案", style="Card.TLabelframe")
        detail_frame = ttk.LabelFrame(bottom, text="提取与可生成设置", style="Card.TLabelframe")
        bottom.add(archive_frame, weight=3)
        bottom.add(detail_frame, weight=2)

        material_columns = ("materialId", "riskId", "title", "extractionStatus", "generationStatus")
        self.material_tree = ttk.Treeview(archive_frame, columns=material_columns, show="headings", height=17)
        for column, title, width in [
            ("materialId", "素材ID", 190), ("riskId", "风险ID", 90), ("title", "标题", 260),
            ("extractionStatus", "提取状态", 100), ("generationStatus", "可生成", 100),
        ]:
            self.material_tree.heading(column, text=title)
            self.material_tree.column(column, width=width, minwidth=70, anchor=W)
        self.material_tree.bind("<<TreeviewSelect>>", lambda _event: self._load_selected_material())
        material_scroll = ttk.Scrollbar(archive_frame, orient=VERTICAL, command=self.material_tree.yview)
        self.material_tree.configure(yscrollcommand=material_scroll.set)
        self.material_tree.pack(side=LEFT, fill="both", expand=True)
        material_scroll.pack(side=RIGHT, fill=Y)

        self.edit_vars = {
            "materialId": tk.StringVar(), "suggestedQuestionType": tk.StringVar(),
            "extractionStatus": tk.StringVar(value="待提取"), "generationStatus": tk.StringVar(value="不可生成"),
        }
        ttk.Label(detail_frame, textvariable=self.edit_vars["materialId"], font=("Microsoft YaHei UI", 11, "bold"), foreground="#17365D").pack(anchor=W)
        ttk.Label(detail_frame, text="生成素材（去标识化）").pack(anchor=W, pady=(10, 2))
        self.generated_material_text = tk.Text(detail_frame, height=7, wrap="word", font=("Microsoft YaHei UI", 10))
        self.generated_material_text.pack(fill=X)
        ttk.Label(detail_frame, text="事实要点").pack(anchor=W, pady=(8, 2))
        self.fact_points_text = tk.Text(detail_frame, height=3, wrap="word", font=("Microsoft YaHei UI", 10))
        self.fact_points_text.pack(fill=X)
        ttk.Label(detail_frame, text="风险触发点").pack(anchor=W, pady=(8, 2))
        self.risk_trigger_text = tk.Text(detail_frame, height=3, wrap="word", font=("Microsoft YaHei UI", 10))
        self.risk_trigger_text.pack(fill=X)
        editor_row = ttk.Frame(detail_frame)
        editor_row.pack(fill=X, pady=10)
        ttk.Label(editor_row, text="建议题型").grid(row=0, column=0, sticky=W)
        self.question_type_entry = ttk.Entry(editor_row, textvariable=self.edit_vars["suggestedQuestionType"], width=18)
        self.question_type_entry.grid(row=0, column=1, sticky=W, padx=5)
        ttk.Label(editor_row, text="提取状态").grid(row=1, column=0, sticky=W, pady=6)
        self.extraction_box = ttk.Combobox(editor_row, state="readonly", textvariable=self.edit_vars["extractionStatus"], width=16)
        self.extraction_box.grid(row=1, column=1, sticky=W, padx=5, pady=6)
        ttk.Label(editor_row, text="可生成状态").grid(row=2, column=0, sticky=W)
        self.generation_box = ttk.Combobox(editor_row, state="readonly", textvariable=self.edit_vars["generationStatus"], width=16)
        self.generation_box.grid(row=2, column=1, sticky=W, padx=5)
        ttk.Button(detail_frame, text="保存提取结果", style="Accent.TButton", command=self._save_material).pack(anchor="e", pady=(8, 0))

    @staticmethod
    def _labeled_widget(parent: ttk.Widget, label: str, widget: ttk.Widget, row: int, column: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky=W, padx=(0, 6), pady=5)
        widget.grid(row=row, column=column + 1, sticky="ew", padx=(0, 12), pady=5)

    def _labeled_entry(self, parent: ttk.Widget, label: str, key: str, row: int, column: int, width: int) -> None:
        entry = ttk.Entry(parent, textvariable=self.intake_vars[key], width=width)
        self._labeled_widget(parent, label, entry, row, column)

    def _run_async(self, description: str, work: callable, on_success: callable, on_error: callable | None = None) -> None:
        self.status_text.set(f"{description}…")

        def runner() -> None:
            try:
                result = work()
            except Exception as error:  # noqa: BLE001 - 将后端错误原样呈现给操作者。
                if on_error is None:
                    self.after(0, lambda: self._show_error(description, error))
                else:
                    self.after(0, lambda: on_error(error))
            else:
                self.after(0, lambda: on_success(result))

        threading.Thread(target=runner, daemon=True).start()

    def _show_error(self, description: str, error: Exception) -> None:
        self.status_text.set(f"{description}失败")
        messagebox.showerror("操作失败", str(error), parent=self)

    def _refresh_async(self) -> None:
        self._run_async("刷新项目数据", self.backend.snapshot, self._apply_snapshot)

    def _apply_snapshot(self, snapshot: dict) -> None:
        self.snapshot_data = snapshot
        summary = snapshot["summary"]
        for key, variable in getattr(self, "summary_vars", {}).items():
            variable.set(str(summary.get(key, 0)))
        self.routes_by_id = {route["routeId"]: route for route in snapshot["routes"]}
        self.materials_by_id = {material["materialId"]: material for material in snapshot["materials"]}
        self.route_selector.configure(values=sorted(self.routes_by_id))
        self.material_type_box.configure(values=["新闻报道", "官方通报", "案例摘要", "数据集元数据", "事实核查", "科普材料", "其他"])
        self.authorization_box.configure(values=["人工确认-已获授权", "V3来源"])
        self.extraction_box.configure(values=["待提取", "提取中", "已提取", "提取失败"])
        self.generation_box.configure(values=["不可生成", "待复核", "可生成"])
        statuses = ["全部", *sorted({route["enableStatus"] for route in snapshot["routes"]})]
        self.source_filter_box.configure(values=statuses)
        if self.source_filter.get() not in statuses:
            self.source_filter.set("全部")
        self._apply_one_click_catalog(snapshot)
        self._apply_corpus_catalog(snapshot)
        self._refresh_route_tree()
        self._refresh_material_tree()
        self.status_text.set("项目数据已刷新")

    def _apply_corpus_catalog(self, snapshot: dict) -> None:
        """把登记表中的可运行网站和五大类风险转成语料采集页的多选控件。"""
        if not hasattr(self, "corpus_site_cards_frame"):
            return
        catalog = snapshot.get("selectionCatalog", {})
        selection = snapshot.get("sourceSelection", {})
        selected_source_ids = set(selection.get("selectedSourceIds", []))
        selected_scene_codes = set(selection.get("selectedSceneCodes", []))
        for child in self.corpus_site_cards_frame.winfo_children():
            child.destroy()
        for child in self.corpus_scene_cards_frame.winfo_children():
            child.destroy()
        self.corpus_site_selection_vars.clear()
        self.corpus_scene_selection_vars.clear()
        self.corpus_scene_risk_counts.clear()

        sites = catalog.get("sites", [])
        selectable_sites = [site for site in sites if site.get("selectable")]
        # 并入 HTML 列表直采来源（无需登记表 JSON 路由，直接抓官方静态页面）
        for html_source in self._read_html_sources():
            source_id = html_source.get("sourceId", "")
            if not source_id:
                continue
            selectable_sites.append({
                "sourceId": source_id,
                "siteName": html_source.get("siteName", source_id),
                "sourceLanguages": [html_source.get("outputLanguage", "zh")],
                "coveredRiskCount": "多类",
                "runnableRouteCount": "HTML直采",
                "html": True,
            })
        for index, site in enumerate(selectable_sites):
            source_id = site["sourceId"]
            variable = tk.BooleanVar(value=source_id in selected_source_ids)
            self.corpus_site_selection_vars[source_id] = variable
            card = ttk.LabelFrame(self.corpus_site_cards_frame, text=source_id, padding=8)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 10) if index % 3 < 2 else 0, pady=3)
            ttk.Checkbutton(card, text=site["siteName"], variable=variable).pack(anchor=W)
            languages = " / ".join(site.get("sourceLanguages", [])) or "未标注语言"
            if site.get("html"):
                detail = f"{languages} · HTML 列表直采 · 官方通报/辟谣页"
            else:
                detail = f"{languages} · 覆盖 {site.get('coveredRiskCount', 0)} 类风险 · {site.get('runnableRouteCount', 0)} 条可运行路由"
            ttk.Label(card, text=detail, style="Subtle.TLabel").pack(anchor=W, pady=(3, 0))
            self.corpus_site_cards_frame.columnconfigure(index % 3, weight=1)
        unavailable_count = len(sites) - len(selectable_sites)
        self.corpus_site_note.set(f"当前可运行网站 {len(selectable_sites)} 个；另有 {unavailable_count} 个登记来源因门禁或授权状态未参与语料采集。")

        scenes = catalog.get("scenes", [])
        for index, scene in enumerate(scenes):
            scene_code = scene["sceneCode"]
            variable = tk.BooleanVar(value=scene_code in selected_scene_codes)
            self.corpus_scene_selection_vars[scene_code] = variable
            self.corpus_scene_risk_counts[scene_code] = int(scene.get("riskCount", 0))
            card = ttk.LabelFrame(self.corpus_scene_cards_frame, text=scene_code, padding=8)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 10) if index % 3 < 2 else 0, pady=3)
            ttk.Checkbutton(card, text=scene["scene"], variable=variable).pack(anchor=W)
            ttk.Label(card, text=f"覆盖 {scene.get('riskCount', 0)} 类风险", style="Subtle.TLabel").pack(anchor=W, pady=(3, 0))
            self.corpus_scene_cards_frame.columnconfigure(index % 3, weight=1)

    def _read_html_sources(self) -> list[dict]:
        """读取 HTML 列表直采来源配置（data/corpus/html_sources.json），失败返回空列表。"""
        config_path = self.project_root / "data" / "corpus" / "html_sources.json"
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            sources = raw.get("sources", raw) if isinstance(raw, dict) else raw
            return sources if isinstance(sources, list) else []
        except (OSError, ValueError):
            return []

    def _selected_corpus_site_ids(self) -> list[str]:
        return sorted(source_id for source_id, variable in self.corpus_site_selection_vars.items() if variable.get())

    def _selected_corpus_scene_codes(self) -> list[str]:
        return sorted(scene_code for scene_code, variable in self.corpus_scene_selection_vars.items() if variable.get())

    def _set_all_corpus_site_selection(self, value: bool) -> None:
        for variable in self.corpus_site_selection_vars.values():
            variable.set(value)

    def _set_all_corpus_scene_selection(self, value: bool) -> None:
        for variable in self.corpus_scene_selection_vars.values():
            variable.set(value)

    def _run_corpus_collection(self) -> None:
        selected_source_ids = self._selected_corpus_site_ids()
        selected_scene_codes = self._selected_corpus_scene_codes()
        if not selected_source_ids:
            messagebox.showwarning("未选择网站", "请至少选择一个可运行网站。", parent=self)
            return
        if not selected_scene_codes:
            messagebox.showwarning("未选择类别", "请至少选择一个一级风险类别。", parent=self)
            return
        try:
            target_per_risk = int(self.corpus_target_per_risk.get())
            negative_target = int(self.corpus_negative_target.get())
            zh_percent = int(self.corpus_zh_percent.get())
        except ValueError:
            messagebox.showwarning("参数错误", "目标量和中文占比必须填写整数。", parent=self)
            return
        if target_per_risk < 1 or target_per_risk > 500:
            messagebox.showwarning("数量错误", "每类正样本目标量必须是 1 至 500 的整数。", parent=self)
            return
        if negative_target < 0 or negative_target > 100000:
            messagebox.showwarning("数量错误", "负样本目标量必须是 0 至 100000 的整数。", parent=self)
            return
        if zh_percent < 0 or zh_percent > 100:
            messagebox.showwarning("比例错误", "中文占比必须在 0 至 100 之间。", parent=self)
            return
        payload = {
            "batchId": self.corpus_batch.get(),
            "zhPercent": zh_percent,
            "targetPerRisk": target_per_risk,
            "negativeTarget": negative_target,
            "selectedSourceIds": selected_source_ids,
            "selectedSceneCodes": selected_scene_codes,
        }
        self.corpus_button.configure(state="disabled")

        def complete(result: dict) -> None:
            self.last_corpus_batch_path = str(self.backend.project_root / "data" / "corpus" / result["batchId"])
            self._write_corpus_result(result)
            self.open_corpus_batch_button.configure(state="normal")
            self.corpus_button.configure(state="normal")
            self.status_text.set("语料采集完成")
            self._refresh_async()

        self._run_async(
            "采集语料",
            lambda: self.backend.run_corpus_collection(payload),
            complete,
            on_error=self._corpus_collection_error,
        )

    def _corpus_collection_error(self, error: Exception) -> None:
        self.corpus_button.configure(state="normal")
        self._show_error("采集语料", error)

    def _write_corpus_result(self, result: dict) -> None:
        positive_by_risk = result.get("positiveByRisk", {})
        positive_summary = "、".join(
            f"{key}×{count}" for key, count in sorted(positive_by_risk.items())
        ) if positive_by_risk else "无"
        negative_by_language = result.get("negativeByLanguage", {})
        shortage_lines = "\n".join(
            f"  - {entry['riskId']} / {entry['language']}：目标 {entry['target']}，实际 {entry['collected']}"
            for entry in result.get("shortage", [])
        ) if result.get("shortage") else "  无（配额全部达标）"
        content = (
            "语料采集完成\n\n"
            f"批次：{result['batchId']}\n"
            f"选择：{len(result['selectedSourceIds'])} 个网站，{len(result['selectedSceneCodes'])} 个一级类别\n"
            f"配置：中文占比 {result['zhPercent']}%，每类正样本目标 {result['targetPerRisk']}，负样本目标 {result['negativeTarget']}\n\n"
            f"产出：正样本 {result['positiveCount']} 条 / 负样本 {result['negativeCount']} 条\n"
            f"正样本分布：{positive_summary}\n"
            f"负样本分布：中文 {negative_by_language.get('zh', 0)}，英文 {negative_by_language.get('en', 0)}\n\n"
            f"配额缺口：\n{shortage_lines}\n\n"
            f"正样本文件：{result['positivePath']}\n"
            f"负样本文件：{result['negativePath']}\n"
            f"运行清单：{result['manifestPath']}\n"
        )
        if result.get("shortagePath"):
            content += f"缺口报告：{result['shortagePath']}\n"
        self.corpus_result_text.configure(state="normal")
        self.corpus_result_text.delete("1.0", END)
        self.corpus_result_text.insert("1.0", content)
        self.corpus_result_text.configure(state="disabled")

    def _open_last_corpus_batch(self) -> None:
        if not self.last_corpus_batch_path:
            messagebox.showwarning("暂无输出", "请先完成一次语料采集。", parent=self)
            return
        self._open_path(Path(self.last_corpus_batch_path))

    def _apply_one_click_catalog(self, snapshot: dict) -> None:
        """把登记表中的可运行网站和五大类风险转成默认页的多选控件。"""
        catalog = snapshot.get("selectionCatalog", {})
        selection = snapshot.get("sourceSelection", {})
        selected_source_ids = set(selection.get("selectedSourceIds", []))
        selected_scene_codes = set(selection.get("selectedSceneCodes", []))
        for child in self.site_cards_frame.winfo_children():
            child.destroy()
        for child in self.scene_cards_frame.winfo_children():
            child.destroy()
        self.site_selection_vars.clear()
        self.scene_selection_vars.clear()
        self.scene_risk_counts.clear()

        sites = catalog.get("sites", [])
        selectable_sites = [site for site in sites if site.get("selectable")]
        for index, site in enumerate(selectable_sites):
            source_id = site["sourceId"]
            variable = tk.BooleanVar(value=source_id in selected_source_ids)
            self.site_selection_vars[source_id] = variable
            card = ttk.LabelFrame(self.site_cards_frame, text=source_id, padding=8)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 10) if index % 3 < 2 else 0, pady=3)
            ttk.Checkbutton(card, text=site["siteName"], variable=variable).pack(anchor=W)
            languages = " / ".join(site.get("sourceLanguages", [])) or "未标注语言"
            ttk.Label(
                card,
                text=f"{languages} · 覆盖 {site.get('coveredRiskCount', 0)} 类风险 · {site.get('runnableRouteCount', 0)} 条可运行路由",
                style="Subtle.TLabel",
            ).pack(anchor=W, pady=(3, 0))
            self.site_cards_frame.columnconfigure(index % 3, weight=1)
        unavailable_count = len(sites) - len(selectable_sites)
        self.site_note.set(f"当前可运行网站 {len(selectable_sites)} 个；另有 {unavailable_count} 个登记来源因门禁或授权状态未参与本次自动采集。")

        scenes = catalog.get("scenes", [])
        for index, scene in enumerate(scenes):
            scene_code = scene["sceneCode"]
            variable = tk.BooleanVar(value=scene_code in selected_scene_codes)
            variable.trace_add("write", lambda *_args: self._update_total_minimum())
            self.scene_selection_vars[scene_code] = variable
            self.scene_risk_counts[scene_code] = int(scene.get("riskCount", 0))
            card = ttk.LabelFrame(self.scene_cards_frame, text=scene_code, padding=8)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 10) if index % 3 < 2 else 0, pady=3)
            ttk.Checkbutton(card, text=scene["scene"], variable=variable).pack(anchor=W)
            ttk.Label(card, text=f"覆盖 {scene.get('riskCount', 0)} 类风险", style="Subtle.TLabel").pack(anchor=W, pady=(3, 0))
            self.scene_cards_frame.columnconfigure(index % 3, weight=1)
        self._update_total_minimum()

    def _selected_site_ids(self) -> list[str]:
        return sorted(source_id for source_id, variable in self.site_selection_vars.items() if variable.get())

    def _selected_scene_codes(self) -> list[str]:
        return sorted(scene_code for scene_code, variable in self.scene_selection_vars.items() if variable.get())

    def _selected_risk_count(self) -> int:
        return sum(self.scene_risk_counts.get(scene_code, 0) for scene_code in self._selected_scene_codes())

    def _set_all_site_selection(self, value: bool) -> None:
        for variable in self.site_selection_vars.values():
            variable.set(value)

    def _set_all_scene_selection(self, value: bool) -> None:
        for variable in self.scene_selection_vars.values():
            variable.set(value)

    def _update_total_minimum(self) -> None:
        if not hasattr(self, "total_spinbox"):
            return
        minimum = max(1, self._selected_risk_count())
        self.total_spinbox.configure(from_=minimum)
        try:
            current = int(self.one_click_total.get())
        except ValueError:
            current = minimum
        if current < minimum:
            self.one_click_total.set(str(minimum))

    def _run_one_click(self) -> None:
        selected_source_ids = self._selected_site_ids()
        selected_scene_codes = self._selected_scene_codes()
        if not selected_source_ids:
            messagebox.showwarning("未选择网站", "请至少选择一个可运行网站。", parent=self)
            return
        if not selected_scene_codes:
            messagebox.showwarning("未选择类别", "请至少选择一个一级风险类别。", parent=self)
            return
        try:
            total_count = int(self.one_click_total.get())
            chinese_percent = int(self.one_click_chinese_percent.get())
        except ValueError:
            messagebox.showwarning("参数错误", "生成数量和中文占比必须填写整数。", parent=self)
            return
        minimum = self._selected_risk_count()
        if total_count < minimum or total_count > 1000:
            messagebox.showwarning("数量错误", f"生成数量必须是 {minimum} 至 1000 的整数。", parent=self)
            return
        if chinese_percent < 0 or chinese_percent > 100:
            messagebox.showwarning("比例错误", "中文占比必须在 0 至 100 之间。", parent=self)
            return
        payload = {
            "batchId": self.one_click_batch.get(),
            "runDate": self.one_click_date.get(),
            "totalCount": total_count,
            "chinesePercent": chinese_percent,
            "selectedSourceIds": selected_source_ids,
            "selectedSceneCodes": selected_scene_codes,
        }
        self.one_click_button.configure(state="disabled")

        def complete(result: dict) -> None:
            self.last_output_paths = {
                "incrementalPath": result["generation"]["incrementalPath"],
                "masterPath": result["generation"]["masterPath"],
            }
            self._write_one_click_result(result)
            self.open_incremental_button.configure(state="normal")
            self.open_master_button.configure(state="normal")
            self.one_click_button.configure(state="normal")
            self.status_text.set("题库生成完成")
            self._refresh_async()

        self._run_async(
            "采集并生成题库",
            lambda: self.backend.run_one_click(payload),
            complete,
            on_error=self._one_click_error,
        )

    def _one_click_error(self, error: Exception) -> None:
        self.one_click_button.configure(state="normal")
        self._show_error("采集并生成题库", error)

    def _write_one_click_result(self, result: dict) -> None:
        collection = result["collection"]
        generation = result["generation"]
        source_counts = generation["sourceCounts"]
        selection = result["selection"]
        content = (
            "题库已生成\n\n"
            f"批次：{generation['batchId']}\n"
            f"选择：{len(selection['selectedSourceIds'])} 个网站，{len(selection['selectedSceneCodes'])} 个一级类别，覆盖 {selection['selectedRiskCount']} 类风险\n"
            f"题目：共 {generation['generatedCount']} 道（中文 {generation['chineseCount']} / 英文 {generation['englishCount']}）\n\n"
            f"受控采集：可运行路由 {collection['selectedRouteCount']}，成功 {collection['successfulRouteCount']}，失败 {collection['failedRouteCount']}，整理上下文 {collection['contextCount']} 条\n"
            f"题目来源：采集摘要 {source_counts['collected']}，人工素材 {source_counts['material']}，合成补位 {source_counts['synthetic']}\n\n"
            f"本次题库：{generation['incrementalPath']}\n"
            f"汇总题库：{generation['masterPath']}\n"
        )
        self.one_click_result_text.configure(state="normal")
        self.one_click_result_text.delete("1.0", END)
        self.one_click_result_text.insert("1.0", content)
        self.one_click_result_text.configure(state="disabled")

    def _open_last_output(self, key: str) -> None:
        output = self.last_output_paths.get(key)
        if not output:
            messagebox.showwarning("暂无输出", "请先完成一次题库生成。", parent=self)
            return
        self._open_path(Path(output))

    def _refresh_route_tree(self) -> None:
        if not hasattr(self, "route_tree"):
            return
        for item in self.route_tree.get_children():
            self.route_tree.delete(item)
        active_filter = self.source_filter.get()
        for route in self.snapshot_data.get("routes", []):
            if active_filter != "全部" and route["enableStatus"] != active_filter:
                continue
            self.route_tree.insert("", END, values=(
                route["routeId"], route["riskId"], route["siteName"], route["outputLanguage"],
                route["enableStatus"], route["verificationLevel"], route["runGate"],
            ))

    def _refresh_material_tree(self) -> None:
        for item in self.material_tree.get_children():
            self.material_tree.delete(item)
        for material in self.snapshot_data.get("materials", []):
            self.material_tree.insert("", END, iid=material["materialId"], values=(
                material["materialId"], material["riskId"], material["title"], material["extractionStatus"], material["generationStatus"],
            ))

    def _apply_selected_route(self) -> None:
        route = self.routes_by_id.get(self.intake_vars["routeId"].get())
        if not route:
            return
        self.intake_vars["sourceUrl"].set(route["entryUrl"])

    def _choose_sidecar(self) -> None:
        manual_dir = self.backend.project_root / "data" / "manual_import"
        manual_dir.mkdir(parents=True, exist_ok=True)
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择项目内 UTF-8 原文文件",
            initialdir=manual_dir,
            filetypes=[("Text or Markdown", "*.txt *.md")],
        )
        if not selected:
            return
        candidate = Path(selected)
        try:
            relative = candidate.resolve().relative_to(self.backend.project_root)
            if not str(relative).replace("\\", "/").startswith("data/manual_import/"):
                raise ValueError
        except ValueError:
            messagebox.showwarning("路径不允许", "旁车原文必须位于 data/manual_import/ 内。", parent=self)
            return
        self.intake_vars["sidecarPath"].set(relative.as_posix())

    def _submit_intake(self) -> None:
        route = self.routes_by_id.get(self.intake_vars["routeId"].get())
        if not route:
            messagebox.showwarning("缺少来源路由", "请先选择来源路由。", parent=self)
            return
        body = self.body_text.get("1.0", "end-1c")
        row = {
            "来源路由ID": route["routeId"], "来源ID": route["sourceId"], "来源链接": self.intake_vars["sourceUrl"].get(),
            "标题": self.intake_vars["title"].get(), "发布时间": self.intake_vars["publicationDate"].get(), "来源地区": route["region"],
            "来源语言": route["sourceLanguage"], "素材类型": self.intake_vars["materialType"].get(), "授权确认": self.intake_vars["authorization"].get(),
            "授权证据ID": self.intake_vars["evidenceId"].get(), "授权证据URL": self.intake_vars["evidenceUrl"].get(),
            "授权URL前缀": self.intake_vars["urlPrefix"].get(), "授权范围": self.intake_vars["scope"].get(), "确认人": self.intake_vars["confirmer"].get(),
            "确认日期": self.intake_vars["confirmationDate"].get(), "有效期": self.intake_vars["expiryDate"].get(), "风险ID": route["riskId"],
            "场景": route["scene"], "类别": route["category"], "原始正文": body, "原文文件路径": self.intake_vars["sidecarPath"].get(),
        }
        payload = {"batchId": self.intake_vars["batchId"].get(), "row": row}

        def complete(result: dict) -> None:
            self.status_text.set(f"入库完成：成功 {result.get('accepted', 0)} 条，拒绝 {result.get('rejected', 0)} 条")
            if result.get("accepted", 0):
                self.body_text.delete("1.0", END)
                self.intake_vars["sidecarPath"].set("")
            self._refresh_async()

        self._run_async("提交素材入库", lambda: self.backend.stage_intake(payload), complete)

    def _load_selected_material(self) -> None:
        selection = self.material_tree.selection()
        if not selection:
            return
        material = self.materials_by_id.get(selection[0])
        if not material:
            return
        self.edit_vars["materialId"].set(material["materialId"])
        self.edit_vars["suggestedQuestionType"].set(material["suggestedQuestionType"])
        self.edit_vars["extractionStatus"].set(material["extractionStatus"] or "待提取")
        self.edit_vars["generationStatus"].set(material["generationStatus"] or "不可生成")
        for widget, value in [
            (self.generated_material_text, material["generatedMaterial"]),
            (self.fact_points_text, material["factPoints"]),
            (self.risk_trigger_text, material["riskTrigger"]),
        ]:
            widget.delete("1.0", END)
            widget.insert("1.0", value)

    def _save_material(self) -> None:
        material_id = self.edit_vars["materialId"].get()
        if not material_id:
            messagebox.showwarning("未选择素材", "请先从素材档案选择一条记录。", parent=self)
            return
        payload = {
            "materialId": material_id,
            "generatedMaterial": self.generated_material_text.get("1.0", "end-1c"),
            "factPoints": self.fact_points_text.get("1.0", "end-1c"),
            "riskTrigger": self.risk_trigger_text.get("1.0", "end-1c"),
            "suggestedQuestionType": self.edit_vars["suggestedQuestionType"].get(),
            "extractionStatus": self.edit_vars["extractionStatus"].get(),
            "generationStatus": self.edit_vars["generationStatus"].get(),
        }

        def complete(_result: dict) -> None:
            self.status_text.set("素材提取结果已保存")
            self._refresh_async()

        self._run_async("保存提取结果", lambda: self.backend.update_material(payload), complete)

    def _open_path(self, candidate: Path) -> None:
        try:
            self.backend.open_project_path(candidate)
        except Exception as error:  # noqa: BLE001 - 向用户展示明确的路径限制或不存在原因。
            messagebox.showerror("无法打开", str(error), parent=self)


def smoke_test() -> dict:
    """不创建 Tk 窗口，供自动测试确认一键页可获得网站和五大类选择数据。"""
    backend = DesktopBackend()
    snapshot = backend.snapshot()
    return {
        "desktop_ready": True,
        "summary": snapshot["summary"],
        "workspaces": WORKSPACE_NAMES,
        "selection_catalog": snapshot["selectionCatalog"],
        "source_selection": snapshot["sourceSelection"],
    }


def main() -> None:
    if "--smoke-test" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(smoke_test(), ensure_ascii=False))
        return
    application = DesktopApplication(DesktopBackend())
    application.mainloop()


if __name__ == "__main__":
    main()
