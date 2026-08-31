"""功能:
  Scrapling 爬虫封装：来源自动核验、列表/详情抓取、HTTPS 门禁、同域过滤、
  内容哈希去重、每请求礼貌延时、逐条落盘（crawl/<sourceId>/items.jsonl）。
实现:
  Scrapling 仅在真正发起请求时导入（便于测试离线注入 fake fetch_fn）；
  中文项目路径下 libcurl 无法读取 certifi 证书，首次请求前把证书复制到 ASCII
  路径并设置 CURL_CA_BUNDLE。抓取的原始 HTML 通过正则提取标题/正文并过滤样板行。
输入: 来源 dict（storage.SOURCE_DEFAULTS 结构）、settings。
输出: items.jsonl 行（每条 dict）、核验结果 dict、爬取统计 dict。
依赖: Python 3.10+ 标准库；运行期 scrapling[fetchers]（requirements.txt 已声明）。
用法:
  stats = crawler.crawl_source(source, settings, on_event, out_dir, seen_hashes)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit


class CrawlError(Exception):
    """列表首页或整站级失败。"""


class FetchError(Exception):
    """单个请求级失败（超时、状态异常、超大响应）。"""


_ca_ascii_path: str | None = None

BOILERPLATE_LINE = re.compile(
    r"^(搜索|登录|注册|首页|当前位置|分享到|返回|相关阅读|友情链接|网站地图|版权声明|版权所有"
    r"|关于我们|联系我们|主办单位|承办单位|Copyright|©|All\s+Rights\s+Reserved)",
    re.IGNORECASE,
)
NAV_NOISE_LINE = re.compile(
    r"^(Menu|Donate|Articles|Latest|Fact checks|Analysis|Comment|Topics|Politics|Health|Immigration"
    r"|Economy, Business & Finance|Culture & Society|Science & Technology|Environment|Crime|Law"
    r"|Education|Europe|Online|Search|Subscribe|Newsletter|Sign in|Log in|Skip to content|Main menu"
    r"|Footer|Home|About|Contact|Press|Privacy|Terms|Accessibility|Cookies)$",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>([\s\S]*?)</title>", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_safe_url(url: str) -> bool:
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.port in (None, 443)
        and not parts.username
        and not parts.password
        and bool(parts.netloc)
    )


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _ensure_ascii_ca_bundle() -> None:
    """中文路径下 curl_cffi 读取 certifi 证书失败（curl error 77），复制到 ASCII 路径。"""
    global _ca_ascii_path
    if _ca_ascii_path:
        return
    try:
        import certifi

        source = certifi.where()
        if all(ord(ch) < 128 for ch in source):
            _ca_ascii_path = source
            return
        target = Path(tempfile.gettempdir()) / "gtq_cacert.pem"
        if not target.exists() or target.stat().st_size != Path(source).stat().st_size:
            shutil.copyfile(source, target)
        os.environ["CURL_CA_BUNDLE"] = str(target)
        _ca_ascii_path = str(target)
    except Exception:  # 环境异常时交由请求层自然报错
        _ca_ascii_path = "unavailable"


def _scrapling_fetch(url: str, settings: dict) -> tuple[int, str, str]:
    from scrapling.fetchers import Fetcher  # 延迟导入，保持模块可离线导入

    _ensure_ascii_ca_bundle()
    try:
        response = Fetcher.get(url, timeout=settings["requestTimeoutSeconds"])
    except Exception as error:  # scrapling 内部已重试，失败即该请求失败
        raise FetchError(str(error)[:200]) from error
    status = int(getattr(response, "status", 0) or 0)
    body = getattr(response, "body", b"") or b""
    limit = max(1, int(settings.get("responseLimitMiB", 2))) * 1024 * 1024
    if len(body) > limit:
        raise FetchError(f"响应超过 {settings.get('responseLimitMiB', 2)} MiB 上限")
    raw = getattr(response, "html_content", None)
    if not isinstance(raw, str):
        raw = body.decode("utf-8", "replace")
    final = getattr(response, "url", None) if isinstance(getattr(response, "url", None), str) else url
    return status, raw, final


def extract_title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    return normalize_text(match.group(1)) if match else ""


def extract_text(html: str) -> str:
    scope = html or ""
    text = (
        scope.replace("<script", "\n<script")
        .replace("</script>", "</script>\n")
        .replace("<style", "\n<style")
        .replace("</style>", "</style>\n")
    )
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&quot;", '"').replace("&#0*39;", "'")
    )
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = normalize_text(raw_line)
        if not line:
            continue
        if len(line) <= 12 and BOILERPLATE_LINE.match(line):
            continue
        if len(line) <= 40 and NAV_NOISE_LINE.match(line):
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return "\n".join(lines)


def rawLine(line: str) -> str:
    return re.sub(r"[ \t]+", " ", line)


def extract_links(html: str, pattern: str, base_url: str, source_host: str) -> tuple[list[str], int]:
    """按正则提取详情链接：绝对化、去重、仅 HTTPS、仅同域。返回 (links, cross_domain_count)。"""
    try:
        regex = re.compile(pattern)
    except re.error:
        return [], 0
    seen: set[str] = set()
    links: list[str] = []
    cross_domain = 0
    for match in regex.finditer(html or ""):
        href = match.group(1) if match.groups() else match.group(0)
        href = str(href or "").strip()
        if not href or href == "#" or href.lower().startswith("javascript:"):
            continue
        try:
            absolute = urljoin(base_url, href)
            parts = urlsplit(absolute)
        except ValueError:
            continue
        if parts.scheme != "https":
            continue
        if parts.netloc.lower() != source_host:
            cross_domain += 1
            continue
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links, cross_domain


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


def build_item(source: dict, url: str, final_url: str, title: str, text: str, http_status: int) -> dict:
    digest = content_hash(title + "\n" + text)
    return {
        "itemId": f"ITM-{digest[:12]}",
        "sourceId": source.get("sourceId", ""),
        "url": url,
        "finalUrl": final_url or url,
        "title": title,
        "text": text,
        "fetchedAt": now_iso(),
        "httpStatus": http_status,
        "contentHash": digest,
        "language": source.get("language", "zh"),
    }


def _delay(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _source_list_url(source: dict) -> str:
    template = str(source.get("listUrlTemplate") or source.get("url") or "")
    return template.replace("{num}", str(source.get("startPage", 1)))


def _json_content_ok(body: str) -> bool:
    import json as _json

    try:
        data = _json.loads(body)
    except ValueError:
        return False
    if isinstance(data, list):
        return bool(data)
    if isinstance(data, dict):
        return any(isinstance(v, list) and v for v in data.values())
    return False


def verify_source(source: dict, settings: dict, fetch_fn=None) -> dict:
    """自动核验：HTTPS 门禁 → 可达 → 结构（能提取条目）→ 内容（≥50 字）。"""
    fetch_fn = fetch_fn or _scrapling_fetch
    started = time.perf_counter()
    result = {
        "sourceId": source.get("sourceId", ""),
        "name": source.get("name", ""),
        "passed": False,
        "https": False,
        "reachable": False,
        "structure": False,
        "content": False,
        "reason": "",
        "elapsedMs": 0,
    }
    entry = str(source.get("url") or source.get("listUrlTemplate") or "")
    if not is_safe_url(entry):
        result["reason"] = "URL 不是 HTTPS（443）或包含凭据"
        result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        return result
    result["https"] = True
    try:
        status, body, final_url = fetch_fn(_source_list_url(source), settings)
    except FetchError as error:
        result["reason"] = f"请求失败：{error}"
        result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        return result
    result["reachable"] = 0 < status < 400
    if not result["reachable"]:
        result["reason"] = f"HTTP {status}"
        result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        return result
    if str(source.get("method", "html")) == "json":
        result["structure"] = _json_content_ok(body)
        result["content"] = len(normalize_text(body)) >= 50
        result["reason"] = "" if result["structure"] else "JSON 响应中未定位到条目数组"
    else:
        source_host = urlsplit(entry).netloc.lower()
        links, _cross = extract_links(
            body, str(source.get("itemPattern", "")),
            str(source.get("itemUrlBase") or entry), source_host,
        )
        result["structure"] = len(links) >= 1
        if result["structure"]:
            _delay(max(0, settings.get("crawlDelayMs", 500)) / 1000)
            try:
                detail_status, detail_html, _ = fetch_fn(links[0], settings)
                text = extract_text(detail_html)
                result["content"] = detail_status < 400 and len(text) >= 50
                if not result["content"]:
                    result["reason"] = "详情页正文不足 50 字"
            except FetchError as error:
                result["reason"] = f"详情页请求失败：{error}"
        else:
            result["reason"] = "列表页未按 itemPattern 提取到条目链接"
    result["passed"] = result["reachable"] and result["structure"] and result["content"]
    if result["passed"]:
        result["reason"] = ""
    result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
    return result


def crawl_source(source: dict, settings: dict, on_event, out_dir: Path,
                 seen_hashes: set[str] | None = None, fetch_fn=None) -> dict:
    """抓取单个来源：列表页翻页 → 详情逐条 → 逐条写 items.jsonl。返回统计（含 items 列表）。"""
    fetch_fn = fetch_fn or _scrapling_fetch
    seen_hashes = seen_hashes if seen_hashes is not None else set()
    started = time.perf_counter()
    delay = max(0, settings.get("crawlDelayMs", 500)) / 1000
    stats = {
        "sourceId": source.get("sourceId", ""),
        "pages": 0, "fetched": 0, "kept": 0, "duplicates": 0,
        "crossDomain": 0, "failed": 0, "elapsedMs": 0, "status": "completed",
        "items": [],
    }
    template = str(source.get("listUrlTemplate") or "")
    if not template or not is_safe_url(template.replace("{num}", "1")):
        stats["status"] = "failed"
        stats["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        raise CrawlError(f"{source.get('sourceId', '')} 的列表 URL 缺失或不是 HTTPS")
    source_host = urlsplit(str(source.get("itemUrlBase") or source.get("url") or template)).netloc.lower()
    max_items = int(source.get("maxItems", 20))
    out_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / "items.jsonl"
    start_page = int(source.get("startPage", 1))
    max_pages = int(source.get("maxPages", 1))
    base_url = str(source.get("itemUrlBase") or source.get("url") or template)

    with items_path.open("a", encoding="utf-8") as fh:
        for page in range(start_page, start_page + max_pages):
            if len(stats["items"]) >= max_items:
                break
            page_url = template.replace("{num}", str(page))
            _delay(delay)
            try:
                status, html, final_url = fetch_fn(page_url, settings)
            except FetchError as error:
                if page == start_page:
                    stats["status"] = "failed"
                    raise CrawlError(f"列表页请求失败：{error}") from error
                on_event({"stage": "crawl", "level": "warn", "sourceId": stats["sourceId"],
                          "message": f"第 {page} 页失败（{error}），视为已到底"})
                break
            if not (0 < status < 400):
                if page == start_page:
                    stats["status"] = "failed"
                    raise CrawlError(f"列表页 HTTP {status}")
                on_event({"stage": "crawl", "level": "warn", "sourceId": stats["sourceId"],
                          "message": f"第 {page} 页 HTTP {status}，视为已到底"})
                break
            stats["pages"] += 1
            links, cross = extract_links(html, str(source.get("itemPattern", "")), base_url, source_host)
            stats["crossDomain"] += cross
            if not links:
                on_event({"stage": "crawl", "level": "info", "sourceId": stats["sourceId"],
                          "message": f"第 {page} 页无新链接，停止翻页"})
                break
            for link in links:
                if len(stats["items"]) >= max_items:
                    break
                _delay(delay)
                try:
                    detail_status, detail_html, detail_final = fetch_fn(link, settings)
                except FetchError as error:
                    stats["failed"] += 1
                    on_event({"stage": "crawl", "level": "warn", "sourceId": stats["sourceId"],
                              "message": f"详情失败 {link}：{error}"})
                    continue
                if not (0 < detail_status < 400):
                    stats["failed"] += 1
                    continue
                stats["fetched"] += 1
                title = extract_title(detail_html)
                text = extract_text(detail_html)
                if not title and not text:
                    continue
                item = build_item(source, link, detail_final, title, text, detail_status)
                if item["contentHash"] in seen_hashes:
                    stats["duplicates"] += 1
                    continue
                seen_hashes.add(item["contentHash"])
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                stats["items"].append(item)
                stats["kept"] += 1
        stats["elapsedMs"] = int((time.perf_counter() - started) * 1000)
    on_event({"stage": "crawl", "level": "info", "sourceId": stats["sourceId"],
              "message": f"完成：{stats['pages']} 页 / 保留 {stats['kept']} 条 / 重复 {stats['duplicates']}"})
    return stats
