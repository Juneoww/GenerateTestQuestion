"""验证历史 TC 原题可生成变种且不会覆盖原历史文件。"""
import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import app


class HistoryStrategyTests(unittest.TestCase):
    def test_load_history_generate_export_preserves_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            batch = output / '历史批次'
            batch.mkdir()
            question = {'seq': 1, 'question': '历史图片提示词', 'questionType': 'image',
                        'riskId': 'R1', 'sceneCode': 'A.1', 'category': '测试', 'language': 'zh',
                        'sourceName': '来源', 'sourceUrl': '', 'evidenceText': '依据'}
            original_json = json.dumps({'questions': [question]}, ensure_ascii=False).encode('utf-8')
            (batch / 'questions.json').write_bytes(original_json)
            original_excel = '历史原始文件'.encode('utf-8')
            (batch / 'questions.xlsx').write_bytes(original_excel)
            window = app.DesktopApplication()
            window.attributes('-alpha', 0)
            try:
                window.update()
                with patch.object(app.pipeline, 'resolve_output_dir', return_value=output):
                    window._load_history_batch()
                dialog = next(child for child in window.winfo_children()
                              if isinstance(child, tk.Toplevel) and child.title() == '选择历史批次')
                next(child for child in dialog.winfo_children()
                     if isinstance(child, ttk.Button) and child.cget('text') == '加载').invoke()
                window.update()
                self.assertTrue(window.current_is_history)
                self.assertFalse(window.strategy_button.instate(['disabled']))
                with patch.object(app.messagebox, 'showinfo') as info:
                    window._open_strategy_window('tc')
                    info.assert_not_called()
                strategy = next(iter(window._strategy_windows.values()))
                strategy.selected_strategies['R01'].set(True)
                strategy._generate()
                deadline = time.monotonic() + 10
                while strategy.busy and time.monotonic() < deadline:
                    window.update()
                    time.sleep(.01)
                self.assertFalse(strategy.busy)
                self.assertEqual(strategy.rows[1]['status'], 'generated')
                with patch('strategy_ui.messagebox.showinfo'), patch('strategy_ui.messagebox.showerror') as error:
                    strategy._export()
                    deadline = time.monotonic() + 15
                    while strategy.busy and time.monotonic() < deadline:
                        window.update()
                        time.sleep(.01)
                    self.assertFalse(strategy.busy)
                    error.assert_not_called()
                self.assertTrue(Path(strategy.last_export).is_file())
                self.assertEqual(Path(strategy.last_export).parent.parent, batch)
                self.assertEqual((batch / 'questions.json').read_bytes(), original_json)
                self.assertEqual((batch / 'questions.xlsx').read_bytes(), original_excel)
                strategy.destroy()
            finally:
                for timer in window.tk.call('after', 'info'):
                    window.after_cancel(timer)
                window.destroy()
