"""验证原题悬浮提示完整内容、长文本滚动和离开时关闭。"""
import time
import tkinter as tk
import unittest

from strategy_ui import StrategyWindow


class SourceTooltipTests(unittest.TestCase):
    def test_source_preview_button_wheel_scrolls_list(self):
        root = tk.Tk()
        window = StrategyWindow(root, [{"question": str(i)} for i in range(25)], "tc", ".")
        try:
            root.update()
            self.assertEqual(window.source.yview()[0], 0.0)
            window.source_preview_buttons[0].event_generate("<MouseWheel>", delta=-120)
            root.update()
            self.assertGreater(window.source.yview()[0], 0.0)
        finally:
            window.destroy()
            root.destroy()

    def test_hover_expands_to_fit_medium_length_question(self):
        root = tk.Tk()
        text = "中等长度原题\n" * 20
        window = StrategyWindow(root, [{"question": text}], "tc", ".")
        try:
            root.update()
            window.source_checks[0].event_generate("<Enter>")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                root.update()
                if window.source_tooltip.popup:
                    break
                time.sleep(.01)
            root.update()
            self.assertEqual(window.source_tooltip.text_widget.yview(), (0.0, 1.0))
        finally:
            window.destroy()
            root.destroy()

    def test_visible_hover_and_persistent_full_text_without_changing_selection(self):
        root = tk.Tk()
        text = "完整长题\n" * 250 + "全文末尾"
        window = StrategyWindow(root, [{"question": text}], "tc", ".")
        try:
            root.update()
            check = window.source_checks[0]
            check.event_generate("<Enter>")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                root.update()
                if window.source_tooltip.popup and window.source_tooltip.popup.winfo_ismapped():
                    break
                time.sleep(.01)
            tooltip = window.source_tooltip
            self.assertTrue(tooltip.popup and tooltip.popup.winfo_ismapped())
            self.assertEqual(tooltip.text_widget.get("1.0", "end-1c"), text)
            check.event_generate("<Leave>")
            deadline = time.monotonic() + .6
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertIsNone(tooltip.popup)
            window.source_preview_buttons[0].invoke()
            root.update()
            self.assertTrue(tooltip.popup.winfo_ismapped())
            check.event_generate("<Leave>")
            deadline = time.monotonic() + .6
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertTrue(tooltip.popup and tooltip.popup.winfo_ismapped())
            self.assertEqual(tooltip.text_widget.get("1.0", "end-1c"), text)
            self.assertTrue(window.source_vars[0].get())
            check.event_generate("<MouseWheel>", delta=-120)
            root.update()
            self.assertTrue(tooltip.popup and tooltip.popup.winfo_ismapped())
            window.source_scrollbar.event_generate("<Button-1>", x=3, y=3)
            root.update()
            self.assertTrue(tooltip.popup and tooltip.popup.winfo_ismapped())
            tooltip.text_widget.yview_moveto(1)
            self.assertGreater(tooltip.text_widget.yview()[0], 0)
        finally:
            window.destroy()
            root.destroy()

    def test_hover_shows_full_text_and_scrolls_then_hides(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"无法创建 Tk 窗口：{error}")
        root.withdraw()
        text = "原题内容\n" * 200 + "末尾完整内容"
        window = StrategyWindow(root, [{"question": text}], "tc", ".")
        try:
            root.update()
            self.assertNotIn("\n", window.source_checks[0].cget("text"))
            window.source_checks[0].event_generate("<Enter>")
            deadline = time.monotonic() + 1.5
            while window.source_tooltip.popup is None and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            tooltip = window.source_tooltip
            self.assertIsNotNone(tooltip.popup)
            self.assertEqual(tooltip.text_widget.get("1.0", "end-1c"), text)
            tooltip.text_widget.yview_moveto(1.0)
            self.assertGreater(tooltip.text_widget.yview()[0], 0)
            tooltip.hide()
            self.assertIsNone(tooltip.popup)
            window.source_checks[0].event_generate("<Enter>")
            deadline = time.monotonic() + 1.5
            while tooltip.popup is None and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertIsNotNone(tooltip.popup)
            window.destroy()
            root.update()
        finally:
            root.destroy()
