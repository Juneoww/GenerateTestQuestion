"""功能：验证二期策略在三类原题入口生成可追溯结果。
实现：使用真实策略引擎与结果构造流程，检查状态和原始记录。
输入：TC260、OWASP LLM 和 Agentic 的代表性原题。
输出：各策略生成状态、原题关联和原始数据不变性的断言。
"""
import unittest

from strategy_engine import STRATEGIES, apply_strategy
from strategy_ui import make_variant_rows


class PhaseTwoIntegrationTests(unittest.TestCase):
    def test_seven_strategies_work_on_all_three_original_types(self):
        strategies = ['R17_repeat', 'R17_swap', 'R17_delete', 'R19_zwsp',
                      'R20_fullwidth', 'R21_chunks', 'R24_partial_base64']
        examples = [
            ('tc', {'riskId': 'R1', 'question': '测A试B原C题', 'questionType': 'text'}),
            ('llm', {'riskId': 'LLM01', 'prompt': '测A试B原C题', 'assertion': '保留断言'}),
            ('agentic', {'riskId': 'ASI05', 'prompt': '测A试B原C题', 'assertion': '保留断言'}),
        ]
        registered = {item['id']: item for item in STRATEGIES}
        self.assertNotIn('R13_caesar3', registered)
        for strategy in strategies:
            self.assertEqual(registered[strategy]['group'], '基础规则')
        for framework, original in examples:
            with self.subTest(framework=framework):
                rows = make_variant_rows([original], [0], strategies, framework, apply_strategy)
                self.assertEqual(len(rows), 8)
                self.assertEqual(rows[0]['status'], 'basic')
                self.assertEqual([row['status'] for row in rows[1:]], ['generated'] * 7)
                self.assertTrue(all(row['originalText'] == '测A试B原C题' for row in rows))
                self.assertTrue(all(row['sourceRecord'] == original for row in rows))
                self.assertTrue(all(row['sourceRecord'] is not original for row in rows))
                self.assertTrue(all(row['reviewStatus'] == 'needs_review' for row in rows[1:]))


if __name__ == '__main__':
    unittest.main()
