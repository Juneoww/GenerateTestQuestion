# GenerateTestQuestion

面向内容安全测试的桌面工具：**爬取网站 → 生成题目**。从已核验的可爬站点抓取公开报道与通报，
通过 OpenAI 兼容大模型生成参照 TC260-003 风险分类的中英文测试提示集（仅题干，无选项与答案），
每道题可追溯到依据的原文。纯 Python 单栈。

## 功能

- **生成**（主页）：站点按中/英文分组折叠多选 → 大类折叠卡片 + 三态整组勾选（5 大类 31 小类）→
  数量与中英文比例 → 一键生成。选择全程实时计数，未选站点或未选小类时开始按钮置灰并提示缺什么；
  实时运行日志；原文↔题目对照区（题干、风险类别、依据原文、来源链接，题干摘要列支持横向滚动读全文）。
- **来源管理**：站点清单（状态：待核验/可爬/核验失败/停用），一键自动核验——通过即进入生成页；
  支持新增站点（HTTPS URL + 条目提取正则）。
- **设置**：模型接口地址 / API Key / 模型名 / 温度 / 超时 / 重试 / 爬取延时，测试连接。
- **全过程留痕**：网站名单、核验日志、每批次爬取内容（items.jsonl）、模型调用记录、运行日志、批次汇总。

## 快速开始

```bat
uv venv
uv pip install -p .venv/Scripts/python.exe -r requirements.txt
run.bat
```

- 首次使用先到 **设置** 页填入模型配置并「测试连接」（DeepSeek / 智谱 / 通义 / Kimi / OpenAI 等
  OpenAI 兼容接口均可，接口地址填到 /v1 等版本号一级）。
- 无界面自检：`.venv\Scripts\python app.py --smoke-test`。

## 使用说明

首次使用按 设置 → 来源管理 → 生成 的顺序配置一次；之后日常操作只集中在"生成"页。

1. **配置模型**（设置页）：填接口地址（到 /v1 一级）、API Key、模型名，点「测试连接」通过后保存。
2. **核验来源**（来源管理页）：点「核验全部」（或选中若干行后点「核验选中」）；状态变为"可爬"的站点
   才会出现在生成页。要新增站点，点「新增站点」填 HTTPS 地址与条目提取正则。
3. **选择网站**（生成页第 1 步）：点「中文站点 / 英文站点」标题展开列表，点击整行即可勾选/取消；
   工具栏提供全选 / 清空 / 全选中文 / 全选英文，标题条徽章实时显示该组"已选 n/m"。
4. **选择题型**（第 2 步）：点大类标题展开小类。标题行左侧三态框整组勾选/清空（"—"表示部分选中），
   也可在小类里单独增减；收起状态同样可以整组操作，徽章始终显示该组已选数。
5. **生成**（第 3 步）：设置生成数量（须 ≥ 所选小类数，≤ 1000）与中文占比，点「开始生成」；
   进度与错误在运行日志实时输出。页面内容超出一屏时，滚轮即可上下滚动整页。
6. **查看结果**（第 5 步）：对照区点任一题，右侧显示题干、类型、依据原文与来源链接；
   题干摘要列可向右滑动看全文。点「加载历史批次」（Ctrl+L）回看过往批次，
   右侧按钮可直达批次目录、题库 Excel 与该题来源网页。

快捷键：`Ctrl+1 / Ctrl+2 / Ctrl+3` 切换 生成 / 来源管理 / 设置 三个工作区，`Ctrl+L` 加载历史批次。

每批次产物位于 `data/output/<批次>/`：题目 Excel/JSON、爬取内容 items.jsonl、模型调用记录、
运行日志与批次汇总。

## 免安装版（Windows exe）

不想装 Python 也可以直接用打包好的单文件程序：到
[Releases](https://github.com/Juneoww/GenerateTestQuestion/releases)
下载 `GenerateTestQuestion.exe`（约 60 MB），放到任意**可写**目录（如桌面、D 盘某文件夹）双击运行。

- 首次运行会在 exe 旁边生成 `data/` 目录（内置 16 个来源站点与 TC260 风险目录）。
- 到「设置」页填入模型接口地址与 API Key，「测试连接」通过后保存即可开始生成。
- 升级：下载新版 exe 覆盖旧文件即可，`data/`（已保存的设置与历史批次）不受影响。
- 命令行自检：`GenerateTestQuestion.exe --smoke-test`，输出 JSON 即为正常。
- SmartScreen 首次可能提示"未知发布者"，点「更多信息 → 仍要运行」。

自行打包：配好虚拟环境后运行 `build_exe.bat`（PyInstaller 单文件模式），产物在 `dist/`。

## 运行要求

- Windows + Python ≥3.10（经 uv 独立环境 `.venv`）。
- 依赖：`scrapling[fetchers]`（抓取，内置指纹伪装与重试）、`openpyxl`（Excel 导出），见 `requirements.txt`。
- 项目路径含中文时，crawler 会自动把证书复制到 %TEMP% 并设置 `CURL_CA_BUNDLE`（已内置，无需处理）。

## 测试

```bash
.venv/Scripts/python -m unittest discover -s tests
```

全部测试离线可跑（mock 抓取与模型调用，无外部网络依赖）。

## 目录与数据

| 路径 | 内容 |
|---|---|
| `app.py` | Tkinter 桌面端（三页） |
| `crawler.py` | Scrapling 封装：HTTPS 门禁、同域过滤、每请求延时、条目提取、逐条落盘 |
| `question_generator.py` | OpenAI 兼容出题：提示词、JSON 校验、去重、重试、调用留痕 |
| `pipeline.py` | 批次编排：配额分配、原文轮转、熔断、缺口报告 |
| `storage.py` / `reporting.py` / `excel_export.py` | 数据读写 / 留痕文档 / Excel 导出 |
| `data/sources.json` | 来源清单（状态机：pending → ready/failed，另有 disabled） |
| `data/risk_catalog.json` | TC260 风险目录（5 大类、31 小类） |
| `data/settings.json` | 模型配置（含 API Key，不入库） |
| `data/output/<批次>/` | 题目 Excel/JSON、爬取内容、llm_calls、run.log、manifest、爬取报告 |
| `data/reports/` | 网站名单、核验日志（每次核验后刷新） |
| `data/_legacy/` | 旧版语料/题库批次归档 |

以上 `data/` 运行数据均不入 git；入库的只有代码、文档与测试。

## 来源合规

所有来源仅接受 HTTPS（443、无凭据）；抓取限同域、逐请求礼貌延时；公开可浏览不等于已获授权，
来源以公开的辟谣/监管/司法/事实核查类页面为主，仅提取标题与正文用于出题，不做整站镜像。

## 设计文档

- 需求方案：`docs/2026-08-28-crawl-to-question-rewrite-design.md`（v1.2）
- 产品设计：`docs/2026-08-31-crawl-to-question-product-design.md`
- UI 交互原型：`docs/prototype-multiselect.html`（多选框折叠卡片方案，浏览器直接打开可交互）
