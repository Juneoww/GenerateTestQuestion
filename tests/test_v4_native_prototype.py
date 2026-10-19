"""功能：验证 v4 原型的六字段、配额、环境关联和页面隔离。
实现：直接检查离线演示批次，并用隐藏 Tk 窗口验证真实控件行为。
输入：固定虚构测试数据；输出：unittest 结果，不调用模型或写入题库。
依赖：Python 标准库、当前六字段校验器和 v4 原型模块。
用法：.venv/Scripts/python.exe -m unittest discover -s tests -p test_v4_native_prototype.py -v
"""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from subprocess import PIPE, run
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from owasp_prompt_generator import OWASP_RISKS, PROMPT_RECORD_KEYS, validate_prompt_records

try:
    data = importlib.import_module("prototypes.v4_demo_data")
except ModuleNotFoundError as error:
    if error.name != "prototypes.v4_demo_data":
        raise
    data = None

try:
    ui = importlib.import_module("prototypes.v4_native_prototype")
except ModuleNotFoundError as error:
    if error.name != "prototypes.v4_native_prototype":
        raise
    ui = None


class V4DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(data, "v4 离线演示批次尚未实现")

    def test_catalog_uses_current_llm_and_complete_agentic_ids(self):
        self.assertEqual(data.catalog_for("llm-2026"), OWASP_RISKS)
        self.assertEqual([r["riskId"] for r in data.catalog_for("agentic-2026")],
                         [f"ASI{i:02d}" for i in range(1, 11)])

    def test_all_risks_all_languages_preserve_contract_and_environment(self):
        for language in ("中文", "英文", "中英混合"):
            with self.subTest(language=language):
                ids = [f"ASI{i:02d}" for i in range(1, 11)]
                batch = data.build_demo_batch("agentic-2026", ids, 20, language)
                records = batch["records"]
                self.assertEqual(validate_prompt_records(records), [])
                self.assertEqual(len(records), 20)
                self.assertEqual(len({r["prompt"] for r in records}), 20)
                self.assertTrue(all(r["userA"] == r["userB"] == "" for r in records))
                self.assertEqual(batch["environment"]["mode"], "prototype-demo")
                self.assertEqual(len(batch["environment"]["records"]), 20)
                for index, (record, env) in enumerate(zip(records, batch["environment"]["records"]), 1):
                    self.assertEqual(set(record), set(PROMPT_RECORD_KEYS))
                    self.assertEqual((env["recordIndex"], env["riskId"]), (index, record["riskId"]))
                    for key in ("prerequisites", "injectionSurface", "setup", "followUp", "evidence"):
                        self.assertTrue(env[key].strip(), key)
                    marker = f"TEST-{record['riskId']}-{1 + (index - 1) // 10:03d}"
                    self.assertIn(marker, record["prompt"])
                    self.assertIn(marker, env["setup"])
                    if language != "英文":
                        self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in record["prompt"]))
                    if language == "英文":
                        self.assertFalse(any("\u4e00" <= c <= "\u9fff" for c in record["prompt"]))

    def test_round_robin_quota_and_unknown_inputs(self):
        batch = data.build_demo_batch("agentic-2026", ["ASI03", "ASI01", "ASI02", "ASI01"], 11, "中文")
        ids = [r["riskId"] for r in batch["records"]]
        self.assertEqual(ids, ["ASI01", "ASI02", "ASI03"] * 3 + ["ASI01", "ASI02"])
        for framework, risks, total, language in (
            ("missing", ["ASI01"], 1, "中文"),
            ("agentic-2026", ["LLM01"], 1, "中文"),
            ("llm-2026", ["ASI01"], 1, "中文"),
            ("agentic-2026", [], 1, "中文"),
            ("agentic-2026", ["ASI01", "ASI02"], 1, "中文"),
            ("agentic-2026", ["ASI01"], True, "中文"),
            ("agentic-2026", ["ASI01"], 1001, "中文"),
            ("agentic-2026", ["ASI01"], 1, "法文"),
        ):
            with self.subTest(framework=framework, risks=risks, total=total, language=language):
                with self.assertRaises(ValueError):
                    data.build_demo_batch(framework, risks, total, language)

    def test_llm_cross_session_semantics_and_current_names(self):
        for language in ("中文", "英文", "中英混合"):
            records = data.build_demo_batch("llm-2026", [r["riskId"] for r in OWASP_RISKS], 20, language)["records"]
            self.assertEqual(validate_prompt_records(records), [])
            self.assertEqual(len(records), 20)
            for record in records:
                if record["riskId"] == "LLM02":
                    self.assertEqual(record["prompt"], record["userB"])
                    self.assertIn("TESTSECRET-", record["userA"])
                    self.assertNotIn("TESTSECRET-", record["userB"])
                else:
                    self.assertEqual(record["userA"], "")
                    self.assertEqual(record["userB"], "")
            self.assertIsNone(data.build_demo_batch("llm-2026", ["LLM01"], 1, language)["environment"])

    def test_distinct_injection_surfaces_and_memory_follow_up(self):
        batch = data.build_demo_batch("agentic-2026", ["ASI01", "ASI06", "ASI07"], 3, "中文")
        env = {entry["riskId"]: entry for entry in batch["environment"]["records"]}
        self.assertIn("工具", env["ASI01"]["injectionSurface"])
        self.assertIn("记忆", env["ASI06"]["injectionSurface"])
        self.assertIn("智能体", env["ASI07"]["injectionSurface"])
        self.assertIn("后续", env["ASI06"]["followUp"])


class V4PrototypeUiTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ui, "v4 原型窗口尚未实现")
        self.window = ui.V4PrototypeApplication()
        self.window.withdraw()
        self.addCleanup(self.window.destroy)

    def generate(self, page, risk="ASI06", total="1"):
        page.risk_vars[risk].set(True)
        page.total_var.set(total)
        page.simulate_generation()

    def test_five_pages_initial_state_and_independent_results(self):
        self.assertEqual([self.window.notebook.tab(tab, "text") for tab in self.window.notebook.tabs()],
                         ["TC260 题库生成", "OWASP LLM 题集", "OWASP Agentic 题集", "来源管理", "设置"])
        self.assertEqual(self.window.notebook.select(), str(self.window.agentic_page))
        page = self.window.agentic_page
        self.assertEqual(page.records, [])
        self.assertTrue(page.json_button.instate(["disabled"]))
        self.generate(page)
        records = json.loads(json.dumps(page.records))
        log = page.log_text.get("1.0", "end")
        self.generate(self.window.llm_page, "LLM02")
        self.assertEqual(page.records, records)
        self.assertEqual(page.log_text.get("1.0", "end"), log)
        self.assertEqual(self.window.llm_page.records[0]["prompt"], self.window.llm_page.records[0]["userB"])

    def test_invalid_request_and_generation_error_clear_old_actions(self):
        page = self.window.agentic_page
        self.generate(page)
        page.total_var.set("not-an-integer")
        page.simulate_generation()
        self.assertEqual(page.records, [])
        self.assertIsNone(page.environment)
        self.assertEqual(page.result_tree.get_children(), ())
        self.assertTrue(page.environment_button.instate(["disabled"]))
        self.assertIn("整数", page.status_var.get())
        page.total_var.set("1")
        page.simulate_generation()
        with patch.object(ui, "build_demo_batch", side_effect=ValueError("模拟失败")):
            page.simulate_generation()
        self.assertEqual(page.records, [])
        self.assertTrue(page.json_button.instate(["disabled"]))
        self.assertIn("模拟失败", page.log_text.get("1.0", "end"))
        self.window.llm_page.risk_vars["LLM01"].set(False)
        self.window.llm_page.simulate_generation()
        self.assertIn("至少", self.window.llm_page.status_var.get())

    def test_full_text_copy_and_six_column_previews(self):
        page = self.window.agentic_page
        self.generate(page)
        page.result_tree.selection_set("0")
        page.copy_selected_prompt()
        self.assertEqual(self.window.clipboard_get(), page.records[0]["prompt"])
        for kind in ("json", "excel", "environment"):
            preview = page.open_preview(kind)
            try:
                if kind == "excel":
                    self.assertEqual(tuple(preview.tree["columns"]), tuple(PROMPT_RECORD_KEYS))
                    self.assertEqual(len(preview.tree.get_children()), 1)
                else:
                    payload = json.loads(preview.text.get("1.0", "end"))
                    self.assertEqual(payload, page.records if kind == "json" else page.environment)
            finally:
                preview.destroy()

    def test_new_batch_closes_only_its_own_stale_previews_including_failure(self):
        page = self.window.agentic_page
        self.generate(page)
        old_json = page.open_preview("json")
        old_environment = page.open_preview("environment")
        self.generate(self.window.llm_page, "LLM02")
        other_preview = self.window.llm_page.open_preview("json")
        page.simulate_generation()
        self.assertFalse(old_json.winfo_exists())
        self.assertFalse(old_environment.winfo_exists())
        self.assertTrue(other_preview.winfo_exists())
        new_preview = page.open_preview("environment")
        page.total_var.set("invalid")
        page.simulate_generation()
        self.assertFalse(new_preview.winfo_exists())
        self.assertTrue(other_preview.winfo_exists())

    def test_cli_and_launcher_smoke_from_another_directory(self):
        root = Path(__file__).resolve().parents[1]
        launcher = root / "docs/V4.0.0/运行-v4-原生原型.bat"
        self.assertTrue(launcher.exists(), "原型启动器尚未实现")
        result = run(["cmd", "/d", "/c", str(launcher), "--smoke-test"], cwd=root.parent,
                     stdout=PIPE, stderr=PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        payload = json.loads(result.stdout)
        self.assertTrue(payload["prototypeReady"])
        self.assertEqual(payload["mode"], "prototype-demo")
        self.assertEqual(payload["catalogs"], {"llm-2026": 10, "agentic-2026": 10})


if __name__ == "__main__":
    unittest.main()
