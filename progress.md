# 素材归档与人工导入进度

## 2026-08-26

### 设计确认

- **状态：** completed
- 用户已确认“原始全文层 + 生成素材层”方案。
- 已写入素材归档与人工导入设计：`docs/2026-08-27-source-items-material-archive-design.md`。

### 模板与入库实现

- **状态：** completed
- 已创建 `data/source_items.xlsx`、手工入库校验和项目内原始 JSON 档案流程。
- 素材档案是后续出题器的直接输入；完整原文不会写入该工作表。
- S12 的 V3 仅保留数据集元数据门禁，未配置可复查 JSON 分发 URL 时，全文入库会被拒绝。

## 测试结果

| 测试 | 预期 | 实际 | 状态 |
|---|---|---|---|
| `source_registry.integration.mjs` | 15 网站、31 风险、124 路由和 V3 门禁 | PASS | completed |
| `source_items.template.integration.mjs` | 5 工作表、31 风险、受控下拉和空模板计数 | PASS | completed |
| `source_items.ingest.integration.mjs` | 授权门禁、原始层边界、旁车清理、去重与恢复 | PASS | completed |

## 错误日志

| 时间 | 错误 | 尝试 | 处理 |
|---|---|---:|---|
| — | 暂无 | 0 | — |

## 2026-08-27

### 桌面端推进

- **状态：** completed
- 已采用无额外安装依赖的 Python Tkinter + Node Excel 数据服务方案，并实现了来源查看、人工素材入库、去标识化提取与题库生成四个工作区。
- 已通过界面生成首批 `BASELINE-20260827`：155 题，其中中文 124 题、英文 31 题；文件位于 `data/question_bank/`。

### 桌面端验证

| 测试 | 预期 | 实际 | 状态 |
|---|---|---|---|
| `desktop_data_service.integration.mjs` | 来源摘要、素材提取更新、人工入库和原文隔离 | PASS | completed |
| `question_bank.integration.mjs` | 155 题、31 风险、80/20 中英文、去重与可追溯来源 | PASS | completed |
| `desktop_app.smoke.py` | 本地数据桥和四个工作区可启动 | PASS | completed |
| 可视化验收 | 依次打开四个工作区并从窗口生成基线题库 | PASS | completed |

## 2026-08-28

### 一键生成与五大类多选

- **状态：** implementation completed
- 默认工作区已调整为“**一键生成**”，用户日常仅需选择可运行网站、勾选 5 个一级风险类别、填写数量和中文占比，再点击“开始采集并生成题库”。
- `来源配置` 保留登记表查看；原有人工素材导入与提取已移至 `高级维护`，不再出现在日常生成流程中。
- 当前登记表中自动可运行网站为 `S12`；用户选定的网站与一级类别没有允许路由交集时，会在发起请求前明确拒绝运行。
- 采集器仅读取允许的 HTTPS JSON 元数据，响应不保存为素材；题库按“采集摘要 → 可生成素材 → synthetic 补位”顺序填充，并输出三类来源统计。
- 批次清单保存所选网站、一级类别、题量、比例和路由指纹；同批次不同参数会在网络请求和输出发布前被拒绝。两个 Excel 发布支持失败回滚。

### 自动验证

| 测试 | 实际 | 状态 |
|---|---|---|
| `source_selection.integration.mjs` | 15 个网站目录、5 个一级类别、选择持久化与门禁 | PASS |
| `source_collector.integration.mjs` | HTTPS/JSON/响应大小/重定向门禁和白名单上下文 | PASS |
| `question_bank.integration.mjs` | 多选类别、精确比例、三类来源、清单与双工作簿回滚 | PASS |
| `one_click_run.integration.mjs` | 一键编排、来源/类别交集、采集失败补位和冲突预检 | PASS |
| `desktop_data_service.integration.mjs` | 数据桥与高级维护素材操作 | PASS |
| `source_items.ingest.integration.mjs` | 授权门禁与素材原文边界 | PASS |
| `desktop_app.smoke.py` | 一键工作区、5 类多选目录与本地数据桥 | PASS |

### 待做的人工验收

- 系统当前处于锁屏状态，尚未对新的一键默认页面执行人工可视化检查；自动烟测和端到端隔离测试均已通过。

### 合格率语料集：HTML 直采与英文批次升级

- **状态：** completed
- 中文正样本定稿 `CORPUS-20260828-ZH12377-V2`：12377 全量 157 条，10 类风险覆盖，空白噪声从 51.3% 降至 2.1%。
- 英文正样本升级 `CORPUS-20260828-EN-V2`（166 条）+ `CORPUS-20260828-EN-SNOPES`（24 条）：`extractHtmlText` 改造为优先提取 `<article>/<main>` 正文区域 + 中英文导航/样板行过滤，英文批次导航噪声降为 0，风险覆盖扩展到 7 类（含 A2-09）。
- 来源配置扩展到 9 源：新增 Snopes 事实核查（`?page={num}` 分页，article 结构，Claim/Rating 清晰）。
- 旧批次（EN-DEMO、EN-FILL、ZH12377、ZH12377-CLEAN、HTML-DEMO×2、DEMO）已归档至 `data/corpus/_archive/`，语料库保持单一有效版本。
- 集成测试 9 项全部通过，无回归。

### 负样本批量采集（4000 条）

- **状态：** completed
- 负样本循环改造为多轮请求：随机条目接口单轮 20 条，重复请求直到语言配额满（连续 3 轮零新增自动放弃），429/5xx 指数退避重试 2s→32s（连续 5 次失败才放弃），轮间 ≥500ms 礼貌延时。
- `minNegativeTextChars=80` 最小长度过滤：维基小作品（短条目）跳过并记入哈希避免重复抓取；集成测试增至 10 项全过（新增短文本过滤用例）。
- **正式批次 `CORPUS-20260828-NEG-4000` 定稿：4000/4000 全满（zh 2800 + en 1200），零缺口、零重复、全部 ≥80 字符（zh 均长 192 / en 均长 450），共过滤 1169 条小作品。**
- 风险关键词误报扫描：约 1% 负样本在百科语境命中分类器关键词，属可接受范围。
- 首轮未过滤版本已备份 `_archive/NEG-4000-run1-backup/`。
