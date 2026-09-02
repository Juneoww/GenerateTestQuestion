"""临时验证：不显示窗口，离屏校验生成页多选框新交互（验证后可删除）。"""
import io
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import app as app_module  # noqa: E402

a = app_module.DesktopApplication()
a.withdraw()
a.update()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))


# 基础：目录加载与默认态（小类默认全选，站点默认全不选）
check("目录加载无异常", a.status_text.get() == "项目数据已刷新")
check("站点数=16", len(a.site_vars) == 16)
check("小类数=31", len(a.risk_vars) == 31)
check("大类数=5", len(a.scene_vars) == 5)
check("站点徽章 0/16", a.site_badge.cget("text") == "已选 0/16")
check("小类徽章 31/31", a.risk_badge.cget("text") == "已选 31/31")
check("初始禁用(未选站点)", a.start_button.instate(["disabled"]))

# 站点分组折叠：默认收起，展开后挂载，分组徽章随选择联动
check("站点组默认收起", all(not w["expanded"] for w in a.site_group_widgets.values()))
a._toggle_site_group("zh")
a.update()
check("中文组展开 body=pack", a.site_group_widgets["zh"]["body"].winfo_manager() == "pack")
a._select_sites("zh", True)
a.update()
check("中文组徽章 5/5", a.site_group_widgets["zh"]["count"].cget("text") == "已选 5/5")
check("英文组徽章 0/11", a.site_group_widgets["en"]["count"].cget("text") == "已选 0/11")
a._toggle_site_group("zh")
a.update()
check("中文组再收起", a.site_group_widgets["zh"]["body"].winfo_manager() == "")
a._select_sites(None, False)  # 恢复全不选，供后续用例使用

# 真实事件路径：<Button-1> 绑定触发展开（等价于用户点标题）
a.scene_widgets["A.2"]["arrow"].event_generate("<Button-1>")
a.update()
check("A.2 事件绑定展开", a.scene_widgets["A.2"]["expanded"] is True
      and a.scene_widgets["A.2"]["body"].winfo_manager() == "pack")
a.scene_widgets["A.2"]["arrow"].event_generate("<Button-1>")
a.update()
check("A.2 事件绑定收起", a.scene_widgets["A.2"]["body"].winfo_manager() == "")
a.site_group_widgets["en"]["arrow"].event_generate("<Button-1>")
a.update()
check("英文组事件绑定展开", a.site_group_widgets["en"]["expanded"] is True
      and a.site_group_widgets["en"]["body"].winfo_manager() == "pack")

# 整页滚动：折叠高度 < 展开高度；题目列表与来源表都接了横向滚动条
h_collapsed = a._page_inner.winfo_reqheight()
for code in a.scene_widgets:
    if not a.scene_widgets[code]["expanded"]:
        a._toggle_scene_expand(code)
a.update()
h_expanded = a._page_inner.winfo_reqheight()
for code in a.scene_widgets:  # 恢复收起，不影响后续用例
    if a.scene_widgets[code]["expanded"]:
        a._toggle_scene_expand(code)
a.update()
check("展开后整页更高", h_expanded > h_collapsed)
check("题目表接横向滚动", bool(a.question_tree.cget("xscrollcommand")))
check("题干摘要列宽=1200", a.question_tree.column("digest")["width"] == 1200)
a.current_questions = [{"seq": 1, "riskId": "A1-01", "sceneCode": "A.1", "category": "测试",
                        "language": "zh", "question": "长" * 120,
                        "sourceName": "x", "sourceUrl": "u", "evidenceText": "e"}]
a._populate_question_tree()
stored = a.question_tree.item("1", "values")[2]
check("题干全文入库不截断", stored == "长" * 120)
check("来源表接横向滚动", bool(a.source_tree.cget("xscrollcommand")))
check("日志框接纵向滚动", bool(a.log_text.cget("yscrollcommand")))

# 设置页：产物存放路径输入框
check("设置含产物路径项", "outputDir" in a.setting_vars)
a.setting_vars["outputDir"].set("D:\\题库产物")
check("产物路径被收集", a._collect_settings()["outputDir"] == "D:\\题库产物")
check("产物路径原样解析", str(app_module.pipeline.resolve_output_dir(
    {"outputDir": "D:\\题库产物"})) == "D:\\题库产物")
check("空产物路径回退默认", app_module.pipeline.resolve_output_dir({})
      == app_module.storage.DATA_DIR / "output")

# 三态父框：取消 A1-01 → A.1 变 mixed，计数 30/31
a.risk_vars["A1-01"].set(False)
a._sync_scene("A.1")
check("A.1 计数 7/8", a.scene_widgets["A.1"]["count"].cget("text") == "7/8")
check("A.1 三态 mixed", a.scene_vars["A.1"].get() == "mixed")
check("A.1 按钮=全选本组", a.scene_widgets["A.1"]["mini"].cget("text") == "全选本组")

# 折叠/展开：默认收起，toggle 后 body 挂载，再 toggle 收起
check("A.1 默认收起", a.scene_widgets["A.1"]["expanded"] is False)
check("body 未挂载", a.scene_widgets["A.1"]["body"].winfo_manager() == "")
a._toggle_scene_expand("A.1")
a.update()
check("展开后 body=pack", a.scene_widgets["A.1"]["body"].winfo_manager() == "pack")
check("箭头=▼", a.scene_widgets["A.1"]["arrow"].cget("text") == "▼")
a._toggle_scene_expand("A.1")
a.update()
check("再收起 body 卸载", a.scene_widgets["A.1"]["body"].winfo_manager() == "")
check("箭头=▶", a.scene_widgets["A.1"]["arrow"].cget("text") == "▶")

# 收起状态下整组操作：清空 A.1 → 徽章 0/8、父框 0、全局 23/31、开始禁用
a._set_scene_group("A.1", False)
a.update()
check("A.1 清空后 0/8", a.scene_widgets["A.1"]["count"].cget("text") == "0/8")
check("A.1 父框=0", a.scene_vars["A.1"].get() == "0")
check("全局 23/31", a.risk_badge.cget("text") == "已选 23/31")
check("A.1 仍收起", a.scene_widgets["A.1"]["expanded"] is False)
check("仍禁用(未选站点)", a.start_button.instate(["disabled"]))

# 选站点后：风险为 23 非零，但站点=0 依旧禁用；选 1 个站点 → 启用
a._select_sites("zh", True)
a.update()
check("全选中文后站点 5/16", a.site_badge.cget("text") == "已选 5/16")
check("中文站点全中", all(a.site_language[s] == "zh" for s, v in a.site_vars.items() if v.get()))
check("英文站点未受影响", all(not v.get() for s, v in a.site_vars.items()
                              if a.site_language[s] == "en"))
check("启用", a.start_button.instate(["!disabled"]))
check("提示含就绪", "就绪" in a.go_hint.cget("text"))

# _on_scene_toggle 语义（用 invoke 模拟真实点击：ttk 先翻转变量，再触发 command）
box = a.scene_widgets["A.1"]["box"]  # 此时 A.1 var == "0"
a.risk_vars["A1-01"].set(False)
a._sync_scene("A.1")
box.invoke()
a.update()
check("部分选中(mixed)点击→全选", a.scene_vars["A.1"].get() == "1"
      and sum(v.get() for rid, v in a.risk_vars.items() if rid.startswith("A1-")) == 8)
check("alternate 标志已清除", not box.instate(["alternate"]))
box.invoke()  # 1 → 0：整组清空
a.update()
check("点父框(1→0) 全组清空", a.scene_vars["A.1"].get() == "0"
      and sum(v.get() for rid, v in a.risk_vars.items() if rid.startswith("A1-")) == 0)

# 清空小类 → 禁用并提示"还差小类"
a._clear_all_risks()
a.update()
check("清空后禁用+提示", a.start_button.instate(["disabled"]) and "小类" in a.go_hint.cget("text"))

# 恢复默认全选；刷新目录后选择状态保持
a._select_all_risks()
a.site_vars["PIAO-ZH"].set(True)
a._refresh_selection_catalog()
a.update()
check("刷新后站点勾选保持", a.site_vars["PIAO-ZH"].get() is True)
check("刷新后小类全选恢复", a.risk_badge.cget("text") == "已选 31/31")
check("刷新后默认收起", all(w["expanded"] is False for w in a.scene_widgets.values()))

a.destroy()

failed = [n for n, ok in checks if not ok]
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
sys.exit(1 if failed else 0)
