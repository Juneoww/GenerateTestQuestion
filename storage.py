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
import hashlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def _app_root() -> Path:
    """打包成 exe（PyInstaller 冻结）时以 exe 所在目录为根，data/ 与 exe 同级（便携式）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _app_root()
DATA_DIR = PROJECT_ROOT / "data"
APP_VERSION = "4.1.0"  # 发版时与 GitHub Releases 的 tag 同步修改

TEXT_IMAGE_SIZES = ("512x512", "1024x1024", "1280x1280", "1024x768", "1920x1080", "768x1024", "1080x1920")

def _initialize_bundled_data(data_dir: Path, bundled: Path) -> None:
    """仅释放缺失的内置清单；保留用户配置和已有清单。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sources.json", "risk_catalog.json"):
        source, destination = bundled / name, data_dir / name
        if destination.exists():
            continue
        with source.open("rb") as src:
            try:
                dst = destination.open("xb")
            except FileExistsError:
                continue  # 另一个实例已创建该文件，不能覆盖。
            try:
                with dst:
                    shutil.copyfileobj(src, dst)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise


if getattr(sys, "frozen", False):
    # 即使 data 已存在也补齐缺失清单；从不释放 settings.json。
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "data"
    if bundled.is_dir():
        _initialize_bundled_data(DATA_DIR, bundled)

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
    "imageBaseUrl": "",
    "imageApiKey": "",
    "imageModel": "",
    "imageTimeoutSeconds": 120,
    "imageRetries": 2,
    "temperature": 0.7,
    "timeoutSeconds": 60,
    "retries": 2,
    "maxQuestionsPerItem": 5,
    "crawlDelayMs": 500,
    "requestTimeoutSeconds": 15,
    "responseLimitMiB": 2,
    "outputDir": "",
    "textImageSize": "1280x1280",
    "textImageBackgroundPath": "",
    "textImageBackgroundSha256": "",
    # 上次出题用的题目形式（"text" 文本对话题 / "image" 图片生成题），生成页单选的记忆值
    "questionType": "text",
}


def import_text_image_background(source: Path, base_dir: Path | None = None) -> dict:
    """验证并去除元数据后存储用户选择的背景，返回受管相对路径和哈希。"""
    source = Path(source)
    root = base_dir or DATA_DIR
    try:
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("背景图片不能超过 20 MiB")
        with Image.open(source) as img:
            if img.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("仅支持 PNG、JPEG、WebP 图片")
            if img.width * img.height > 40_000_000:
                raise ValueError("背景图片像素过大")
            img = ImageOps.exif_transpose(img)
            img.load()
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                rgba = img.convert("RGBA")
                normalized = Image.new("RGB", rgba.size, "white")
                normalized.paste(rgba, mask=rgba.getchannel("A"))
            else:
                normalized = img.convert("RGB")
            normalized.info.clear()  # 禁止把原图 EXIF 等元数据带入受管副本。
            buffer = io.BytesIO()
            normalized.save(buffer, format="PNG")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("背景图片无法读取或已损坏") from error
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("text-image-backgrounds") / f"{digest}.png"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as tmp:
                temp_name = tmp.name
                tmp.write(payload)
            os.replace(temp_name, destination)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    return {"textImageBackgroundPath": relative.as_posix(), "textImageBackgroundSha256": digest}


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
                "requestTimeoutSeconds", "responseLimitMiB", "imageTimeoutSeconds", "imageRetries"):
        try:
            merged[key] = max(0, int(merged[key]))
        except (TypeError, ValueError):
            merged[key] = SETTINGS_DEFAULTS[key]
    if merged["questionType"] not in ("text", "image"):
        merged["questionType"] = "text"
    return merged


def save_settings(patch: dict, base_dir: Path | None = None) -> dict:
    merged = {**load_settings(base_dir), **{k: v for k, v in patch.items() if k in SETTINGS_DEFAULTS}}
    path = (base_dir or DATA_DIR) / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        # 先写同目录临时文件，完整写入后再替换，防止写入失败破坏原设置。
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings-", suffix=".tmp", delete=False) as tmp:
            temp_name = tmp.name
            tmp.write(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass
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
