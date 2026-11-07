"""功能：在纯白或本地背景上绘制完整的文字测试题并保存 PNG。
实现：Pillow 实测字体与行宽、自动换行及缩放，校验后通过临时文件原子落盘。
输入：题干、输出路径、画布尺寸、可选背景路径；输出：字号、字体标识、题干摘要。
依赖：Pillow、随包 Noto Sans SC 字体或支持题干字符的系统字体；不调用任何模型服务。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import warnings

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

# 渲染阶段只接收已预检的受管 PNG 批次快照；原始上传文件的 20 MiB 限制由 storage 执行。
MAX_BACKGROUND_SNAPSHOT_BYTES = 160 * 1024 * 1024
MAX_BACKGROUND_PIXELS = 40_000_000


def validate_background(path: Path) -> None:
    """验证受管背景快照能够解码且未超过快照大小及像素限制。"""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BACKGROUND_SNAPSHOT_BYTES:
            raise ValueError('背景图片文件过大')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValueError('不支持的背景图片格式')
                if image.width * image.height > MAX_BACKGROUND_PIXELS:
                    raise ValueError('背景图片尺寸过大')
                image.verify()
            with Image.open(path) as image:
                image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('背景图片不存在、损坏或无法解码') from error


def _font_path() -> Path | None:
    # PyInstaller 单文件将资源解压到 _MEIPASS；源码运行时资源位于项目目录。
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    bundled = root / 'assets' / 'fonts' / 'NotoSansSC-VF.ttf'
    if bundled.is_file():
        return bundled
    fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for name in ('msyh.ttc', 'msyh.ttf', 'simsun.ttc', 'simhei.ttf'):
        path = fonts / name
        if path.is_file():
            return path
    return None


def _load_font(path: Path, size: int):
    font = ImageFont.truetype(str(path), size)
    if path.name == 'NotoSansSC-VF.ttf':
        # 此版本的可变字体默认是 Thin；使用 Regular 保证中文笔画清晰。
        font.set_variation_by_name('Regular')
    return font


def _check_glyphs(font, text: str) -> None:
    """与字体的缺字图形比较，阻止使用缺字方框冒充题干。"""
    missing = font.getmask('\U0010ffff')
    signature = (missing.size, bytes(missing))
    for char in set(text):
        if char in '\n\r\t ':
            continue
        glyph = font.getmask(char)
        if (glyph.size, bytes(glyph)) == signature:
            raise ValueError('字体不支持题干中的部分字符')


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines = []
    # 仅排版时把不同平台的换行转换成统一断行，原题干与哈希保持不变。
    paragraphs = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    for paragraph in paragraphs:
        line = ''
        # 英文单词尽量保持完整，过长单词退回逐字拆分。
        tokens = re.findall(r'[A-Za-z0-9]+(?:[\'\-][A-Za-z0-9]+)*|[^A-Za-z0-9]', paragraph)
        for token in tokens:
            if draw.textlength(line + token, font=font) <= max_width:
                line += token
                continue
            if line:
                lines.append(line)
                line = ''
            for char in token:
                if draw.textlength(line + char, font=font) > max_width:
                    if not line:
                        raise ValueError('文字太宽，无法完整显示')
                    lines.append(line)
                    line = ''
                line += char
        lines.append(line)
    return lines


def render_text_image(question: str, image_path: Path, size: tuple[int, int], background_path: Path | None = None) -> dict:
    """输出一张包含完整题干的图片，无法完整显示时抛出异常。"""
    if not isinstance(question, str) or not question.strip():
        raise ValueError('题干为空')
    if '\t' in question or len(question) > 5000:
        raise ValueError('题干无法完整显示')
    if len(size) != 2 or any(type(x) is not int or x < 512 or x > 4096 for x in size):
        raise ValueError('图片尺寸无效')
    width, height = size
    canvas = Image.new('RGB', (width, height), 'white')
    if background_path is not None:
        validate_background(background_path)
        with Image.open(background_path) as source:
            bg = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGBA'), (width, height), Image.Resampling.LANCZOS)
            white = Image.new('RGBA', bg.size, 'white')
            white.alpha_composite(bg)
            canvas.paste(white.convert('RGB'), ((width - bg.width) // 2, (height - bg.height) // 2))
    path = _font_path()
    if not path:
        raise ValueError('未找到支持中文的字体')
    scale = min(size) / 1280
    margin = max(32, round(96 * scale))
    minimum = max(20, round(28 * scale))
    default = max(minimum, round(48 * scale))
    draw = ImageDraw.Draw(canvas)
    chosen = None
    for font_size in range(default, minimum - 1, -1):
        try:
            font = _load_font(path, font_size)
            _check_glyphs(font, question)
            lines = _wrap(draw, question, font, width - 2 * margin)
        except OSError as error:
            raise ValueError('无法加载文字字体') from error
        ascent, descent = font.getmetrics()
        line_height = max(ascent + descent, round(font_size * 1.3))
        if len(lines) * line_height <= height - 2 * margin:
            chosen = (font, font_size, lines, line_height)
            break
    if not chosen:
        raise ValueError('文字无法在图片中完整显示')
    font, font_size, lines, line_height = chosen
    top = (height - len(lines) * line_height) // 2
    if background_path is not None:
        max_text_width = max((draw.textlength(line, font=font) for line in lines), default=0)
        pad = max(12, font_size // 2)
        x0 = max(margin // 2, (width - max_text_width) / 2 - pad)
        x1 = min(width - margin // 2, (width + max_text_width) / 2 + pad)
        y0 = max(margin // 2, top - pad)
        y1 = min(height - margin // 2, top + len(lines) * line_height + pad)
        overlay = Image.new('RGBA', canvas.size, (255, 255, 255, 0))
        ImageDraw.Draw(overlay).rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 245))
        canvas = Image.alpha_composite(canvas.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        x = (width - draw.textlength(line, font=font)) / 2
        draw.text((x, top + index * line_height), line, font=font, fill=(24, 24, 24))
    output = Path(image_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.text-image-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            canvas.save(handle, format='PNG')
        with Image.open(temporary) as check:
            check.load()
            if check.format != 'PNG' or check.size != size:
                raise ValueError('图片保存校验失败')
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {'fontSize': font_size, 'fontName': path.name,
            'textSha256': hashlib.sha256(question.encode('utf-8')).hexdigest()}
