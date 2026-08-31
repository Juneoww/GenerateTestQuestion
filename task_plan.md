# 爬取出题一体化改造计划

## 目标

按 `docs/2026-08-28-crawl-to-question-rewrite-design.md`（v1.2 需求）与
`docs/2026-08-31-crawl-to-question-product-design.md`（产品设计）实施：
**爬取网站 → 生成题目（测试提示集，仅题干无答案）**，纯 Python 单栈（Tkinter + Scrapling + openpyxl）。

## 当前阶段

全部核心阶段完成；待办：P1 来源扩充、P7 README 更新与首次真机验收。

## 环境

- 独立环境：uv `.venv`（Python 3.12.12），依赖 `requirements.txt`（scrapling[fetchers]==0.4.15、openpyxl>=3.1）。
- 启动：`run.bat` 或 `.venv/Scripts/python app.py`；烟测：`python app.py --smoke-test`。
- 已知修复：中文项目路径下 curl_cffi 读不了 certifi 证书（curl error 77），crawler 首次请求前把证书复制到 ASCII 路径并设 `CURL_CA_BUNDLE`。

## 阶段

### P1 来源侦察

- [ ] 调研更多辟谣/监管/司法/事实核查类站点，走核验接口自动探测
- [ ] 扩充 `data/sources.json`，刷新 `data/reports/网站名单.md`、`核验日志.md`
- 种子：9 个旧实测 HTML 源已入清单（2026-08-28），其中 12377/辟谣平台已于 08-31 用新爬虫实测核验通过

### P2 风险目录提取

- [x] `data/risk_catalog.json`（5 大类、31 小类，已校验）
- **状态：** completed 2026-08-28

### P3 爬虫实现（Scrapling）

- [x] `crawler.py`：HTTPS 门禁、Fetcher 封装、正则条目提取、同域过滤、每请求延时、
      内容哈希去重、核验四项探测、逐条落盘 `crawl/<sourceId>/items.jsonl`
- [x] 真实验证：12377-JSAL、PIAO-ZH 核验通过（2026-08-31）
- **状态：** completed 2026-08-31

### P4 LLM 出题服务

- [x] `question_generator.py`：OpenAI 兼容调用（urllib）、提示词模板、JSON 数组解析（容忍代码围栏）、
      语言占比校验、SHA-256 去重、重试、`llm_calls.jsonl` 留痕
- **状态：** completed 2026-08-31（真实模型联调待用户填入 API Key 后进行）

### P5 界面重构

- [x] 新 `app.py`：生成 / 来源管理 / 设置三页；两级题型联动；运行日志；
      原文↔题目对照区；测试连接；新增/核验/停用站点
- [x] 烟测 `tests/test_app_smoke.py` 通过
- **状态：** completed 2026-08-31（界面可视化人工验收待做）

### P6 导出与串联

- [x] `pipeline.py` 批次编排：配额拆分（半递增取整）、小类轮转、原文按来源轮转取用、
      连续 5 次空产出熔断、缺口如实报告；`excel_export.py`；manifest/爬取报告；全局哈希索引
- [x] 端到端集成测试（fake 爬虫 + fake 出题）通过
- **状态：** completed 2026-08-31

### P7 清理与交付

- [x] 旧 Node 服务/测试删除、旧数据归档 `data/_legacy/`（`corpus/_archive` 待占用释放后移动）
- [x] 全量回归：`python -m unittest discover -s tests` 35/35 通过
- [ ] README 更新（纯 Python 部署说明、uv 环境创建步骤）
- [ ] 首次带真实 API Key 的端到端出题验收

## 测试

| 套件 | 覆盖 | 状态 |
|---|---|---|
| `tests/test_quota.py` | 配额拆分边界、轮转分配求和不变量 | PASS |
| `tests/test_generator.py` | 响应解析/围栏容忍/语言校验/去重/重试留痕 | PASS |
| `tests/test_crawler.py` | 门禁/链接提取/正文样板过滤/落盘/去重/核验判定 | PASS |
| `tests/test_storage.py` | 三 JSON 读写、默认值合并、目录完整性 5/31 | PASS |
| `tests/test_reporting.py` | 名单/核验日志/爬取报告 | PASS |
| `tests/test_pipeline.py` | 端到端产物齐全、熔断、缺口、无源报错 | PASS |
| `tests/test_app_smoke.py` | 烟测 JSON | PASS |

## 已做决定

见设计文档第 3 节（v1.2）与产品设计文档第 3 节。

## 错误记录

| 时间 | 错误 | 处理 |
|---|---|---|
| 2026-08-28 | `data/corpus/_archive` 移动被拒（Permission denied，疑似 WPS/终端占用） | 保留原处，待占用释放后移入 `data/_legacy/` |
| 2026-08-31 | venv 在中文路径下 curl_cffi 证书加载失败（curl error 77） | crawler 启动时复制证书到 %TEMP% 并设 `CURL_CA_BUNDLE` |
| 2026-08-31 | 配额 0.5 被银行家舍入舍向偶数 | `split_language_quota` 改为半递增取整 `int(x+0.5)` |
