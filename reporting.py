"""功能:
  生成与追加过程留痕文档：网站名单（全量重生成）、核验日志（追加式）、爬取报告（按批次）。
实现:
  纯标准库 Markdown 渲染；输出路径可由调用方指定（便于测试隔离），目录自动创建。
输入: 来源列表、核验结果列表、爬取统计列表。
输出: data/reports/网站名单.md、data/reports/核验日志.md、<批次>/crawl_report.md。
依赖: Python 3.10+ 标准库。
用法:
  reporting.write_site_list(sources); reporting.append_verify_log(results)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from storage import DATA_DIR, STATUS_LABELS


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_site_list(sources: list[dict], out_path: Path | None = None) -> Path:
    path = out_path or (DATA_DIR / "reports" / "网站名单.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    ready = sum(1 for s in sources if s.get("status") == "ready")
    lines = [
        "# 可爬取网站名单",
        "",
        f"- 更新时间：{_now_local()}",
        f"- 站点数：{len(sources)}（可爬 {ready}）",
        "",
        "| 来源ID | 名称 | 语言 | 方式 | 引擎 | 状态 | 最近核验 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in sources:
        status = STATUS_LABELS.get(s.get("status", ""), str(s.get("status", "")))
        lines.append(
            f"| {s.get('sourceId', '')} | {s.get('name', '')} | {s.get('language', '')} "
            f"| {s.get('method', '')} | {s.get('engine', '')} | {status} "
            f"| {s.get('lastCheckedAt') or '—'} | {s.get('note') or '—'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append_verify_log(results: list[dict], log_path: Path | None = None) -> Path:
    path = log_path or (DATA_DIR / "reports" / "核验日志.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if r.get("passed"))

    def flag(name: str) -> str:
        return "✓" if r.get(name) else "✗"

    lines = [
        "",
        f"## {_now_local()} 核验 {len(results)} 站（通过 {passed}）",
        "",
        "| 来源ID | HTTPS | 可达 | 结构 | 内容 | 结论 | 原因 | 耗时ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.get('sourceId', '')} | {flag('https')} | {flag('reachable')} | {flag('structure')} "
            f"| {flag('content')} | {'通过' if r.get('passed') else '失败'} "
            f"| {r.get('reason') or '—'} | {r.get('elapsedMs', 0)} |"
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def write_crawl_report(batch_dir: Path, crawl_stats: list[dict]) -> Path:
    path = batch_dir / "crawl_report.md"
    lines = [
        "# 爬取报告",
        "",
        f"- 批次：{batch_dir.name}",
        f"- 生成时间：{_now_local()}",
        "",
        "| 来源ID | 列表页数 | 详情成功 | 保留 | 重复 | 跨域丢弃 | 失败 | 耗时ms | 结论 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in crawl_stats:
        lines.append(
            f"| {s.get('sourceId', '')} | {s.get('pages', 0)} | {s.get('fetched', 0)} "
            f"| {s.get('kept', 0)} | {s.get('duplicates', 0)} | {s.get('crossDomain', 0)} "
            f"| {s.get('failed', 0)} | {s.get('elapsedMs', 0)} | {s.get('status', '')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
