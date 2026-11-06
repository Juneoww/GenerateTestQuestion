"""验证文字图片配置及背景副本，不访问外部服务。"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app
import storage


class TextImageSettingsTests(unittest.TestCase):
    def test_settings_replace_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage.save_settings({'model': '原模型'}, root)
            before = (root / 'settings.json').read_bytes()
            with patch('storage.os.replace', side_effect=OSError('磁盘错误')):
                with self.assertRaises(OSError):
                    storage.save_settings({'model': '新模型'}, root)
            self.assertEqual((root / 'settings.json').read_bytes(), before)
            self.assertEqual(storage.load_settings(root)['model'], '原模型')
            self.assertEqual(list(root.glob('*.tmp')), [])

    def test_settings_write_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage.save_settings({'model': '原模型'}, root)
            before = (root / 'settings.json').read_bytes()
            original_factory = tempfile.NamedTemporaryFile

            class FailingWriter:
                def __init__(self, **kwargs):
                    self.file = original_factory(**kwargs)
                    self.name = self.file.name

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.file.close()

                def write(self, value):
                    self.file.write(value[:5])
                    raise OSError('磁盘写入失败')

            with patch('storage.tempfile.NamedTemporaryFile', side_effect=lambda **kwargs: FailingWriter(**kwargs)):
                with self.assertRaises(OSError):
                    storage.save_settings({'model': '新模型'}, root)
            self.assertEqual((root / 'settings.json').read_bytes(), before)
            self.assertEqual(list(root.glob('*.tmp')), [])

    def test_save_failure_shows_error_and_keeps_pending_background(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, 'DATA_DIR', Path(temp)):
            with patch.object(storage, 'load_sources', return_value=[]), patch.object(storage, 'load_catalog', return_value=[]):
                window = app.DesktopApplication()
            try:
                window.attributes('-alpha', 0)
                window._pending_text_background = ''
                with patch.object(storage, 'save_settings', side_effect=OSError('磁盘错误')), patch.object(app.messagebox, 'showerror') as showerror:
                    window._save_settings()
                self.assertEqual(window._pending_text_background, '')
                self.assertTrue(showerror.called)
            finally:
                window.destroy()

    def test_old_settings_default_and_managed_background(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = storage.load_settings(root)
            self.assertEqual(settings['textImageSize'], '1280x1280')
            self.assertEqual(settings['textImageBackgroundPath'], '')
            source = root / 'source.jpg'
            Image.new('RGB', (50, 60), 'blue').save(source)
            info = storage.import_text_image_background(source, root)
            saved = root / info['textImageBackgroundPath']
            self.assertTrue(saved.is_file())
            self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), info['textImageBackgroundSha256'])
            source.unlink()
            self.assertTrue(saved.exists())
            self.assertEqual(storage.save_settings(info, root)['textImageBackgroundPath'], info['textImageBackgroundPath'])

    def test_rejects_invalid_background(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'bad.png'
            source.write_bytes(b'not image')
            with self.assertRaises(ValueError):
                storage.import_text_image_background(source, Path(temp))

    def test_tabs_preset_and_text_option(self):
        with patch.object(storage, 'load_settings', return_value=storage.SETTINGS_DEFAULTS.copy()):
            window = app.DesktopApplication()
        try:
            window.attributes('-alpha', 0)
            tabs = window.settings_notebook.tabs()
            self.assertEqual(window.settings_notebook.tab(tabs[3], 'text'), '文字图片')
            self.assertEqual(str(window.text_image_size_combo.cget('state')), 'readonly')
            self.assertEqual(window.setting_vars['textImageSize'].get(), '1280x1280')
            self.assertFalse(window.text_image_enabled_var.get())
        finally:
            window.destroy()

    def test_save_and_clear_background_and_keep_option_off_in_image_mode(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, 'DATA_DIR', Path(temp)):
            source = Path(temp) / 'sample.png'
            Image.new('RGB', (30, 40), 'blue').save(source)
            with patch.object(storage, 'load_sources', return_value=[]), patch.object(storage, 'load_catalog', return_value=[]):
                window = app.DesktopApplication()
            try:
                window.attributes('-alpha', 0)
                window._pending_text_background = str(source)
                window.setting_vars['textImageSize'].set('1920x1080')
                window._save_settings()
                saved = storage.load_settings()
                self.assertEqual(saved['textImageSize'], '1920x1080')
                self.assertTrue((Path(temp) / saved['textImageBackgroundPath']).is_file())
                window._clear_text_background()
                window._save_settings()
                self.assertEqual(storage.load_settings()['textImageBackgroundPath'], '')
                window.question_type_var.set('image')
                window._update_selection_summary()
                self.assertIn('disabled', window.text_image_check.state())
            finally:
                window.destroy()


if __name__ == '__main__':
    unittest.main()
