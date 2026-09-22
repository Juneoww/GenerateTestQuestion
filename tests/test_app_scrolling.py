"""功能: 回归验证生成页第 4/5 块的稳定高度与鼠标滚轮接力。
实现: 创建透明的真实 Tk 窗口，发送滚轮事件并检查控件几何和 yview。
输入: 项目默认配置与内存中的长日志/题目样例；不发起爬取或模型调用。
输出: unittest 检查结果，不修改用户配置或批次数据。
依赖: 项目运行依赖、可用的 Tk 图形环境。
用法: .venv/Scripts/python -m unittest discover -s tests -p test_app_scrolling.py -v
"""
import sys
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class GeneratePageScrollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = app.DesktopApplication()
        # 透明但保持映射，才能执行 Tk 的真实布局与控件类事件绑定。
        cls.window.attributes("-alpha", 0)
        cls.window.update()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.window.tk.call("after", "info"):
            cls.window.after_cancel(timer)
        cls.window.destroy()

    def setUp(self):
        self.window.geometry("1280x900")
        self.window.generate_tab.master.select(self.window.generate_tab)
        for widget in (self.window.log_text, self.window.detail_text):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", "\n".join(f"测试内容 {n}" for n in range(100)))
            widget.configure(state="disabled")
        tree = self.window.question_tree
        tree.delete(*tree.get_children())
        for index in range(100):
            tree.insert("", "end", values=(index, "A1-01", "测试题干"))
        self.window.update()
        self.canvas = self.window._page_canvas
        self.canvas.yview_moveto(0)
        for widget in self.scroll_widgets:
            widget.yview_moveto(0)
        self.window.update()

    @property
    def scroll_widgets(self):
        return (self.window.log_text, self.window.detail_text, self.window.question_tree)

    def wheel(self, widget, delta, **kwargs):
        widget.event_generate("<MouseWheel>", delta=delta, **kwargs)
        self.window.update()

    def center_page(self):
        self.canvas.yview_moveto(1)
        self.canvas.yview_moveto(self.canvas.yview()[0] / 2)
        self.window.update()

    def test_result_panels_keep_readable_height_when_window_resizes(self):
        initial = None
        for geometry in ("1280x900", "1020x720", "1920x1080", "1280x900"):
            with self.subTest(geometry=geometry):
                self.window.geometry(geometry)
                self.window.update()
                heights = tuple(w.winfo_height() for w in self.scroll_widgets)
                self.assertGreaterEqual(heights[0], 100, "日志应保留多行阅读空间")
                self.assertGreaterEqual(heights[1], 300, "详情不能被压缩为几行")
                self.assertGreaterEqual(heights[2], 300, "题目表不能被压缩为几行")
                if initial is not None:
                    self.assertEqual(heights, initial, "窗口变化不应挤压第 4/5 块")
                initial = heights

    def test_page_wheel_can_reveal_entire_comparison_and_actions(self):
        self.assertLess(self.canvas.yview()[1], 1, "应产生整页滚动范围")
        for _ in range(40):
            self.wheel(self.window.selection_summary, -120)
        self.assertAlmostEqual(self.canvas.yview()[1], 1)
        top = self.canvas.winfo_rooty()
        bottom = top + self.canvas.winfo_height()
        for widget in (self.window.detail_text, self.window.question_tree,
                       self.window.open_batch_button):
            with self.subTest(widget=widget.winfo_class()):
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(widget.winfo_rooty(), top)
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)

    def test_both_comparison_columns_remain_readable_in_small_window(self):
        self.window.geometry("1020x720")
        self.window.update()
        self.canvas.yview_moveto(1)
        self.window.update()
        for widget in (self.window.question_tree, self.window.detail_text):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreaterEqual(widget.winfo_width(), 300, "左右两列都需保留阅读宽度")

    def test_inner_widgets_scroll_locally_before_handoff_at_both_edges(self):
        for widget in self.scroll_widgets:
            for delta, edge in ((-120, 1), (120, 0)):
                with self.subTest(widget=widget.winfo_class(), delta=delta):
                    self.center_page()
                    widget.yview_moveto(0.4)
                    self.window.update()
                    page_before, inner_before = self.canvas.yview(), widget.yview()
                    self.wheel(widget, delta)
                    self.assertNotEqual(widget.yview(), inner_before)
                    self.assertEqual(self.canvas.yview(), page_before)

                    widget.yview_moveto(edge)
                    self.window.update()
                    inner_before = widget.yview()
                    self.wheel(widget, delta)
                    self.assertEqual(widget.yview(), inner_before)
                    if delta < 0:
                        self.assertGreater(self.canvas.yview()[0], page_before[0])
                    else:
                        self.assertLess(self.canvas.yview()[0], page_before[0])

    def test_empty_inner_widget_hands_off_to_page(self):
        widget = self.window.log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")
        self.window.update()
        self.wheel(widget, -120)
        self.assertGreater(self.canvas.yview()[0], 0)

    def test_event_that_reaches_inner_edge_does_not_also_scroll_page(self):
        # 内层最后一小段仍由原生绑定滚完；下一次滚轮才交给页面。
        widget = self.window.log_text
        widget.yview_moveto(1)
        widget.yview_scroll(-1, "pixels")
        self.window.update()
        self.assertLess(widget.yview()[1], 1)
        page_before = self.canvas.yview()
        self.wheel(widget, -120)
        self.assertEqual(self.canvas.yview(), page_before)
        self.wheel(widget, -120)
        self.assertGreater(self.canvas.yview()[0], page_before[0])

    def test_small_deltas_and_x11_wheel_events_scroll_in_both_directions(self):
        for event, kwargs, down in (("<MouseWheel>", {"delta": -1}, True),
                                    ("<MouseWheel>", {"delta": 1}, False),
                                    ("<Button-5>", {}, True),
                                    ("<Button-4>", {}, False)):
            with self.subTest(event=event, kwargs=kwargs):
                self.center_page()
                before = self.canvas.yview()[0]
                self.window.selection_summary.event_generate(event, **kwargs)
                self.window.update()
                after = self.canvas.yview()[0]
                if down:
                    self.assertGreater(after, before)
                else:
                    self.assertLess(after, before)

    def test_shift_zero_delta_and_spinbox_do_not_scroll_page(self):
        self.center_page()
        before = self.canvas.yview()
        self.wheel(self.window.selection_summary, -120, state=1)
        self.wheel(self.window.selection_summary, 0)
        spinbox = self.window._generate_widgets[0]
        self.wheel(spinbox, -120)
        self.assertEqual(self.canvas.yview(), before)

    def test_both_edges_stop_without_overscroll(self):
        for edge, delta in ((0, 120), (1, -120)):
            with self.subTest(edge=edge):
                self.canvas.yview_moveto(edge)
                self.window.log_text.yview_moveto(edge)
                self.window.update()
                before = self.canvas.yview(), self.window.log_text.yview()
                self.wheel(self.window.log_text, delta)
                self.assertEqual((self.canvas.yview(), self.window.log_text.yview()), before)

    def test_wheel_in_other_tabs_and_dialogs_does_not_move_generate_page(self):
        self.center_page()
        before = self.canvas.yview()
        self.wheel(self.window, -120)
        self.assertEqual(self.canvas.yview(), before)
        dialog = tk.Toplevel(self.window)
        dialog.attributes("-alpha", 0)
        try:
            label = tk.Label(dialog, text="其他窗口")
            label.pack()
            self.window.update()
            self.wheel(label, -120)
            self.assertEqual(self.canvas.yview(), before)
        finally:
            dialog.destroy()
        self.window.generate_tab.master.select(self.window.sources_tab)
        self.window.update()
        self.wheel(self.window.source_tree, -120)
        self.assertEqual(self.canvas.yview(), before)

    def test_page_that_fits_preserves_inner_scroll_and_spinbox_behavior(self):
        # 模拟整页完全可见，无需把真实窗口扩大到显示器以外。
        region = self.canvas.cget("scrollregion")
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(),
                                            self.canvas.winfo_height()))
        try:
            self.canvas.yview_moveto(0)
            self.window.log_text.yview_moveto(0)
            self.wheel(self.window.log_text, -120)
            self.assertGreater(self.window.log_text.yview()[0], 0)
            self.assertEqual(self.canvas.yview(), (0.0, 1.0))
            self.wheel(self.window._generate_widgets[0], -120)
            self.assertEqual(self.canvas.yview(), (0.0, 1.0))
        finally:
            self.canvas.configure(scrollregion=region)


if __name__ == "__main__":
    unittest.main()
