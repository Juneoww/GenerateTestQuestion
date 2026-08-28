# GenerateTestQuestion

面向内容安全测试的中英文风险题库生成桌面端。选择已核验的来源网站与五大一级风险类别，填写题量与中英文占比后一键完成受控采集、素材整理与题库 Excel 输出；语料采集与人工素材维护放在独立工作区。

## 功能工作区

- **一键生成**：网站 + 五大类多选 + 题量 / 中文占比 → 受控采集并生成题库（采集摘要 → 人工素材 → 合成补位三级来源）。
- **语料采集**：正负样本语料批次，内容哈希去重、最小长度过滤、配额缺口报告，输出 JSONL。
- **来源配置**：来源登记表（15 个候选站点、124 条路由）与核验等级（V0–V3）门禁视图。
- **高级维护**：人工素材入库（授权门禁、原始全文隔离、旁车清理）与去标识化提取。

## 来源合规

仅核验等级 V2/V3 且运行门禁为"允许"的来源参与自动采集；负样本与 HTML 直采配置同样受 HTTPS 门禁约束。公开可浏览不等于已获授权，所有启用结论必须有人工核验证据。

## 运行要求

- Windows + Python 3.13+（标准库 Tkinter，无第三方 Python 依赖）。
- Node.js 24+（采集服务依赖 `--use-env-proxy` 读取系统代理），运行时需提供 `@oai/artifact-tool` 包（Excel 读写）。
- 访问 GitHub 或来源站点受限时，可通过系统代理（`HTTPS_PROXY` / `HTTP_PROXY`）或 `git -c http.proxy=...` 处理。

## 使用

```bash
python app.py                # 启动桌面端
python app.py --smoke-test   # 无界面自检，输出 JSON 摘要

# 集成测试（无外部网络依赖，逐个运行）
node tests/corpus_collector.integration.mjs
node tests/question_bank.integration.mjs
```

## 目录结构

- `app.py`：Tkinter 桌面端，所有 Node 调用后台线程执行，路径操作限制在项目目录内。
- `tools/`：Node 数据服务（来源选择、受控采集、素材入库、题库生成、一键编排）。
- `tests/`：集成测试与桌面端烟测。
- `data/`：登记表与采集配置入库；语料批次、题库产物等运行数据不入库。
- `docs/`：设计文档与实施计划。
