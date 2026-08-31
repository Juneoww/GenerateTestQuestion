"""集成测试：爬虫的门禁、链接提取、正文提取、逐条落盘、去重与核验判定（fake fetch，无网络）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crawler

SETTINGS = {"crawlDelayMs": 0, "requestTimeoutSeconds": 5, "responseLimitMiB": 2}

LIST_HTML = (
    '<a href="/art/2024/0512/a111_web.html">1</a>'
    '<a href="/art/2024/0513/b222_web.html">2</a>'
    '<a href="/art/2024/0514/c333_web.html">3</a>'
    '<a href="http://www.gov.cn/art/2024/0515/d444_web.html">4</a>'
    '<a href="https://other.example.com/y.html">5</a>'
)
DETAIL_TEMPLATE = (
    "<html><head><title>案例通报 {n}</title></head><body>"
    "<p>第{n}号案例：某公司发布虚假广告被市场监管部门处罚一百万元整，"
    "现已向社会公开通报，并提示广大消费者注意甄别。</p>"
    "<p>搜索</p><p>首页</p></body></html>"
)
SOURCE = {
    "sourceId": "T1", "name": "测试站", "url": "https://www.gov.cn/list1.html",
    "language": "zh", "method": "html",
    "listUrlTemplate": "https://www.gov.cn/list{num}.html",
    "itemPattern": r'href="(/art/[^"]+)"', "itemUrlBase": "https://www.gov.cn",
    "startPage": 1, "maxPages": 2, "maxItems": 5, "engine": "fetcher", "status": "ready",
}


def make_fetch():
    calls = []

    def fetch(url, settings):
        calls.append(url)
        if "/art/" in url:
            n = url.split("/")[-1].split("_")[0]
            return 200, DETAIL_TEMPLATE.format(n=n), url
        return 200, LIST_HTML, url

    return fetch, calls


class SafetyTests(unittest.TestCase):
    def test_is_safe_url(self):
        self.assertTrue(crawler.is_safe_url("https://a.com/x"))
        self.assertTrue(crawler.is_safe_url("https://a.com:443/x"))
        self.assertFalse(crawler.is_safe_url("http://a.com/x"))
        self.assertFalse(crawler.is_safe_url("https://user:pass@a.com/x"))
        self.assertFalse(crawler.is_safe_url("https://a.com:8080/x"))
        self.assertFalse(crawler.is_safe_url("not a url"))


class ExtractTests(unittest.TestCase):
    def test_extract_links_filters(self):
        links, cross = crawler.extract_links(
            LIST_HTML, r'href="(/art/[^"]+)"', "https://www.gov.cn", "www.gov.cn"
        )
        self.assertEqual(len(links), 3)  # http 同域链接被丢弃（非 HTTPS）
        self.assertEqual(cross, 0)
        links2, cross2 = crawler.extract_links(
            LIST_HTML, r'href="(https://[^"]+)"', "https://www.gov.cn", "www.gov.cn"
        )
        self.assertEqual(links2, [])  # 跨域 HTTPS 链接被丢弃
        self.assertEqual(cross2, 1)

    def test_extract_text_boilerplate(self):
        text = crawler.extract_text(DETAIL_TEMPLATE.format(n=1))
        self.assertIn("虚假广告", text)
        lines = text.split("\n")
        self.assertNotIn("搜索", lines)
        self.assertNotIn("首页", lines)

    def test_extract_title(self):
        self.assertIn("案例通报", crawler.extract_title(DETAIL_TEMPLATE.format(n=7)))


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.out_dir = Path(tempfile.mkdtemp(prefix="gtq_crawl_"))
        self.events = []

    def test_crawl_writes_and_dedups(self):
        fetch, calls = make_fetch()
        seen = set()
        stats = crawler.crawl_source(SOURCE, SETTINGS, self.events.append, self.out_dir, seen, fetch)
        self.assertEqual(stats["kept"], 3)
        self.assertEqual(stats["status"], "completed")
        lines = (self.out_dir / "items.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        first = json.loads(lines[0])
        self.assertIn("ITM-", first["itemId"])
        self.assertIn("虚假广告", first["text"])
        # 历史哈希已入 seen：重跑全部去重（两页列表各 3 条链接，共 6 次命中）
        stats2 = crawler.crawl_source(SOURCE, SETTINGS, self.events.append, self.out_dir, seen, fetch)
        self.assertEqual(stats2["kept"], 0)
        self.assertEqual(stats2["duplicates"], 6)

    def test_max_items_cap(self):
        fetch, _ = make_fetch()
        source = {**SOURCE, "maxItems": 2}
        stats = crawler.crawl_source(source, SETTINGS, self.events.append, self.out_dir, set(), fetch)
        self.assertEqual(stats["kept"], 2)

    def test_first_page_failure_raises(self):
        def fetch(url, settings):
            return 503, "", url

        with self.assertRaises(crawler.CrawlError):
            crawler.crawl_source(SOURCE, SETTINGS, self.events.append, self.out_dir, set(), fetch)


class VerifyTests(unittest.TestCase):
    def test_verify_ready(self):
        fetch, _ = make_fetch()
        result = crawler.verify_source(SOURCE, SETTINGS, fetch)
        self.assertTrue(result["passed"])
        self.assertTrue(result["https"] and result["reachable"] and result["structure"] and result["content"])
        self.assertEqual(result["reason"], "")

    def test_verify_http_failure(self):
        def fetch(url, settings):
            return 404, "", url

        result = crawler.verify_source(SOURCE, SETTINGS, fetch)
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "HTTP 404")

    def test_verify_rejects_non_https(self):
        result = crawler.verify_source({**SOURCE, "url": "http://www.gov.cn"}, SETTINGS, None)
        self.assertFalse(result["https"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
