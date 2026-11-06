"""验证图像生成接口的保存、失败分类与重试，不访问真实服务。"""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from PIL import Image
import image_generator


def png_bytes():
    stream = io.BytesIO()
    Image.new('RGB', (2, 2), (12, 22, 32)).save(stream, format='PNG')
    return stream.getvalue()


class Response:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.stream.close()
    def read(self, *args):
        return self.stream.read(*args)


class ImageGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.settings = {'imageBaseUrl': 'https://example.com/v1', 'imageModel': 'test-model',
                         'imageApiKey': 'secret-key', 'imageTimeoutSeconds': 5, 'imageRetries': 2}

    def payload(self, item):
        return Response(json.dumps({'data': [item]}).encode())

    def call(self):
        return image_generator.generate_image('prompt', self.settings, self.path, 1)

    @patch('image_generator._open')
    def test_base64_saves_valid_image(self, request):
        request.return_value = self.payload({'b64_json': base64.b64encode(png_bytes()).decode()})
        result = self.call()
        self.assertEqual(result['imageStatus'], 'success')
        self.assertEqual(result['imagePath'], 'images/0001.png')
        self.assertEqual((self.path / result['imagePath']).read_bytes(), png_bytes())
        self.assertEqual(json.loads(request.call_args.args[0].data),
                         {'model': 'test-model', 'prompt': 'prompt'})

    @patch('image_generator._open')
    def test_url_download_omits_authorization(self, request):
        request.side_effect = [self.payload({'url': 'https://cdn.example.com/image'}), Response(png_bytes())]
        result = self.call()
        self.assertEqual(result['imageStatus'], 'success')
        self.assertIsNone(request.call_args_list[1].args[0].get_header('Authorization'))

    @patch('image_generator._open')
    def test_download_retry_never_repeats_generation(self, request):
        request.side_effect = [self.payload({'url': 'https://cdn.example.com/image'}),
                               URLError('timeout'), Response(png_bytes())]
        with patch('image_generator.time.sleep'):
            result = self.call()
        self.assertEqual(result['imageStatus'], 'success')
        self.assertEqual(request.call_count, 3)
        self.assertIsNotNone(request.call_args_list[0].args[0].data)
        self.assertIsNone(request.call_args_list[1].args[0].data)
        self.assertIsNone(request.call_args_list[2].args[0].data)

    @patch('image_generator._open')
    def test_download_unauthorized_does_not_stop_batch(self, request):
        request.side_effect = [self.payload({'url': 'https://cdn.example.com/image'}),
                               HTTPError('https://cdn.example.com', 401, '', {}, io.BytesIO(b''))]
        result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertFalse(result['globalError'])
        self.assertEqual(request.call_count, 2)

    @patch('image_generator._open')
    def test_corrupt_image_never_success(self, request):
        request.return_value = self.payload({'b64_json': base64.b64encode(b'not an image').decode()})
        result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertFalse(result['imagePath'])
        self.assertFalse(list(self.path.rglob('*.png')))

    @patch('image_generator._open')
    def test_rate_limit_retries(self, request):
        err = HTTPError('https://example.com', 429, '', {}, io.BytesIO(b''))
        request.side_effect = [err, self.payload({'b64_json': base64.b64encode(png_bytes()).decode()})]
        with patch('image_generator.time.sleep'):
            result = self.call()
        self.assertEqual(result['imageStatus'], 'success')
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['imageError'], '')

    @patch('image_generator._open')
    def test_auth_failure_is_global_and_redacted(self, request):
        request.side_effect = HTTPError('https://example.com', 401, '', {}, io.BytesIO(b'secret-key'))
        result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertTrue(result['globalError'])
        self.assertNotIn('secret-key', str(result))
        self.assertEqual(request.call_count, 1)

    @patch('image_generator._open')
    def test_policy_rejection_is_not_retried(self, request):
        body = json.dumps({'error': {'code': 'content_policy_violation'}}).encode()
        request.side_effect = HTTPError('https://example.com', 400, '', {}, io.BytesIO(body))
        result = self.call()
        self.assertEqual(result['imageStatus'], 'rejected')
        self.assertEqual(request.call_count, 1)

    @patch('image_generator._open')
    def test_zhipu_1301_is_reported_as_rejected(self, request):
        self.settings['imageBaseUrl'] = 'https://open.bigmodel.cn/api/paas/v4'
        body = json.dumps({'error': {'code': '1301', 'message': 'secret-key'}}).encode()
        request.side_effect = HTTPError('https://open.bigmodel.cn', 400, '', {}, io.BytesIO(body))
        result = self.call()
        self.assertEqual(result['imageStatus'], 'rejected')
        self.assertIn('1301', result['imageError'])
        self.assertNotIn('secret-key', str(result))
        self.assertEqual(request.call_count, 1)

    @patch('image_generator._open')
    def test_parameter_error_preserves_only_safe_numeric_code(self, request):
        body = json.dumps({'error': {'code': '1210', 'message': 'secret-key'}}).encode()
        request.side_effect = HTTPError('https://example.com', 400, '', {}, io.BytesIO(body))
        result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertIn('1210', result['imageError'])
        self.assertNotIn('secret-key', str(result))

    @patch('image_generator._open')
    def test_untrusted_error_code_is_not_exposed(self, request):
        body = json.dumps({'error': {'code': 'secret-key', 'message': 'secret-key'}}).encode()
        request.side_effect = HTTPError('https://example.com', 400, '', {}, io.BytesIO(body))
        result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertNotIn('secret-key', str(result))

    @patch('image_generator._open')
    def test_network_failure_bounded(self, request):
        request.side_effect = URLError('secret-key')
        with patch('image_generator.time.sleep'):
            result = self.call()
        self.assertEqual(result['imageStatus'], 'failed')
        self.assertEqual(result['attempts'], 3)
        self.assertNotIn('secret-key', str(result))


if __name__ == '__main__':
    unittest.main()
