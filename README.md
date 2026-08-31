# GenerateTestQuestion

面向内容安全测试的桌面工具：**爬取网站 → 生成题目**。从已核验的可爬站点抓取公开报道与通报，
通过 OpenAI 兼容大模型生成参照 TC260-003 风险分类的中英文测试提示集（仅题干，无选项与答案），
每道题可追溯到依据的原文。纯 Python 单栈。

## 功能

- **生成**（主页）：网站多选 → 大类/小类两级题型联动（5 大类 31 小类）→ 数量与中英文比例 → 一键生成；
  实时运行日志；原文↔题目对照区（题干、风险类别、依据原文、来源链接）。
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
