"""功能:
  提供 data/ 下三个 JSON（来源清单、模型设置、风险目录）的读写、默认值合并与查询辅助。
实现:
  纯标准库；来源条目读取时补全默认字段并修正整数边界；设置读取时合并默认值；
  风险目录提供场景列表、小类平铺查询。所有函数可传入 base_dir 便于测试隔离。
输入: data/sources.json、data/settings.json、data/risk_catalog.json。
输出: dict / list 及写回文件（UTF-8、缩进 2、ensure_ascii=False）。
依赖: Python 3.10+ 标准库。
用法:
  import storage; sources = storage.load_sources()
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _app_root() -> Path:
    """打包成 exe（PyInstaller 冻结）时以 exe 所在目录为根，data/ 与 exe 同级（便携式）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _app_root()
DATA_DIR = PROJECT_ROOT / "data"

if getattr(sys, "frozen", False) and not DATA_DIR.exists():
    # 首次运行：把随包内置的来源清单/风险目录释放到 exe 旁边。
    # 刻意不含 settings.json——API Key 必须由使用者自己填写。
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "data"
    if bundled.exists():
        shutil.copytree(bundled, DATA_DIR)

SOURCE_DEFAULTS = {
    "method": "html",
    "language": "zh",
    "engine": "fetcher",
    "startPage": 1,
    "maxPages": 1,
    "maxItems": 20,
    "status": "pending",
    "note": "",
    "lastCheckedAt": "",
}

STATUS_LABELS = {
    "pending": "待核验",
    "ready": "可爬",
    "failed": "核验失败",
    "disabled": "已停用",
}

SETTINGS_DEFAULTS = {
    "baseUrl": "",
    "apiKey": "",
    "model": "",
    "temperature": 0.7,
    "timeoutSeconds": 60,
    "retries": 2,
    "maxQuestionsPerItem": 5,
    "crawlDelayMs": 500,
    "requestTimeoutSeconds": 15,
    "responseLimitMiB": 2,
    "outputDir": "",
}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_sources(base_dir: Path | None = None) -> list[dict]:
    data_dir = base_dir or DATA_DIR
    payload = _read_json(data_dir / "sources.json", {}) or {}
    sources = []
    for raw in payload.get("sources", []):
        item = {**SOURCE_DEFAULTS, **raw}
        try:
            item["startPage"] = max(1, int(item["startPage"]))
            item["maxPages"] = max(1, int(item["maxPages"]))
            item["maxItems"] = max(1, int(item["maxItems"]))
        except (TypeError, ValueError):
            item["startPage"], item["maxPages"], item["maxItems"] = 1, 1, 20
        sources.append(item)
    return sources


def save_sources(sources: list[dict], base_dir: Path | None = None) -> None:
    data_dir = base_dir or DATA_DIR
    payload = {
        "formatVersion": 1,
        "description": "可爬取来源清单。状态机：pending→ready/failed，另有 disabled；自动核验通过（ready）即进入生成页。",
        "sources": sources,
    }
    _write_json(data_dir / "sources.json", payload)


def load_settings(base_dir: Path | None = None) -> dict:
    data_dir = base_dir or DATA_DIR
    raw = _read_json(data_dir / "settings.json", {}) or {}
    merged = {**SETTINGS_DEFAULTS, **{k: v for k, v in raw.items() if k in SETTINGS_DEFAULTS}}
    try:
        merged["temperature"] = float(merged["temperature"])
    except (TypeError, ValueError):
        merged["temperature"] = SETTINGS_DEFAULTS["temperature"]
    for key in ("timeoutSeconds", "retries", "maxQuestionsPerItem", "crawlDelayMs",
                "requestTimeoutSeconds", "responseLimitMiB"):
        try:
            merged[key] = max(0, int(merged[key]))
        except (TypeError, ValueError):
            merged[key] = SETTINGS_DEFAULTS[key]
    return merged


def save_settings(patch: dict, base_dir: Path | None = None) -> dict:
    merged = {**load_settings(base_dir), **{k: v for k, v in patch.items() if k in SETTINGS_DEFAULTS}}
    _write_json((base_dir or DATA_DIR) / "settings.json", merged)
    return load_settings(base_dir)  # 回读以完成类型强转


def load_catalog(base_dir: Path | None = None) -> list[dict]:
    data_dir = base_dir or DATA_DIR
    payload = _read_json(data_dir / "risk_catalog.json", {}) or {}
    scenes = payload.get("scenes", [])
    if not scenes:
        raise RuntimeError("data/risk_catalog.json 缺失或为空；请先完成风险目录提取。")
    return scenes


def catalog_risks(scenes: list[dict]) -> list[dict]:
    risks = []
    for scene in scenes:
        for risk in scene.get("risks", []):
            risks.append({
                "riskId": risk.get("riskId", ""),
                "sceneCode": scene.get("sceneCode", ""),
                "scene": scene.get("scene", ""),
                "category": risk.get("category", ""),
                "zhTopic": risk.get("zhTopic", ""),
                "enTopic": risk.get("enTopic", ""),
            })
    return risks
