# 一键来源到题库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日常操作收敛为“选择网站与一级风险类别、设置数量和中文比例、一次点击生成题库”。

**Architecture:** Node 侧分为来源选择持久化、受控 JSON 采集、题库编排三个边界；Python Tkinter 仅展示极简页面并调用单一编排命令。采集上下文不保存原始响应，题库生成器合并采集上下文、既有可生成素材和显式 synthetic 补位，所有发布使用项目内临时文件和原子替换。

**Tech Stack:** Python 3.13 标准库 Tkinter、Node.js 内置 fetch/crypto/fs、现有 `@oai/artifact-tool`、Node `assert` 集成测试。

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `tools/source_selection_service.mjs` | 从登记表整理站点/五类风险选择器数据，读写 `data/source_selection.json`。 |
| `tools/source_collector_service.mjs` | 只抓取允许路由的 JSON、提取白名单上下文、写入 `data/collected_contexts/`。 |
| `tools/one_click_run_service.mjs` | 校验用户参数、编排选择→采集→题库生成并返回用户可见统计。 |
| `tools/question_bank_service.mjs` | 支持已选风险集合、中文比例、采集上下文、来源明细、批次清单和原子 Excel 发布。 |
| `tools/desktop_data_service.mjs` | 扩展快照，返回站点、一级场景和已保存选择；保留高级人工素材操作。 |
| `app.py` | 默认显示“一键生成”，将人工素材页面移动到“高级维护”。 |
| `tests/source_selection.integration.mjs` | 验证站点/场景目录与项目内选择保存。 |
| `tests/source_collector.integration.mjs` | 使用注入 fetch mock 验证门禁、HTTP/重定向/大小/JSON 处理和上下文边界。 |
| `tests/one_click_run.integration.mjs` | 验证选类、比例、批次指纹、来源统计和失败时不发布半成品。 |
| `tests/desktop_app.smoke.py` | 验证新的默认工作区、五类选择器和无窗口启动摘要。 |

不创建 Git 提交：用户只授权了项目实现，没有授权改写仓库历史。

### Task 1: 建立来源选择目录与持久化

**Files:**
- Create: `tools/source_selection_service.mjs`
- Create: `tests/source_selection.integration.mjs`
- Modify: `tools/desktop_data_service.mjs`

- [x] **Step 1: 写失败的来源选择集成测试**

在临时项目副本中断言目录含 15 个站点、5 个稳定场景（`A.1`–`A.5`）、31 个风险；仅有允许且已启用来源可选；默认场景为五类全选。每个站点还须返回语言、覆盖风险数、运行状态和最近运行摘要所需字段。另断言未知场景、未知来源、候选/门禁未启用来源、空列表均被 `saveSourceSelection()` 拒绝。

```js
const catalog = await getSelectionCatalog(testRoot);
assert.equal(catalog.scenes.length, 5);
assert.deepEqual(catalog.defaultSceneCodes, ["A.1", "A.2", "A.3", "A.4", "A.5"]);
assert.equal(catalog.sites.filter((site) => site.selectable).length, 1);
```

- [x] **Step 2: 运行失败测试**

Run: `node tests/source_selection.integration.mjs`  
Expected: FAIL，因为选择服务不存在。

- [x] **Step 3: 实现最小选择服务**

实现 `getSelectionCatalog(projectRoot)`、`readSourceSelection(projectRoot)`、`saveSourceSelection(projectRoot, payload)`：

```js
const selectedSceneCodes = [...new Set(payload.selectedSceneCodes)].sort();
const selectedSourceIds = [...new Set(payload.selectedSourceIds)].sort();
if (!selectedSceneCodes.length) throw new Error("至少选择一个一级风险类别");
if (!selectedSourceIds.length) throw new Error("至少选择一个可运行网站");
if (!selectedSceneCodes.every((code) => sceneCodeSet.has(code))) throw new Error("包含未知一级风险类别");
if (!selectedSourceIds.every((id) => selectableSourceIds.has(id))) throw new Error("包含不可运行网站");
```

站点可选性必须由该站点下是否存在 `enableStatus.startsWith("已启用") && runGate.startsWith("允许：")` 的路由计算；保存 JSON 时只写格式版本、选择列表和保存时间。

- [x] **Step 4: 扩展桌面快照并运行通过测试**

`getDesktopSnapshot` 返回 `sourceSelection` 和 `selectionCatalog`，但不返回正文。  
Run: `node tests/source_selection.integration.mjs`  
Expected: PASS。

### Task 2: 编写受控 JSON 采集器

**Files:**
- Create: `tools/source_collector_service.mjs`
- Create: `tests/source_collector.integration.mjs`

- [x] **Step 1: 写失败的采集器测试**

用可注入 `fetchImpl` 的 mock 验证：允许 HTTPS 默认/443 路由只请求一次；HTTP、非 443 端口或门禁不允许的路由在请求前被拒绝且 `fetchImpl` 零调用；重定向、非 JSON、超 1 MiB 和超时不会创建上下文；输出 JSON 包含跳过/失败原因而不含原始响应字段。另验证 BFS 深度/容器/每路由上下文上限、字段优先级、标题和描述截断、固定入口 URL、`CTX-` 去重。

```js
const result = await collectSelectedSources({
  projectRoot: testRoot,
  batchId: "RUN-001",
  selectedSourceIds: ["S12"],
  selectedSceneCodes: ["A.3"],
  fetchImpl: fakeFetch,
});
assert.equal(result.contexts.length, 1);
assert.ok(!JSON.stringify(result).includes("fullText"));
```

- [x] **Step 2: 运行失败测试**

Run: `node tests/source_collector.integration.mjs`  
Expected: FAIL，因为采集器模块不存在。

- [x] **Step 3: 实现路由过滤与请求边界**

实现 `collectSelectedSources()` 与 `extractContextsFromJson()`：

```js
const parsedUrl = new URL(route.entryUrl);
const routeAllowed = parsedUrl.protocol === "https:"
  && (parsedUrl.port === "" || parsedUrl.port === "443")
  && route.enableStatus.startsWith("已启用")
  && route.runGate.startsWith("允许：")
  && selectedSourceIds.includes(route.sourceId)
  && selectedSceneCodes.includes(route.riskId.split("-")[0]);

const response = await fetchImpl(route.entryUrl, {
  method: "GET",
  redirect: "error",
  headers: { "user-agent": "GenerateTestQuestion/1.0" },
  signal: AbortSignal.timeout(12_000),
});
```

流读取累计字节数，超过 1 MiB 立即中止；只接受 `application/json` 或 `+json`。采用规格中的 BFS/字段白名单/`CTX-` 哈希规则，写入 `data/collected_contexts/<batchId>.json`，并使用临时 `.tmp` 后 `rename` 发布。

- [x] **Step 4: 运行采集器测试**

Run: `node tests/source_collector.integration.mjs`  
Expected: PASS，所有失败原因明确且输出没有 HTML/全文。

### Task 3: 重构题库生成契约

**Files:**
- Modify: `tools/question_bank_service.mjs`
- Modify: `tests/question_bank.integration.mjs`

- [x] **Step 1: 写失败的可选场景与比例测试**

在隔离副本中调用生成器，传入全部五类、155、80；断言 124/31、31 风险、每类 5/1 英。再传入 `A3`、10、50，断言只输出 A3 风险且语言目标严格等于 5/5；覆盖批次 ID、日期和比例的非法值、采集/人工/合成三类来源精确统计、以及“采集全失败但人工素材存在”不得误报为全部合成。

```js
assert.equal(result.chineseCount, Math.round(target * chinesePercent / 100));
assert.ok(records.every((record) => record["风险ID"].startsWith("A3-")));
assert.equal(new Set(records.map((record) => record["来源类型"])).size, 1);
```

- [x] **Step 2: 运行失败测试**

Run: `node tests/question_bank.integration.mjs`  
Expected: FAIL，因为旧生成器固定 31 类、5 槽和 155 上限。

- [x] **Step 3: 扩展题库记录与分配器**

在现有题库列末尾追加 `来源类型`、`来源上下文ID`、`素材ID`，保持旧列顺序。新增：

```js
const chineseCount = Math.round(target * chinesePercent / 100);
const selectedRisks = risks.filter((risk) => sceneCodes.includes(risk.sceneCode));
if (target < selectedRisks.length) throw new Error("生成数量不能小于已选风险类别数");
```

稳定风险轮询与均匀语言槽位必须精确满足目标数；每次优先同风险的 collected context，再使用同风险 material，最后 synthetic。合成记录固定写 `synthetic://<risk>/<lang>/<sequence>`。

- [x] **Step 4: 实现批次清单与原子发布**

将规范化参数和所选路由指纹保存为 `data/question_bank/<batchId>/run_manifest.json`。`batchId`、日期和比例必须先严格校验；同批参数不一致直接失败。两个 `.xlsx` 先写至同目录临时文件，重新导入并检查行数后进入事务：为既有增量/汇总创建项目内备份，依次替换两文件；若任一次替换失败，恢复两个备份（原先不存在的文件则删除新文件），最后清理临时与备份。测试中注入“首个替换成功、第二个替换失败”，断言两个既有文件字节均不变。

- [x] **Step 5: 运行题库测试**

Run: `node tests/question_bank.integration.mjs`  
Expected: PASS，覆盖来源统计、重跑、分组、比例与原子保护。

### Task 4: 添加单一编排命令

**Files:**
- Create: `tools/one_click_run_service.mjs`
- Modify: `tools/desktop_data_service.mjs`
- Modify: `tests/one_click_run.integration.mjs`

- [x] **Step 1: 写失败的编排测试**

断言一次 `runOneClickGeneration()` 调用会保存选择、采集上下文、生成题库，并返回 `collection` 与 `generation` 两段统计。无选择、空场景、数量不足、无可运行来源和批次冲突不得创建新的 xlsx；其中“无可运行来源”必须通过选择一个全局可运行、但对当前所选一级类别没有允许路由的网站来验证。还须覆盖所有采集失败但仍由人工素材或 synthetic 完整出库的情况，以及三类来源统计的精确和。另覆盖：总题量必须为整数且范围为“已选风险数–1000”、中文占比必须为 0–100 整数、日期必须为真实存在的 `YYYY-MM-DD` 日历日期。

- [x] **Step 2: 运行失败测试**

Run: `node tests/one_click_run.integration.mjs`  
Expected: FAIL，因为编排服务不存在。

- [x] **Step 3: 实现编排服务和 CLI**

`runOneClickGeneration()` 先完整校验批次 ID、真实日历日期、选类、整数题量与整数比例，再根据“来源已启用 + 门禁允许 + 来源ID已选择 + 场景ID已选择”计算可运行路由交集；交集为空则拒绝运行。通过后才调用选择服务、采集器与题库生成器。将 CLI 动作暴露为：

```text
node tools/one_click_run_service.mjs --payload-file data/.ui_requests/<id>.json
```

请求文件路径必须复用现有项目内限制；返回 JSON 只含统计、路径和可显示错误原因。

- [x] **Step 4: 运行编排测试**

Run: `node tests/one_click_run.integration.mjs`  
Expected: PASS。

### Task 5: 重做 Tkinter 默认页面

**Files:**
- Modify: `app.py`
- Modify: `tests/desktop_app.smoke.py`

- [x] **Step 1: 写失败的桌面烟测**

更新断言，期待默认工作区为 `一键生成`，并在 smoke JSON 中暴露五个场景和来源选择摘要；不再要求默认页含人工素材页。

- [x] **Step 2: 运行失败测试**

Run: `python tests/desktop_app.smoke.py`  
Expected: FAIL，因为当前工作区仍为四个旧标签。

- [x] **Step 3: 实现极简默认页**

保留 `来源配置` 与 `高级维护`，但将首个标签替换为 `一键生成`。该页需包含：

```text
网站卡片（仅可运行来源）复选列表 + 全选可用按钮 + 来源语言筛选 + 每站覆盖风险数/运行状态/最近结果
不可用来源摘要 + “打开来源登记表”入口
五个一级类别 Checkbutton（默认全选）
数量 Spinbox(动态最小值=已选风险数，最大1000) + 中文占比整数 Spinbox(0–100) + 日期 + 批次
“开始采集并生成题库”按钮 + 结构化结果摘要
```

通过 `DesktopBackend.run_one_click(payload)` 调用编排服务；场景勾选变化时动态更新最小题量并保留合法值，执行期间禁用主按钮，完成后显示来源统计和两个可打开路径。原人工素材页重命名为 `高级维护`，不改变其现有授权校验。

- [x] **Step 4: 运行烟测与静态编译**

Run: `python -m py_compile app.py && python tests/desktop_app.smoke.py`  
Expected: PASS。

### Task 6: 端到端验证与可视化验收

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [x] **Step 1: 运行完整回归**

Run:

```powershell
node tests/source_selection.integration.mjs
node tests/source_collector.integration.mjs
node tests/question_bank.integration.mjs
node tests/one_click_run.integration.mjs
node tests/source_items.ingest.integration.mjs
python tests/desktop_app.smoke.py
```

Expected: 全部 PASS。

- [ ] **Step 2: 启动并可视化检查（当前系统锁屏，待解锁后执行）**

Run: `python app.py`  
检查默认页中网站选择、五类多选、数量/比例和主按钮；以隔离模拟采集结果运行一次，确认输出统计与 Excel 路径一致。

- [x] **Step 3: 更新进度文档**

记录已完成的一键流程、当前登记表只允许的站点数量、合成补位口径和所有测试结果。
