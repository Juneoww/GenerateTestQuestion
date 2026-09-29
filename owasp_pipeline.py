"""功能：
  编排 OWASP LLM Top 10 2026 提示词的实际批次生成与文件交付。
实现：
  校验模型设置后调用 OWASP 模型生成器；事件和每次模型调用分别写入运行日志与调用日志。
  JSON、Excel、manifest 和日志先在隐藏暂存目录写好，再一次发布；失败时仅发布诊断文件。
输入：
  params{riskIds,total,language}、完整模型设置、事件回调及可注入的时钟和聊天函数。
输出：
  完成或失败的批次汇总；完成时含最终 JSON、Excel 路径和六字段记录。
依赖：
  Python 标准库、storage、question_generator 公共聊天接口、OWASP 生成器和导出器。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import question_generator
import storage
from owasp_export import export_prompt_xlsx
from owasp_prompt_generator import (
    OWASP_RISKS,
    _canonical_risk_ids,
    _normalize_language,
    generate_prompt_records,
)


DEFAULT_OUTPUT_DIR = storage.DATA_DIR / "output"


def _now_iso() -> str:
    """为 JSONL 审计事件提供与 TC260 同类的 UTC 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


class _EventTee:
    """同一事件同时写入本批次 run.log 并投递给界面回调。"""

    def __init__(self, on_event: Callable[[dict], None], log_path: Path):
        self.on_event = on_event
        self.log_path = log_path

    def __call__(self, event: dict) -> None:
        logged = {"ts": _now_iso(), **event, "kind": "owasp"}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(logged, ensure_ascii=False) + "\n")
        self.on_event(logged)


def _validate_request(params: dict, settings: dict, on_event: Callable[[dict], None]
                      ) -> tuple[dict, list[dict]]:
    """在创建任何批次目录前统一验证模型配置、风险配额和语言。"""
    if not isinstance(params, dict):
        raise ValueError("OWASP 批次参数必须是对象。")
    if not isinstance(settings, dict):
        raise ValueError("模型设置必须是对象。")
    if not callable(on_event):
        raise ValueError("运行事件回调不可用。")
    for key, label in (("baseUrl", "模型接口地址"), ("model", "模型名称")):
        if type(settings.get(key)) is not str or not settings[key].strip():
            raise ValueError(f"请先在设置页填写{label}。")
    for key in ("maxQuestionsPerItem", "retries"):
        try:
            int(settings[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"模型设置 {key} 必须是整数。") from error

    risk_ids = _canonical_risk_ids(params.get("riskIds"))
    total = params.get("total")
    if type(total) is not int or total < len(risk_ids):
        raise ValueError(f"生成数量必须是至少 {len(risk_ids)} 的整数。")
    language = params.get("language")
    _normalize_language(language)
    base, extra = divmod(total, len(risk_ids))
    catalog = {risk["riskId"]: risk for risk in OWASP_RISKS}
    by_risk = [
        {"riskId": risk_id, "riskName": catalog[risk_id]["riskName"],
         "target": base + (index < extra), "generated": 0, "calls": 0}
        for index, risk_id in enumerate(risk_ids)
    ]
    return {"riskIds": risk_ids, "total": total, "language": language}, by_risk


def resolve_output_dir(settings: dict | None) -> Path:
    """沿用 TC260 的输出目录规则：空值默认、绝对路径原样、相对路径相对项目根目录。"""
    custom = str((settings or {}).get("outputDir") or "").strip()
    if not custom:
        return DEFAULT_OUTPUT_DIR
    candidate = Path(custom)
    return candidate if candidate.is_absolute() else storage.PROJECT_ROOT / candidate


def _create_batch_paths(output_root: Path, now: datetime) -> tuple[str, Path, Path]:
    """预留隐藏暂存目录；同秒冲突时追加序号，绝不覆盖已发布的批次。"""
    output_root.mkdir(parents=True, exist_ok=True)
    base_id = f"OWASP-{now:%Y%m%d-%H%M%S}"
    suffix = 0
    while True:
        batch_id = base_id if suffix == 0 else f"{base_id}-{suffix:02d}"
        batch_dir = output_root / batch_id
        staging_dir = output_root / f".{batch_id}.partial"
        if batch_dir.exists():
            suffix += 1
            continue
        try:
            staging_dir.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        # 暂存目录创建期间可能有其他进程刚发布同名批次；放弃当前空暂存目录并换序号。
        if batch_dir.exists():
            try:
                staging_dir.rmdir()
            except OSError:
                pass
            suffix += 1
            continue
        return batch_id, batch_dir, staging_dir


def _write_json_file(path: Path, records: list[dict[str, str]]) -> None:
    """写入最终 JSON 数组的临时文件，保持六字段记录的原有键顺序。"""
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _publish_batch_dir(staging_dir: Path, batch_dir: Path) -> None:
    """一次重命名完整暂存批次，避免 JSON 与 Excel 分别发布造成半成品可见。"""
    if batch_dir.exists():
        raise FileExistsError(f"目标批次目录已存在，拒绝覆盖：{batch_dir}")
    staging_dir.rename(batch_dir)


def _write_manifest(batch_dir: Path, payload: dict) -> None:
    """写入独立的批次诊断信息，避免污染最终六字段 JSON。"""
    (batch_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _build_manifest(batch_id: str, created_at: datetime, params: dict, model: str,
                    by_risk: list[dict], status: str, error: str, record_count: int) -> dict:
    """把模型、配额和调用统计留在 manifest，而不污染最终六字段数组。"""
    completed = status == "completed"
    return {
        "formatVersion": "3.0.0",
        "artifactKind": "owaspPromptSet",
        "batchId": batch_id,
        "createdAt": created_at.isoformat(),
        "status": status,
        "error": error,
        "params": params,
        "model": model,
        "recordCount": record_count,
        "generate": {
            "calls": sum(item["calls"] for item in by_risk),
            "byRisk": by_risk,
        },
        "output": {
            "json": "owasp_prompts.json" if completed else "",
            "xlsx": "owasp_prompts.xlsx" if completed else "",
            "runLog": "run.log",
            "llmCalls": "llm_calls.jsonl",
        },
    }


def _cleanup_hidden_staging(staging_dir: Path) -> None:
    """仅清理本次暂存中的已知文件；被 Windows 锁住时保留隐藏目录。"""
    for name in ("owasp_prompts.json", "owasp_prompts.xlsx", "manifest.json",
                 "run.log", "llm_calls.jsonl"):
        try:
            (staging_dir / name).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        staging_dir.rmdir()
    except OSError:
        pass


def _publish_failure_batch(staging_dir: Path, batch_dir: Path, manifest: dict) -> None:
    """从干净的诊断暂存目录发布三文件批次，不依赖半成品可被删除。"""
    if not staging_dir.exists() and batch_dir.is_dir():
        # 成功发布后的晚到异常：先将含交付文件的目录重新隐藏，再发布纯诊断目录。
        batch_dir.rename(staging_dir)
    diagnostic_dir = staging_dir.with_name(staging_dir.name + ".diagnostic")
    suffix = 1
    while True:
        try:
            diagnostic_dir.mkdir()
            break
        except FileExistsError:
            diagnostic_dir = staging_dir.with_name(f"{staging_dir.name}.diagnostic-{suffix:02d}")
            suffix += 1
    for name in ("run.log", "llm_calls.jsonl"):
        source = staging_dir / name
        destination = diagnostic_dir / name
        if source.exists():
            shutil.copyfile(source, destination)
        else:
            destination.touch()
    _write_manifest(diagnostic_dir, manifest)
    if batch_dir.exists():
        raise FileExistsError(f"目标批次目录已存在，拒绝覆盖：{batch_dir}")
    diagnostic_dir.rename(batch_dir)
    _cleanup_hidden_staging(staging_dir)


def _failure_summary(batch_id: str, batch_dir: Path, staging_dir: Path,
                     created_at: datetime, params: dict, model: str,
                     by_risk: list[dict], events: _EventTee, error: Exception) -> dict:
    """保留调用日志和失败 manifest，返回空交付路径以清空界面旧产物动作。"""
    message = str(error) or error.__class__.__name__
    if not staging_dir.exists() and batch_dir.is_dir():
        events.log_path = batch_dir / "run.log"
    try:
        events({"stage": "export", "level": "error", "message": f"OWASP 批次失败：{message}"})
    except Exception as log_error:  # noqa: BLE001 - 尽最大努力保留已有审计文件
        message = f"{message}；写入失败事件失败：{log_error}"
    manifest = _build_manifest(batch_id, created_at, params, model, by_risk, "failed", message, 0)
    exposed_batch_dir = ""
    try:
        _publish_failure_batch(staging_dir, batch_dir, manifest)
        exposed_batch_dir = str(batch_dir)
    except OSError as diagnostic_error:
        # 文件系统本身拒绝发布时，保留隐藏暂存目录中的日志供人工恢复。
        message = f"{message}；发布失败诊断文件失败：{diagnostic_error}"
    return {
        "batchId": batch_id,
        "batchDir": exposed_batch_dir,
        "status": "failed",
        "error": message,
        "recordCount": 0,
        "jsonPath": "",
        "xlsxPath": "",
        "records": [],
    }


def run_batch(
    params: dict,
    settings: dict,
    on_event: Callable[[dict], None],
    now_fn: Callable[[], datetime] | None = None,
    chat_fn: Callable[[dict, list[dict]], str] = question_generator.chat_completion,
) -> dict:
    """复用模型设置生成 OWASP 提示词，并成对发布 JSON 与 Excel。"""
    normalized_params, by_risk = _validate_request(params, settings, on_event)
    created_at = (now_fn or datetime.now)()
    if not isinstance(created_at, datetime):
        raise ValueError("批次时钟必须返回 datetime。")
    batch_id, batch_dir, staging_dir = _create_batch_paths(resolve_output_dir(settings), created_at)
    final_json = batch_dir / "owasp_prompts.json"
    final_xlsx = batch_dir / "owasp_prompts.xlsx"
    staged_json = staging_dir / final_json.name
    staged_xlsx = staging_dir / final_xlsx.name
    run_log = staging_dir / "run.log"
    calls_log = staging_dir / "llm_calls.jsonl"
    events = _EventTee(on_event, run_log)
    stats_by_id = {item["riskId"]: item for item in by_risk}

    def record_call(record: dict) -> None:
        with calls_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        stats = stats_by_id[record["riskId"]]
        stats["calls"] += 1
        stats["generated"] += record["got"]

    try:
        run_log.touch()
        calls_log.touch()
        events({"stage": "generate", "level": "info",
                "message": f"OWASP 批次 {batch_id} 开始：{len(by_risk)} 项风险，共 {normalized_params['total']} 条。"})
        records = generate_prompt_records(
            normalized_params["riskIds"], normalized_params["total"],
            normalized_params["language"], settings, chat_fn=chat_fn,
            record_call=record_call, on_event=events,
        )
        _write_json_file(staged_json, records)
        export_prompt_xlsx(records, staged_xlsx)
        events({"stage": "export", "level": "info",
                "message": f"OWASP 批次 {batch_id} 已生成 {len(records)} 条，正在发布 JSON 与 Excel。"})
        manifest = _build_manifest(batch_id, created_at, normalized_params, settings["model"],
                                   by_risk, "completed", "", len(records))
        _write_manifest(staging_dir, manifest)
        _publish_batch_dir(staging_dir, batch_dir)
    except Exception as error:  # noqa: BLE001 - 任意生成、导出或发布错误都应收束为失败诊断批次
        return _failure_summary(batch_id, batch_dir, staging_dir, created_at,
                                normalized_params, settings["model"], by_risk, events, error)
    return {
        "batchId": batch_id,
        "batchDir": str(batch_dir),
        "status": "completed",
        "error": "",
        "recordCount": len(records),
        "jsonPath": str(final_json),
        "xlsxPath": str(final_xlsx),
        "records": records,
    }
