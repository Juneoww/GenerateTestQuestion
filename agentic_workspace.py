"""功能：为 Agentic 题集保存独立的页面状态。
实现：复用主窗口的 OWASP 页面布局、生成和结果操作。
输入：主窗口；输出：Agentic 页面控件和本批次路径。
依赖：主窗口共享的 OWASP 页面逻辑。
"""


class AgenticWorkspace:
    """共享 OWASP 界面，每个工作区独立保存选择与结果。"""

    def __init__(self, host):
        self.host = host
        self.owasp_records = []
        self.owasp_batch_dir = self.owasp_json = self.owasp_xlsx = ""
        self.owasp_risk_vars = {}
        self._owasp_generate_widgets = []
        host._build_owasp_tab(self)

    def artifact_paths(self):
        return self.owasp_batch_dir, self.owasp_json, self.owasp_xlsx

    def start(self):
        self.host._start_owasp_batch(self)

    def finish(self, done):
        self.host._finish_owasp_batch(done, self)
