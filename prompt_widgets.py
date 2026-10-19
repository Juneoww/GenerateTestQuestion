"""功能：统一正式 LLM／Agentic 结果表的六列表头与尺寸。
实现：仅配置传入 Treeview，不持有页面状态或调用生成服务。
输入：结果表和可选紧凑布局；输出：配置后的控件，无文件副作用。
依赖：现有六字段契约和 Tkinter Treeview 接口。
"""
from owasp_prompt_generator import PROMPT_RECORD_KEYS


def configure_prompt_columns(tree, *, compact: bool = False) -> None:
    """框架共用固定六列，Agentic 的空会话列缩窄以便阅读 prompt。"""
    titles = ("风险编号", "风险名称", "userA", "userB", "prompt", "断言")
    widths = (90, 150, 80, 80, 380, 320) if compact else (100, 150, 260, 260, 320, 220)
    for key, title, width in zip(PROMPT_RECORD_KEYS, titles, widths):
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=min(100, width), anchor="w", stretch=True)
