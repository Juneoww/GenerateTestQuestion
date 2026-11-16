"""验证单条原题的本地策略变换及边界。"""
import base64
import codecs
import html
import json
import unittest
from urllib.parse import unquote_to_bytes

from strategy_engine import STRATEGIES, apply_strategy, decode_emoji


class StrategyEngineTests(unittest.TestCase):
    def test_catalog_ids_are_unique(self):
        ids = [row['id'] for row in STRATEGIES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('R09', ids)
        self.assertIn('I09', ids)

    def test_emoji_roundtrip_and_known_promptfoo_byte_mapping(self):
        source = '猫🐈\nA'
        result = apply_strategy('R09', source)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(decode_emoji(result['text']), source)
        self.assertEqual(apply_strategy('R09', 'A')['text'], '😊' + chr(0xE0131))

    def test_standard_encoding_preserves_utf8(self):
        result = apply_strategy('R01', '你好')
        self.assertIn(base64.b64encode('你好'.encode()).decode(), result['text'])

    def test_unmatched_or_unsafe_input_is_skipped(self):
        self.assertEqual(apply_strategy('R02', '中文')['status'], 'skipped')
        self.assertEqual(apply_strategy('R07', '中文')['status'], 'skipped')
        self.assertEqual(apply_strategy('R03', 'https://example.com')['status'], 'generated')
        self.assertEqual(apply_strategy('I09', '普通题目')['status'], 'generated')

    def test_instruction_wrap_and_json_encoding(self):
        text = 'Test "quoted"\n你好'
        self.assertIn(text, apply_strategy('I03', text)['text'])
        self.assertIn('request', apply_strategy('I07_json', text)['text'])

    def test_every_registered_strategy_has_predictable_result(self):
        for spec in STRATEGIES:
            with self.subTest(strategy=spec['id']):
                result = apply_strategy(spec['id'], 'hello world', language='en')
                self.assertIn(result['status'], ('generated', 'skipped'))
                if result['status'] == 'generated':
                    self.assertTrue(result['text'])

    def test_character_changes_apply_to_identifiers_too(self):
        text = 'help <secret> https://example.com'
        for strategy in ('R03', 'R05', 'R08', 'R16_space'):
            with self.subTest(strategy=strategy):
                output = apply_strategy(strategy, text)['text']
                self.assertNotIn('<secret>', output)
                self.assertNotIn('https://example.com', output)

    def test_rot13_with_identifier_is_reversible(self):
        result = apply_strategy('R02', 'Help https://example.com')
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(codecs.decode(result['text'].split('\n', 1)[1], 'rot_13'), 'Help https://example.com')

    def test_html_entities_refuse_non_roundtrip_characters(self):
        self.assertEqual(apply_strategy('R12_html', 'hello\x00')['status'], 'skipped')
        result = apply_strategy('R12_html', '猫🐈\n')
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(html.unescape(result['text'].split('\n', 1)[1]), '猫🐈\n')

    def test_json_escape_roundtrips_astral_and_controls(self):
        text = '猫🐈\x00\n'
        result = apply_strategy('R12_unicode', text)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(json.loads('"' + result['text'].split('\n', 1)[1] + '"'), text)

    def test_unchanged_payload_does_not_count_as_transformation(self):
        self.assertEqual(apply_strategy('R10', 'abc')['status'], 'skipped')
        self.assertEqual(apply_strategy('R18', 'aba')['status'], 'skipped')

    def test_reversible_encodings_preserve_utf8_bytes(self):
        text = '猫 🐈\nTest'
        payload = lambda strategy: apply_strategy(strategy, text)['text'].split('\n', 1)[1]
        self.assertEqual(base64.b64decode(payload('R01')), text.encode())
        self.assertEqual(bytes.fromhex(payload('R04')), text.encode())
        self.assertEqual(unquote_to_bytes(payload('R10')), text.encode())
        for strategy, base in (('R11_binary', 2), ('R11_octal', 8), ('R11_decimal', 10)):
            with self.subTest(strategy=strategy):
                self.assertEqual(bytes(int(part, base) for part in payload(strategy).split()), text.encode())
        self.assertEqual(codecs.decode(apply_strategy('R02', 'Hello World')['text'].split('\n', 1)[1], 'rot_13'), 'Hello World')
        self.assertEqual(payload('R18')[::-1], text)

    def test_promptfoo_adapted_transform_examples(self):
        self.assertEqual(apply_strategy('R06', 'Hello World')['text'], 'helloWorld')
        self.assertEqual(apply_strategy('R08', 'Hello World')['text'], 'elloHay orldWay')
        self.assertTrue(apply_strategy('R07', 'Hello World')['text'].endswith(
            '.... . .-.. .-.. --- / .-- --- .-. .-.. -..'))
        self.assertEqual(apply_strategy('R07', 'Hello 中文')['status'], 'skipped')

    def test_lowercase_converts_identifiers_and_words(self):
        self.assertEqual(apply_strategy('R15_lower', 'HELLO WORLD API_KEY')['text'],
                         'hello world api_key')

    def test_snake_case_tools_are_also_transformed(self):
        text = 'please call mock_report, mock_export and write_test_marker'
        for strategy in ('R03', 'R05', 'R08', 'R15_upper', 'R16_space'):
            with self.subTest(strategy=strategy):
                result = apply_strategy(strategy, text)
                self.assertEqual(result['status'], 'generated')
                for identifier in ('mock_report', 'mock_export', 'write_test_marker'):
                    self.assertNotIn(identifier, result['text'])
                self.assertNotEqual(result['text'], text)

    def test_reverse_roundtrips_multi_codepoint_emoji(self):
        for text in ('国旗 🇨🇳', '人物 👨🏿', '家庭 👨\u200d👩\u200d👧', '你好\u0301'):
            with self.subTest(text=text):
                result = apply_strategy('R18', text)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(result['text'].split('\n', 1)[1][::-1], text)

    def test_decode_rejects_invalid_payload(self):
        with self.assertRaises(ValueError):
            decode_emoji('😊a')


if __name__ == '__main__':
    unittest.main()
