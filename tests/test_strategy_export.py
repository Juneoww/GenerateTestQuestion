"""验证原题和本次变种合并导出、图片定位与文本保真。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from openpyxl import load_workbook
from PIL import Image

from strategy_export import export_strategy_xlsx


class StrategyExportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'result.xlsx'
        self.rows = [
            {'sourceIndex': 1, 'riskId': 'A1', 'riskName': '风险', 'originalText': '=猫',
             'strategyId': 'basic', 'strategyName': '原题', 'variantText': '=猫', 'status': 'basic', 'reason': ''},
            {'sourceIndex': 1, 'riskId': 'A1', 'riskName': '风险', 'originalText': '=猫',
             'strategyId': 'R09', 'strategyName': 'emoji编码', 'variantText': '🙂\U000e0151', 'status': 'generated', 'reason': ''},
            {'sourceIndex': 1, 'riskId': 'A1', 'riskName': '风险', 'originalText': '=猫',
             'strategyId': 'R07', 'strategyName': '摩尔斯', 'variantText': '', 'status': 'skipped', 'reason': '字符不支持'},
        ]

    def test_export_baseline_variant_and_skip_as_literal_cells(self):
        stats = export_strategy_xlsx(self.path, self.rows)
        self.assertEqual(stats['imageRecords'], [])
        sheet = load_workbook(self.path).active
        self.assertEqual(sheet.max_row, 4)
        headers = {cell.value: cell.column for cell in sheet[1]}
        self.assertEqual(sheet.cell(2, headers['原子问题']).value, '=猫')
        self.assertEqual(sheet.cell(2, headers['原子问题']).data_type, 's')
        self.assertEqual(sheet.cell(3, headers['变种问题']).value, '🙂\U000e0151')
        self.assertEqual(sheet.cell(4, headers['原因']).value, '字符不支持')

    def test_context_is_exported_for_original_and_variant_without_guessing_surface(self):
        context = {'questionType': 'image', 'originalUserA': '=第一条',
                   'originalUserB': '第二条', 'originalAssertion': '原始断言',
                   'plannedInputSurface': '工具返回正文'}
        rows = [dict(row, **context) for row in self.rows[:2]]
        rows.append(dict(self.rows[2], questionType='text'))
        export_strategy_xlsx(self.path, rows)
        sheet = load_workbook(self.path).active
        headers = {cell.value: cell.column for cell in sheet[1]}
        for row_number in (2, 3):
            for heading, expected in [('原题题型', 'image'), ('原题 userA', '=第一条'),
                                      ('原题 userB', '第二条'), ('原题断言', '原始断言'),
                                      ('原题预期输入面（目录）', '工具返回正文')]:
                self.assertEqual(sheet.cell(row_number, headers[heading]).value, expected)
            self.assertEqual(sheet.cell(row_number, headers['原题 userA']).data_type, 's')
        self.assertIsNone(sheet.cell(4, headers['原题预期输入面（目录）']).value)

    def test_review_status_distinguishes_original_and_unverified_variant(self):
        rows = [dict(self.rows[0], reviewStatus='not_applicable'),
                dict(self.rows[1], reviewStatus='needs_review'), self.rows[2]]
        export_strategy_xlsx(self.path, rows)
        sheet = load_workbook(self.path).active
        headers = {cell.value: cell.column for cell in sheet[1]}
        self.assertEqual(sheet.cell(2, headers['复核状态']).value, '不适用')
        self.assertEqual(sheet.cell(3, headers['复核状态']).value, '待复核')
        self.assertIsNone(sheet.cell(4, headers['复核状态']).value)

    def test_image_baseline_and_hidden_variant_does_not_claim_image(self):
        def fake_render(text, path, size, background):
            Image.new('RGB', (32, 32), 'white').save(path)
        with mock.patch('strategy_export.render_text_image', side_effect=fake_render):
            stats = export_strategy_xlsx(self.path, self.rows, text_image_config=((512, 512), None))
        sheet = load_workbook(self.path).active
        headers = {cell.value: cell.column for cell in sheet[1]}
        self.assertEqual(len(sheet._images), 1)
        self.assertIn('无法', sheet.cell(3, headers['文字图片']).value)
        self.assertEqual(sheet.cell(4, headers['文字图片']).value, '不适用')
        self.assertEqual(stats['imagesSucceeded'], 1)
        self.assertEqual(stats['imageRecords'], [
            {'rowIndex': 1, 'strategyId': 'basic', 'status': 'success', 'relativePath': 'images/strategy_000001.png', 'reason': ''},
            {'rowIndex': 2, 'strategyId': 'R09', 'status': 'skipped', 'relativePath': '', 'reason': '表情后的不可见编码无法通过文字图片保留，仅绘制表情会丢失隐藏内容'},
            {'rowIndex': 3, 'strategyId': 'R07', 'status': 'skipped', 'relativePath': '', 'reason': '变种未生成'},
        ])

    def test_oversize_or_illegal_cell_fails_without_truncating(self):
        for value in ['🙂' * 16384, '含\x00字符']:
            rows = [dict(self.rows[0], originalText=value)]
            with self.assertRaises(ValueError):
                export_strategy_xlsx(self.path, rows)
            self.assertFalse(self.path.exists())

    def test_image_failure_preserves_text_and_records_reason(self):
        with mock.patch('strategy_export.render_text_image', side_effect=ValueError('文字无法完整显示')):
            stats = export_strategy_xlsx(self.path, self.rows, text_image_config=((512, 512), None))
        sheet = load_workbook(self.path).active
        headers = {cell.value: cell.column for cell in sheet[1]}
        self.assertEqual(sheet.cell(2, headers['原子问题']).value, '=猫')
        self.assertIn('文字无法完整显示', sheet.cell(2, headers['文字图片']).value)
        self.assertEqual(stats['imagesFailed'], 1)
        self.assertEqual(stats['imageRecords'][0], {'rowIndex': 1, 'strategyId': 'basic',
                         'status': 'failed', 'relativePath': '', 'reason': '文字无法完整显示'})

    def test_cancellation_cleans_only_owned_staged_image(self):
        def fake_render(text, path, size, background):
            Image.new('RGB', (32, 32), 'white').save(path)

        calls = 0
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise RuntimeError('取消')

        with mock.patch('strategy_export.render_text_image', side_effect=fake_render):
            with self.assertRaisesRegex(RuntimeError, '取消'):
                export_strategy_xlsx(self.path, self.rows, text_image_config=((512, 512), None), checkpoint=checkpoint)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.root / 'images' / 'strategy_000001.png').exists())
