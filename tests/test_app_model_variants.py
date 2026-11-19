"""验证模型改写入口在原题窗口使用第三个策略下拉组。"""

import tempfile
import unittest
from unittest.mock import patch

import app


class ModelVariantEntryTests(unittest.TestCase):
    def setUp(self):
        settings = patch.object(app.storage, "load_settings", return_value={})
        self.settings = settings.start()
        self.addCleanup(settings.stop)
        self.window = app.DesktopApplication()
        self.window.withdraw()
        self.window.update_idletasks()
        self.addCleanup(self._destroy_window)

    def _destroy_window(self):
        for timer in self.window.tk.call("after", "info"):
            self.window.after_cancel(timer)
        self.window.destroy()

    def test_main_window_has_no_model_rewrite_button(self):
        def labels(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TButton":
                    yield child.cget("text")
                yield from labels(child)

        self.assertNotIn("模型改写变种", list(labels(self.window)))

    def test_current_batch_window_has_third_dropdown_with_multiple_strategies(self):
        with tempfile.TemporaryDirectory() as directory:
            self.settings.return_value = {"outputDir": directory}
            records = [{"question": "当前批次原题", "language": "zh"}]
            self.window.current_questions = records
            self.window.current_batch_dir = directory
            self.window._open_strategy_window("tc")
            rules = next(iter(self.window._strategy_windows.values()))
            self.addCleanup(rules.destroy)
            rules.strategy_group_buttons["基础规则"].invoke()
            rules._set_group("基础规则", True)
            rule_ids = set(rules._selected()[1])
            self.assertTrue(rule_ids)

            group = "模型改写变种"
            entry = rules.strategy_group_buttons[group]
            self.assertIs(entry.master, rules.strategy_select)
            self.assertEqual(int(entry.grid_info()["column"]), 2)
            entry.invoke()

            self.assertEqual(rules.open_strategy_group, group)
            self.assertEqual(rules.records, records)
            self.assertEqual(set(rules._selected()[1]), rule_ids)
            for strategy_id in ("S01", "S17", "S18"):
                checkbox = next(
                    item for item in rules.strategy_checks if item.cget("text").startswith(strategy_id + " ")
                )
                checkbox.invoke()
            self.assertEqual(set(rules._selected()[1]) - rule_ids, {"S01", "S17", "S18"})
            self.assertIn("已选 3", entry.cget("text"))
            self.assertEqual(list(self.window._strategy_windows.values()), [rules])


if __name__ == "__main__":
    unittest.main()
