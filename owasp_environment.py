"""功能：把生成时指定的 Agentic 环境配置导出为独立 JSON 和可读说明。
实现：按最终六字段记录顺序复制同一风险配置，使用行号和 prompt 哈希关联。
输入：正式六字段记录与暂存目录；输出：environment.json、environment.md。
依赖：Python 标准库、版本化风险目录与六字段校验器；无网络调用。
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from owasp_catalog import AGENTIC_FRAMEWORK, AGENTIC_RISKS, CATALOG_VERSION, SOURCE_URL
from owasp_prompt_generator import validate_prompt_records


def build_environment(records: list[dict[str, str]]) -> dict:
    """仅把目录中已分配的环境关联到真实结果，拒绝跨框架与名称错配。"""
    errors = validate_prompt_records(records)
    if errors:
        raise ValueError("；".join(errors))
    catalog = {risk["riskId"]: risk for risk in AGENTIC_RISKS}
    entries = []
    for index, record in enumerate(records, 1):
        risk = catalog.get(record["riskId"])
        if risk is None or risk["riskName"] != record["riskName"]:
            raise ValueError("环境记录必须属于当前 Agentic 目录。")
        if record["userA"] or record["userB"]:
            raise ValueError("Agentic 环境记录仅支持指定注入位置的单 prompt。")
        entries.append({"recordIndex": index, "riskId": record["riskId"],
                        "promptSha256": hashlib.sha256(record["prompt"].encode("utf-8")).hexdigest(),
                        **copy.deepcopy(risk["environment"])})
    return {"schemaVersion": "1.0", "framework": AGENTIC_FRAMEWORK, "catalogVersion": CATALOG_VERSION,
            "mode": "model-generated", "environmentSource": "catalog-profile", "sourceUrl": SOURCE_URL,
            "note": "环境配置已提供给生成模型；语义一致性与实际行为仍需人工验证，未自动执行被测系统。",
            "records": entries}


def write_environment_files(records: list[dict[str, str]], directory: Path) -> tuple[Path, Path]:
    """只向本次批次暂存目录写入两种环境说明，由外层统一原子发布。"""
    payload = build_environment(records)
    json_path = directory / "environment.json"
    markdown_path = directory / "environment.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Agentic 2026 题集环境说明", "", payload["note"], "",
             "recordIndex 从 1 开始，对应 JSON 顺序及 Excel 数据行顺序（不计表头）。",
             "使用前核对 promptSha256；环境信息不属于最终六字段记录。", ""]
    labels = {"prerequisites": "前置环境", "injectionSurface": "输入位置", "setup": "配置与授权任务",
              "followUp": "后续操作", "evidence": "观察证据"}
    for entry in payload["records"]:
        lines += [f"## 第 {entry['recordIndex']} 条 · {entry['riskId']}", "", f"prompt SHA-256：`{entry['promptSha256']}`", ""]
        for key, label in labels.items():
            lines += [f"**{label}：** {entry[key]}", ""]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path
