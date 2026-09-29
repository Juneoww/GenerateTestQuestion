# GenerateTestQuestion

面向内容安全测试的桌面工具：**爬取网站 → 生成题目**。从已核验的可爬站点抓取公开报道与通报，
通过 OpenAI 兼容大模型生成参照 TC260-003 风险分类的中英文测试提示集（仅题干，无选项与答案），
每道题可追溯到依据的原文，并保留来源素材与 TC260-003 风险小类的情境关联。题目形式二选一：
**文本对话题**（测文本模型）或**图片生成题**（题干为可直接输入文生图模型的提示词，图片批次名带
`-IMG`）。v3.0.0 在同一桌面程序中新增独立的 **OWASP LLM Top 10 2026 红队提示词**工作区：
它复用设置页的 OpenAI 兼容模型生成可复制的红队候选 prompt，不爬取网站，也不调用被测系统；结果实际导出为 JSON / Excel。纯 Python 单栈。

## 功能

- **生成**（主页）：站点按中/英文分组折叠多选 → 「题目类型」中的 TC260 风险小类（大类折叠卡片 +
  三态整组勾选，5 大类 31 小类）→ 第 3 步的题目形式（文本对话题 / 图片生成题）+ 数量与中英文比例
  → 一键生成（上次的形式会被记住）。
  选择全程实时计数，未选站点或未选小类时开始按钮置灰并提示缺什么；
  实时运行日志；原文↔题目对照区（题干、题型、风险类别、依据原文、来源链接，题干摘要列支持横向滚动读全文）。
- **OWASP 红队提示词**：选择官方 2026 版 LLM01–LLM10 风险、数量和语言，由设置页模型按风险目标生成。页面显示独立运行日志和运行结果；结果表与 JSON
  严格只有 `riskId | riskName | userA | userB | prompt | assertion` 六字段；Excel 只有 `测试提示词` 一张六列表。
  跨会话记录先发送 `userA`，再在另一会话只发送一次 `userB` 或镜像字段 `prompt`；虚构秘密只出现在 A，不应由 B 预先说出。普通记录的 `userA` / `userB` 留空。
- **来源管理**：站点清单（状态：待核验/可爬/核验失败/停用），一键自动核验——通过即进入生成页；
  支持新增站点（HTTPS URL + 条目提取正则）。
- **设置**：模型接口地址 / API Key / 模型名 / 温度 / 超时 / 重试 / 爬取延时 / 产物存放路径，测试连接。
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
   该选择会被记住。图片生成题的题干可直接作为文生图提示词使用，两种形式都会依据来源原文和
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

快捷键：`Ctrl+1 / Ctrl+2 / Ctrl+3 / Ctrl+4` 切换 生成 / OWASP 红队提示词 / 来源管理 / 设置 四个工作区，`Ctrl+L` 加载 TC260 历史批次。

每批次产物位于 `data/output/<批次>/`：题目 Excel/JSON、爬取内容 items.jsonl、模型调用记录、
运行日志与批次汇总。文本批次名为 `BATCH-YYYYMMDD-HHMMSS`，图片生成题批次名为
`BATCH-YYYYMMDD-HHMMSS-IMG`。

`questions.json` 的批次参数与每题记录、`manifest.json` 的批次参数、以及 `llm_calls.jsonl` 的每条
调用记录都会保留 `questionType`（`text` 或 `image`）。`questions.xlsx` 共 13 列，`题型`（文本/图片）
插在 `题干` 后；旧批次缺少该字段时按文本处理。外部脚本应按表头名称读取 Excel，勿依赖固定列号。

OWASP 批次以 `OWASP-YYYYMMDD-HHMMSS` 命名；同秒重复生成会自动追加序号，绝不覆盖旧批次。其 `owasp_prompts.json`
顶层是一个数组，每项严格只含 `riskId`、`riskName`、`userA`、`userB`、`prompt`、`assertion`；`owasp_prompts.xlsx` 只有
`测试提示词` 工作表，列为 `风险编号 | 风险名称 | userA | userB | prompt | 断言`。若写 JSON 或 Excel 任一步失败，最终文件不会发布，
批次目录只保留失败 `manifest.json`、`run.log`、`llm_calls.jsonl` 供排查。Excel 中由模型生成的文本按字面字符串保存，以 `=` 开头也不会被当作公式。

OWASP 模型输出会经过六字段、风险归属、语言、跨会话镜像和明显秘密重复检查，以及全批次 `prompt` 去重；不足时对对应风险有限重试。这些是格式与部分可用性门槛，**不能证明提示词在任意被测系统上可执行，更不能证明存在漏洞**。交付物是待人工验证的红队候选提示词；RAG、工具、跨会话等场景需要被测系统具备相应能力和隔离夹具。

## 免安装版（Windows exe）

本轮 v3.0.0 OWASP 模型生成更新以当前源码通过 `run.bat` 运行的功能为准；已有 Releases 中的 exe 不会自动更新，只有重新打包并发布的 exe 才包含本轮改动。

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
