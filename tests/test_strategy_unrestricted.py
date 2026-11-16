"""验证原题变种不再受风险、输入面或题型语义限制。"""
import codecs
import unittest

from strategy_engine import apply_strategy
from strategy_ui import make_variant_rows


class UnrestrictedVariantTests(unittest.TestCase):
    def test_original_text_variants_cover_all_record_types(self):
        cases = [
            ('agentic', {'riskId': 'ASI05', 'prompt': '工具返回内容', 'userA': '', 'userB': '', 'extra': {'labels': ['原值']}}),
            ('llm', {'riskId': 'LLM01', 'prompt': '用户B输入', 'userA': '用户A输入', 'userB': '用户B输入'}),
            ('tc', {'riskId': 'R1', 'question': '图片提示词', 'questionType': 'image'}),
        ]
        for framework, source in cases:
            with self.subTest(framework=framework):
                rows = make_variant_rows([source], [0], ['R01', 'I09'], framework, apply_strategy)
                self.assertEqual([row['status'] for row in rows], ['basic', 'generated', 'generated'])
                self.assertEqual(rows[1]['sourceRecord'], source)
                self.assertIsNot(rows[1]['sourceRecord'], source)
                self.assertEqual(rows[1]['reviewStatus'], 'needs_review')
                if 'extra' in source:
                    source['extra']['labels'].append('更新')
                    self.assertEqual(rows[1]['sourceRecord']['extra']['labels'], ['原值'])

    def test_hidden_context_template_accepts_any_nonempty_original(self):
        result = apply_strategy('I09', '介绍退款流程')
        self.assertEqual(result['status'], 'generated')
        self.assertIn('介绍退款流程', result['text'])

    def test_character_rules_can_transform_pure_url(self):
        original = 'https://example.com'
        for strategy in ('R02', 'R03', 'R05', 'R08', 'R15_upper', 'R16_space', 'R18'):
            with self.subTest(strategy=strategy):
                result = apply_strategy(strategy, original)
                self.assertEqual(result['status'], 'generated')
                self.assertNotEqual(result['text'], original)

    def test_rot13_and_reverse_support_original_identifiers(self):
        text = 'Help https://example.com 👨\u200d👩'
        rot = apply_strategy('R02', text)
        reverse = apply_strategy('R18', text)
        self.assertEqual(rot['status'], 'generated')
        self.assertEqual(codecs.decode(rot['text'].split('\n', 1)[1], 'rot_13'), text)
        self.assertEqual(reverse['status'], 'generated')
        self.assertEqual(reverse['text'].split('\n', 1)[1][::-1], text)
