"""验证各类别独立展开、多选及生成期间的状态。"""
import threading
import time
import tkinter as tk
import unittest

from strategy_ui import StrategyWindow


class StrategyDropdownTests(unittest.TestCase):
    def test_independent_category_selection_and_busy_state(self):
        root = tk.Tk()
        try:
            window = StrategyWindow(root, [{"question": "测试"}], "tc", ".")
            window.geometry("900x650")
            root.update()
            base = window.strategy_group_buttons["基础规则"]
            instruction = window.strategy_group_buttons["直接指令"]
            base.invoke()
            root.update()
            self.assertEqual(window.open_strategy_group, "基础规则")
            self.assertTrue(window.strategy_group_panels["基础规则"].winfo_ismapped())
            self.assertFalse(window.strategy_group_panels["直接指令"].winfo_ismapped())
            window.strategy_checks[0].invoke()
            window.strategy_checks[1].invoke()
            self.assertIn("2", base.cget("text"))
            instruction.invoke()
            root.update()
            self.assertEqual(window.open_strategy_group, "直接指令")
            self.assertFalse(window.strategy_group_panels["基础规则"].winfo_ismapped())
            first_instruction = next(i for i, s in enumerate(window.specs) if s["group"] == "直接指令")
            window.strategy_checks[first_instruction].invoke()
            self.assertIn("1", instruction.cget("text"))
            self.assertEqual(len(window._selected()[1]), 3)
            self.assertTrue(window.export_button.winfo_ismapped())
            self.assertTrue(window.generate_button.winfo_ismapped())
            self.assertLessEqual(window.strategy_group_panels["直接指令"].winfo_rooty() + window.strategy_group_panels["直接指令"].winfo_height(), window.export_button.winfo_rooty())
            finished = threading.Event()
            window._run(lambda: (finished.wait(2), ("generated", []))[1])
            self.assertIsNone(window.open_strategy_group)
            self.assertTrue(base.instate(["disabled"]))
            self.assertTrue(instruction.instate(["disabled"]))
            finished.set()
            deadline = time.monotonic() + 3
            while window.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertFalse(base.instate(["disabled"]))
            window.destroy()
        finally:
            root.destroy()

    def test_group_controls_scroll_and_clear_only_their_group(self):
        root = tk.Tk()
        try:
            window = StrategyWindow(root, [{"question": "测试"}], "tc", ".")
            window.geometry("900x650")
            root.update()
            window.strategy_group_buttons["基础规则"].invoke()
            root.update()
            canvas = window.strategy_group_canvases["基础规则"]
            window.strategy_checks[0].event_generate("<MouseWheel>", delta=-120)
            root.update()
            self.assertGreater(canvas.yview()[0], 0)
            window._set_group("基础规则", True)
            window._set_group("直接指令", True)
            window._set_group("基础规则", False)
            self.assertTrue(window._selected()[1])
            self.assertTrue(all(s.startswith("I") for s in window._selected()[1]))
            window.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
