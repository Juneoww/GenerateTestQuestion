"""集成测试：批次编排端到端（fake 爬虫 + fake 出题，无网络）——产物齐全、配额正确、熔断路径。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import question_generator

SETTINGS = {
    "baseUrl": "", "apiKey": "", "model": "test-model", "temperature": 0.5,
    "timeoutSeconds": 5, "retries": 2, "maxQuestionsPerItem": 5,
    "crawlDelayMs": 0, "requestTimeoutSeconds": 5, "responseLimitMiB": 2,
    "imageBaseUrl": "https://example.com/v1", "imageModel": "test-image",
}
FAKE_SOURCES = [
    {"sourceId": "S1", "name": "来源一", "url": "https://s1.com", "language": "zh",
     "method": "html", "status": "ready", "engine": "fetcher", "note": "", "lastCheckedAt": "",
     "startPage": 1, "maxPages": 1, "maxItems": 10},
    {"sourceId": "S2", "name": "来源二", "url": "https://s2.com", "language": "en",
     "method": "html", "status": "ready", "engine": "fetcher", "note": "", "lastCheckedAt": "",
     "startPage": 1, "maxPages": 1, "maxItems": 10},
]
RISK_IDS = ["A1-01", "A1-02", "A1-03", "A1-04", "A1-05"]


def fake_crawl(source, settings, on_event, out_dir, seen_hashes, fetch_fn=None):
    language = source.get("language", "zh")
    items = []
    for i in range(2):
        text = f"素材{source['sourceId']}{i}：某公司虚假宣传被处罚一百万元，已公开通报。"
        items.append({
            "itemId": f"ITM-{source['sourceId']}{i}",
            "sourceId": source["sourceId"], "url": f"https://x.com/{i}",
            "finalUrl": f"https://x.com/{i}", "title": f"标题{source['sourceId']}{i}",
            "text": text, "fetchedAt": "2026-08-31T00:00:00Z", "httpStatus": 200,
            "contentHash": f"hash-{source['sourceId']}{i}", "language": language,
        })
    return {"sourceId": source["sourceId"], "pages": 1, "fetched": 2, "kept": 2,
            "duplicates": 0, "crossDomain": 0, "failed": 0, "elapsedMs": 1,
            "status": "completed", "items": items}


def fake_generate(item, risk, language, count, settings, seen, record_call, events,
                  question_type="text"):
    produced = []
    for i in range(count):
        q = f"针对{risk['riskId']}的{language}测试问题{item['itemId']}{i}？"
        digest = question_generator.question_hash(q)
        if digest in seen:
            continue
        seen.add(digest)
        produced.append({"question": q})
    record_call({"ts": "2026-08-31T00:00:00Z", "model": settings["model"], "riskId": risk["riskId"],
                 "questionType": question_type, "language": language, "itemId": item["itemId"],
                 "asked": count, "got": len(produced),
                 "status": "ok" if produced else "parse_error", "attempt": 1,
                 "elapsedMs": 1, "promptChars": 100, "error": None})
    return produced


def fake_generate_empty(*args, **kwargs):
    return []


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="gtq_pipe_")
        self.addCleanup(temp_dir.cleanup)
        self.tmp = Path(temp_dir.name)
        self.original_output = pipeline.OUTPUT_DIR
        self.original_load = pipeline.storage.load_sources
        self.original_crawl = pipeline.crawler.crawl_source
        pipeline.OUTPUT_DIR = self.tmp
        pipeline.storage.load_sources = lambda base_dir=None: [dict(s) for s in FAKE_SOURCES]
        pipeline.crawler.crawl_source = fake_crawl
        self.events = []
        self.addCleanup(setattr, pipeline, "OUTPUT_DIR", self.original_output)
        self.addCleanup(setattr, pipeline.storage, "load_sources", self.original_load)
        self.addCleanup(setattr, pipeline.crawler, "crawl_source", self.original_crawl)

    def run_batch(self, generate_fn=fake_generate, total=3, zh_percent=67, risk_ids=None,
                  question_type="text", image_fn=None):
        params = {"sourceIds": ["S1", "S2"], "riskIds": risk_ids or ["A1-01", "A1-02"],
                  "total": total, "zhPercent": zh_percent, "questionType": question_type}
        return pipeline.run_batch(params, SETTINGS, self.events.append,
                                  fetch_fn=lambda *a: (200, "", ""), generate_fn=generate_fn,
                                  image_fn=image_fn or self.fake_image)

    @staticmethod
    def fake_image(prompt, settings, batch_dir, seq):
        path = batch_dir / "images" / f"{seq:04}.png"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"image")
        return {"imageStatus": "success", "imagePath": f"images/{seq:04}.png",
                "imageError": "", "imageModel": "test-image", "attempts": 1, "elapsedMs": 1}

    def test_image_results_preserve_files_and_report_partial_status(self):
        def fake_image(prompt, settings, batch_dir, seq):
            if seq == 1:
                return self.fake_image(prompt, settings, batch_dir, seq)
            return {"imageStatus": "rejected" if seq == 2 else "failed", "imagePath": "",
                    "imageError": "拒绝" if seq == 2 else "出错", "imageModel": "test-image"}
        summary = self.run_batch(total=3, zh_percent=100, risk_ids=["A1-01"],
                                 question_type="image", image_fn=fake_image)
        batch = Path(summary["batchDir"])
        self.assertEqual(summary["imageSummary"], {"status": "partial", "promptCount": 3,
                         "imageSuccessCount": 1, "imageRejectedCount": 1, "imageFailedCount": 1})
        self.assertTrue((batch / summary["questions"][0]["imagePath"]).is_file())
        self.assertEqual([q["imageStatus"] for q in summary["questions"]], ["success", "rejected", "failed"])
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["imageSummary"], summary["imageSummary"])
        from openpyxl import load_workbook
        workbook = load_workbook(batch / "questions.xlsx", read_only=True)
        self.addCleanup(workbook.close)
        ws = workbook.active
        self.assertEqual([ws.cell(1, c).value for c in range(14, 18)],
                         ["图片路径", "图片状态", "图片模型", "图片失败原因"])

    def test_global_image_failure_stops_remaining_requests(self):
        generate_image = Mock(return_value={"imageStatus": "failed", "imageError": "鉴权失败",
                                           "globalError": True})
        summary = self.run_batch(total=3, zh_percent=100, risk_ids=["A1-01"],
                                 question_type="image", image_fn=generate_image)
        self.assertEqual(generate_image.call_count, 1)
        self.assertEqual(summary["imageSummary"]["imageFailedCount"], 3)
        self.assertEqual(summary["imageSummary"]["status"], "failed")
        self.assertIn("未调用", summary["questions"][1]["imageError"])

    def test_image_batch_requires_configuration_before_crawling(self):
        params = {"sourceIds": ["S1"], "riskIds": ["A1-01"], "total": 1,
                  "zhPercent": 100, "questionType": "image"}
        with self.assertRaisesRegex(ValueError, "文生图"):
            pipeline.run_batch(params, dict(SETTINGS, imageBaseUrl=""), self.events.append,
                               generate_fn=fake_generate, image_fn=self.fake_image)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_same_second_batch_names_do_not_overwrite(self):
        from datetime import datetime
        from unittest.mock import patch
        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 3, 12, 0, 0, tzinfo=tz)
        with patch.object(pipeline, "datetime", FixedClock):
            first = self.run_batch(total=1, question_type="image")
            first_file = Path(first["batchDir"]) / "images/0001.png"
            first_file.write_bytes(b"first batch")
            second = self.run_batch(total=1, question_type="image")
        self.assertNotEqual(first["batchDir"], second["batchDir"])
        self.assertTrue(second["batchId"].endswith("-IMG"))
        self.assertEqual(first_file.read_bytes(), b"first batch")

    def test_image_event_has_safe_diagnostics_and_progress_omits_evidence(self):
        summary = self.run_batch(total=1, question_type="image")
        event = next(e for e in self.events if e.get("stage") == "image")
        self.assertEqual((event["model"], event["status"], event["attempts"], event["elapsedMs"]),
                         ("test-image", "success", 1, 1))
        progress = json.loads((Path(summary["batchDir"]) / "image_progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["questions"][0]["question"], summary["questions"][0]["question"])
        self.assertNotIn("evidenceText", progress["questions"][0])

    def test_end_to_end(self):
        summary = self.run_batch()
        batch_dir = Path(summary["batchDir"])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["questionCount"], 3)
        self.assertEqual(summary["zhCount"], 2)
        self.assertEqual(summary["enCount"], 1)
        for name in ("questions.json", "questions.xlsx", "manifest.json",
                     "run.log", "crawl_report.md", "llm_calls.jsonl"):
            self.assertTrue((batch_dir / name).exists(), f"缺少产物 {name}")
        doc = json.loads((batch_dir / "questions.json").read_text(encoding="utf-8"))
        self.assertEqual([q["seq"] for q in doc["questions"]], [1, 2, 3])
        self.assertEqual(doc["shortage"], [])
        manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["generate"]["calls"], 3)
        by_source = {s["sourceId"]: s for s in manifest["crawl"]["bySource"]}
        self.assertEqual(by_source["S1"]["kept"], 2)  # 条目落盘由 test_crawler 覆盖

    def test_abort_circuit_breaker(self):
        summary = self.run_batch(generate_fn=fake_generate_empty, total=5, zh_percent=100, risk_ids=RISK_IDS)
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["questionCount"], 0)
        # 熔断在第 3 组的第 1 次调用触发（5 连空），此前 3 组计入缺口
        self.assertEqual(len(summary["shortage"]), 3)

    def test_all_crawls_fail_records_failed_batch_without_model_calls(self):
        def fail_crawl(*args, **kwargs):
            raise pipeline.crawler.CrawlError("列表页请求失败：curl: (35) Connection was reset")

        pipeline.crawler.crawl_source = fail_crawl
        generate = Mock(side_effect=AssertionError("没有素材时不得调用模型"))
        summary = self.run_batch(generate_fn=generate, total=4, zh_percent=100,
                                 question_type="image")
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["questionCount"], 0)
        self.assertIn("来源抓取失败", summary["error"])
        self.assertIn("未调用模型", summary["error"])
        generate.assert_not_called()
        batch_dir = Path(summary["batchDir"])
        manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["error"], summary["error"])
        self.assertEqual(manifest["generate"]["calls"], 0)
        self.assertEqual(sum(s["target"] for s in manifest["shortage"]), 4)
        self.assertIn("curl: (35)", manifest["crawl"]["bySource"][0]["reason"])
        self.assertTrue((batch_dir / "questions.json").exists())
        self.assertTrue((batch_dir / "crawl_report.md").exists())
        self.assertEqual(self.events[-1]["level"], "error")
        self.assertIn("批次失败", self.events[-1]["message"])
        self.assertNotIn("批次完成", self.events[-1]["message"])

    def test_empty_material_pool_explains_no_new_material(self):
        def empty_crawl(*args, **kwargs):
            return {**fake_crawl(*args, **kwargs), "items": [], "kept": 0, "duplicates": 2}

        pipeline.crawler.crawl_source = empty_crawl
        generate = Mock(side_effect=AssertionError("没有素材时不得调用模型"))
        summary = self.run_batch(generate_fn=generate)
        self.assertEqual(summary["status"], "failed")
        self.assertIn("未获取到可用的新素材", summary["error"])
        self.assertIn("去重", summary["error"])
        generate.assert_not_called()

    def test_zero_valid_questions_is_failed_without_hitting_circuit_breaker(self):
        summary = self.run_batch(generate_fn=fake_generate_empty, total=2,
                                 zh_percent=100, risk_ids=["A1-01"])
        self.assertEqual(summary["status"], "failed")
        self.assertIn("模型未产出有效题目", summary["error"])
        self.assertEqual(self.events[-1]["level"], "error")

    def test_one_failed_source_does_not_fail_successful_generation(self):
        def partly_failed_crawl(source, *args, **kwargs):
            if source["sourceId"] == "S2":
                raise pipeline.crawler.CrawlError("列表页请求失败")
            return fake_crawl(source, *args, **kwargs)

        pipeline.crawler.crawl_source = partly_failed_crawl
        summary = self.run_batch(total=2, zh_percent=100, risk_ids=["A1-01"])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["questionCount"], 2)

    def test_shortage_when_pool_exhausted(self):
        # 每条原文只出 1 道（maxQuestionsPerItem 生效上限外的池子限制由 visited 模拟）
        def limited(item, risk, language, count, settings, seen, record_call, events,
                    question_type="text"):
            return fake_generate(item, risk, language, min(count, 1), settings, seen,
                                 record_call, events, question_type=question_type)
        summary = self.run_batch(generate_fn=limited, total=6, zh_percent=100, risk_ids=["A1-01"])
        # 2 条中文素材，每条 1 道 → 最多 2 题，目标 6 → 缺口
        self.assertEqual(summary["questionCount"], 2)
        self.assertEqual(len(summary["shortage"]), 1)
        self.assertEqual(summary["shortage"][0]["target"], 6)

    def test_image_batch_marks_dir_and_questions(self):
        summary = self.run_batch(total=2, zh_percent=100, risk_ids=["A1-01"], question_type="image")
        batch_dir = Path(summary["batchDir"])
        self.assertTrue(summary["batchId"].endswith("-IMG"), summary["batchId"])
        self.assertTrue(batch_dir.name.endswith("-IMG"))
        self.assertTrue(all(q["questionType"] == "image" for q in summary["questions"]))
        doc = json.loads((batch_dir / "questions.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["params"]["questionType"], "image")
        manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["params"]["questionType"], "image")
        # 留痕行区分题目形式
        calls = [json.loads(line) for line in
                 (batch_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(calls and all(c["questionType"] == "image" for c in calls))

    def test_text_batch_default_keeps_plain_dir_name_when_question_type_is_omitted(self):
        params = {"sourceIds": ["S1", "S2"], "riskIds": ["A1-01", "A1-02"],
                  "total": 3, "zhPercent": 67}
        summary = pipeline.run_batch(params, SETTINGS, self.events.append,
                                     fetch_fn=lambda *a: (200, "", ""), generate_fn=fake_generate)
        self.assertNotIn("-IMG", summary["batchId"])
        self.assertTrue(all(q["questionType"] == "text" for q in summary["questions"]))

    def test_invalid_question_types_rejected_before_creating_batch_dir(self):
        for question_type in (None, 0, "", "unknown"):
            with self.subTest(question_type=question_type):
                params = {"sourceIds": ["S1", "S2"], "riskIds": ["A1-01", "A1-02"],
                          "total": 3, "zhPercent": 67, "questionType": question_type}
                children_before = set(self.tmp.iterdir())
                with self.assertRaisesRegex(ValueError, "题目形式"):
                    pipeline.run_batch(params, SETTINGS, self.events.append,
                                       fetch_fn=lambda *a: (200, "", ""), generate_fn=fake_generate)
                self.assertEqual(set(self.tmp.iterdir()), children_before)

    def test_no_ready_sources_raises(self):
        pipeline.storage.load_sources = lambda base_dir=None: []
        with self.assertRaises(RuntimeError):
            self.run_batch()

    def test_resolve_output_dir(self):
        self.assertEqual(pipeline.resolve_output_dir({}), pipeline.OUTPUT_DIR)
        self.assertEqual(pipeline.resolve_output_dir({"outputDir": "   "}), pipeline.OUTPUT_DIR)
        self.assertEqual(pipeline.resolve_output_dir({"outputDir": "D:\\题库"}), Path("D:\\题库"))
        self.assertEqual(pipeline.resolve_output_dir({"outputDir": "out/lib"}),
                         pipeline.storage.PROJECT_ROOT / "out" / "lib")

    def test_run_batch_uses_custom_output_dir(self):
        custom_root = self.tmp / "custom_lib"
        settings = dict(SETTINGS, outputDir=str(custom_root))
        params = {"sourceIds": ["S1"], "riskIds": ["A1-01"], "total": 2, "zhPercent": 50}
        summary = pipeline.run_batch(params, settings, self.events.append,
                                     fetch_fn=lambda *a: (200, "", ""), generate_fn=fake_generate)
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(summary["batchDir"].startswith(str(custom_root)))
        # 去重索引随产物目录走
        self.assertTrue((custom_root / ".hash_index.json").exists())


if __name__ == "__main__":
    unittest.main()
