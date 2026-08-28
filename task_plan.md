# 爬取出题一体化改造计划

## 目标

按 `docs/2026-08-28-crawl-to-question-rewrite-design.md`（v1.2）实施：**爬取网站 → 生成题目（测试提示集，仅题干无答案）**，纯 Python 单栈（Tkinter + Scrapling + openpyxl）。

## 当前阶段

Phase 1 来源侦察 / Phase 3 爬虫实现（项目整理已完成，代码待开工）

## 阶段

### P1 来源侦察

- [ ] 调研辟谣/监管/司法/事实核查类站点，自动核验可达性与结构
- [ ] 扩充 `data/sources.json`，产出 `data/reports/网站名单.md`、`核验日志.md`
- 种子：`data/sources.json` 已含 9 个旧实测 HTML 源（2026-08-28）

### P2 风险目录提取

- [x] 从旧 `build_source_registry.mjs` 提取 `data/risk_catalog.json`（5 大类、31 小类，已校验）
- **状态：** completed 2026-08-28

### P3 爬虫实现（Scrapling）

- [ ] `pip install "scrapling[fetchers]" openpyxl`
- [ ] HTTPS 门禁、Fetcher 封装、条目提取、去重、限速、留痕落盘
- [ ] `crawler.py` + 集成测试

### P4 LLM 出题服务

- [ ] OpenAI 兼容客户端、提示词模板、JSON 校验、去重、重试与缺口统计、模型调用记录落盘
- [ ] `question_generator.py` + 单测

### P5 界面重构

- [ ] 三页 UI（生成 / 来源 / 设置）、日志队列、原文↔题目对照区
- [ ] 新 `app.py` + 烟测

### P6 导出与串联

- [ ] openpyxl 导出、批次目录、manifest、端到端编排与集成测试

### P7 清理与交付

- [x] 删除 `tools/` 全部 Node 服务与旧测试；移除 node_modules 链接
- [x] 旧批次数据移入 `data/_legacy/`（`data/corpus/_archive` 8.2MB 被进程占用，待关闭占用程序后移动）
- [ ] 删除旧 `app.py` 或重写（当前 app.py 仍引用已删除的 tools/，运行会失败）
- [ ] README 更新（纯 Python 部署）、全量回归、推送 GitHub

## 已做决定

见设计文档第 3 节（v1.2）：测试提示集只出题干、Scrapling 统一引擎、自动核验即用、全过程留痕、OpenAI 兼容模型、旧数据归档。

## 错误记录

| 时间 | 错误 | 处理 |
|---|---|---|
| 2026-08-28 | `data/corpus/_archive` 移动被拒（Permission denied，疑似 WPS/终端占用） | 保留原处，待占用释放后移入 `data/_legacy/` |
