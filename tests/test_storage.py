"""集成测试：三个 JSON 的读写、默认值合并与风险目录完整性。"""
import json
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

    def test_legacy_settings_file_defaults_question_type_to_text(self):
        (self.base / "settings.json").write_text(
            json.dumps({"apiKey": "legacy-key"}), encoding="utf-8"
        )

        loaded = storage.load_settings(self.base)

        self.assertEqual(loaded["questionType"], "text")

    def test_settings_image_question_type_persists_through_save_and_load(self):
        saved = storage.save_settings({"questionType": "image"}, self.base)
        loaded = storage.load_settings(self.base)

        self.assertEqual(saved["questionType"], "image")
        self.assertEqual(loaded["questionType"], "image")

    def test_invalid_settings_question_type_defaults_to_text(self):
        (self.base / "settings.json").write_text(
            json.dumps({"questionType": "unknown"}), encoding="utf-8"
        )

        loaded = storage.load_settings(self.base)

        self.assertEqual(loaded["questionType"], "text")

    def test_catalog_integrity(self):
        scenes = storage.load_catalog()
        self.assertEqual(len(scenes), 5)
        risks = storage.catalog_risks(scenes)
        self.assertEqual(len(risks), 31)
        ids = [r["riskId"] for r in risks]
        self.assertEqual(len(ids), len(set(ids)))
        codes = sorted({r["sceneCode"] for r in risks})
        self.assertEqual(codes, ["A.1", "A.2", "A.3", "A.4", "A.5"])

    def test_frozen_resources_initialize_empty_directory_without_settings(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bundled = root / "bundle"
            bundled.mkdir()
            (bundled / "sources.json").write_text("sources", encoding="utf-8")
            (bundled / "risk_catalog.json").write_text("risks", encoding="utf-8")
            (bundled / "settings.json").write_text("do-not-copy", encoding="utf-8")
            target = root / "app" / "data"

            storage._initialize_bundled_data(target, bundled)

            self.assertEqual((target / "sources.json").read_text(encoding="utf-8"), "sources")
            self.assertEqual((target / "risk_catalog.json").read_text(encoding="utf-8"), "risks")
            self.assertFalse((target / "settings.json").exists())

    def test_frozen_resources_repair_missing_without_overwriting_existing_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bundled, target = root / "bundle", root / "data"
            bundled.mkdir()
            target.mkdir()
            (bundled / "sources.json").write_text("new-sources", encoding="utf-8")
            (bundled / "risk_catalog.json").write_text("new-risks", encoding="utf-8")
            (target / "sources.json").write_text("user-sources", encoding="utf-8")
            (target / "settings.json").write_text("user-settings", encoding="utf-8")

            storage._initialize_bundled_data(target, bundled)

            self.assertEqual((target / "sources.json").read_text(encoding="utf-8"), "user-sources")
            self.assertEqual((target / "risk_catalog.json").read_text(encoding="utf-8"), "new-risks")
            self.assertEqual((target / "settings.json").read_text(encoding="utf-8"), "user-settings")

    def test_frozen_resources_repair_missing_sources_without_replacing_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bundled, target = root / "bundle", root / "data"
            bundled.mkdir()
            target.mkdir()
            (bundled / "sources.json").write_text("new-sources", encoding="utf-8")
            (bundled / "risk_catalog.json").write_text("new-risks", encoding="utf-8")
            (target / "risk_catalog.json").write_text("user-risks", encoding="utf-8")

            storage._initialize_bundled_data(target, bundled)

            self.assertEqual((target / "sources.json").read_text(encoding="utf-8"), "new-sources")
            self.assertEqual((target / "risk_catalog.json").read_text(encoding="utf-8"), "user-risks")


if __name__ == "__main__":
    unittest.main()
