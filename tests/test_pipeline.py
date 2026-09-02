"""集成测试：批次编排端到端（fake 爬虫 + fake 出题，无网络）——产物齐全、配额正确、熔断路径。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import question_generator

SETTINGS = {
    "baseUrl": "", "apiKey": "", "model": "test-model", "temperature": 0.5,
    "timeoutSeconds": 5, "retries": 2, "maxQuestionsPerItem": 5,
    "crawlDelayMs": 0, "requestTimeoutSeconds": 5, "responseLimitMiB": 2,
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


def fake_generate(item, risk, language, count, settings, seen, record_call, events):
    produced = []
    for i in range(count):
        q = f"针对{risk['riskId']}的{language}测试问题{item['itemId']}{i}？"
        digest = question_generator.question_hash(q)
        if digest in seen:
            continue
        seen.add(digest)
        produced.append({"question": q})
    record_call({"ts": "2026-08-31T00:00:00Z", "model": settings["model"], "riskId": risk["riskId"],
                 "language": language, "itemId": item["itemId"], "asked": count, "got": len(produced),
                 "status": "ok" if produced else "parse_error", "attempt": 1,
                 "elapsedMs": 1, "promptChars": 100, "error": None})
    return produced


def fake_generate_empty(*args, **kwargs):
    return []


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gtq_pipe_"))
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

    def run_batch(self, generate_fn=fake_generate, total=3, zh_percent=67, risk_ids=None):
        params = {"sourceIds": ["S1", "S2"], "riskIds": risk_ids or ["A1-01", "A1-02"],
                  "total": total, "zhPercent": zh_percent}
        return pipeline.run_batch(params, SETTINGS, self.events.append,
                                  fetch_fn=lambda *a: (200, "", ""), generate_fn=generate_fn)

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

    def test_shortage_when_pool_exhausted(self):
        # 每条原文只出 1 道（maxQuestionsPerItem 生效上限外的池子限制由 visited 模拟）
        limited = lambda item, risk, language, count, settings, seen, record_call, events: fake_generate(item, risk, language, min(count, 1), settings, seen, record_call, events)
        summary = self.run_batch(generate_fn=limited, total=6, zh_percent=100, risk_ids=["A1-01"])
        # 2 条中文素材，每条 1 道 → 最多 2 题，目标 6 → 缺口
        self.assertEqual(summary["questionCount"], 2)
        self.assertEqual(len(summary["shortage"]), 1)
        self.assertEqual(summary["shortage"][0]["target"], 6)

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
