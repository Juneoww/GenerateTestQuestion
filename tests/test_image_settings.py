"""验证独立图片模型设置及设置页分组，不调用外部接口。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import storage


class ImageSettingsTests(unittest.TestCase):
    def test_save_feedback_matches_selected_tab_and_saves_both_models(self):
        with patch.object(storage, "load_settings", return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes("-alpha", 0)
            window.setting_vars["model"].set("text-model")
            window.setting_vars["imageModel"].set("image-model")
            tabs = window.settings_notebook.tabs()
            with patch.object(storage, "save_settings", side_effect=lambda values: values) as save:
                for index, expected in ((0, "文字模型：text-model"), (1, "文生图模型：image-model"), (2, "设置已保存")):
                    window.settings_notebook.select(tabs[index])
                    window._save_settings()
                    self.assertIn(expected, window.connection_result.get())
                    self.assertEqual(save.call_args.args[0]["model"], "text-model")
                    self.assertEqual(save.call_args.args[0]["imageModel"], "image-model")
        finally:
            window.destroy()

    def test_image_connectivity_uses_image_configuration(self):
        with patch.object(storage, "load_settings", return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes("-alpha", 0)
            window.setting_vars["imageBaseUrl"].set("https://images.example/v1")
            window.setting_vars["imageModel"].set("image-model")
            window.setting_vars["temperature"].set("invalid")
            with tempfile.TemporaryDirectory() as temp, patch.object(storage, "DATA_DIR", Path(temp)), patch("app.messagebox.askyesno", return_value=True), patch("app.threading.Thread") as thread, patch("image_generator.generate_image", return_value={"imageStatus": "success", "imagePath": "images/0001.png"}) as image_test, patch("question_generator.test_connection") as text_test:
                thread.return_value.start.side_effect = lambda: thread.call_args.kwargs["target"]()
                window._test_connection_async("image")
            image_test.assert_called_once()
            self.assertEqual(image_test.call_args.args[1]["imageBaseUrl"], "https://images.example/v1")
            self.assertEqual(image_test.call_args.args[1]["imageRetries"], 0)
            text_test.assert_not_called()
            event = window.events.get_nowait()
            self.assertEqual(event["modelKind"], "image")
            self.assertTrue(event["ok"])
            self.assertTrue(event["imagePath"].endswith("0001.png"))
        finally:
            window.destroy()

    def test_image_test_requires_confirmation_and_prevents_duplicate_calls(self):
        with patch.object(storage, "load_settings", return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes("-alpha", 0)
            window.setting_vars["imageBaseUrl"].set("https://images.example/v1")
            window.setting_vars["imageModel"].set("image-model")
            with patch("app.messagebox.askyesno", return_value=False), patch("app.threading.Thread") as thread:
                window._test_connection_async("image")
                thread.assert_not_called()
            with patch("app.messagebox.askyesno", return_value=True), patch("app.threading.Thread") as thread:
                window._test_connection_async("image")
                window._test_connection_async("image")
                self.assertEqual(thread.call_count, 1)
        finally:
            window.destroy()
    def test_each_model_tab_has_its_own_connectivity_button(self):
        with patch.object(storage, "load_settings", return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes("-alpha", 0)
            tabs = window.settings_notebook.tabs()
            with patch.object(window, "_test_connection_async") as run:
                for index, kind in ((0, "text"), (1, "image")):
                    frame = window.nametowidget(tabs[index])
                    buttons = [w for w in frame.winfo_children() if w.winfo_class() == "TButton" and w.cget("text") == "测试连通"]
                    self.assertEqual(len(buttons), 1)
                    buttons[0].invoke()
                    run.assert_called_with(kind)
                common = window.nametowidget(tabs[2])
                self.assertFalse(any(w.winfo_class() == "TButton" and w.cget("text") == "测试连通" for w in common.winfo_children()))
        finally:
            window.destroy()
    def test_legacy_defaults_and_independent_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            storage.save_settings({"baseUrl": "https://text/v1", "model": "text"}, path)
            old = storage.load_settings(path)
            self.assertEqual(old["imageBaseUrl"], "")
            self.assertEqual(old["imageTimeoutSeconds"], 120)
            new = storage.save_settings({"imageBaseUrl": "https://image/v1", "imageModel": "img",
                                         "imageApiKey": "key", "imageRetries": "3"}, path)
            self.assertEqual(new["baseUrl"], "https://text/v1")
            self.assertEqual(new["imageRetries"], 3)
            self.assertEqual(storage.load_settings(path)["imageModel"], "img")

    def test_settings_have_three_tabs_and_independent_fields(self):
        with patch.object(storage, "load_settings", return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes("-alpha", 0)
            tabs = window.settings_notebook.tabs()
            self.assertEqual([window.settings_notebook.tab(tab, "text") for tab in tabs],
                             ["文字模型", "文生图模型", "通用设置"])
            window.setting_vars["baseUrl"].set("https://text/v1")
            window.setting_vars["imageBaseUrl"].set("https://image/v1")
            window.settings_notebook.select(tabs[1])
            window.setting_vars["imageModel"].set("image-model")
            window.settings_notebook.select(tabs[2])
            window.setting_vars["crawlDelayMs"].set("250")
            window.settings_notebook.select(tabs[0])
            patch_values = window._collect_settings()
            self.assertNotEqual(patch_values["baseUrl"], patch_values["imageBaseUrl"])
            self.assertEqual(patch_values["imageModel"], "image-model")
            self.assertEqual(patch_values["crawlDelayMs"], 250)
            with patch.object(storage, "save_settings", side_effect=lambda values: values) as save:
                window._save_settings()
            self.assertEqual(save.call_args.args[0], patch_values)
            self.assertEqual(set(save.call_args.args[0]), set(window.setting_vars))
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
