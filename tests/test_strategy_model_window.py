"""验证当前批次原题与规则、模型变种同窗生成和导出。"""
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from strategy_ui import StrategyWindow, make_variant_rows


class ModelVariantWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.root.destroy)
        self.original = '请根据公开手册列出两种可导出格式。'
        self.record = {'seq': 7, 'prompt': self.original, 'language': 'zh', 'assertion': '列出两种格式'}
        self.settings = patch('storage.load_settings', return_value={
            'baseUrl': 'https://example.test/v1', 'model': 'model', 'apiKey': 'secret'})
        self.settings_mock = self.settings.start()
        self.addCleanup(self.settings.stop)
        self.window = StrategyWindow(self.root, [self.record], 'agentic', self.temp.name)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.window.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.window.busy)

    def test_all_groups_use_one_current_original_and_export_together(self):
        window = self.window
        for sid in ('R01', 'R04', 'R18', 'I01', 'I02', 'I03', 'S01', 'S17', 'S18'):
            window.selected_strategies[sid].set(True)
        window._selection_changed()
        self.assertFalse(hasattr(window, 'model_source_frame'))
        self.assertIn('最多 9 条变种', window.estimate.get())
        self.assertIn('最多 3 次模型请求', window.estimate.get())

        def model(sid, text, **kwargs):
            self.assertEqual(text, self.original)
            self.assertEqual(kwargs['language'], 'zh')
            return {'status': 'generated', 'text': f'{sid} 的结果', 'reason': '',
                    'modelMeta': {'model': 'model'}}

        with patch('strategy_model.apply_model_strategy', side_effect=model) as call:
            window._generate()
            self.wait_idle()
        self.assertEqual(call.call_count, 3)
        self.assertEqual(len(window.rows), 10)
        self.assertEqual(sum(row['strategyId'] == 'basic' for row in window.rows), 1)
        self.assertTrue(all(row['originalText'] == self.original for row in window.rows))
        self.assertTrue(all(row['originalAssertion'] == '列出两种格式' for row in window.rows))
        self.assertTrue(all(row['reviewStatus'] == '' for row in window.rows if row['strategyId'].startswith('S')))

        with patch('strategy_ui.messagebox.showinfo'):
            window._export()
            self.wait_idle()
        exported = Path(window.last_export)
        workbook = load_workbook(exported, read_only=True)
        try:
            rows = list(workbook.active.values)
            self.assertEqual(len(rows), 11)
            self.assertEqual(sum(row[4] == 'basic' for row in rows[1:]), 1)
        finally:
            workbook.close()
        manifest = json.loads(exported.with_name('strategy_variants.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['results']), 10)
        self.assertNotIn('secret', json.dumps(manifest))

    def test_model_cancel_keeps_previous_results(self):
        self.window.selected_strategies['S01'].set(True)
        self.window._selection_changed()
        previous = [{'status': 'generated', 'strategyId': 'S01'}]
        self.window.rows = previous
        started, release = threading.Event(), threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(2)
            return {'status': 'generated', 'text': '新结果'}

        with patch('strategy_model.apply_model_strategy', side_effect=slow):
            self.window._generate()
            try:
                self.assertTrue(started.wait(2))
                self.window.model_cancel_button.invoke()
            finally:
                release.set()
            self.wait_idle()
        self.assertIs(self.window.rows, previous)

    def test_multiple_languages_and_independent_model_strategies(self):
        self.window.destroy()
        records = [{'prompt': '查询示例手册', 'language': 'zh'},
                   {'prompt': 'Check the sample manual', 'language': 'en'}]
        self.window = StrategyWindow(self.root, records, 'llm', self.temp.name)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        for sid in ('S01', 'S17', 'S18'):
            self.window.selected_strategies[sid].set(True)
        self.window._selection_changed()
        self.assertIn('最多 6 次模型请求', self.window.estimate.get())

        def model(sid, text, **kwargs):
            expected_language = 'zh' if text == records[0]['prompt'] else 'en'
            self.assertEqual(kwargs['language'], expected_language)
            return {'status': 'generated', 'text': '相同变种', 'reason': ''}

        with patch('strategy_model.apply_model_strategy', side_effect=model) as call:
            self.window._generate()
            self.wait_idle()
        self.assertEqual(call.call_count, 6)
        self.assertEqual([row['status'] for row in self.window.rows],
                         ['basic', 'generated', 'generated', 'generated'] * 2)

    def test_model_failure_does_not_block_other_strategies(self):
        for sid in ('R01', 'S01', 'S17'):
            self.window.selected_strategies[sid].set(True)
        self.window._selection_changed()

        def model(sid, *_args, **_kwargs):
            if sid == 'S01':
                raise RuntimeError('sensitive detail')
            return {'status': 'generated', 'text': '新的表达'}

        with patch('strategy_model.apply_model_strategy', side_effect=model):
            self.window._generate()
            self.wait_idle()
        self.assertEqual([row['status'] for row in self.window.rows],
                         ['basic', 'generated', 'failed', 'generated'])
        self.assertNotIn('sensitive detail', self.window.rows[2]['reason'])

    def test_all_frameworks_keep_the_current_original_and_assertion(self):
        for framework, source in (
            ('tc', {'question': self.original, 'language': 'zh', 'assertion': '两种'}),
            ('llm', {'prompt': self.original, 'language': 'zh', 'assertion': '两种'}),
            ('agentic', {'prompt': self.original, 'language': 'zh', 'assertion': '两种'}),
        ):
            with self.subTest(framework=framework):
                rows = make_variant_rows([source], [0], ['S01'], framework,
                                         lambda *_args, **_kw: {'status': 'generated', 'text': '改写结果'},
                                         model_strategy_ids={'S01'})
                self.assertEqual([row['strategyId'] for row in rows], ['basic', 'S01'])
                self.assertEqual(rows[1]['originalText'], self.original)
                self.assertEqual(rows[1]['originalAssertion'], '两种')

    def test_missing_config_does_not_block_rules_alone(self):
        self.window.model_ready = False
        self.window.selected_strategies['S01'].set(True)
        self.window.selected_strategies['R01'].set(True)
        self.window._selection_changed()
        self.assertIn('配置文本模型', self.window.estimate.get())
        self.assertTrue(self.window.generate_button.instate(['disabled']))
        self.window.selected_strategies['S01'].set(False)
        self.window._selection_changed()
        self.assertTrue(self.window.generate_button.instate(['!disabled']))


if __name__ == '__main__':
    unittest.main()
