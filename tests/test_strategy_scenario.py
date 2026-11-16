"""验证只从本批次快照读取预期输入面，旧批次不推断。"""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from strategy_scenario import load_planned_surfaces


class StrategyScenarioTests(unittest.TestCase):
    def test_attaches_only_recorded_catalog_surfaces_without_mutating_original(self):
        records = [{"riskId": "ASI05", "prompt": "工具结果", "plannedInputSurface": "伪造"}, {"riskId": "ASI07", "prompt": "消息"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"plannedScenarios": {"source": "catalog", "byRisk": {
                "ASI05": {"injectionSurface": "工具返回正文"}}}}, ensure_ascii=False), encoding="utf-8")
            result = load_planned_surfaces(records, "agentic", directory)
            self.assertEqual(result, ["工具返回正文", ""])
            self.assertEqual(records[0]["plannedInputSurface"], "伪造")
            self.assertEqual(load_planned_surfaces(records, "llm", directory), ["", ""])

    def test_missing_or_invalid_manifest_does_not_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            record = [{"riskId": "ASI05", "prompt": "输入", "plannedInputSurface": "伪造"}]
            self.assertEqual(load_planned_surfaces(record, "agentic", directory), [""])
            (Path(directory) / "manifest.json").write_text("not json", encoding="utf-8")
            self.assertEqual(load_planned_surfaces(record, "agentic", directory), [""])

    def test_window_reads_original_batch_snapshot(self):
        from strategy_ui import StrategyWindow
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "manifest.json").write_text(json.dumps({"plannedScenarios": {
                    "source": "catalog", "byRisk": {"ASI05": {"injectionSurface": "工具返回正文"}}}},
                    ensure_ascii=False), encoding="utf-8")
                original = {"riskId": "ASI05", "prompt": "工具结果", "plannedInputSurface": "伪造"}
                window = StrategyWindow(root, [original], "agentic", directory)
                self.assertEqual(window.planned_surfaces, ["工具返回正文"])
                self.assertEqual(window.records[0], original)
                from strategy_ui import make_variant_rows
                transform = lambda *_args, **_kw: {"status": "generated", "text": "变种"}
                rows = make_variant_rows(window.records, [0], ["R01"], "agentic", transform,
                                         planned_surfaces=window.planned_surfaces)
                self.assertEqual(rows[1]["plannedInputSurface"], "工具返回正文")
                self.assertEqual(rows[1]["sourceRecord"], original)
                no_snapshot = make_variant_rows([original], [0], ["R01"], "agentic", transform)
                self.assertEqual(no_snapshot[1]["plannedInputSurface"], "")
                window.destroy()
        finally:
            root.destroy()
