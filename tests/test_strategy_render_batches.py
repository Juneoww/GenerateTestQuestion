"""验证大量变种结果分批渲染及中途关闭的窗口生命周期。"""
import threading
import time
import tkinter as tk
import unittest

from strategy_ui import StrategyWindow


class StrategyRenderBatchTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.window = StrategyWindow(self.root, [{'question': '原题'}], 'tc', '.')
        self.window.withdraw()
        self.window.selected_strategies['R01'].set(True)

    def tearDown(self):
        self.root.destroy()

    def _start_render(self):
        rows = [{'sourceIndex': index, 'strategyId': 'basic', 'strategyName': '原题',
                 'status': 'basic', 'reason': '', 'originalText': '原题', 'variantText': '原题'}
                for index in range(2000)]
        ready = threading.Event()
        def task():
            ready.set()
            return 'generated', rows
        self.window._run(task)
        self.assertTrue(ready.wait(3))
        deadline = time.monotonic() + 3
        while self.window.tasks.empty() and time.monotonic() < deadline:
            time.sleep(.01)
        self.window.after_cancel(self.window._poll_after)
        self.window._poll()
        return rows

    def test_large_result_renders_incrementally_with_controls_disabled(self):
        rows = self._start_render()
        self.assertTrue(self.window.busy)
        self.assertGreater(len(self.window.tree.get_children()), 0)
        self.assertLess(len(self.window.tree.get_children()), len(rows))
        self.assertTrue(self.window.generate_button.instate(['disabled']))
        self.assertTrue(self.window.export_button.instate(['disabled']))
        self.assertTrue(self.window.source_checks[0].instate(['disabled']))
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.window.busy)
        self.assertEqual(len(self.window.tree.get_children()), len(rows))
        self.assertFalse(self.window.export_button.instate(['disabled']))
        self.assertFalse(self.window.source_checks[0].instate(['disabled']))

    def test_close_during_render_cancels_scheduled_callbacks(self):
        self._start_render()
        self.assertIsNotNone(getattr(self.window, '_render_after', None))
        self.window._close()
        self.assertFalse(self.window.winfo_exists())
        self.root.update()
