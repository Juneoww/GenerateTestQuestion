"""功能：导出本次原题及规则变种到同一 Excel 工作表。

实现：按调用方提供的顺序写入基线和变种，文本作为字面值；可选复用现有文字图片渲染。
输入：输出路径、状态记录、可选画布配置及停止检查；图片背景为预先冻结的字节。
输出：Excel、可选 PNG 文件及图片统计；无网络或模型调用。
依赖：openpyxl、Pillow 与项目内文字图片模块；调用方负责独立暂存目录与发布。
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from excel_export import write_text_image_cells
from text_image_renderer import render_text_image

_COLUMNS = (
    ('原题序号', 'sourceIndex', 12), ('风险编号', 'riskId', 14), ('风险类别', 'riskName', 22),
    ('原子问题', 'originalText', 55), ('策略编号', 'strategyId', 14), ('攻击方式', 'strategyName', 24),
    ('变种问题', 'variantText', 60), ('状态', 'status', 14), ('原因', 'reason', 36),
    ('来源', 'sourceName', 22), ('来源链接', 'sourceUrl', 36),
    ('原题题型', 'questionType', 14), ('原题 userA', 'originalUserA', 45),
    ('原题 userB', 'originalUserB', 45), ('原题断言', 'originalAssertion', 45),
    ('原题预期输入面（目录）', 'plannedInputSurface', 30),
    ('复核状态', 'reviewStatus', 14),
)
_ILLEGAL_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')
_IMAGE_REASON = '此策略无法通过文字图片保留隐藏内容'
_STATUS_LABELS = {'basic': '原题', 'generated': '已生成', 'skipped': '不适用', 'failed': '失败'}
_REVIEW_LABELS = {'needs_review': '待复核', 'not_applicable': '不适用'}


def _literal(value: object) -> str:
    """以 UTF-16 单元计长度，拒绝 Excel 无法保存的内容而不截断。"""
    text = '' if value is None else str(value)
    try:
        length = len(text.encode('utf-16-le')) // 2
    except UnicodeEncodeError as error:
        raise ValueError('文本包含无效 Unicode 字符') from error
    if length > 32767:
        raise ValueError('文本超出 Excel 单元格长度限制')
    if _ILLEGAL_XML.search(text):
        raise ValueError('文本包含 Excel 无法保存的控制字符')
    return text


def export_strategy_xlsx(
    path: str | Path,
    rows: list[dict],
    *,
    text_image_config: tuple[tuple[int, int], bytes | None] | None = None,
    output_dir: str | Path | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict:
    """导出已有状态行；调用方负责加入 basic 行以及准备独立批次目录。"""
    destination = Path(path)
    published_dir = Path(output_dir) if output_dir is not None else destination.parent
    check = checkpoint or (lambda: None)
    normalized = []
    for row in rows:
        check()
        if row.get('status') not in ('basic', 'generated', 'skipped', 'failed'):
            raise ValueError('变种状态无效')
        values = []
        for _, field, _ in _COLUMNS:
            value = row.get(field, '')
            if field == 'status':
                value = _STATUS_LABELS[row['status']]
            elif field == 'reviewStatus':
                value = _REVIEW_LABELS.get(value, value)
            values.append(_literal(value))
        normalized.append(values)

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '原题与变种'
    headers = [label for label, _, _ in _COLUMNS]
    if text_image_config is not None:
        headers += ['文字图片', '图片存储路径']
    sheet.append(headers)
    for column, (_, _, width) in enumerate(_COLUMNS, 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    if text_image_config is not None:
        sheet.column_dimensions[get_column_letter(len(_COLUMNS) + 1)].width = 28
        sheet.column_dimensions[get_column_letter(len(_COLUMNS) + 2)].width = 65
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{len(rows) + 1}'
    for values in normalized:
        sheet.append(values)
    for row in sheet.iter_rows(min_row=2, max_col=len(_COLUMNS)):
        for cell in row:
            cell.data_type = 's'
            cell.alignment = Alignment(wrap_text=True, vertical='top')

    stats = {'imagesSucceeded': 0, 'imagesFailed': 0, 'imagesSkipped': 0, 'imageRecords': []}
    created: list[Path] = []
    background_file = None
    temporary = None
    try:
        if text_image_config is not None:
            size, background = text_image_config
            if background is not None:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.strategy-bg-', suffix='.png', delete=False) as handle:
                    background_file = Path(handle.name)
                    handle.write(background)
            for index, record in enumerate(rows, 1):
                check()
                number = index + 1
                col = len(_COLUMNS) + 1
                status = record['status']
                image_record = {'rowIndex': index, 'strategyId': str(record.get('strategyId', '')),
                                'status': 'skipped', 'relativePath': '', 'reason': ''}
                stats['imageRecords'].append(image_record)
                if status not in ('basic', 'generated'):
                    sheet.cell(number, col, '不适用')
                    image_record['reason'] = '变种未生成'
                    stats['imagesSkipped'] += 1
                    continue
                if record.get('strategyId', '').upper() == 'R09':
                    sheet.cell(number, col, _IMAGE_REASON)
                    image_record['reason'] = _IMAGE_REASON
                    stats['imagesSkipped'] += 1
                    continue
                content = record.get('originalText', '') if status == 'basic' else record.get('variantText', '')
                relative = Path('images') / f'strategy_{index:06d}.png'
                picture = destination.parent / relative
                picture.parent.mkdir(parents=True, exist_ok=True)
                if picture.exists():
                    raise FileExistsError(f'图片路径已存在：{picture}')
                try:
                    render_text_image(content, picture, size, background_file)
                    created.append(picture)
                    write_text_image_cells(sheet, number, col,
                                           {'textImageStatus': 'success', 'textImagePath': str(relative)},
                                           destination.parent, published_dir)
                    image_record['status'] = 'success'
                    image_record['relativePath'] = relative.as_posix()
                    stats['imagesSucceeded'] += 1
                except (OSError, ValueError) as error:
                    if picture in created:
                        picture.unlink(missing_ok=True)
                        created.remove(picture)
                    reason = '文字图片生成失败' if isinstance(error, OSError) else str(error)
                    sheet.cell(number, col, _literal('生成失败：' + reason))
                    image_record['status'] = 'failed'
                    image_record['reason'] = reason
                    stats['imagesFailed'] += 1
        check()
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.strategy-xlsx-', suffix='.xlsx', delete=False) as handle:
            temporary = Path(handle.name)
        workbook.save(temporary)
        check()
        os.replace(temporary, destination)
        return stats
    except BaseException:
        for picture in created:
            picture.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if background_file is not None:
            background_file.unlink(missing_ok=True)
