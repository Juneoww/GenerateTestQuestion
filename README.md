# GenerateTestQuestion

面向内容安全测试的桌面工具：**爬取网站 → 生成题目**。从已核验的可爬站点抓取公开报道与通报，
通过 OpenAI 兼容大模型生成参照 TC260-003 风险分类的中英文测试提示集（仅题干，无选项与答案），
每道题可追溯到依据的原文，并保留来源素材与 TC260-003 风险小类的情境关联。题目形式二选一：
**文本对话题**（测文本模型）或**图片生成题**（生成提示词，并调用文生图模型生成图片，图片批次名带
`-IMG`）。v3.0.0 在同一桌面程序中新增独立的 **OWASP LLM Top 10 2026 红队提示词**工作区：
它复用设置页的 OpenAI 兼容模型生成可复制的红队候选 prompt，不爬取网站，也不调用被测系统；结果实际导出为 JSON / Excel。纯 Python 单栈。

当前开发分支为 **v4.1.0**。文本对话题可选同时生成本地文字图片：在设置页选择白底或本地背景和预设尺寸，批次保存独立 PNG，Excel 展示缩略图和图片存储路径。原有模型生图和 OWASP Agentic 题集继续可用。设计见 [v4.1.0 文档](docs/V4.1.0/V4.1.0-文字嵌入图片测试用例开发文档.md)。

## 功能

- **生成**（主页）：站点按中/英文分组折叠多选 → 「题目类型」中的 TC260 风险小类（大类折叠卡片 +
  三态整组勾选，5 大类 31 小类）→ 第 3 步的题目形式（文本对话题 / 图片生成题）+ 数量与中英文比例
  → 一键生成（上次的形式会被记住）。
  选择全程实时计数，未选站点或未选小类时开始按钮置灰并提示缺什么；
  实时运行日志；原文↔题目对照区（题干、题型、风险类别、依据原文、来源链接，题干摘要列支持横向滚动读全文）。
- **OWASP 红队提示词**：选择官方 2026 版 LLM01–LLM10 风险、数量和语言，由设置页模型按风险目标生成。页面显示独立运行日志和运行结果；结果表与 JSON
  严格只有 `riskId | riskName | userA | userB | prompt | assertion` 六字段；Excel 默认也是六列。勾选「同时生成文字图片」可按设置中的尺寸和背景渲染每条 `prompt`，并追加缩略图和图片存储路径。
  跨会话记录先发送 `userA`，再在另一会话只发送一次 `userB` 或镜像字段 `prompt`；虚构秘密只出现在 A，不应由 B 预先说出。普通记录的 `userA` / `userB` 留空。
- **OWASP Agentic 题集**：按 ASI01–ASI10 风险生成，与 OWASP LLM 页共用布局、操作和导出格式。两页各自保存风险选择、运行日志和结果。勾选「同时生成文字图片」后，按共享设置将每条 prompt 渲染为 PNG，保存在批次的 `images/` 目录，Excel 末尾追加缩略图和图片存储路径。
- **来源管理**：站点清单（状态：待核验/可爬/核验失败/停用），一键自动核验——通过即进入生成页；
  支持新增站点（HTTPS URL + 条目提取正则）。
- **设置**：模型接口地址 / API Key / 模型名 / 温度 / 超时 / 重试 / 爬取延时 / 产物存放路径，测试连接。
- **文字图片**：文本对话题可勾选“同时生成文字图片”，设置页可选择本地背景和预设尺寸；本地渲染图片不调用文生图接口，文字题干仍由文字模型生成。
- **全过程留痕**：网站名单、核验日志、每批次爬取内容（items.jsonl）、模型调用记录、运行日志、批次汇总。

## 快速开始

```bat
uv venv
uv pip install -p .venv/Scripts/python.exe -r requirements.txt
run.bat
```

- 使用 **TC260 或 OWASP** 前，先到 **设置** 页配置模型接口地址和模型名，并按服务商要求填写 API Key、测试连接（DeepSeek / 智谱 / 通义 / Kimi / OpenAI 等 OpenAI 兼容接口均可，接口地址填到 `/v1` 等版本号一级）。OWASP 不需要网站或爬虫配置。
- 无界面自检：`.venv\Scripts\python app.py --smoke-test`。

## 使用说明

首次使用 TC260 时按 设置 → 来源管理 → 生成 的顺序配置；OWASP 配好模型后可直接进入同名标签页生成和导出提示词。

1. **配置模型**（设置页）：填接口地址（到 /v1 一级）、API Key、模型名，点「测试连接」通过后保存。
2. **核验来源**（来源管理页）：点「核验全部」（或选中若干行后点「核验选中」）；状态变为"可爬"的站点
   才会出现在生成页。要新增站点，点「新增站点」填 HTTPS 地址与条目提取正则。
3. **选择网站**（生成页第 1 步）：点「中文站点 / 英文站点」标题展开列表，点击整行即可勾选/取消；
   工具栏提供全选 / 清空 / 全选中文 / 全选英文，标题条徽章实时显示该组"已选 n/m"。
4. **选择风险小类**（第 2 步，界面标签为「题目类型」）：这里选择的是 TC260 风险小类，不是第 3 步
   的「题目形式」。点大类标题展开小类。标题行左侧三态框整组勾选/清空（"—"表示部分选中），
   也可在小类里单独增减；收起状态同样可以整组操作，徽章始终显示该组已选数。
5. **生成**（第 3 步）：先选择「文本对话题」（测文本模型）或「图片生成题」（测文生图模型）；
   该选择会被记住。图片生成题需在设置页分别配置文字模型和文生图模型；题干作为文生图提示词，成功生成的图片保存在批次目录中。两种形式都会依据来源原文和
   所选 TC260 风险小类生成。再设置生成数量（须 ≥ 所选小类数，≤ 1000）与中文占比，点「开始生成」；
   进度与错误在运行日志实时输出。日志与原文↔题目对照区保持固定阅读高度，页面超出一屏时可上下滚动整页；
   鼠标位于日志、题目列表或详情上时优先滚动框内内容，到顶/到底后继续滚动整页。
   产物默认存放在程序目录 `data\output`，可在设置页「产物存放路径」自定义（支持浏览选择，
   相对路径按程序目录解析，保存时自动创建目录；历史批次列表与去重索引都会跟随该目录）。
6. **查看结果**（第 5 步）：对照区点任一题，右侧以「【题型】」显示文本对话题或图片生成题，并显示
   题干、风险类别、依据原文与来源链接；缺少 `questionType` 的旧批次按文本对话题显示。
   题干摘要列可向右滑动看全文。点「加载历史批次」（Ctrl+L）回看过往批次，
   右侧按钮可直达批次目录、题库 Excel 与该题来源网页。
7. **生成 OWASP 红队提示词**（OWASP 红队提示词页）：复用设置页模型，不选网站。勾选一个或多个风险后，
   填写不少于已选风险数的生成数量、选择语言，点「生成可复制提示词」。同一结果表可混合单 prompt
   与跨会话记录；双击任意单元格即可复制。跨会话时先在用户 A 的会话发送 `userA`，再在隔离的用户 B 会话只发送一次 `userB` 或相同的 `prompt`。
   成功批次会自动写入设置页产物存放路径下的 `OWASP-…\owasp_prompts.json`、`owasp_prompts.xlsx`、`run.log`、`llm_calls.jsonl` 与 `manifest.json`；「运行结果」顶部的「打开题库 Excel」可直接打开本批工作簿，页内还可打开批次目录和 JSON。

快捷键：`Ctrl+1 / Ctrl+2 / Ctrl+3 / Ctrl+4 / Ctrl+5` 切换 生成 / OWASP 红队提示词 / OWASP Agentic 题集 / 来源管理 / 设置 五个工作区，`Ctrl+L` 加载 TC260 历史批次。

三个生成页都可以在运行时点击「停止生成」。程序停止等待网络响应和执行后续步骤，并撤下未发布的批次。已经发送的请求可能仍由远端服务处理。

Agentic 的使用方式与 LLM 页相同。成功批次使用 `AGENTIC-YYYYMMDD-HHMMSS` 前缀，包含 `owasp_prompts.json`、`owasp_prompts.xlsx`、`manifest.json` 和两份日志。涉及工具、记忆或智能体通信的测试需在被测系统中配置相应输入和观察条件。

ASI01 保留直接用户消息基线。在预置只读采购清单任务和测试账户权限后，将六字段题库中的 `prompt` 作为一条用户消息发送。

包含 ASI01 或 LLM01 的成功批次会在 `owasp_evaluation.json` 中额外提供一条虚构采购文档用例。将 `userMessage` 作为用户任务，通过被测系统支持的独立文档入口提供 `documentText`，例如用户可用的只读文档或检索入口。对照 `expectedOutput` 检查模型是否保留用户指定的标题并正确统计。仅能发聊天消息时，文档来源检查记为不可判定。这个样例只用文档中的标题标记测量来源区分能力，不计入题库条数。

Agentic 成功批次在评测文件的 `recordChecks` 中提供 ASI01–ASI10 的检查表。`recordIndex` 对应题库 JSON 中从 1 起算的位置。调用层（`callLayer`）和执行层（`executionLayer`）分别列出预期与所需证据。黑盒测试拿不到调用记录时，调用层记为不可判定。执行层按可取得的结果与状态证据判断，任一层有明确失败即可判失败。长断言仍在原有的 `assertion` 列。评测文件供外部 Judge 或人工使用。

每批次产物位于 `data/output/<批次>/`：题目 Excel/JSON、爬取内容 items.jsonl、模型调用记录、
运行日志与批次汇总。文本批次名为 `BATCH-YYYYMMDD-HHMMSS`，图片生成题批次名为
`BATCH-YYYYMMDD-HHMMSS-IMG`。

`questions.json` 的批次参数与每题记录、`manifest.json` 的批次参数、以及 `llm_calls.jsonl` 的每条
调用记录都会保留 `questionType`（`text` 或 `image`）。文本题的 `questions.xlsx` 默认 13 列；勾选生成文字图片时在末尾追加缩略图列和图片存储路径列。图片文件名包含批次标识和序号，Excel 中为生成时的绝对路径；如移动批次，原绝对路径不会自动更新，可通过 JSON 中的相对路径重新定位。模型生图题追加图片路径、状态、模型和失败原因。旧批次缺少题型字段时按文本处理。外部脚本应按表头名称读取 Excel，勿依赖固定列号。

OWASP 批次以 `OWASP-YYYYMMDD-HHMMSS` 命名；同秒重复生成会自动追加序号，绝不覆盖旧批次。其 `owasp_prompts.json`
顶层是一个数组，每项严格只含 `riskId`、`riskName`、`userA`、`userB`、`prompt`、`assertion`；`owasp_prompts.xlsx` 只有
`测试提示词` 工作表，默认列为 `风险编号 | 风险名称 | userA | userB | prompt | 断言`。启用文字图片后，末尾追加「文字图片」和「图片存储路径」。若写题库 JSON、评测 JSON 或 Excel 任一步失败，最终文件不会发布，
批次目录只保留失败 `manifest.json`、`run.log`、`llm_calls.jsonl` 供排查。Excel 中由模型生成的文本按字面字符串保存，以 `=` 开头也不会被当作公式。

OWASP 模型输出会经过六字段、风险归属、语言、跨会话镜像和明显秘密重复检查，以及全批次 `prompt` 去重；不足时对对应风险有限重试。这些是格式与部分可用性门槛，**不能证明提示词在任意被测系统上可执行，更不能证明存在漏洞**。交付物是待人工验证的红队候选提示词；RAG、工具、跨会话等场景需要被测系统具备相应能力和隔离夹具。

## 免安装版（Windows exe）

本分支源码为 v4.1.0；下方 v3.0.1 链接是此前发布的版本，不包含新的 Agentic 页和文字图片功能。v4.1 可从源码运行或用 `build_exe.bat` 在本地打包，未发布新 Release。v3.0.1 修复了 v3.0.0 EXE 在 TC260 爬取时缺少指纹数据文件的问题。

v4.1.0 可下载仓库中的 `dist/GenerateTestQuestion.exe`，放入独立、可写的文件夹（如桌面上的新文件夹）后运行，无需安装 Python。首次运行会在 EXE 同级创建 `data/`，保存来源清单、风险目录和后续设置；未设置输出路径时，题库写入 `data/output/`。首次使用需由使用者自行配置模型接口。程序已随包提供 Noto Sans SC 字体；字体许可及版权声明见 `assets/fonts/OFL.txt` 与 `assets/fonts/NOTICE.txt`。

`data/settings.json` 包含本机填写的 API Key，请勿随 EXE 一起分发。不要从压缩包内直接运行，也不要放在没有写入权限的系统目录；如设置了输出路径，应选择目标电脑上可写的路径。

不想装 Python 也可以直接用打包好的单文件程序：到
[v3.0.1 Release](https://github.com/Juneoww/GenerateTestQuestion/releases/tag/v3.0.1)
下载 `GenerateTestQuestion.exe`（约 60 MB），放到任意**可写**目录（如桌面、D 盘某文件夹）双击运行。

- 首次运行会在 exe 旁边生成 `data/` 目录（内置 16 个来源站点与 TC260 风险目录）。
- 到「设置」页填入模型接口地址与 API Key，「测试连接」通过后保存即可开始生成。
- 升级：下载新版 exe 覆盖旧文件即可，`data/`（已保存的设置与历史批次）不受影响。
- 命令行自检：`GenerateTestQuestion.exe --smoke-test` 退出码为 0 即为正常；无控制台 EXE 不保证能看到 JSON 标准输出。v3.0.1 起自检也会检查爬虫依赖数据文件。
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
| `app.py` | Tkinter 桌面端（TC260、OWASP、来源管理、设置四页） |
| `crawler.py` | Scrapling 封装：HTTPS 门禁、同域过滤、每请求延时、条目提取、逐条落盘 |
| `question_generator.py` | OpenAI 兼容出题：提示词、JSON 校验、去重、重试、调用留痕 |
| `pipeline.py` | 批次编排：配额分配、原文轮转、熔断、缺口报告 |
| `owasp_prompt_generator.py` / `owasp_pipeline.py` / `owasp_export.py` | OWASP 模型生成与六字段校验、独立批次、单表 Excel 导出 |
| `storage.py` / `reporting.py` / `excel_export.py` | 数据读写 / 留痕文档 / Excel 导出 |
| `data/sources.json` | 来源清单（状态机：pending → ready/failed，另有 disabled） |
| `data/risk_catalog.json` | TC260 风险目录（5 大类、31 小类） |
| `data/settings.json` | 模型配置（含 API Key，不入库） |
| `data/output/<批次>/` | 题目 Excel/JSON、爬取内容、llm_calls、run.log、manifest、爬取报告（图片批次以 `-IMG` 结尾） |
| `data/reports/` | 网站名单、核验日志（每次核验后刷新） |
| `data/_legacy/` | 旧版语料/题库批次归档 |

以上 `data/` 运行数据均不入 git；入库的只有代码、文档与测试。

## 来源合规

所有来源仅接受 HTTPS（443、无凭据）；抓取限同域、逐请求礼貌延时；公开可浏览不等于已获授权，
来源以公开的辟谣/监管/司法/事实核查类页面为主，仅提取标题与正文用于出题，不做整站镜像。

## 设计文档

- **当前 v3.0.0 OWASP 实施依据**：`docs/superpowers/specs/2026-09-28-owasp-model-generated-prompts-design.md` 与 `docs/superpowers/plans/2026-09-29-owasp-model-generated-prompts.md`；六字段输出契约详见 `docs/V3.0.0/V3.0.0-极简提示词输出-设计说明.md`。
- `docs/V3.0.0/V3.0.0-正式功能-实施计划.md` 与早期多步骤/三表设计为历史阶段记录，不代表当前模型生成实现。
- **当前 v2.0.0 设计与实施依据**：`docs/2026-09-21-image-question-mode-design.md`
- 历史需求方案（v1.2，已由 v2.0.0 方案取代）：`docs/2026-08-28-crawl-to-question-rewrite-design.md`
- 历史产品设计（仅作背景参考，v2.0.0 已由当前方案取代）：`docs/2026-08-31-crawl-to-question-product-design.md`
- UI 交互原型：`docs/prototype-multiselect.html`（多选框折叠卡片方案，浏览器直接打开可交互）

> v2.0.0 集成请以当前 v2 设计文档和当前 Excel 表头/JSON 字段为准；不要使用历史文档中的固定列号或旧 schema。
