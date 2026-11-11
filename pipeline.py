"""功能:
  批次编排：建批次目录 → 逐站爬取 → 按小类×语言配额出题 → 导出 Excel/JSON → 留痕落盘。
实现:
  配额拆分与小类轮转分配为纯函数；事件经 EventTee 同时投递 UI 队列与 run.log；
  连续 5 次出题空手而归触发熔断（aborted），已产出题目照常导出；全局哈希索引
  data/output/.hash_index.json 支撑跨批次去重。无素材或零题产出记为 failed，并保留失败留痕。
输入: params{sourceIds, riskIds, total, zhPercent, questionType}、settings、on_event 回调。
      questionType："text"（默认）=面向 AI 服务的测试问题；"image"=文生图提示词（批次名带 -IMG）。
输出: 汇总 dict（questions、批次目录路径、统计、shortage、status）。
依赖: Python 3.10+ 标准库、openpyxl（经 excel_export）。
用法:
  summary = pipeline.run_batch(params, settings, on_event)
"""
from __future__ import annotations

import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import crawler
import excel_export
import question_generator as generator
import reporting
import storage
from generation_control import GenerationCancelled, checkpoint, seal, track_batch
from text_image_renderer import load_text_image_config

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


def _generate_images(questions, settings, batch_dir, batch_id, events, image_fn):
    """逐题生图，阶段快照与实际文件按批次内序号对应。"""
    progress_path = batch_dir / "image_progress.json"
    for question in questions:
        question.update(imageStatus="pending", imagePath="", imageModel=settings.get("imageModel", ""), imageError="")

    def save_progress(complete=False):
        temp_path = progress_path.with_suffix(".json.tmp")
        try:
            keys = ("seq", "question", "riskId", "language", "imageStatus", "imagePath", "imageModel", "imageError")
            records = [{key: q.get(key, "") for key in keys} for q in questions]
            temp_path.write_text(json.dumps({"batchId": batch_id, "complete": complete,
                                           "questions": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(progress_path)
        finally:
            temp_path.unlink(missing_ok=True)

    save_progress()
    stop = False
    for question in questions:
        checkpoint()
        seq = question["seq"]
        question["imageStatus"] = "in_progress"
        save_progress()
        if stop:
            result = {"imageStatus": "failed", "imageError": "图像接口配置错误，未调用此题。"}
        else:
            try:
                result = image_fn(question["question"], settings, batch_dir, seq)
            except GenerationCancelled:
                raise
            except Exception:
                # 避免将意外异常中的认证信息或远程链接写入产物。
                result = {"imageStatus": "failed", "imageError": "图像生成发生异常，请检查接口配置。"}
        status = result.get("imageStatus")
        relative = result.get("imagePath") or ""
        if status == "success":
            target = (batch_dir / relative).resolve()
            try:
                valid = bool(relative) and target.is_relative_to((batch_dir / "images").resolve()) and target.is_file()
            except (OSError, ValueError):
                valid = False
            if not valid:
                status = "failed"
                result = {"imageError": "图片文件未能保存。"}
        if status not in ("success", "rejected", "failed"):
            status, result = "failed", {"imageError": "图像接口返回无效状态。"}
        question.update(imageStatus=status, imagePath=relative if status == "success" else "",
                        imageModel=settings.get("imageModel", ""), imageError=result.get("imageError", "") if status != "success" else "")
        stop = stop or bool(result.get("globalError"))
        save_progress()
        counts = {s: sum(q["imageStatus"] == s for q in questions) for s in ("success", "rejected", "failed")}
        events({"stage": "image", "level": "info" if status == "success" else "warn", "seq": seq,
                "model": settings.get("imageModel", ""), "status": status,
                "attempts": result.get("attempts", 0), "elapsedMs": result.get("elapsedMs", 0),
                "message": f"图片 {seq}/{len(questions)}：成功 {counts['success']}，拒绝 {counts['rejected']}，失败 {counts['failed']}"})
    save_progress(True)
    counts = {s: sum(q["imageStatus"] == s for q in questions) for s in ("success", "rejected", "failed")}
    total = len(questions)
    status = "not_started" if not total else ("completed" if counts["success"] == total else ("partial" if counts["success"] else "failed"))
    return {"status": status, "promptCount": total, "imageSuccessCount": counts["success"],
            "imageRejectedCount": counts["rejected"], "imageFailedCount": counts["failed"]}


def _render_text_images(questions, batch_dir, size, background_path, events, render):
    """逐题渲染本地图片，保留题干、状态和可追溯的输入哈希。"""
    progress = batch_dir / "image_progress.json"
    for question in questions:
        question.update(textImageStatus="pending", textImagePath="", textImageError="")

    def save_progress(complete=False):
        temp = progress.with_suffix(".json.tmp")
        keys = ("seq", "question", "riskId", "language", "textImageStatus", "textImagePath", "textImageError")
        try:
            temp.write_text(json.dumps({"complete": complete, "questions": [{k: q.get(k, "") for k in keys} for q in questions]}, ensure_ascii=False), encoding="utf-8")
            temp.replace(progress)
        finally:
            temp.unlink(missing_ok=True)

    save_progress()
    success = 0
    for question in questions:
        checkpoint()
        seq = question["seq"]
        # 批次目录原子去重，文件名同时携带批次标识，便于跨批次汇总图片。
        rel = f"images/{batch_dir.name}-{seq:04d}.png"
        try:
            info = render(question["question"], batch_dir / rel, size, background_path)
            if not (batch_dir / rel).is_file():
                raise ValueError("图片文件未保存")
            question.update(textImageStatus="success", textImagePath=rel, textImageError="",
                            textImageTextSha256=hashlib.sha256(question["question"].encode("utf-8")).hexdigest(),
                            textImageFontSize=info.get("fontSize"), textImageFontName=info.get("fontName", ""))
            success += 1
        except (OSError, ValueError) as error:
            question.update(textImageStatus="failed", textImagePath="", textImageError=str(error),
                            textImageTextSha256=hashlib.sha256(question["question"].encode("utf-8")).hexdigest(),
                            textImageFontSize=None)
        events({"stage": "text_image", "seq": seq, "level": "info", "message": f"文字图片 {seq}/{len(questions)}"})
        save_progress()
    save_progress(True)
    return {"promptCount": len(questions), "successCount": success, "failedCount": len(questions)-success,
            "status": "not_started" if not questions else ("completed" if success == len(questions) else ("partial" if success else "failed"))}


def run_batch(params: dict, settings: dict, on_event, fetch_fn=None, generate_fn=None, image_fn=None, text_render_fn=None) -> dict:
    checkpoint()
    started = time.perf_counter()
    question_type = generator.normalize_question_type(params.get("questionType", "text"))
    text_image_enabled = question_type == "text" and bool(params.get("textImageEnabled", False))
    text_size, background_data = load_text_image_config(settings) if text_image_enabled else (None, None)
    if question_type == "image" and not all(str(settings.get(k) or "").strip() for k in ("imageBaseUrl", "imageModel")):
        raise ValueError("图片生成题需要配置文生图接口地址和模型名。")
    batch_base = f"BATCH-{datetime.now():%Y%m%d-%H%M%S}"
    batch_suffix = "-IMG" if question_type == "image" else ""
    batch_id = batch_base + batch_suffix
    output_root = resolve_output_dir(settings)
    hash_path = _hash_index_path(output_root)
    batch_dir = output_root / batch_id

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

    output_root.mkdir(parents=True, exist_ok=True)
    counter = 1
    while True:
        try:
            batch_dir.mkdir(exist_ok=False)
            track_batch(batch_dir)
            break
        except FileExistsError:
            counter += 1
            batch_id = f"{batch_base}-{counter}{batch_suffix}"
            batch_dir = output_root / batch_id
    background_path = None
    if background_data is not None:
        background_path = batch_dir / "background.png"
        background_path.write_bytes(background_data)
    crawl_dir = batch_dir / "crawl"
    run_log = batch_dir / "run.log"
    events = _EventTee(on_event, run_log)
    events({"stage": "crawl", "level": "info", "message": f"批次 {batch_id} 开始：{len(selected)} 站，{len(risk_ids)} 小类，共 {total} 题"})

    hash_index = _load_hash_index(hash_path)
    seen_hashes = set(hash_index.keys())
    crawl_stats: list[dict] = []
    pools: dict[str, list[dict]] = {"zh": [], "en": []}
    for source in selected:
        checkpoint()
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
        return actual(item, risk, language, count, settings, seen_questions, record_call, events,
                      question_type=question_type)

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
            checkpoint()
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
                    "questionType": question_type,
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
    checkpoint()
    for seq, q in enumerate(questions, 1):
        q["seq"] = seq
    text_image_summary = None
    if text_image_enabled:
        if text_render_fn is None:
            from text_image_renderer import render_text_image
            text_render_fn = render_text_image
        text_image_summary = _render_text_images(questions, batch_dir, text_size, background_path, events, text_render_fn)
    image_summary = None
    if question_type == "image":
        if image_fn is None:
            from image_generator import generate_image
            image_fn = generate_image
        image_summary = _generate_images(questions, settings, batch_dir, batch_id, events, image_fn)
    checkpoint()
    questions_path.write_text(json.dumps({
        "formatVersion": 1,
        "batchId": batch_id,
        "createdAt": now_iso(),
        "params": {"sourceIds": params.get("sourceIds", []), "riskIds": risk_ids,
                   "total": total, "zhPercent": zh_percent, "questionType": question_type,
                   "model": settings.get("model", ""), "textImageEnabled": text_image_enabled,
                   **({"textImageSize": list(text_size), "textImageBackground": "background.png" if background_data else "",
                       "textImageBackgroundSha256": hashlib.sha256(background_data).hexdigest() if background_data else ""} if text_image_enabled else {})},
        "questions": questions,
        "shortage": shortage,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    xlsx_path = batch_dir / "questions.xlsx"
    try:
        excel_export.export_xlsx(questions, {"batchId": batch_id, "questionType": question_type, "textImageEnabled": text_image_enabled}, xlsx_path)
        export_error = ""
    except Exception as error:  # 导出失败不吞掉题目，JSON 仍可用
        export_error = str(error)
        events({"stage": "export", "level": "error", "message": f"Excel 导出失败：{export_error}"})

    call_count = 0
    if calls_path.exists():
        with calls_path.open(encoding="utf-8") as fh:
            call_count = sum(1 for _ in fh)

    # 正常走到导出阶段不等于成功出题；失败和中止的原因在汇总、日志与 UI 中保持一致。
    batch_status = "aborted" if aborted else "completed"
    batch_error = ""
    if aborted:
        batch_error = f"连续 {ABORT_FAILURE_STREAK} 次出题无产出，已中止批次；已产出的题目仍保留。"
    elif total > 0 and not questions:
        batch_status = "failed"
        if any(pools.values()):
            batch_error = "模型未产出有效题目，请检查运行日志和模型调用记录中的错误或校验结果。"
        elif all(s["status"] == "failed" for s in crawl_stats):
            batch_error = ("所有选中来源抓取失败，未获取到可用素材，未调用模型。"
                           "请检查网络连接，在来源管理中重新核验，或更换来源后重试。")
        else:
            batch_error = ("未获取到可用的新素材（无有效条目或已被历史去重），未调用模型。"
                           "请检查抓取日志，增加或更换来源后重试。")

    manifest = {
        "formatVersion": 1,
        "batchId": batch_id,
        "createdAt": now_iso(),
        "status": batch_status,
        "error": batch_error,
        "exportError": export_error,
        "params": {"sourceIds": params.get("sourceIds", []), "riskIds": risk_ids,
                   "total": total, "zhPercent": zh_percent, "questionType": question_type,
                   "model": settings.get("model", "")},
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
    if image_summary is not None:
        manifest["imageSummary"] = image_summary
    if text_image_summary is not None:
        manifest["textImageSummary"] = text_image_summary
        manifest["params"].update(textImageEnabled=True, textImageSize=list(text_size),
                                  textImageBackground="background.png" if background_data else "",
                                  textImageBackgroundSha256=hashlib.sha256(background_data).hexdigest() if background_data else "")
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    reporting.write_crawl_report(batch_dir, crawl_stats)

    seal()
    new_hashes = {h: {"batchId": batch_id} for h in seen_hashes if h not in hash_index}
    hash_index.update(new_hashes)
    _save_hash_index(hash_path, hash_index)

    zh_count = sum(1 for q in questions if q["language"] == "zh")
    summary = {
        "batchId": batch_id,
        "batchDir": str(batch_dir),
        "status": batch_status,
        "error": batch_error,
        "exportError": export_error,
        "questionCount": len(questions),
        "zhCount": zh_count,
        "enCount": len(questions) - zh_count,
        "crawl": crawl_stats,
        "shortage": shortage,
        "questionsPath": str(questions_path),
        "xlsxPath": "" if export_error else str(xlsx_path),
        "questions": questions,
    }
    if image_summary is not None:
        summary["imageSummary"] = image_summary
    if text_image_summary is not None:
        summary["textImageSummary"] = text_image_summary
    outcome = {"completed": "批次完成", "failed": "批次失败", "aborted": "批次中止"}[batch_status]
    level = {"completed": "info", "failed": "error", "aborted": "warn"}[batch_status]
    reason = f"；{batch_error}" if batch_error else ""
    events({"stage": "export", "level": level,
            "message": (f"{outcome}：{len(questions)} 题（中 {zh_count} / 英 {len(questions) - zh_count}）"
                        f"{reason} → {batch_dir}")})
    return summary
