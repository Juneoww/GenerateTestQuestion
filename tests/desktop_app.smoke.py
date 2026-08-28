"""功能:
  验证桌面应用的无窗口启动路径能提供一键生成页面所需的五大类与网站选择摘要。
实现:
  以子进程运行 app.py --smoke-test，解析标准输出 JSON，不创建 Tk 窗口。
输入:
  项目根目录中的 app.py、Node 数据桥和 Excel 工作簿。
输出:
  标准输出测试结果；不修改项目数据。
依赖:
  Python 3.13+、Node.js 和本项目已有 Node 依赖。
用法:
  python tests/desktop_app.smoke.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    result = subprocess.run(
        [sys.executable, "app.py", "--smoke-test"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["desktop_ready"] is True
    assert payload["summary"]["routeCount"] == 124
    assert payload["summary"]["riskCount"] == 31
    assert payload["workspaces"] == ["一键生成", "来源配置", "高级维护"]
    assert len(payload["selection_catalog"]["scenes"]) == 5
    assert payload["source_selection"]["selectedSceneCodes"] == ["A.1", "A.2", "A.3", "A.4", "A.5"]
    assert payload["source_selection"]["selectedSourceIds"] == ["S12"]
    print("PASS desktop app smoke: one-click workspace, five-category selector and local bridge are ready")


if __name__ == "__main__":
    main()
