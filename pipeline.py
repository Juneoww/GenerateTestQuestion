"""功能:
  批次编排：建批次目录 → 逐站爬取 → 按小类×语言配额出题 → 导出 Excel/JSON → 留痕落盘。
实现:
  配额拆分与小类轮转分配为纯函数；事件经 EventTee 同时投递 UI 队列与 run.log；
  连续 5 次出题空手而归触发熔断（aborted），已产出题目照常导出；全局哈希索引
  data/output/.hash_index.json 支撑跨批次去重。
输入: params{sourceIds, riskIds, total, zhPercent}、settings、on_event 回调。
输出: 汇总 dict（questions、批次目录路径、统计、shortage、status）。
依赖: Python 3.10+ 标准库、openpyxl（经 excel_export）。
用法:
  summary = pipeline.run_batch(params, settings, on_event)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import crawler
import excel_export
import question_generator as generator
import reporting
import storage

DATA_DIR = storage.DATA_DIR
OUTPUT_DIR = DATA_DIR / "output"
ABORT_FAILURE_STREAK = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_language_quota(total: int, zh_percent: int) -> tuple[int, int]:
    """四舍五入取半递增（int(x+0.5)），避免 Python 银行家舍入把 0.5 舍向偶数。"""
    pct = max(0, min(100, zh_percent))
    zh = int(total * pct / 100 + 0.5)
    return zh, total - zh


def allocate(total: int, risk_ids: list[str]) -> list[int]:
    """把 total 在小类间轮转分配（余数给前几项），保证 sum == total。"""
    if not risk_ids:
        return []
    base, remainder = divmod(max(0, total), len(risk_ids))
    return [base + (1 if index < remainder else 0) for index in range(len(risk_ids))]


class _EventTee:
    """把事件同时投递 UI 回调与 run.log（JSON 行）。"""

    def __init__(self, on_event, run_log_path: Path):
        self.on_event = on_event
        self.log_path = run_log_path

    def __call__(self, event: dict) -> None:
        event = {"ts": now_iso(), **event}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self.on_event(event)


def resolve_output_dir(settings: dict) -> Path:
    """产物根目录：settings['outputDir'] 非空则用之（相对路径按程序根目录解析），否则 data/output。"""
    custom = str((settings or {}).get("outputDir") or "").strip()
    if not custom:
        return OUTPUT_DIR
    path = Path(custom)
    return path if path.is_absolute() else (storage.PROJECT_ROOT / path)


def _hash_index_path(output_root: Path) -> Path:
    return output_root / ".hash_index.json"


def _load_hash_index(index_path: Path) -> dict:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return payload.get("index", {}) if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_hash_index(index_path: Path, index: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps({"formatVersion": 1, "index": index}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_batch(params: dict, settings: dict, on_event, fetch_fn=None, generate_fn=None) -> dict:
    started = time.perf_counter()
    batch_id = f"BATCH-{datetime.now():%Y%m%d-%H%M%S}"
    output_root = resolve_output_dir(settings)
    hash_path = _hash_index_path(output_root)
    batch_dir = output_root / batch_id
    crawl_dir = batch_dir / "crawl"
    run_log = batch_dir / "run.log"
    events = _EventTee(on_event, run_log)

    risk_ids = list(params.get("riskIds", []))
    total = int(params.get("total", 0))
    zh_percent = int(params.get("zhPercent", 50))
    sources = {s["sourceId"]: s for s in storage.load_sources() if s.get("status") == "ready"}
    selected = [sources[sid] for sid in params.get("sourceIds", []) if sid in sources]
    if not selected:
        raise RuntimeError("没有可用来源：请先在来源管理页核验通过（可爬）至少一个站点。")
    if not risk_ids:
        raise RuntimeError("未选择任何风险小类。")
    catalog_risks = {r["riskId"]: r for r in storage.catalog_risks(storage.load_catalog())}
    for rid in risk_ids:
        if rid not in catalog_risks:
            raise RuntimeError(f"风险小类 {rid} 不在风险目录中。")

    batch_dir.mkdir(parents=True, exist_ok=True)
    events({"stage": "crawl", "level": "info", "message": f"批次 {batch_id} 开始：{len(selected)} 站，{len(risk_ids)} 小类，共 {total} 题"})

    hash_index = _load_hash_index(hash_path)
    seen_hashes = set(hash_index.keys())
    crawl_stats: list[dict] = []
    pools: dict[str, list[dict]] = {"zh": [], "en": []}
    for source in selected:
        try:
            stats = crawler.crawl_source(
                source, settings, events, crawl_dir / source["sourceId"], seen_hashes, fetch_fn
            )
        except crawler.CrawlError as error:
            stats = {"sourceId": source["sourceId"], "pages": 0, "fetched": 0, "kept": 0,
                     "duplicates": 0, "crossDomain": 0, "failed": 0, "elapsedMs": 0,
                     "status": "failed", "items": [], "reason": str(error)}
            events({"stage": "crawl", "level": "error", "sourceId": source["sourceId"],
                    "message": str(error)})
        crawl_stats.append({k: v for k, v in stats.items() if k != "items"})
        pools[str(source.get("language", "zh"))].extend(stats["items"])

    zh_total, en_total = split_language_quota(total, zh_percent)
    quota_plan = [
        (lang, rid, target)
        for lang, lang_total in (("zh", zh_total), ("en", en_total))
        for rid, target in zip(risk_ids, allocate(lang_total, risk_ids))
    ]
    source_names = {s["sourceId"]: s.get("name", "") for s in selected}
    calls_path = batch_dir / "llm_calls.jsonl"

    def record_call(record: dict) -> None:
        with calls_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def generate(item, risk, language, count):
        actual = generate_fn or generator.generate_questions
        return actual(item, risk, language, count, settings, seen_questions, record_call, events)

    seen_questions: set[str] = set()
    questions: list[dict] = []
    shortage: list[dict] = []
    generated_counts: dict[tuple[str, str], int] = {}
    failure_streak = 0
    aborted = False

    for lang, rid, target in quota_plan:
        if target <= 0:
            continue
        risk = catalog_risks[rid]
        pool = pools.get(lang) or pools.get("zh" if lang == "en" else "en") or []
        remaining = target
        pointer = 0
        visited: set[str] = set()
        generated_counts[(lang, rid)] = 0
        while remaining > 0 and len(visited) < len(pool):
            item = pool[pointer % len(pool)]
            pointer += 1
            if item["itemId"] in visited:
                continue
            visited.add(item["itemId"])
            ask = min(remaining, max(1, settings.get("maxQuestionsPerItem", 5)))
            got = generate(item, risk, lang, ask)
            for piece in got:
                questions.append({
                    **piece,
                    "language": lang,
                    "sceneCode": risk["sceneCode"],
                    "scene": risk["scene"],
                    "riskId": rid,
                    "category": risk["category"],
                    "sourceId": item["sourceId"],
                    "sourceName": source_names.get(item["sourceId"], item["sourceId"]),
                    "sourceUrl": item.get("finalUrl") or item.get("url", ""),
                    "evidenceText": item.get("text", ""),
                    "model": settings.get("model", ""),
                    "generatedAt": now_iso(),
                })
            remaining -= len(got)
            generated_counts[(lang, rid)] += len(got)
            failure_streak = 0 if got else failure_streak + 1
            if failure_streak >= ABORT_FAILURE_STREAK:
                aborted = True
                events({"stage": "generate", "level": "error",
                        "message": f"连续 {ABORT_FAILURE_STREAK} 次出题无产出，熔断终止批次"})
                break
        if remaining > 0:
            shortage.append({"riskId": rid, "language": lang, "target": target,
                             "generated": generated_counts[(lang, rid)]})
        if aborted:
            break

    questions_path = batch_dir / "questions.json"
    for seq, q in enumerate(questions, 1):
        q["seq"] = seq
    questions_path.write_text(json.dumps({
        "formatVersion": 1,
        "batchId": batch_id,
        "createdAt": now_iso(),
        "params": {"sourceIds": params.get("sourceIds", []), "riskIds": risk_ids,
                   "total": total, "zhPercent": zh_percent, "model": settings.get("model", "")},
        "questions": questions,
        "shortage": shortage,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    xlsx_path = batch_dir / "questions.xlsx"
    try:
        excel_export.export_xlsx(questions, {"batchId": batch_id}, xlsx_path)
        export_error = ""
    except Exception as error:  # 导出失败不吞掉题目，JSON 仍可用
        export_error = str(error)
        events({"stage": "export", "level": "error", "message": f"Excel 导出失败：{export_error}"})

    call_count = 0
    if calls_path.exists():
        with calls_path.open(encoding="utf-8") as fh:
            call_count = sum(1 for _ in fh)

    manifest = {
        "formatVersion": 1,
        "batchId": batch_id,
        "createdAt": now_iso(),
        "status": "aborted" if aborted else "completed",
        "params": {"sourceIds": params.get("sourceIds", []), "riskIds": risk_ids,
                   "total": total, "zhPercent": zh_percent, "model": settings.get("model", "")},
        "crawl": {"bySource": crawl_stats},
        "generate": {
            "calls": call_count,
            "byRisk": [{"riskId": rid, "language": lang, "target": target,
                        "generated": generated_counts.get((lang, rid), 0)}
                       for lang, rid, target in quota_plan if target > 0],
        },
        "output": {"questionsJson": str(questions_path), "questionsXlsx": "" if export_error else str(xlsx_path),
                   "runLog": str(run_log)},
        "shortage": shortage,
        "elapsedMs": int((time.perf_counter() - started) * 1000),
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    reporting.write_crawl_report(batch_dir, crawl_stats)

    new_hashes = {h: {"batchId": batch_id} for h in seen_hashes if h not in hash_index}
    hash_index.update(new_hashes)
    _save_hash_index(hash_path, hash_index)

    zh_count = sum(1 for q in questions if q["language"] == "zh")
    summary = {
        "batchId": batch_id,
        "batchDir": str(batch_dir),
        "status": "aborted" if aborted else "completed",
        "questionCount": len(questions),
        "zhCount": zh_count,
        "enCount": len(questions) - zh_count,
        "crawl": crawl_stats,
        "shortage": shortage,
        "questionsPath": str(questions_path),
        "xlsxPath": "" if export_error else str(xlsx_path),
        "questions": questions,
    }
    events({"stage": "export", "level": "info",
            "message": f"批次完成：{len(questions)} 题（中 {zh_count} / 英 {len(questions) - zh_count}）→ {batch_dir}"})
    return summary
