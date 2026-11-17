"""验证文字图片不生成时的具体原因和导出一致性。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import load_workbook

from strategy_export import export_strategy_xlsx
from text_image_renderer import render_text_image


class ImageReasonsTests(TestCase):
    def test_hidden_reasons_distinguish_emoji_and_zero_width(self):
        rows = [
            {'originalText': '测试', 'variantText': '😊\U000e0131', 'strategyId': 'R09', 'status': 'generated'},
            {'originalText': '测试', 'variantText': '测\u200b试', 'strategyId': 'R19_zwsp', 'status': 'generated'},
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.xlsx'
            result = export_strategy_xlsx(path, rows, text_image_config=((1280, 1280), None))
            book = load_workbook(path)
            try:
                sheet = book.active
                headers = {cell.value: cell.column for cell in sheet[1]}
                emoji = result['imageRecords'][0]['reason']
                zero_width = result['imageRecords'][1]['reason']
                self.assertIn('表情后', emoji)
                self.assertIn('隐藏', emoji)
                self.assertIn('零宽', zero_width)
                self.assertNotEqual(emoji, zero_width)
                self.assertEqual(sheet.cell(2, headers['文字图片']).value, emoji)
                self.assertEqual(sheet.cell(3, headers['文字图片']).value, zero_width)
                self.assertEqual(sheet.cell(2, headers['状态']).value, '已生成')
            finally:
                book.close()

    def test_layout_failure_includes_actual_parameters(self):
        text = '01 ' * 1440 + '01'
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as error:
                render_text_image(text, Path(tmp) / 'test.png', (1280, 1280))
        message = str(error.exception)
        for detail in ('4322', '1280', '28', '字号'):
            self.assertIn(detail, message)

    def test_length_limit_and_tabs_have_distinct_reasons(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.png'
            with self.assertRaisesRegex(ValueError, '5001.*5000'):
                render_text_image('x' * 5001, path, (1280, 1280))
            with self.assertRaisesRegex(ValueError, '制表符'):
                render_text_image('a\tb', path, (1280, 1280))
