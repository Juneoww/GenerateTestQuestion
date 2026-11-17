"""验证二期零宽字符变种的 Excel、图片和复制行为。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from openpyxl import load_workbook
from PIL import Image

from strategy_export import export_strategy_xlsx
from strategy_ui import StrategyWindow


class InvisibleVariantExportTests(TestCase):
    def test_zero_width_codepoints_roundtrip_without_misleading_image(self):
        original = '原\u200b文🙂\nAB'
        variant = '原\u200b文🙂\nA\u200bB'
        rows = [
            {'originalText': original, 'variantText': original, 'strategyId': 'basic', 'status': 'basic'},
            {'originalText': original, 'variantText': variant, 'strategyId': 'R19_zwsp', 'status': 'generated'},
        ]

        def render(text, path, size, background):
            Image.new('RGB', (32, 32), 'white').save(path)

        with TemporaryDirectory() as temp:
            path = Path(temp) / 'variants.xlsx'
            with mock.patch('strategy_export.render_text_image', side_effect=render) as renderer:
                result = export_strategy_xlsx(path, rows, text_image_config=((128, 128), None))
            book = load_workbook(path)
            self.addCleanup(book.close)
            sheet = book.active
            headers = {cell.value: cell.column for cell in sheet[1]}
            self.assertEqual(sheet.cell(2, headers['原子问题']).value, original)
            self.assertEqual(sheet.cell(3, headers['变种问题']).value, variant)
            self.assertEqual(len(sheet._images), 1)
            self.assertIn('无法', sheet.cell(3, headers['文字图片']).value)
            self.assertEqual(renderer.call_count, 1)
            self.assertEqual(result['imagesSkipped'], 1)
            self.assertEqual(result['imageRecords'][1]['strategyId'], 'R19_zwsp')
            self.assertEqual(result['imageRecords'][1]['status'], 'skipped')

    def test_copy_uses_unmodified_variant_text(self):
        variant = '测\u200b试🙂A\u200bB'
        dialog = mock.Mock()
        dialog.tree.selection.return_value = ('0',)
        dialog.rows = [{'variantText': variant}]
        StrategyWindow._copy(dialog)
        dialog.clipboard_clear.assert_called_once_with()
        dialog.clipboard_append.assert_called_once_with(variant)

    def test_published_manifest_and_workbook_preserve_identical_codepoints(self):
        original = '甲\u200b乙🙂\nAB'
        variant = '甲\u200b乙🙂\nA\u200bB'
        with TemporaryDirectory() as temp:
            dialog = mock.Mock()
            dialog.batch_dir = Path(temp)
            dialog.framework = 'LLM'
            dialog.with_images.get.return_value = False
            dialog.rows = [
                {'originalText': original, 'variantText': original, 'strategyId': 'basic', 'status': 'basic'},
                {'originalText': original, 'variantText': variant, 'strategyId': 'R19_zwsp', 'status': 'generated'},
            ]
            dialog.specs = [{'id': 'R19_zwsp'}]
            result = []
            dialog._run.side_effect = lambda task: result.append(task())
            StrategyWindow._export(dialog)
            self.assertEqual(result[0][0], 'exported')
            path = Path(result[0][1][0])
            data = json.loads((path.parent / 'strategy_variants.json').read_text(encoding='utf-8'))
            self.assertEqual(data['results'][1]['originalText'], original)
            self.assertEqual(data['results'][1]['variantText'], variant)
            book = load_workbook(path)
            try:
                sheet = book.active
                headers = {cell.value: cell.column for cell in sheet[1]}
                self.assertEqual(sheet.cell(3, headers['变种问题']).value, variant)
            finally:
                book.close()
