# 爬取出题一体化改造计划

## 目标

按 `docs/2026-08-28-crawl-to-question-rewrite-design.md`（v1.2 需求）与
`docs/2026-08-31-crawl-to-question-product-design.md`（产品设计）实施：
**爬取网站 → 生成题目（测试提示集，仅题干无答案）**，纯 Python 单栈（Tkinter + Scrapling + openpyxl）。

## 当前阶段

P1–P6 全部完成。剩余（用户侧）：填入模型 API Key 做首次真实出题联调、界面可视化人工验收；
（工程侧小尾巴）：`corpus/_archive` 待占用释放后归档、仓库 README 已更新待推送确认。

## 环境

- 独立环境：uv `.venv`（Python 3.12.12），依赖 `requirements.txt`（scrapling[fetchers]==0.4.15、openpyxl>=3.1）。
- 启动：`run.bat` 或 `.venv/Scripts/python app.py`；烟测：`python app.py --smoke-test`。
- 已知修复：中文项目路径下 curl_cffi 读不了 certifi 证书（curl error 77），crawler 首次请求前把证书复制到 ASCII 路径并设 `CURL_CA_BUNDLE`。

## 阶段

### P1 来源侦察

- [x] 候选站点探查（HTML 链接结构分析）与批量自动核验：**7/7 通过**（2026-08-31）
- [x] `data/sources.json` 扩充至 16 源：中文新增网信办 CAC-ZH、国家版权局 NCAC-ZH、中消协 CCA-ZH；
      英文新增 PolitiFact、FactCheck.org、AFP、Truth or Fiction
- [x] `data/reports/网站名单.md`、`核验日志.md` 已生成（本地留痕，不入库）
- 本轮失败候选（仅记日志）：市监总局、证监会（列表页 JS 壳）、Lead Stories（403 反爬，
  后续可配 stealthy 引擎重试）
- **状态：** completed 2026-08-31

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
- [x] 旧 `app.py` 已被三页新版重写（不再引用 tools/）
- [x] README 更新（纯 Python 部署说明、uv 环境创建步骤）
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

## 2026-09-24：v3.0.0 方案阶段

- [x] 完成现有 Tkinter 桌面端、批次链路、Excel 导出、PyInstaller 配置及测试基线审计。
- [x] 已建立项目 CodeGraph 索引，供后续定位 UI、生成、导出和打包影响面。
- [x] 已按 OWASP 官方 2026 目录核对风险编号，确认其顺序不能沿用早期草案。
- [x] 已输出待评审设计稿：`docs/V3.0.0/V3.0.0-OWASP-LLM-2026-设计方案.md`。
- [x] 用户确认“一个桌面工具、TC260/OWASP 两个工作区、两条独立 pipeline”的原型方向。
- [x] 已完成 P0 独立 Tkinter 原型、启动 BAT 与回归验证；未修改 v2 业务代码。
- [x] 用户已确认输出收敛：OWASP 原型保留风险编号、风险名称和可复制提示词契约；不再输出富 `testCases`、详情区或 Excel 三表。风险编号与名称独立保存，不做硬编码绑定。
- [x] 已完成 P0.2 风险编号与名称解耦：JSON/Excel/UI 均为六字段，未来 `LLM99` 等编号和新名称可独立通过校验；保持跨会话镜像规则。
- [x] 用户已确认极简六字段方向，并完成 P1 正式生成路径与真实 JSON / Excel 导出实现。

## 2026-09-28：v3.0.0 P1 正式功能

- [x] 当时新增 `owasp_prompt_generator.py` 固定蓝图版；该阶段已被 2026-09-29 的模型生成版替换，以下 P1 记录仅作历史留痕。
- [x] 新增 `owasp_export.py`：实际 `openpyxl` 单表导出，表头固定为“风险编号 / 风险名称 / userA / userB / prompt / 断言”。
- [x] 新增 `owasp_pipeline.py`：不调用 TC260、爬虫或目标系统；完整产物先写隐藏暂存目录，再以目录级原子发布避免半成品。
- [x] 在 `app.py` 接入“OWASP 红队提示词”独立标签页和专属后台事件；失败会清空上一批 JSON / Excel / 复制动作，避免误操作旧产物。
- [x] 版本升级为 3.0.0；109/109 离线单元测试、编译、烟测和 diff 检查均通过；正式窗口已启动供人工查看。

## 2026-09-29：v3.0.0 OWASP 模型生成版（当前）

- [x] 用户确认复用 TC260 的 OpenAI 兼容模型接口、设置、调用日志和批次导出体验；OWASP 仍不读取网站素材或自动调用被测系统。
- [x] 依照 `docs/superpowers/plans/2026-09-29-owasp-model-generated-prompts.md` 完成公共聊天接口、可变风险系统提示词、六字段校验、全批次去重、有限补生成、审计日志、单表 Excel 与 Tkinter 工作区集成。
- [x] 按 [OWASP 2026 官方资源](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) 更正 LLM03–LLM10 的风险映射；LLM08 为 Hidden Context Exposure。LLM02 只允许 A 含虚构秘密，B 不得预先复述明显秘密标识。
- [x] 使用当前配置的生成模型做真实抽样：十类混合 10 条、中文 LLM02 三条和英文 LLM02 两条均生成；样本属于待人工验证的红队候选提示词，不代表目标系统漏洞。可用示例批次见 `data/output/live-validation/OWASP-20260929-131351`、`OWASP-20260929-130756`、`OWASP-20260929-130824`。
- [x] 更新当前使用说明并标记旧固定蓝图、多步骤／三表设计为历史记录。
- [x] 主代理完成最终编译、155/155 全量测试、烟测、`git diff --check`、真实模型混合批次与 JSON/Excel 一致性核对；综合代码审查的三项重要问题与输出目录切换后的打开路径问题均已修复并复审通过。
- [ ] 在用户桌面运行 `run.bat` 完成人工点击验收；当前工具会话可启动 Tk 进程但无法取得可见窗口句柄，不能代替人工窗口验收。

## 2026-09-29：OWASP 页面日志与 Excel 入口调整

- [x] 核对现有 UI、事件、设置目录与 Excel 自动产出路径；用户确认参照 TC260 的「打开题库 Excel」，无需另存为。
- [x] 固化短设计：`docs/superpowers/specs/2026-09-29-owasp-workspace-log-excel-design.md`。
- [x] 补 UI 失败测试：移除授权门禁、独立运行日志、结果标题、可见 Excel 按钮与整页滚动。
- [x] 修改 `app.py`，保持 OWASP 生成／导出契约不变；同步 README 和使用说明。
- [x] 运行定向及全量测试、编译、烟测、diff 检查，完成复审；最终 162/162 通过。
