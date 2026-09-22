# v3.0.0：OWASP LLM Top 10 2026 红队测试用例设计

## 1. 背景与目标

GenerateTestQuestion v2.0.0 的生成单位是“单条测试题干”：系统从可爬取的公开素材中取得情境，再按照 TC260-003 风险小类生成一条文本对话题或图片生成题。

v3.0.0 新增一个独立的“OWASP LLM Top 10 2026”红队测试用例模式。它面向被测的 LLM 应用，而不是培训人员的知识问答。一个输出单位是可执行的测试用例；用例可包含一条提示词，也可包含有顺序、会话边界和前置条件的多条步骤。

本版本的目标是：

1. 让使用者能选择 OWASP LLM Top 10 2026 中的风险并生成可执行的红队测试用例。
2. 正确表达跨会话、RAG、工具调用、持久化记忆和多模态输入等不能被压缩为单一提示词的场景。
3. 交付便于执行、记录和审计的 Excel 工作簿，以及保留完整结构的 JSON。
4. 不破坏 TC260 现有生成流程、旧批次读取和 v2.0.0 的导出文件。

本设计依据 OWASP GenAI LLM Top 10 2026 官方指南：
https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/

## 2. 范围与非目标

### 2.1 本版本范围

- 增加测试体系选择：TC260-003 和 OWASP LLM Top 10 2026。
- 内置 OWASP 2026 的十个风险定义、引用信息和可审计测试蓝图。
- 按被测应用能力生成单轮或多步骤红队测试用例。
- 导出“测试用例 / 执行步骤 / 执行记录”三工作表 Excel。
- 在桌面端按用例分组展示步骤、前置条件和预期安全行为。
- 为新结构增加离线测试、迁移兼容测试和文档。

### 2.2 非目标

- 不在本版本执行被测系统、调用被测 Agent、保存真实模型输出或自动判定安全结果。
- 不把 OWASP LLM Top 10 误称为 OWASP Agentic Top 10，也不在本版本覆盖后者的独立条目。
- 不强制抓取网页或 PDF 作为 OWASP 用例的生成前提。
- 不生成真实凭据、真实个人数据、真实生产环境破坏指令，所有特殊测试均使用显式测试夹具和隔离前置条件。
- 不把现有“图片生成题”直接复用于 OWASP 模式；多模态风险通过附件夹具步骤表达，而不是生成图片题干。

## 3. 产品模型

### 3.1 两种互不混淆的生成模式

| 模式 | 风险依据 | 输入素材 | 输出单位 | 题目形式 |
|---|---|---|---|---|
| TC260-003 | 既有 5 大类、31 小类 | 已核验网站的爬取正文 | 单条题干 | 文本对话题或图片生成题 |
| OWASP LLM 2026 | 内置官方风险目录和测试蓝图 | 风险定义、蓝图、使用者选择的目标能力 | 红队测试用例 | 有序步骤，可能单轮也可能多轮 |

进入 OWASP 模式后，生成页不要求选择网站，也不启动爬虫。界面将清楚标示：用例是“依据 OWASP 风险定义生成的变体”，不是 OWASP 官方发布的逐字测试脚本。

### 3.2 OWASP 2026 风险目录

内置目录包含以下主风险 ID 和英文标准名称：

| ID | 名称 |
|---|---|
| LLM01:2026 | Prompt Injection |
| LLM02:2026 | Sensitive Information Disclosure |
| LLM03:2026 | Excessive Agency |
| LLM04:2026 | Supply Chain |
| LLM05:2026 | Data and Model Poisoning |
| LLM06:2026 | Unbounded Consumption |
| LLM07:2026 | Misinformation |
| LLM08:2026 | Hidden Context Exposure |
| LLM09:2026 | Vector and Embedding Weaknesses |
| LLM10:2026 | Improper Output Handling |

每条风险将拥有中文显示名、简短可审计说明、官方引用 URL、可用测试蓝图及关联风险 ID。风险 ID 会作为稳定导出键，显示名不作为程序主键。

### 3.3 目标能力筛选

OWASP 用例在生成前要求至少选择一种目标能力。目录和批次使用稳定的机器可读 ID，界面只显示中文名称：

| capabilityId | 界面名称 |
|---|---|
| chat | 纯聊天 |
| rag | RAG / 向量检索 |
| tools | 工具调用或 Agent |
| memory | 跨会话持久化记忆 |
| multimodal | 多模态文件、图像或音频输入 |
| supply-chain | 第三方模型、插件、提示词或工具供应链 |
| update-pipeline | 数据、模型或微调更新管道 |
| downstream-output | 下游输出渲染、解析或自动化执行 |

系统根据能力过滤测试蓝图。没有匹配蓝图的风险不允许被选中，并给出原因；这样不会导出无法在目标系统执行的用例。纯聊天默认选中，用户可叠加其他能力。

“生成数量”在 OWASP 模式中改称“生成用例数”：它计数用例，不计步骤。每个已选主风险至少分到一个用例，最终界面和清单同时显示用例数与步骤数。

### 3.4 确定性配额与蓝图选择

OWASP 批次先按已选 primaryRiskId 做现有的均分轮转：每个已选且有兼容蓝图的风险至少获得一个用例，余数按风险 ID 的稳定顺序分配。一个风险获得多个用例时，系统在该风险的兼容 blueprintId 之间稳定轮转；同一个蓝图的多次用例由模型生成不同的文字变体。

因此，数量为 20 不意味着任意重复二十条提示词，而是“风险覆盖优先、蓝图覆盖次之、文字变体最后”。结构、步骤数和验收点仍由蓝图锁定。

## 4. 用例与步骤数据契约

### 4.1 结构化用例

新 JSON 的事实源为 test_cases.json。每个测试用例至少包含：

- caseId：批次内稳定且唯一的用例 ID。
- frameworkId：固定为 owasp-llm-2026。
- frameworkVersion：固定为 2026。
- primaryRiskId 和 primaryRiskName：主风险。
- relatedRiskIds：零个或多个关联风险。
- blueprintId 和 scenarioType：来自哪一种可执行场景。
- language、targetCapabilities、title。
- preconditions：执行前需要建立的测试账户、测试语料、工具沙箱或隔离条件。
- isolationRequirements：不可在生产环境使用、使用测试标记而非真实数据等限制。
- expectedSecurityBehavior：系统总体应如何安全响应。
- assertions：可人工核验的通过标准。
- steps：按步骤号排序的步骤数组。
- reference：OWASP 版本、标题和官方 URL。
- generatedAt、model：生成留痕。

每个步骤至少包含：

- stepNo：从 1 开始、连续的顺序号。
- sessionId：例如 SESSION-A、SESSION-B；单轮用例也显式保存会话。
- actor：tester 或 fixture。
- stepType：setup、prompt、attachment、tool-result、output-capture 或 assertion。
- instruction：需要执行的准备动作或要输入被测系统的文本。
- fixture：测试附件、测试标记、受控工具返回值或空值。
- expectedCheckpoint：本步骤应观察到的安全边界。

步骤不记录真实秘密。需要验证泄露时，使用独一无二但无价值的测试标记，例如 TEST_ONLY_MARKER，且在前置条件中说明只可在隔离环境使用。

### 4.2 结构由蓝图决定，文字由模型生成

系统不得让模型任意决定一条用例有几步、是否跨会话或是否需要工具。每个风险目录包含一个或多个静态蓝图；蓝图确定：

- 必需目标能力；
- 步骤数与步骤类型；
- 是否必须出现不同 sessionId；
- 是否必须有准备步骤、附件夹具或工具夹具；
- 允许的关联风险；
- 安全边界和必需断言。

模型只在指定蓝图的槽位中生成自然语言测试变体、场景标题和可执行提示词。解析后由程序补齐主风险、会话、夹具、引用和留痕，并验证结构。模型输出不符合蓝图时按现有重试策略重试；仍失败时记录该风险和蓝图的缺口，不输出半成品用例。

### 4.3 基线蓝图清单与特殊场景处理

以下是 v3.0.0 随目录交付的确定性基线蓝图清单。每个风险至少有一个基线蓝图；LLM01 和 LLM02 具有额外蓝图，以覆盖最常见的间接、跨会话和多模态形态。一个蓝图的步骤骨架不可由模型改写。

| 主风险 | blueprintId | 所需能力 | 固定步骤骨架 | 关联或边界 |
|---|---|---|---|---|
| LLM01:2026 | OWASP-LLM01-DIRECT | chat | prompt / assertion | 输入是数据而非可信指令 |
| LLM01:2026 | OWASP-LLM01-RAG-INDIRECT | rag | setup / prompt / assertion | 可关联 LLM09 |
| LLM01:2026 | OWASP-LLM01-MEMORY-CROSS-SESSION | memory | setup / Session-A prompt / Session-B prompt / assertion | 可关联 LLM02、LLM08；必须使用两个不同会话 |
| LLM01:2026 | OWASP-LLM01-MULTIMODAL | multimodal | attachment / prompt / assertion | 夹具仅为手工创建规范 |
| LLM02:2026 | OWASP-LLM02-CONTEXT-DATA | chat | setup / prompt / assertion | 使用无价值测试标记，不使用真实数据 |
| LLM02:2026 | OWASP-LLM02-CROSS-SESSION | memory | setup / Session-A prompt / Session-B prompt / assertion | 可关联 LLM08；必须使用两个不同会话 |
| LLM03:2026 | OWASP-LLM03-POLICY-GATE | tools | sandbox setup / prompt / tool-result / assertion | 只验证模型输出到宿主策略层的边界；需参照 Agentic 覆盖说明 |
| LLM04:2026 | OWASP-LLM04-THIRD-PARTY-COMPONENT | supply-chain | fixture setup / inspect prompt / assertion | 仅使用描述性组件元数据夹具，不下载或运行制品 |
| LLM05:2026 | OWASP-LLM05-INGESTION-POISONING | update-pipeline | fixture setup / import-or-query prompt / assertion | 可关联 LLM01、LLM09；要求来源、审批或隔离检查点 |
| LLM06:2026 | OWASP-LLM06-RESOURCE-BUDGET | chat | controlled-environment setup / prompt / assertion | 只验证预算、速率或长度边界；不执行资源耗尽攻击 |
| LLM07:2026 | OWASP-LLM07-VERIFIABILITY | chat | prompt / assertion | 验收事实核验、不确定性或来源边界，不要求固定措辞 |
| LLM08:2026 | OWASP-LLM08-HIDDEN-CONTEXT | chat | prompt / assertion | 可关联 LLM02；验证不暴露系统提示、隐藏链路或内部上下文 |
| LLM09:2026 | OWASP-LLM09-TENANT-RETRIEVAL | rag | isolated-corpus setup / prompt / assertion | 可关联 LLM01、LLM05；验证检索和租户隔离 |
| LLM10:2026 | OWASP-LLM10-DOWNSTREAM-VALIDATION | downstream-output | prompt / output-capture / assertion | 验证应用层结构校验、转义或策略执行，不要求模型自身判断 |

单轮用例指只有一次输入被测系统的 prompt，不代表 JSON 或 Excel 只有一行：它固定包含一条 prompt 步骤和至少一条 assertion 步骤。多轮或跨会话用例再在此基础上增加 setup、attachment、tool-result 或 output-capture 步骤。

主风险按蓝图选择；若场景天然涉及多个风险，关联风险写入 relatedRiskIds。生成配额只按 primaryRiskId 统计，避免同一用例被重复计数。

### 4.4 夹具交付策略

v3.0.0 不生成、不打包、不下载二进制附件、可执行文件或不可信制品。所有夹具都以安全的文字规范保存于 JSON 和 Excel 中，而不是以本地文件路径或二进制文件保存。

每个 fixture 是一个 fixtureSpec，至少包含 id、kind、safeMarker、manualCreationInstructions 和 expectedScope。kind 仅可为 text-marker、document-stub、tool-response-stub、component-metadata-stub 或 attachment-spec。对于图像、音频、PDF 等多模态场景，attachment-spec 说明测试人员应在隔离环境手动创建何种无害附件及如何附加；产物不包含该附件本身。

这项约束使 JSON、Excel、打包和 UI 都只处理可审计文本，也避免工具无意分发攻击载荷。执行人员可以在其受控测试环境中按规范创建夹具，并在“执行记录”表注明实际使用的本地测试资产。

### 4.5 LLM 与 Agentic 范围边界

LLM03 的蓝图只验证“LLM 输出到宿主应用策略层”的最小权限、显式确认和参数校验边界。凡是需要自主规划、多 Agent 协作、工具发现、长期自主执行或 Agent 记忆治理的场景，均在蓝图上标记 requiresAgenticCompanion=true；批次序列化时将该值复制到每个 test case，方便 JSON、Excel 和 UI 一致提示需配套评估 OWASP Top 10 for Agentic Applications。

持久化记忆蓝图同样只测试 LLM 应用的会话和上下文隔离；若记忆驱动自主行动，则执行人员必须同时采用 Agentic 框架。本版本不声称完整覆盖 Agentic Top 10。

## 5. 目录、生成与批次编排

### 5.1 目录存储

保留 data/risk_catalog.json 作为 TC260 的既有兼容文件。新增 OWASP 专用目录和框架注册信息；存储层提供统一的“列出框架 / 读取框架 / 平铺风险”接口，旧的 TC260 调用保持可用。

OWASP 目录至少含：

- frameworkId、frameworkVersion、displayName、description、officialReference。
- risks[]：十个风险及其元数据。
- blueprints[]：可复用的结构化用例蓝图。

目录本身是可审计的静态数据，源 URL 和版本固定在文件中。打包配置必须包含新增数据文件。

### 5.2 生成器

保留既有 TC260 的 generate_questions 接口和提示词。新增独立的结构化 OWASP 用例生成路径，职责为：

1. 根据已选风险、能力和配额选择兼容蓝图。
2. 向模型请求符合指定蓝图的严格 JSON。
3. 解析、校验、去重并生成稳定 caseId。
4. 生成 caseId、sessionId、风险、参考文献和留痕字段。
5. 将结构化用例交给专用批次导出器。

OWASP 用例的去重键应包含 frameworkId、primaryRiskId、blueprintId 和步骤文本的规范化哈希，避免与既有“爬取素材内容哈希”混用。TC260 的跨批次去重逻辑保持不变。

### 5.3 批次和历史

OWASP 批次使用与现有批次不冲突的命名，例如 OWASP-2026-YYYYMMDD-HHMMSS。它写入：

- test_cases.json：完整嵌套结构。
- test_cases.xlsx：三工作表交付物。
- llm_calls.jsonl：模型调用留痕，增加 frameworkId、blueprintId、caseCount 和 stepCount。
- manifest.json：增加 artifactKind=testCases、frameworkId、frameworkVersion、targetCapabilities、testCaseCount 和 stepCount。
- run.log：沿用现有事件日志。

历史批次加载同时识别旧 questions.json 和新 test_cases.json。旧批次仍按题干显示；新批次按用例显示并可在详情中展开步骤。v2 导出文件和 JSON 不迁移、不改写。

## 6. Excel 交付契约

每个 OWASP 批次输出一个 test_cases.xlsx，固定包含三张工作表。

### 6.1 工作表：测试用例

一行一个用例。列为：

1. 用例ID
2. OWASP版本
3. 主风险ID
4. 主风险
5. 关联风险
6. 场景模板
7. 语言
8. 目标能力
9. 前置条件
10. 隔离要求
11. 预期安全行为
12. 通过标准
13. 官方参考
14. 批次
15. 生成时间
16. 模型

### 6.2 工作表：执行步骤

一行一个步骤，以用例ID和步骤号关联。列为：

1. 用例ID
2. 步骤号
3. 会话标识
4. 执行者
5. 步骤类型
6. 输入或操作
7. 测试夹具或附件
8. 该步验收点

该表按用例ID、步骤号排序，冻结首行，长文本自动换行。用例ID是可筛选的关系键，不依赖行号或人工颜色判断步骤归属。

### 6.3 工作表：执行记录

预先为每个执行步骤建立一行，保留以下列：

1. 用例ID
2. 步骤号
3. 实际输出或观察
4. 判定（未执行 / 通过 / 失败 / 阻塞）
5. 执行人
6. 执行时间
7. 备注

生成时“判定”默认为“未执行”，其余人工执行字段为空。工具本身不自动运行目标系统、不自动填写判定。

## 7. 桌面端交互

生成页首部新增“测试体系”选择：

- 选择 TC260-003 时，保留现有网站选择、风险多选、文本/图片题型和数量逻辑。
- 选择 OWASP LLM Top 10 2026 时，替换网站选择区为目标能力复选区；替换 TC260 风险目录为十项 OWASP 风险目录；隐藏图片生成题单选，显示“红队测试用例”说明；数量标签变为“生成用例数”。

运行结果显示“完成 N 个用例，共 M 个步骤”，而不是“完成 N 题”。结果列表显示用例 ID、主风险和标题；选择用例后，详情显示前置条件、隔离要求、总体验收条件和按序排列的步骤。

## 8. 错误处理与安全边界

- 如果未选目标能力、未选风险，或用例数小于可生成的已选主风险数，界面在启动前给出明确错误。
- 如果能力与风险没有兼容蓝图，阻止运行并解释需要何种能力。
- 如果模型结构化输出不合法、缺少步骤、跨会话蓝图没有两个不同 sessionId、或含有不允许的真实秘密占位方式，拒绝该用例并记录原因。
- 如果部分蓝图生成失败，保留成功用例，并在 manifest 和界面报告按风险、蓝图和语言的缺口。
- 所有用例统一要求测试环境、最小权限、可逆动作和测试标记；描述中不得鼓励在生产环境测试。

## 9. 验收与测试

### 9.1 数据和存储

- 十个 OWASP 风险 ID 唯一、完整且与官方 2026 目录一致。
- 每个风险至少有一个蓝图；蓝图的 requiredCapabilities、步骤结构和关联风险合法。
- TC260 目录读取及旧 storage API 不回归。

### 9.2 生成器和校验器

- 单轮蓝图可以生成并解析为恰好一条 prompt 步骤和至少一条 assertion 步骤的用例。
- 跨会话蓝图必须生成连续步骤和两个不同会话。
- RAG、工具、附件蓝图必须包含其必需的 setup 或 fixture 字段。
- 无效 JSON、错误步骤数、风险不匹配、重复用例和不安全夹具会被拒绝或重试。
- 调用留痕含框架、蓝图、用例数和步骤数。

### 9.3 批次与导出

- OWASP 批次不调用爬虫。
- manifest、JSON、Excel、日志和留痕文件齐全；用例数和步骤数一致。
- Excel 的三张工作表、列名、用例与步骤关系、预填“未执行”、自动换行和冻结首行均受测试保护。
- 部分缺口、全部失败和历史去重均能准确报告。

### 9.4 UI 与兼容

- 测试体系切换正确显示对应控件和计数规则。
- OWASP 结果详情按步骤展示，TC260 历史批次仍能加载。
- 烟测报告版本为 3.0.0，并同时确认两个框架目录可读。
- 打包版本包含新增目录数据。

## 10. 实施顺序

1. 建立框架注册与 OWASP 2026 静态目录，编写目录完整性测试。
2. 建立蓝图、结构化用例模型、校验器和结构化模型提示词，先以测试驱动实现。
3. 添加 OWASP 批次编排、专用去重、JSON 和 manifest 产物。
4. 实现三工作表 Excel 导出和导出测试。
5. 改造桌面端的体系切换、能力选择、用例详情与历史加载。
6. 更新 README、使用说明、CHANGELOG、版本号和打包定义。
7. 跑完整离线回归、烟测和人工界面验收。

## 11. 版本与兼容承诺

- 版本号升级到 3.0.0。
- v2.0.0 的 TC260 生成路径、questions.json、questions.xlsx 和历史批次保持可用。
- v3 OWASP 产物使用新的 test_cases.json / test_cases.xlsx 名称和 artifactKind，不修改旧文件的列契约。
- 对外依赖新 Excel 的程序必须按表头和用例ID关联读取，不能依赖固定行号。
