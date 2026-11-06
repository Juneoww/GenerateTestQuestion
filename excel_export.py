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


def export_xlsx(questions: list[dict], params: dict, path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试题库"
    bold = Font(bold=True)
    image_batch = params.get("questionType") == "image" or any(q.get("questionType") == "image" for q in questions)
    text_image = bool(params.get("textImageEnabled")) and not image_batch
    columns = COLUMNS + (["图片路径", "图片状态", "图片模型", "图片失败原因"] if image_batch else (["文字图片", "图片存储路径"] if text_image else []))
    widths = WIDTHS + ([30, 14, 20, 45] if image_batch else ([28, 65] if text_image else []))
    thumbnails = []
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
        elif text_image:
            success = q.get("textImageStatus") == "success"
            values.extend(["" if success else "生成失败：" + str(q.get("textImageError", "")),
                           str((path.parent / q["textImagePath"]).resolve()) if success else ""])
        sheet.append(values)
        if text_image and q.get("textImageStatus") == "success":
            # 缩略图保存在内存直到工作簿写入，原图单独留在批次目录。
            with PillowImage.open(path.parent / q["textImagePath"]) as original:
                thumb = original.convert("RGB")
                thumb.thumbnail((180, 120))
                buf = BytesIO()
                thumb.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            thumbnails.append(buf)
            preview = WorkbookImage(buf)
            sheet.add_image(preview, f"N{index + 1}")
            sheet.row_dimensions[index + 1].height = max(30, preview.height * .75 + 5)
    sheet.freeze_panes = "A2"
    wrap = Alignment(wrap_text=True, vertical="top")
    for row in sheet.iter_rows(min_row=2):
        row[1].alignment = wrap
        row[9].alignment = wrap
        if text_image:
            row[14].alignment = wrap
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path
