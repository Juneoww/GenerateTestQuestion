"""功能：读取原题批次中已记录的目录预期输入面。

实现：仅从 Agentic 批次的场景快照取值；旧批次或无效快照留空，不按风险编号推断。
输入：原题列表、题集类型、批次目录；输出：与原题逐项对应的预期输入面列表。
"""
import json
from pathlib import Path


def load_planned_surfaces(records, framework, batch_dir):
    """只读取已保存的目录场景，不修改原题。"""
    by_risk = {}
    if framework == "agentic":
        try:
            manifest = json.loads((Path(batch_dir) / "manifest.json").read_text(encoding="utf-8"))
            scenarios = manifest.get("plannedScenarios", {})
            if isinstance(scenarios, dict) and scenarios.get("source") == "catalog":
                candidate = scenarios.get("byRisk", {})
                if isinstance(candidate, dict):
                    by_risk = candidate
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    result = []
    for record in records:
        scenario = by_risk.get(record.get("riskId"), {})
        surface = scenario.get("injectionSurface", "") if isinstance(scenario, dict) else ""
        result.append(surface if isinstance(surface, str) else "")
    return result
