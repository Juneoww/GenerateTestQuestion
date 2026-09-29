# 更新日志

## v3.0.0 — 2026-09-29

新增 OWASP LLM Top 10 2026 红队提示词工作区，与 TC260 保持同一桌面工具、两条独立生成路径。

### 新增

- OWASP 复用设置页的 OpenAI 兼容模型，由各风险的可变系统提示词生成可直接复制的红队候选 prompt；不读取网站、不启动爬虫、不调用被测系统。风险编号和英文名称按 [OWASP LLM Top 10 2026 官方资源](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) 校正。
- 最终 JSON 严格使用六字段：`riskId`、`riskName`、`userA`、`userB`、`prompt`、`assertion`；风险编号与名称只做独立非空校验，不硬编码绑定关系。
- LLM02 跨会话记录使用 `userA` / `userB` 两段实际 prompt：虚构秘密仅写在 A，B 在另一会话索取但不预先复述秘密，`prompt` 精确镜像 `userB`；普通场景保留空 A/B 字段，混合批次可在同一结果表展示。
- 对模型候选做字段、风险归属、语言、跨会话和占位符检查，全批次 `prompt` 去重；不足时仅对对应风险有限重试。结果仍是待人工验证的红队候选提示词，不代表任何目标存在漏洞。
- 成功批次落盘 `OWASP-…\owasp_prompts.json`、`owasp_prompts.xlsx`、`manifest.json`、`run.log` 与 `llm_calls.jsonl`；Excel 仅一张 `测试提示词` 表，列为“风险编号 / 风险名称 / userA / userB / prompt / 断言”，模型文本按字面字符串写入。
- 导出采用隐藏暂存目录和目录级发布：同秒批次自动避让，模型或导出失败仅保留失败 manifest 与两份诊断日志，不发布 JSON / Excel。

### 兼容性

- TC260 的网站爬取、模型出题、历史批次和 13 列 `questions.xlsx` 保持原样。
- OWASP 不要求 TC260 的来源选择，但使用同一套模型 API 配置；不复用 TC260 网页素材或题目生成函数。

## v2.0.0 — 2026-09-22

这是一个重大版本（major release）。它新增可选择的图片生成题模式，并更新了对外交付的 Excel 列契约。

### 新增

- 生成页第 3 步可选择「文本对话题」或「图片生成题」，并记住上次选择。
- 图片生成题的题干是可直接输入文生图模型的提示词；两种题目形式都保留来源原文情境和 TC260 风险分类依据。
- 图片批次目录以 `-IMG` 结尾；题目详情显示「【题型】」。
- `questions.json` 的批次参数与每题记录、`manifest.json` 的批次参数，以及 `llm_calls.jsonl` 的调用记录均包含
  `questionType`（`text` 或 `image`）。

### 向后兼容与迁移

- 旧设置和历史批次缺少 `questionType` 时，均按文本题处理；已有批次无需迁移。
- `questions.xlsx` 现在有 13 列：在「题干」之后新增「题型」（文本/图片）。这会使其后的列位置右移一列。
- 如有读取 Excel 的外部脚本，请按表头名称定位列，不要依赖固定列号。
