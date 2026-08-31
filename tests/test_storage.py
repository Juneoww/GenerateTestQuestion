"""集成测试：三个 JSON 的读写、默认值合并与风险目录完整性。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="gtq_store_"))

    def test_sources_defaults_roundtrip(self):
        storage.save_sources([{"sourceId": "A", "name": "站点A", "url": "https://a.com"}], self.base)
        loaded = storage.load_sources(self.base)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["status"], "pending")
        self.assertEqual(loaded[0]["engine"], "fetcher")
        self.assertEqual(loaded[0]["maxItems"], 20)

    def test_sources_bad_ints_fall_back(self):
        storage.save_sources([{"sourceId": "A", "url": "https://a.com", "maxItems": "x"}], self.base)
        loaded = storage.load_sources(self.base)
        self.assertEqual(loaded[0]["maxItems"], 20)

    def test_settings_merge_and_coerce(self):
        merged = storage.save_settings({"apiKey": "secret", "retries": "9", "unknown": 1}, self.base)
        self.assertEqual(merged["retries"], 9)
        self.assertEqual(merged["crawlDelayMs"], 500)
        self.assertNotIn("unknown", merged)
        again = storage.load_settings(self.base)
        self.assertEqual(again["apiKey"], "secret")

    def test_catalog_integrity(self):
        scenes = storage.load_catalog()
        self.assertEqual(len(scenes), 5)
        risks = storage.catalog_risks(scenes)
        self.assertEqual(len(risks), 31)
        ids = [r["riskId"] for r in risks]
        self.assertEqual(len(ids), len(set(ids)))
        codes = sorted({r["sceneCode"] for r in risks})
        self.assertEqual(codes, ["A.1", "A.2", "A.3", "A.4", "A.5"])


if __name__ == "__main__":
    unittest.main()
