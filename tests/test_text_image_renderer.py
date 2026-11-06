"""验证本地文字图片生成的内容、尺寸、背景和失败边界。"""
import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

from PIL import Image, ImageChops, ImageDraw
import text_image_renderer as renderer


class TextImageRendererTests(unittest.TestCase):
    def test_white_image_saves_exact_dimensions_and_text_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image.png'
            text = '请描述安全风险。\nHello world!'
            result = renderer.render_text_image(text, path, (1024, 768))
            self.assertEqual(result['textSha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())
            self.assertGreaterEqual(result['fontSize'], 20)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1024, 768))
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                self.assertIsNotNone(ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox())

    def test_windows_and_legacy_newlines_render_as_lines_without_changing_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image.png'
            text = '第一行\r\n第二行\r第三行'
            painted = []
            original_draw_text = ImageDraw.ImageDraw.text

            def record_text(draw, xy, content, *args, **kwargs):
                painted.append(content)
                return original_draw_text(draw, xy, content, *args, **kwargs)

            with mock.patch.object(ImageDraw.ImageDraw, 'text', autospec=True, side_effect=record_text):
                result = renderer.render_text_image(text, path, (1024, 768))

            self.assertEqual(painted, ['第一行', '第二行', '第三行'])
            self.assertEqual(result['textSha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())

    def test_background_is_used_and_aspect_ratio_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            bg = Path(folder) / 'background.png'
            Image.new('RGB', (100, 100), (220, 20, 30)).save(bg)
            output = Path(folder) / 'out.png'
            renderer.validate_background(bg)
            renderer.render_text_image('测试文本', output, (1024, 768), bg)
            with Image.open(output) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(image.getpixel((200, 20)), (220, 20, 30))

    def test_long_text_is_not_silently_cropped(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'out.png'
            with self.assertRaisesRegex(ValueError, '完整|显示|容纳'):
                renderer.render_text_image('测' * 20000, output, (512, 512))
            self.assertFalse(output.exists())

    def test_missing_font_and_corrupt_background_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.png'
            path.write_bytes(b'broken')
            with self.assertRaises(ValueError):
                renderer.validate_background(path)
            with mock.patch.object(renderer, '_font_path', return_value=None):
                with self.assertRaisesRegex(ValueError, '字体'):
                    renderer.render_text_image('测试', Path(folder) / 'out.png', (512, 512))

    def test_managed_snapshot_larger_than_original_import_limit_can_render(self):
        with tempfile.TemporaryDirectory() as folder:
            bg = Path(folder) / 'background.png'
            Image.new('RGB', (20, 20), (90, 120, 150)).save(bg)
            # 合法 PNG 在 IEND 后可有额外字节；稀疏扩展模拟转码后较大的受管快照。
            with bg.open('ab') as f:
                f.truncate(20 * 1024 * 1024 + 1)
            output = Path(folder) / 'out.png'
            renderer.render_text_image('测试图片', output, (512, 512), bg)
            with Image.open(output) as image:
                self.assertEqual(image.size, (512, 512))

    def test_background_over_pixel_limit_is_rejected_before_decode(self):
        def chunk(kind, content):
            checksum = zlib.crc32(kind + content) & 0xffffffff
            return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', checksum)

        with tempfile.TemporaryDirectory() as folder:
            bg = Path(folder) / 'too_many_pixels.png'
            ihdr = struct.pack('>IIBBBBB', 7000, 7000, 8, 2, 0, 0, 0)
            bg.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                           + chunk(b'IDAT', zlib.compress(b'\0')) + chunk(b'IEND', b''))
            with self.assertRaisesRegex(ValueError, '尺寸过大'):
                renderer.validate_background(bg)

    def test_managed_snapshot_over_byte_limit_is_rejected(self):
        with mock.patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=160 * 1024 * 1024 + 1)):
            with self.assertRaisesRegex(ValueError, '文件过大'):
                renderer.validate_background(Path('background.png'))


if __name__ == '__main__':
    unittest.main()
