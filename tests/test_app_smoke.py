"""集成测试：无界面烟测——目录、工作区及爬虫运行时数据完整性。"""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class SmokeTests(unittest.TestCase):
    def test_smoke_test_rejects_missing_crawler_data(self):
        missing = Path(__file__).parent / "missing-input-network-definition.zip"
        with patch("apify_fingerprint_datapoints.get_input_network", return_value=missing):
            with self.assertRaisesRegex(FileNotFoundError, "input-network-definition.zip"):
                app.smoke_test()

    def test_smoke_command_exits_without_gui_dialog_when_data_is_missing(self):
        missing = Path(__file__).parent / "missing-input-network-definition.zip"
        errors = io.StringIO()
        with patch("apify_fingerprint_datapoints.get_input_network", return_value=missing):
            with patch.object(sys, "argv", ["app.py", "--smoke-test"]):
                with patch.object(sys, "stderr", errors):
                    with self.assertRaises(SystemExit) as result:
                        app.main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn("input-network-definition.zip", errors.getvalue())

    def test_smoke_test_payload(self):
        result = app.smoke_test()
        self.assertEqual(result["version"], "3.0.1")
        self.assertTrue(result["desktopReady"])
        self.assertEqual(result["workspaces"], ["生成", "OWASP 红队提示词", "来源管理", "设置"])
        self.assertEqual(result["catalog"], {"scenes": 5, "risks": 31})
        self.assertEqual(result["owasp"], {"risks": 10})
        self.assertGreaterEqual(result["sources"]["total"], 1)
        self.assertGreaterEqual(result["sources"]["ready"], 1)
        self.assertIn("python", result)


if __name__ == "__main__":
    unittest.main()
