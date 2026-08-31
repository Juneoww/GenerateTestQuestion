"""集成测试：无界面烟测——数据桥、风险目录、来源清单与工作区清单。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class SmokeTests(unittest.TestCase):
    def test_smoke_test_payload(self):
        result = app.smoke_test()
        self.assertTrue(result["desktopReady"])
        self.assertEqual(result["workspaces"], ["生成", "来源管理", "设置"])
        self.assertEqual(result["catalog"], {"scenes": 5, "risks": 31})
        self.assertGreaterEqual(result["sources"]["total"], 1)
        self.assertGreaterEqual(result["sources"]["ready"], 1)
        self.assertIn("python", result)


if __name__ == "__main__":
    unittest.main()
