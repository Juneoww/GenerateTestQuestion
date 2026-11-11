"""功能: 为新批次调用文生图接口并保存可解码的图片。
实现: 单图请求、有限重试、响应限流、真实解码、临时文件原子落盘。
输入: 提示词、独立图像接口设置、批次目录和稳定序号。
输出: 图片相对路径、结果状态与脱敏错误；不记录凭据或模型响应。
依赖: Python 标准库、Pillow。
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, UnidentifiedImageError

from generation_control import checkpoint, network_call, wait

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 30 * 1024 * 1024
FORMATS = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}
REJECTION_CODES = {'content_policy_violation', 'moderation_blocked', 'safety_violation', 'content_filter'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect disallowed', headers, fp)


def _open(request, timeout):
    # 不跟随重定向，避免接口鉴权头或远程 URL 被转发至未知地址。
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _read_limited(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('响应超出大小限制')
    return data


def _request_bytes(request, timeout, limit):
    with _open(request, timeout) as response:
        return _read_limited(response, limit)


def _safe_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('图片接口或下载地址无效')
    return value


def _download(url, timeout, retries):
    req = urllib.request.Request(_safe_url(url), headers={'User-Agent': 'GenerateTestQuestion/4'})
    for attempt in range(retries + 1):
        try:
            return network_call(_request_bytes, req, timeout, MAX_IMAGE_BYTES)
        except urllib.error.HTTPError as error:
            transient = error.code == 429 or 500 <= error.code < 600
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            transient = True
        if not transient or attempt == retries:
            raise ValueError('图片下载失败') from None
        wait(min(attempt + 1, 2))
    raise ValueError('图片下载失败')


def _image_bytes(item, timeout, retries):
    encoded = item.get('b64_json')
    if isinstance(encoded, str) and encoded:
        if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError('图片超出大小限制')
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('图片编码无效') from None
    url = item.get('url')
    if isinstance(url, str) and url:
        return _download(url, timeout, retries)
    raise ValueError('响应中没有图片数据')


def _save_image(data, batch_dir, seq):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('图片为空或超出大小限制')
    try:
        with Image.open(io.BytesIO(data)) as img:
            image_format = img.format
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('图片格式无效或内容损坏') from None
    if image_format not in FORMATS:
        raise ValueError('不支持此图片格式')
    directory = Path(batch_dir) / 'images'
    directory.mkdir(parents=True, exist_ok=True)
    filename = f'{seq:04d}.{FORMATS[image_format]}'
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.image-', suffix='.tmp', delete=False) as temp:
            temp_name = temp.name
            temp.write(data)
        os.replace(temp_name, directory / filename)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return f'images/{filename}'


def _error_code(error):
    try:
        data = json.loads(error.read(65536).decode('utf-8'))
        if not isinstance(data, dict):
            return ''
        obj = data.get('error', {})
        value = (obj.get('code') or obj.get('type') or '') if isinstance(obj, dict) else ''
        return str(value).lower() if isinstance(value, (str, int)) else ''
    except (ValueError, UnicodeError, OSError):
        return ''


def generate_image(prompt: str, settings: dict, batch_dir: Path, seq: int) -> dict:
    """按约定返回成功、拒绝或失败状态；不会把原始服务响应写入结果。"""
    started = time.monotonic()
    result = {'imageStatus': 'failed', 'imagePath': '', 'imageModel': str(settings.get('imageModel', '')),
              'imageError': '', 'attempts': 0, 'elapsedMs': 0, 'globalError': False}
    try:
        base = _safe_url(str(settings.get('imageBaseUrl', '')).strip().rstrip('/'))
        if not result['imageModel'].strip() or not isinstance(prompt, str) or not prompt.strip() or seq < 1:
            raise ValueError('图像模型配置或提示词无效')
        timeout = max(1, int(settings.get('imageTimeoutSeconds', 60)))
        retries = max(0, min(5, int(settings.get('imageRetries', 2))))
    except (ValueError, TypeError):
        result.update(imageError='图像接口配置无效，请检查地址、模型名和超时设置。', globalError=True)
        return result
    payload = json.dumps({'model': result['imageModel'], 'prompt': prompt}, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'User-Agent': 'GenerateTestQuestion/4'}
    key = str(settings.get('imageApiKey') or '').strip()
    if key:
        headers['Authorization'] = f'Bearer {key}'
    for attempt in range(1, retries + 2):
        result['attempts'] = attempt
        try:
            request = urllib.request.Request(base + '/images/generations', data=payload, headers=headers, method='POST')
            payload_response = json.loads(network_call(_request_bytes, request, timeout, MAX_RESPONSE_BYTES).decode('utf-8'))
            items = payload_response.get('data') if isinstance(payload_response, dict) else None
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                raise ValueError('响应中没有图片数据')
            image_data = _image_bytes(items[0], timeout, retries)
            checkpoint()
            result['imagePath'] = _save_image(image_data, batch_dir, seq)
            result['imageStatus'] = 'success'
            result['imageError'] = ''
            break
        except urllib.error.HTTPError as error:
            code = _error_code(error)
            # 数字业务码含义依服务商定义，避免将其他接口的同名码误判为内容审核。
            is_zhipu_rejection = urllib.parse.urlsplit(base).hostname == 'open.bigmodel.cn' and code == '1301'
            if code in REJECTION_CODES or is_zhipu_rejection:
                suffix = '（业务码 1301）' if is_zhipu_rejection else ''
                result.update(imageStatus='rejected', imageError=f'图片服务因内容策略拒绝生成{suffix}。')
                break
            if error.code in (401, 403):
                result.update(imageError='图片服务鉴权失败，请检查接口配置。', globalError=True)
                break
            if error.code == 429 or 500 <= error.code < 600:
                result['imageError'] = f'图片服务暂时不可用（HTTP {error.code}）。'
                if attempt <= retries:
                    wait(min(attempt, 2))
                    continue
            else:
                # 服务端原始消息和任意文本可能包含敏感信息，仅展示有界数字业务码。
                business = f'，业务码 {code}' if re.fullmatch(r'[0-9]{1,6}', code) else ''
                result['imageError'] = f'图片服务请求失败（HTTP {error.code}{business}）。'
            break
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            result['imageError'] = '图片服务连接失败或超时。'
            if attempt <= retries:
                wait(min(attempt, 2))
                continue
            break
        except (ValueError, TypeError, UnicodeError, OSError, json.JSONDecodeError):
            # 不透传异常内容：服务端可能返回密钥、下载签名或原始图片。
            result['imageError'] = '图片响应无效、文件损坏或保存失败。'
            break
    result['elapsedMs'] = int((time.monotonic() - started) * 1000)
    return result
