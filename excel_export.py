"""功能:
  用 openpyxl 导出对外交付的题库工作簿。
实现:
  单工作表"测试题库"，固定列序（题干后为"题型"列：文本/图片）；表头加粗、冻结首行、
  列宽预设；原文摘录截断 500 字。
输入: questions 列表、params dict、输出路径。
输出: .xlsx 文件。
依赖: openpyxl（requirements.txt 已声明）。
用法:
  excel_export.export_xlsx(questions, {"batchId": batch_id}, path)
"""
from __future__ import annotations

from pathlib import Path
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as WorkbookImage
from PIL import Image as PillowImage

COLUMNS = ["序号", "题干", "题型", "语言", "大类", "小类ID", "小类", "来源站点",
           "来源URL", "原文摘录", "批次", "生成时间", "模型"]
WIDTHS = [6, 60, 8, 8, 26, 10, 30, 24, 40, 60, 22, 20, 18]
QUESTION_TYPE_LABELS = {"text": "文本", "image": "图片"}
EVIDENCE_LIMIT = 500
TEXT_IMAGE_COLUMNS = ("文字图片", "图片存储路径")
TEXT_IMAGE_WIDTHS = (28, 65)


def write_text_image_cells(sheet, row: int, column: int, image: dict,
                           source_dir: Path, output_dir: Path) -> None:
    """将本地 PNG 缩略图嵌入工作表，并填写原图发布后的绝对路径。"""
    preview_cell = sheet.cell(row, column)
    path_cell = sheet.cell(row, column + 1)
    path_cell.alignment = Alignment(wrap_text=True, vertical="top")
    if image.get("textImageStatus") != "success":
        preview_cell.value = "生成失败：" + str(image.get("textImageError", ""))
        return
    relative = image["textImagePath"]
    path_cell.value = str((output_dir / relative).resolve())
    with PillowImage.open(source_dir / relative) as original:
        thumb = original.convert("RGB")
        thumb.thumbnail((180, 120))
        buf = BytesIO()
        thumb.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    preview = WorkbookImage(buf)
    sheet.add_image(preview, preview_cell.coordinate)
    sheet.row_dimensions[row].height = max(30, preview.height * .75 + 5)


def export_xlsx(questions: list[dict], params: dict, path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试题库"
    bold = Font(bold=True)
    image_batch = params.get("questionType") == "image" or any(q.get("questionType") == "image" for q in questions)
    text_image = bool(params.get("textImageEnabled")) and not image_batch
    columns = COLUMNS + (["图片路径", "图片状态", "图片模型", "图片失败原因"] if image_batch else (list(TEXT_IMAGE_COLUMNS) if text_image else []))
    widths = WIDTHS + ([30, 14, 20, 45] if image_batch else (list(TEXT_IMAGE_WIDTHS) if text_image else []))
    for column, name in enumerate(columns, 1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = bold
        sheet.column_dimensions[get_column_letter(column)].width = widths[column - 1]
    for index, q in enumerate(questions, 1):
        values = [
            index,
            q.get("question", ""),
            QUESTION_TYPE_LABELS.get(q.get("questionType", "text"), "文本"),
            q.get("language", ""),
            q.get("scene", ""),
            q.get("riskId", ""),
            q.get("category", ""),
            q.get("sourceName", ""),
            q.get("sourceUrl", ""),
            (q.get("evidenceText", "") or "")[:EVIDENCE_LIMIT],
            params.get("batchId", ""),
            q.get("generatedAt", ""),
            q.get("model", ""),
        ]
        if image_batch:
            values.extend([q.get("imagePath", ""), q.get("imageStatus", ""), q.get("imageModel", ""), q.get("imageError", "")])
        sheet.append(values)
        if text_image:
            write_text_image_cells(sheet, index + 1, len(COLUMNS) + 1, q, path.parent, path.parent)
    sheet.freeze_panes = "A2"
    wrap = Alignment(wrap_text=True, vertical="top")
    for row in sheet.iter_rows(min_row=2):
        row[1].alignment = wrap
        row[9].alignment = wrap
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path
