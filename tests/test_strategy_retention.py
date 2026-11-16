"""验证变种结果不会因更改选择或重复打开窗口而丢失。"""
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import tkinter as tk

from app import DesktopApplication
from strategy_ui import StrategyWindow


class StrategyRetentionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_changing_selection_keeps_previous_results(self):
        window = StrategyWindow(self.root, [{"question": "第一题"}, {"question": "第二题"}], "tc", ".")
        window.withdraw()
        window.selected_strategies["R01"].set(True)
        window._generate()
        deadline = time.monotonic() + 5
        while window.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(window.busy)
        previous = list(window.rows)
        self.assertTrue(previous)
        window.last_export = "上次结果.xlsx"
        window.open_button.state(["!disabled"])
        window.source_checks[0].invoke()
        self.assertEqual(window.rows, previous)
        self.assertEqual(len(window.tree.get_children()), len(previous))
        self.assertFalse(window.export_button.instate(["disabled"]))
        self.assertEqual(window.last_export, "上次结果.xlsx")
        self.assertFalse(window.open_button.instate(["disabled"]))
        window.destroy()

    def test_reopening_strategy_window_reuses_existing_window(self):
        class Host:
            running = False
            current_questions = [{"question": "原题"}]
            current_is_history = False
        class Window:
            def __init__(self, *args):
                self.raised = False
            def winfo_exists(self):
                return True
            def deiconify(self):
                pass
            def lift(self):
                self.raised = True
            def focus_force(self):
                pass
        with tempfile.TemporaryDirectory() as directory, patch("strategy_ui.StrategyWindow", Window):
            host = Host()
            host.current_batch_dir = directory
            DesktopApplication._open_strategy_window(host, "tc")
            window = next(iter(host._strategy_windows.values()))
            DesktopApplication._open_strategy_window(host, "tc")
            self.assertIs(next(iter(host._strategy_windows.values())), window)
            self.assertTrue(window.raised)

    def test_distinct_batches_and_frameworks_keep_independent_windows(self):
        class Host:
            running = False
            current_questions = [{"question": "第一批"}]
            current_is_history = False
        class Window:
            def __init__(self, *args):
                self.raised = False
            def winfo_exists(self):
                return True
            def deiconify(self):
                pass
            def lift(self):
                self.raised = True
            def focus_force(self):
                pass
        class View:
            owasp_records = [{"prompt": "第二题集"}]
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second, patch("strategy_ui.StrategyWindow", Window):
            host, view = Host(), View()
            host.current_batch_dir = first
            view.owasp_batch_dir = first
            DesktopApplication._open_strategy_window(host, "tc")
            tc_window = next(iter(host._strategy_windows.values()))
            DesktopApplication._open_strategy_window(host, "llm", view)
            self.assertEqual(len(host._strategy_windows), 2)
            host.current_batch_dir = second
            DesktopApplication._open_strategy_window(host, "tc")
            self.assertEqual(len(host._strategy_windows), 3)
            host.current_batch_dir = first
            DesktopApplication._open_strategy_window(host, "tc")
            self.assertTrue(tc_window.raised)
            self.assertEqual(len(host._strategy_windows), 3)

    def test_clicking_original_during_generation_does_not_cancel_it(self):
        window = StrategyWindow(self.root, [{"question": "原题"}], "tc", ".")
        window.withdraw()
        window.selected_strategies["R01"].set(True)
        started, release = threading.Event(), threading.Event()

        def slow_generation(*args):
            started.set()
            release.wait(5)
            return [{"sourceIndex": 1, "strategyId": "basic", "strategyName": "原题",
                     "status": "basic", "reason": "", "originalText": "原题", "variantText": "原题"}]

        try:
            with patch("strategy_ui.make_variant_rows", slow_generation):
                window._generate()
                self.assertTrue(started.wait(3))
                self.assertIn("正在生成变种", window.generate_button.cget("text"))
                window.source_checks[0].invoke()
                self.assertEqual(window._selected()[0], [0])
                self.assertTrue(window.busy)
                self.assertFalse(window.cancel.is_set())
                release.set()
                deadline = time.monotonic() + 5
                while window.busy and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertFalse(window.busy)
                self.assertEqual(window.generate_button.cget("text"), "生成变种")
                self.assertEqual(len(window.rows), 1)
        finally:
            release.set()
            window.destroy()

    def test_generation_error_restores_running_status(self):
        window = StrategyWindow(self.root, [{"question": "原题"}], "tc", ".")
        window.withdraw()
        window.selected_strategies["R01"].set(True)
        started, release = threading.Event(), threading.Event()

        def failing_generation(*args):
            started.set()
            release.wait(5)
            raise ValueError("失败")

        try:
            with patch("strategy_ui.make_variant_rows", failing_generation), patch("strategy_ui.messagebox.showerror"):
                window._generate()
                self.assertTrue(started.wait(3))
                self.assertIn("正在生成变种", window.generate_button.cget("text"))
                release.set()
                deadline = time.monotonic() + 5
                while window.busy and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertFalse(window.busy)
                self.assertEqual(window.generate_button.cget("text"), "生成变种")
        finally:
            release.set()
            window.destroy()

    def test_new_successful_generation_clears_old_export_shortcut(self):
        window = StrategyWindow(self.root, [{"question": "原题"}], "tc", ".")
        window.withdraw()
        window.last_export = "以前导出的文件.xlsx"
        window.open_button.state(["!disabled"])
        window.selected_strategies["R01"].set(True)
        window._generate()
        deadline = time.monotonic() + 5
        while window.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(window.busy)
        self.assertTrue(window.rows)
        self.assertIsNone(window.last_export)
        self.assertTrue(window.open_button.instate(["disabled"]))
        window.destroy()
