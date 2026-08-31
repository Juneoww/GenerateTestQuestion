"""集成测试：网站名单、核验日志、爬取报告三类留痕文档的生成与追加。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reporting

SOURCES = [
    {"sourceId": "A1", "name": "站点一", "language": "zh", "method": "html",
     "engine": "fetcher", "status": "ready", "lastCheckedAt": "2026-08-31", "note": ""},
    {"sourceId": "B2", "name": "站点二", "language": "en", "method": "json",
     "engine": "stealthy", "status": "pending", "lastCheckedAt": "", "note": "待核验"},
]
RESULTS = [
    {"sourceId": "A1", "passed": True, "https": True, "reachable": True,
     "structure": True, "content": True, "reason": "", "elapsedMs": 320},
    {"sourceId": "B2", "passed": False, "https": True, "reachable": False,
     "structure": False, "content": False, "reason": "HTTP 500", "elapsedMs": 88},
]
CRAWL_STATS = [
    {"sourceId": "A1", "pages": 2, "fetched": 20, "kept": 18,
     "duplicates": 2, "crossDomain": 1, "failed": 0, "elapsedMs": 1500, "status": "completed"},
]


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="gtq_report_"))

    def test_site_list(self):
        path = reporting.write_site_list(SOURCES, self.base / "网站名单.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("可爬取网站名单", text)
        self.assertIn("| A1 |", text)
        self.assertIn("可爬", text)
        self.assertIn("待核验", text)

    def test_verify_log_appends(self):
        path = self.base / "核验日志.md"
        reporting.append_verify_log(RESULTS, path)
        reporting.append_verify_log(RESULTS, path)
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("## "), 2)
        self.assertIn("HTTP 500", text)
        self.assertIn("通过 1", text)

    def test_crawl_report(self):
        path = reporting.write_crawl_report(self.base, CRAWL_STATS)
        text = path.read_text(encoding="utf-8")
        self.assertIn("爬取报告", text)
        self.assertIn("| A1 | 2 | 20 | 18 | 2 | 1 | 0 | 1500 | completed |", text)


if __name__ == "__main__":
    unittest.main()
