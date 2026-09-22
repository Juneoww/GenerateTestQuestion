"""功能: 验证批次失败、中止和成功时的界面反馈。
实现: 使用透明 Tk 窗口和内存批次数据；仅替换消息框，防止测试等待人工关闭。
输入: 合成的批次汇总，不抓取网页、不调用模型、不写用户数据。
输出: unittest 检查结果。
依赖: 项目运行依赖与 Tk 图形环境。
用法: .venv/Scripts/python -m unittest discover -s tests -p test_app_batch_result.py -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class BatchResultUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = app.DesktopApplication()
        cls.window.attributes("-alpha", 0)
        cls.window.update()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.window.tk.call("after", "info"):
            cls.window.after_cancel(timer)
        cls.window.destroy()

    def setUp(self):
        self.question = {
            "seq": 1, "question": "上次批次的测试题", "riskId": "A1-01", "sceneCode": "A.1",
            "category": "测试类别", "language": "zh", "sourceName": "测试来源",
            "sourceUrl": "https://example.com/", "evidenceText": "测试依据原文",
        }
        self.window.current_questions = [self.question]
        self.window._populate_question_tree()
        self.window.update()
        self.summary = {
            "batchId": "BATCH-TEST", "batchDir": "test-batch", "xlsxPath": "test-batch/questions.xlsx",
            "questionCount": 0, "zhCount": 0, "enCount": 0, "questions": [], "shortage": [],
            "status": "failed", "error": "所有选中来源抓取失败，未调用模型。",
        }

    def test_failed_batch_shows_error_clears_old_detail_and_keeps_logs_accessible(self):
        with patch.object(app.messagebox, "showerror") as error, \
                patch.object(app.messagebox, "showinfo") as info:
            self.window._finish_batch({"ok": True, "summary": self.summary})
        error.assert_called_once()
        info.assert_not_called()
        self.assertIn("未调用模型", error.call_args.args[1])
        self.assertIn("失败", self.window.status_text.get())
        self.assertEqual(self.window.question_tree.get_children(), ())
        self.assertEqual(self.window.detail_text.get("1.0", "end-1c"), "")
        self.assertTrue(self.window.open_batch_button.instate(["!disabled"]))
        self.assertTrue(self.window.open_xlsx_button.instate(["disabled"]))

    def test_aborted_batch_shows_warning_instead_of_success(self):
        summary = {**self.summary, "status": "aborted", "error": "连续 5 次出题无产出，已中止。",
                   "questions": [self.question], "questionCount": 1, "zhCount": 1}
        with patch.object(app.messagebox, "showwarning") as warning, \
                patch.object(app.messagebox, "showinfo") as info:
            self.window._finish_batch({"ok": True, "summary": summary})
        warning.assert_called_once()
        info.assert_not_called()
        self.assertIn("中止", self.window.status_text.get())
        self.assertTrue(self.window.open_xlsx_button.instate(["!disabled"]))

    def test_successful_batch_keeps_success_dialog_and_question_details(self):
        summary = {**self.summary, "status": "completed", "error": "", "questions": [self.question],
                   "questionCount": 1, "zhCount": 1}
        with patch.object(app.messagebox, "showinfo") as info, \
                patch.object(app.messagebox, "showerror") as error:
            self.window._finish_batch({"ok": True, "summary": summary})
        info.assert_called_once()
        error.assert_not_called()
        self.assertIn("完成", self.window.status_text.get())
        self.assertIn(self.question["question"], self.window.detail_text.get("1.0", "end-1c"))
        self.assertTrue(self.window.open_xlsx_button.instate(["!disabled"]))


if __name__ == "__main__":
    unittest.main()
