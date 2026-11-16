"""功能：在原题上悬浮时显示可滚动的完整原文。

实现：延迟显示轻量窗口，鼠标移入窗口时保持显示，移出或滚动原题列表时关闭。
输入：原题控件及完整文本；输出：只读文本预览窗口，不修改原题。
"""
import tkinter as tk
from tkinter import font, ttk


class SourceTooltip:
    """共享一个预览窗口，避免为每道题常驻独立窗口。"""

    def __init__(self, parent):
        self.parent = parent
        self.popup = None
        self.text_widget = None
        self._show_job = None
        self._hide_job = None
        self._persistent = False
        parent.bind("<Destroy>", self._on_destroy, add="+")

    def attach(self, widget, text):
        widget.bind("<Enter>", lambda _event: self._schedule_show(widget, text), add="+")
        widget.bind("<Leave>", lambda _event: self._schedule_hide(), add="+")

    def _cancel(self, name):
        job = getattr(self, name)
        if job is not None:
            try:
                self.parent.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, name, None)

    def _schedule_show(self, widget, text):
        if self._persistent:
            return
        self.hide()
        self._show_job = self.parent.after(400, lambda: self._show(widget, text))

    def _schedule_hide(self):
        if self._persistent:
            return
        self._cancel("_show_job")
        self._cancel("_hide_job")
        self._hide_job = self.parent.after(300, self.hide)

    def _show(self, widget, text):
        self._show_job = None
        popup = tk.Toplevel(self.parent)
        self.popup = popup
        popup.overrideredirect(True)
        popup.transient(self.parent)
        frame = ttk.Frame(popup, padding=4, relief="solid")
        frame.pack(fill="both", expand=True)
        title = ttk.Label(frame, text="原题全文")
        title.pack(anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.text_widget = tk.Text(frame, width=72, height=12, wrap="word", yscrollcommand=scroll.set)
        self.text_widget.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.text_widget.yview)
        self.text_widget.insert("1.0", text)
        self.text_widget.configure(state="disabled")
        popup.update_idletasks()
        display_lines = (self.text_widget.count("1.0", "end", "displaylines") or (1,))[0]
        line_height = font.Font(font=self.text_widget.cget("font")).metrics("linespace")
        maximum_lines = max(2, (popup.winfo_screenheight() - 150) // line_height)
        self.text_widget.configure(height=min(max(2, display_lines + 1), maximum_lines))
        if display_lines + 1 > maximum_lines:
            title.configure(text="原题全文（内容较长，请移入并滚动查看；也可点击查看全文）")
        for child in (popup, frame, title, self.text_widget, scroll):
            child.bind("<Enter>", lambda _event: self._cancel("_hide_job"), add="+")
            child.bind("<Leave>", lambda _event: self._schedule_hide(), add="+")
        popup.update_idletasks()
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        screen_w, screen_h = popup.winfo_screenwidth(), popup.winfo_screenheight()
        width, height = min(width, screen_w), min(height, screen_h)
        x = min(max(0, widget.winfo_rootx()), max(0, screen_w - width))
        y = widget.winfo_rooty() + widget.winfo_height()
        if y + height > screen_h:
            y = max(0, widget.winfo_rooty() - height)
        popup.geometry(f"{width}x{height}+{x}+{y}")

    def show_persistent(self, text):
        """打开可手动关闭的全文窗口，便于滚动、选择和复制长原题。"""
        self.hide()
        self._persistent = True
        popup = tk.Toplevel(self.parent)
        self.popup = popup
        popup.title("原题全文")
        popup.transient(self.parent)
        popup.geometry("760x520")
        popup.minsize(400, 250)
        popup.protocol("WM_DELETE_WINDOW", self.hide)
        frame = ttk.Frame(popup, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="原题全文（可滚动、选择并复制）").pack(anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.text_widget = tk.Text(frame, wrap="word", yscrollcommand=scroll.set)
        self.text_widget.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.text_widget.yview)
        self.text_widget.insert("1.0", text)
        self.text_widget.configure(state="disabled")

    def hide(self):
        self._cancel("_show_job")
        self._cancel("_hide_job")
        self._persistent = False
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
            self.text_widget = None

    def hide_hover(self):
        """列表滚动只隐藏悬浮提示，不关闭用户主动打开的全文窗口。"""
        if not self._persistent:
            self.hide()

    def _on_destroy(self, event):
        if event.widget is self.parent:
            self.hide()
