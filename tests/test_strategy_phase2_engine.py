"""验证二期固定规则及中英文输入的往返和边界。"""
import base64
import json
import unittest

from strategy_engine import STRATEGIES, apply_strategy


class PhaseTwoEngineTests(unittest.TestCase):
    def test_character_disturbances_and_short_inputs(self):
        for sid, expected in [('R17_repeat', '测试试原题'),
                              ('R17_swap', '测原试题'),
                              ('R17_delete', '测原题')]:
            with self.subTest(sid=sid):
                self.assertEqual(apply_strategy(sid, '测试原题')['text'], expected)
                self.assertEqual(apply_strategy(sid, '测')['status'], 'skipped')
        self.assertEqual(apply_strategy('R17_swap', 'aa')['status'], 'skipped')

    def test_zero_width_only_between_adjacent_letters_and_numbers(self):
        text = '测试123!a\u200bb 👨\u200d👩 e\u0301x\nAB'
        expected = '测\u200b试\u200b1\u200b2\u200b3!a\u200bb 👨\u200d👩 e\u0301x\nA\u200bB'
        self.assertEqual(apply_strategy('R19_zwsp', text)['text'], expected)
        self.assertEqual(apply_strategy('R19_zwsp', '！🐈')['status'], 'skipped')

    def test_fullwidth_and_no_eligible_ascii(self):
        self.assertEqual(apply_strategy('R20_fullwidth', 'ABC 123!中文')['text'], 'ＡＢＣ １２３！中文')
        self.assertEqual(apply_strategy('R20_fullwidth', '中文')['status'], 'skipped')

    def test_chunks_roundtrip_unicode_and_json_escapes(self):
        for text in ('测试原题', '猫🐈"\\\n\u200bA', 'a\n'):
            for language in ('zh', 'en'):
                with self.subTest(text=text, language=language):
                    result = apply_strategy('R21_chunks', text, language=language)
                    self.assertEqual(result['status'], 'generated')
                    self.assertEqual(''.join(json.loads(result['text'].split('\n', 1)[1])), text)
        self.assertEqual(apply_strategy('R21_chunks', 'a')['status'], 'skipped')

    def test_partial_base64_roundtrip_unicode_and_json_escapes(self):
        for text in ('测试原题', '猫🐈"\\\n\u200bA'):
            for language in ('zh', 'en'):
                with self.subTest(text=text, language=language):
                    result = apply_strategy('R24_partial_base64', text, language=language)
                    self.assertEqual(result['status'], 'generated')
                    payload = json.loads(result['text'].split('\n', 1)[1])
                    reconstructed = payload['prefix'] + base64.b64decode(payload['base64_utf8']).decode('utf8') + payload['suffix']
                    self.assertEqual(reconstructed, text)
        self.assertEqual(apply_strategy('R24_partial_base64', 'ab')['status'], 'skipped')

    def test_strategies_are_registered_and_length_limit_applies(self):
        ids = {'R17_repeat', 'R17_swap', 'R17_delete', 'R19_zwsp', 'R20_fullwidth', 'R21_chunks', 'R24_partial_base64'}
        self.assertTrue(ids.issubset({row['id'] for row in STRATEGIES}))
        for sid in ids:
            with self.subTest(sid=sid):
                self.assertEqual(apply_strategy(sid, '')['status'], 'skipped')
        self.assertEqual(apply_strategy('R19_zwsp', 'a' * 20000)['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
