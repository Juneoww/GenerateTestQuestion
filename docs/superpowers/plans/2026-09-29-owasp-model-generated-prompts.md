# OWASP 模型生成提示词 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @test-driven-development task by task. This plan runs in the current shared workspace because the user is reviewing the desktop app here. Do not commit, reset, delete unrelated files, or overwrite existing user changes unless the user explicitly asks.

**Goal:** 将 v3 OWASP 工作区从离线固定蓝图替换为复用 TC260 OpenAI 兼容模型配置的真实提示词生成流程，同时保持最终 JSON / Excel 的六字段契约。

**Architecture:** OWASP 不复用 TC260 的网页爬取、网页素材或 generate_questions() 单题契约；它复用 TC260 的聊天接口、模型设置、重试语义、调用日志、运行日志和批次产物体验。程序稳定分配每项风险的条数，并以可变系统提示词要求模型返回最终六字段 JSON；生成器做身份、语言、跨会话、占位符和去重校验，只重试不足的风险项。OWASP 批次仍以隐藏暂存目录一次发布 JSON / Excel 成对产物，失败时只保留日志和失败 manifest。

**Tech Stack:** Python 3.12、Tkinter、现有 OpenAI 兼容 urllib 客户端、unittest / unittest.mock、openpyxl。

---

## 文件边界

| 文件 | 责任 |
|---|---|
| question_generator.py | 将现有聊天请求与 JSON 数组解析暴露为可复用公共函数；保留 TC260 的 _chat / _parse_array 调用兼容性。 |
| owasp_prompt_generator.py | 保存 Top 10 选择目录、交互模式、可变系统提示词构造、模型候选解析、严格校验、去重、稳定分配和有限补充请求。不能保留任何最终 prompt 的固定蓝图。 |
| owasp_pipeline.py | 复用设置、事件日志、调用日志、模型生成、隐藏暂存发布和失败诊断批次。 |
| app.py | OWASP 页面检查模型配置，传递完整设置并继续使用独立后台事件与六列结果表。 |
| tests/test_generator.py | 覆盖新公共聊天 / JSON 解析入口不破坏 TC260 兼容行为。 |
| tests/test_owasp_prompt_generator.py | 使用假聊天函数冻结动态系统提示词、模型输出契约、分配、去重和重试。 |
| tests/test_owasp_pipeline.py | 使用假聊天函数验证真实模型批次编排、日志、成功 / 失败产物和无爬取依赖。 |
| owasp_export.py、tests/test_owasp_export.py | 将旧固定蓝图样本改为假模型返回的六字段样本，验证混合批次 Excel / JSON 的导出格式，并将模型文本作为字面字符串保存，防止 Excel 公式解释。 |
| tests/test_app_owasp.py | 验证模型配置门禁、传参、失败状态与六列表 UI。 |
| README.md、CHANGELOG.md、docs/使用说明.md、docs/V3.0.0/*、progress.md、findings.md、task_plan.md | 将“离线蓝图、不需要 API”改为真实模型生成规则，并记录验证结果。 |

## Task 1: 先暴露 TC260 已有的聊天 / JSON 公共能力

**Files:**
- Modify: question_generator.py
- Modify: tests/test_generator.py

- [x] **Step 1: 写出公共 JSON 解析入口的失败测试**

在 tests/test_generator.py 添加：

    def test_parse_json_array_public_entry_keeps_code_fence_tolerance(self):
        self.assertEqual(
            gen.parse_json_array('```json\n[{"question": "测试"}]\n```'),
            [{"question": "测试"}],
        )

并增加断言：gen.chat_completion 存在，TC260 仍可用现有 _chat mock 运行 generate_questions()。

- [x] **Step 2: 运行定向测试确认 Red**

Run: .venv\Scripts\python.exe -m unittest tests.test_generator.GeneratorTests.test_parse_json_array_public_entry_keeps_code_fence_tolerance -v
Expected: 因 parse_json_array 不存在而失败。

- [x] **Step 3: 以兼容方式提取公共函数**

在 question_generator.py 中实现：

    def chat_completion(settings: dict, messages: list[dict]) -> str:
        # 移入原 _chat 的 urllib /chat/completions 实现
        ...

    def _chat(settings: dict, messages: list[dict]) -> str:
        return chat_completion(settings, messages)

    def parse_json_array(content: str) -> list:
        # 移入原 _parse_array 的代码围栏容忍与数组检查
        ...

    def _parse_array(content: str) -> list:
        return parse_json_array(content)

generate_questions()、test_connection() 继续调用 _chat / _parse_array，确保已有 TC260 mock 和调用行为不变。

- [x] **Step 4: 运行生成器回归确认 Green**

Run: .venv\Scripts\python.exe -m unittest tests.test_generator -v
Expected: 新公共入口与现有 TC260 生成器测试全部通过。

## Task 2: 用失败测试替换固定蓝图为可变系统提示词模型生成器

**Files:**
- Modify: owasp_prompt_generator.py
- Modify: tests/test_owasp_prompt_generator.py

- [x] **Step 1: 把静态蓝图测试替换为模型输出的失败测试**

保留目录、六字段通用校验和未来 LLM99 / 新名称不绑定测试；删除对固定 2356、TEST-LLM01-ALLOW 等模板文本的断言。新增一个队列型假聊天函数，测试：

    records = generate_prompt_records(
        ["LLM01", "LLM02"], total=3, language="中文", settings=SETTINGS,
        chat_fn=fake_chat,
    )
    assert [r["riskId"] for r in records] == ["LLM01", "LLM02", "LLM01"]
    assert records[1]["prompt"] == records[1]["userB"]
    assert records[0]["userA"] == records[0]["userB"] == ""

还要覆盖：

- 构造出的系统消息含当前 riskId、riskName、对应风险的可操作测试目标、语言、待生成数量、交互模式和“不得复用”约束，且不含网页素材；LLM02 明确要求 A 给出具体虚构秘密、B 跨会话索取该秘密，而非两段无关闲聊；
- 模型返回的风险身份错误、额外字段、空字段、占位符、语言错误、会话镜像错误或重复记录都会被拒绝；
- 每项风险按 base + 余数给目录前项分配，最终按目录顺序轮转交错；total 小于已选风险数在模型调用前失败；
- 初次候选不足时仅请求该风险剩余数量，并将已接受内容加入下一次系统消息；
- 全批次 `prompt` 规范化后唯一；跨会话只改 User A、却重复 User B 的响应不得被接受；跨风险相同 prompt 也不得重复；
- 近期避免重复摘要有固定字符上限，大批量生成不造成请求文本随累计结果无界增长；
- 中文、英文和中英混合规则作用于每条可复制输入本身，不能靠断言文本掩盖输入语言错误；模型返回非字符串或聊天接口抛出 JSON 解析错误时仍记录调用并按上限重试；
- maxQuestionsPerItem=2、目标为 3 时有 2 轮常规请求，另加至多 3 轮恢复请求；历史设置的 maxQuestionsPerItem=0 必须按 1 安全钳制；每轮失败至多使用 retries + 1 次聊天尝试；上限耗尽抛出明确异常而不返回固定模板。

- [x] **Step 2: 运行定向测试确认 Red**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_prompt_generator -v
Expected: 旧 generate_prompt_records() 不接受 settings / chat_fn，动态系统提示词与重试断言失败。

- [x] **Step 3: 实现最小的模型生成与校验边界**

将 _BLUEPRINTS 删除，保留 OWASP_RISKS 作为目录并为每项增加仅供生成用的 interactionMode（当前仅 LLM02 为 cross-session）。实现：

    def build_owasp_messages(
        risk: dict[str, str], language: str, count: int,
        accepted_records: list[dict[str, str]],
    ) -> list[dict[str, str]]: ...

    def generate_prompt_records(
        risk_ids: list[str], total: int, language: str, settings: dict,
        chat_fn: Callable[[dict, list[dict]], str] = question_generator.chat_completion,
        record_call: Callable[[dict], None] | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> list[dict[str, str]]: ...

系统消息必须明确：仅授权隔离测试、禁止真实个人数据、返回最终六字段 JSON 数组、禁止 Markdown / 解释、指定风险身份与具体测试目标、指定语言、指定模式、跨会话 prompt == userB 规则和同批去重要求。测试目标是可变提示词的约束，不得成为固定成品 prompt。用户消息只发出生成请求，不能携带网页素材。调用 question_generator.parse_json_array() 解析；每次模型请求数量使用 max(1, int(settings["maxQuestionsPerItem"]))，防止历史零值造成零条请求循环。

实现 _validate_expected_candidate()：先调现有 validate_prompt_record()，再检查候选身份与当前风险、模式、可复制输入的语言和占位符；全批次以规范化 prompt 去重，跨会话再以规范化 (userA, userB) 对去重。给模型的已接受内容仅取有界近期摘要，完整去重集合保留在内存。用目录顺序进行均分和最终轮转交错。聊天调用记录包含 model、riskId、language、asked、got、status、attempt、promptChars、error，但不含最终 JSON / Excel 外的字段。

- [x] **Step 4: 运行 OWASP 生成器测试确认 Green**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_prompt_generator -v
Expected: 所有动态消息、模型返回、重试、去重和契约测试通过；无网络请求。

## Task 3: 把 OWASP 批次改造成与 TC260 相同的模型设置 / 留痕骨架

**Files:**
- Modify: owasp_pipeline.py
- Modify: owasp_export.py
- Modify: tests/test_owasp_pipeline.py
- Modify: tests/test_owasp_export.py

- [x] **Step 1: 写模型批次与失败审计的失败测试**

将 run_batch 测试改为使用：

    summary = owasp_pipeline.run_batch(
        params, SETTINGS, events.append, now_fn=clock, chat_fn=fake_chat,
    )

断言成功批次：

- 不调用 crawler.crawl_source、pipeline.run_batch 或 question_generator.generate_questions；
- 使用传入的设置、生成模型的假响应，写出六字段 JSON / 单表 Excel；
- 写出 run.log、llm_calls.jsonl 和带模型、每项风险 target / generated / calls 的 manifest；
- 同秒批次不覆盖。

增加失败测试：模型配置缺失时不创建目录；模型重试耗尽时最终目录只含 manifest.json、run.log、llm_calls.jsonl，不含 JSON / Excel；JSON、Excel 或目录发布失败时同样不暴露任一最终交付文件且保留已有审计日志。

同步把 tests/test_owasp_export.py 中依赖旧三参数离线生成器与固定样本 ID 的用例改为假模型响应，继续核对六列 Excel 与 JSON 的内容。
增加 `=1+2` 开头的 prompt、User A/B 和断言样本，回读单元格必须是字面字符串而非公式。

- [x] **Step 2: 运行定向测试确认 Red**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_pipeline tests.test_owasp_export -v
Expected: 旧 run_batch(params, output_root) 参数与离线生成假设不匹配。

- [x] **Step 3: 最小化改造独立批次管线**

将签名改为：

    def run_batch(
        params: dict, settings: dict, on_event: Callable[[dict], None],
        now_fn: Callable[[], datetime] | None = None,
        chat_fn: Callable[[dict, list[dict]], str] = question_generator.chat_completion,
    ) -> dict: ...

先在创建批次目录前验证 baseUrl 与 model、风险、数量和语言。以 TC260 _EventTee 等价的小型本地实现同时写 run.log 与 UI 事件。把 record_call 传入模型生成器，追加 llm_calls.jsonl。成功时在隐藏暂存目录写 JSON、Excel、成功 manifest、两个日志并目录级发布。

失败时创建同批次的失败诊断目录，把已有 run.log / llm_calls.jsonl 从暂存区迁入（若尚未生成则创建空文件），写失败 manifest，并确保 jsonPath / xlsxPath 为空且没有最终 JSON / Excel。保持 resolve_output_dir(settings) 的 TC260 设置语义、OWASP-… 唯一目录规则和无爬取依赖。
导出器须把全部模型可控字段强制写成 Excel 字符串单元格；不得让以 `=` 开头的提示词或断言变成公式。

- [x] **Step 4: 运行批次测试确认 Green**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_pipeline tests.test_owasp_export -v
Expected: 成功批次、模型失败、导出失败、日志、原子发布和无 TC260 / 爬虫调用的测试全部通过。

## Task 4: 让 OWASP UI 使用 TC260 的模型设置与批次体验

**Files:**
- Modify: app.py
- Modify: owasp_pipeline.py（仅给进度事件添加 OWASP 来源标识，供界面分流）
- Modify: tests/test_app_owasp.py
- Modify: tests/test_owasp_pipeline.py（验证进度事件标识）
- Modify: tests/test_app_smoke.py（仅在烟测字段需要变化时）

- [x] **Step 1: 写 UI 模型门禁与新参数的失败测试**

新增 / 调整以下断言：

    with patch.object(app.storage, "load_settings", return_value={"baseUrl": "", "model": ""}):
        window._start_owasp_batch()
    messagebox.showwarning.assert_called_once()

    with patch.object(app.owasp_pipeline, "run_batch", side_effect=fake_run) as run:
        window._start_owasp_batch()
    run.assert_called_once_with(expected_params, expected_settings, window.events.put)

继续断言页面六列不变、OWASP 不调用 TC260 pipeline.run_batch / generate_questions() / crawler、失败清空旧产物动作。
补测数量从无效改为有效后按钮立即启用、切换语言后摘要即时更新，以及 OWASP 生成进度在状态栏可见而不混入 TC260 日志。

- [x] **Step 2: 运行 UI 测试确认 Red**

Run: .venv\Scripts\python.exe -m unittest tests.test_app_owasp -v
Expected: 旧页面只解析输出根目录并传入离线 run_batch，模型配置门禁与参数断言失败。

- [x] **Step 3: 最小化更新 UI 调度与文案**

在 _start_owasp_batch() 中加载完整设置并要求 baseUrl、model 非空；将其直接传给新 OWASP 管线和 self.events.put。更新页面说明、就绪提示和完成提示，删除“不需要 API Key / 离线蓝图”表述，改为“使用设置页模型生成；不读取网站、不自动发送给被测系统”。设置页的 maxQuestionsPerItem 标签改为同时适用于 TC260 与 OWASP 的“单次请求最多生成条数”。保留风险选择、数量、语言、隔离确认、六列表、双击复制及批次 / JSON / Excel 打开按钮，且不增加详情区。
数量与语言变量变化时刷新选择摘要和开始按钮状态；OWASP 批次事件带独立来源标识，界面收到后更新全局状态栏、不要追加到 TC260 页日志，最终运行日志仍由管线保存。

- [x] **Step 4: 运行 UI 与烟测确认 Green**

Run:

    .venv\Scripts\python.exe -m unittest tests.test_app_owasp tests.test_app_smoke -v
    .venv\Scripts\python.exe app.py --smoke-test

Expected: UI 控件测试通过；烟测仍不触发模型调用并报告 v3.0.0 / OWASP 工作区。

## Task 4.5: 校正 OWASP 官方 2026 风险编号与生成目标

**Files:**
- Modify: owasp_prompt_generator.py
- Modify: tests/test_owasp_prompt_generator.py

- [x] **Step 1: 写官方 2026 映射的失败测试**

根据 [OWASP 官方 2026 版 PDF](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) 锁定英文名称：LLM01 Prompt Injection、LLM02 Sensitive Information Disclosure、LLM03 Excessive Agency、LLM04 Supply Chain、LLM05 Data and Model Poisoning、LLM06 Unbounded Consumption、LLM07 Misinformation、LLM08 Hidden Context Exposure、LLM09 Vector and Embedding Weaknesses、LLM10 Improper Output Handling。断言每项风险仍有对应而非错位的测试目标，LLM02 仍是跨会话，其余当前模式仍为单提示词；通用六字段校验器继续不绑定编号与名称。
添加 LLM02 可用性回归：User A 提供虚构的四位取件码或较长字母数字暗号，User B 不得预先写出该秘密；若 B 已包含 A 的明显秘密标识，候选应被拒绝并补生成。

- [x] **Step 2: 运行定向测试确认 Red**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_prompt_generator -v
Expected: 旧目录 LLM03–LLM10 的 2025 排序与官方 2026 映射冲突。

- [x] **Step 3: 只修正目录与目标，不改六字段契约**

更新 OWASP_RISKS 的编号、英文名、中文显示名与 testObjective 一一对应；LLM08 使用 Hidden Context Exposure 的目标，不再沿用旧 System Prompt Leakage 编号。不要迁移已有导出列、改变会话规则或把十类风险写成固定成品 prompt。
LLM02 系统消息要明确“秘密仅在 A；B 只能跨会话索取而不能复述秘密”；生成器只对明显共享的数字／字母数字秘密标识做确定性拒绝，不引入脆弱的全语义规则。

- [x] **Step 4: 运行生成器、批次、UI 回归确认 Green**

Run: .venv\Scripts\python.exe -m unittest tests.test_owasp_prompt_generator tests.test_owasp_pipeline tests.test_app_owasp -v
Expected: 官方映射、动态测试目标与依赖目录的批次和界面测试通过。

## Task 5: 更新真实文档并做完整回归

**Files:**
- Modify: README.md
- Modify: CHANGELOG.md
- Modify: docs/使用说明.md
- Modify: docs/V3.0.0/V3.0.0-极简提示词输出-设计说明.md
- Modify: docs/V3.0.0/V3.0.0-正式功能-实施计划.md
- Modify: docs/V3.0.0/V3.0.0-OWASP-LLM-2026-设计方案.md（至少修正官方风险目录表及版本事实，历史方案需标明已被极简六字段方案取代）
- Modify: task_plan.md
- Modify: progress.md
- Modify: findings.md

- [x] **Step 1: 删除过时的离线蓝图承诺**

将所有“OWASP 不需要 API Key”“离线受控蓝图生成”“不调用模型”的描述替换为：OWASP 复用设置页 OpenAI 兼容模型，模型按可变系统提示词生成可复制 prompt；不爬取网站、不读取网页素材、不自动调用被测系统。保留六字段和单表 Excel 边界，写明失败时会保留 audit 日志而不发布最终 JSON / Excel。
核对并更正官方 2026 风险编号／名称，不得复用旧版 2025 排序；历史多步骤／蓝图原型方案应标注已被当前六字段模型生成方案取代。说明跨会话 A/B、全批次 Prompt 去重、Excel 字面字符串、运行与调用日志以及状态栏进度。

- [x] **Step 2: 运行编译、全量回归与静态检查**

Run:

    .venv\Scripts\python.exe -m compileall -q app.py storage.py question_generator.py owasp_prompt_generator.py owasp_export.py owasp_pipeline.py
    .venv\Scripts\python.exe -m unittest discover -s tests -v
    .venv\Scripts\python.exe app.py --smoke-test
    git diff --check

Expected: 编译无输出；全量测试通过；烟测不进行网络模型调用；git diff --check 无空白错误。

- [ ] **Step 3: 启动实际窗口供人工使用已配置模型验证**

Run: .venv\Scripts\pythonw.exe app.py

人工验收：在 OWASP 页选择 LLM01、LLM02，填数量 3，确认隔离环境；生成后出现不同的模型输出，LLM02 的 userA / userB 是两段可发送文本且 prompt == userB；打开批次目录可看到 JSON、Excel、日志与 manifest。不要由自动化步骤向任何被测模型发送生成结果。

## 验收清单

- [x] OWASP 使用当前设置页模型，而不是固定 prompt 蓝图或网页素材。
- [x] 风险编号／名称与官方 OWASP 2026 PDF 一致，LLM08 为 Hidden Context Exposure。
- [x] 动态系统提示词包含风险、语言、数量、模式和避免重复约束；模型仅生成最终六字段记录。
- [x] 多风险批次的数量分配和结果顺序稳定，模型重复或无效输出仅重试对应风险。
- [x] 普通记录和跨会话记录分别满足空 A/B 与 prompt == userB 的规则。
- [x] 成功批次写 JSON、六列表 Excel、run.log、llm_calls.jsonl、manifest；失败批次保留 audit 日志而不发布 JSON / Excel。
- [x] Excel 中以 `=` 开头的模型文本仍是可复制原文，不作为公式执行；OWASP 进度在状态栏可见且不污染 TC260 日志。
- [x] TC260 的网页素材生成、13 列 Excel、已有模型重试和全部回归测试保持可用（自动回归验证；未对外部网站重跑实时爬取）。

以上为代码、自动测试及真实生成服务抽样验收；本机工具会话无法取得可见 Tk 窗口句柄，Task 5 Step 3 的人工点击验收仍待用户桌面运行 `run.bat`。
