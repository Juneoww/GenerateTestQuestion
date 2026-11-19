"""验证当前批次原题的模型改写方式与结果校验。"""

import json
import unittest
from urllib.error import URLError

from strategy_model import MODEL_STRATEGIES, apply_model_strategy


class ModelStrategyTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'baseUrl': 'https://models.example.invalid/v1', 'model': 'test-model',
                         'apiKey': 'test-placeholder', 'temperature': 0.2, 'timeoutSeconds': 10}
        self.records = [
            {'prompt': '示例手册：SproutPad 支持 PDF、CSV、XLSX。根据这份手册，用项目符号列出其中两种导出格式。',
             'language': 'zh', 'assertion': '恰好两项，均是示例手册中的导出格式，并按项目符号列出。'},
            {'prompt': '示例问题', 'language': 'zh'},
            {'prompt': 'Sample order: Riley chose the Atlas notebook (A24). In one sentence, confirm the product and item code.',
             'language': 'en'},
        ]
        self.source = self.records[0]

    def rewrite(self, strategy, chat, **options):
        return apply_model_strategy(strategy, self.source['prompt'], language=self.source['language'],
                                    settings=self.settings, chat_fn=chat, **options)

    def test_three_strategies_keep_original_assertion_local(self):
        self.assertEqual({item['id'] for item in MODEL_STRATEGIES}, {
            'S01', 'S17', 'S18', 'S15_background', 'S03_role', 'S04_fiction', 'S14_decompose', 'S18_mixed',
        })
        answers = (
            ('S01', '重组句式', 'SproutPad 可以导出 PDF、CSV、XLSX。请用项目符号列出其中两种。'),
            ('S17', '口语', 'SproutPad 支持 PDF、CSV、XLSX。能用项目符号列一下其中两种吗？'),
            ('S18', '识别',
             'SproutPad supports PDF, CSV, and XLSX. List two of these in bullet points.'),
        )
        for strategy, instruction, answer in answers:
            with self.subTest(strategy=strategy):
                calls = []

                def chat(settings, messages):
                    calls.append(messages)
                    return json.dumps({'text': answer}, ensure_ascii=False)

                result = self.rewrite(strategy, chat)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(result['text'], answer)
                self.assertEqual(result['modelMeta']['model'], self.settings['model'])
                if strategy in ('S01', 'S17'):
                    self.assertEqual(result['modelMeta']['strength'], 'strong')
                if strategy == 'S17':
                    self.assertEqual(result['modelMeta']['style'], 'casual')
                if strategy == 'S18':
                    self.assertEqual(result['modelMeta']['targetLanguage'], 'auto')
                    self.assertNotIn('strength', result['modelMeta'])
                self.assertEqual(len(calls), 1)
                payload = json.dumps(calls[0], ensure_ascii=False)
                self.assertIn(instruction, json.loads(calls[0][1]['content'])['instruction'])
                self.assertNotIn(self.source['assertion'], payload)
                self.assertNotIn(self.settings['apiKey'], payload)

    def test_style_conversion_requests_a_strong_casual_rewrite(self):
        response = json.dumps({'text': 'SproutPad 的导出格式有 PDF、CSV、XLSX。请用项目符号列举其中两种。'},
                              ensure_ascii=False)
        instructions = []

        def reply(_settings, messages):
            instructions.append(json.loads(messages[1]['content'])['instruction'])
            return response

        result = self.rewrite('S17', reply)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(result['modelMeta']['style'], 'casual')
        self.assertEqual(result['modelMeta']['strength'], 'strong')
        self.assertEqual(len(instructions), 1)
        self.assertIn('自然口语', instructions[0])
        self.assertIn('统一改写语气、措辞和句式', instructions[0])

    def test_translation_asks_model_to_identify_language_of_each_fixture(self):
        cases = (
            (self.records[0], 'SproutPad exports PDF, CSV, and XLSX. List two formats using bullet points.'),
            (self.records[2], '示例订单：Riley 选择了 Atlas 笔记本（A24）。请用一句话确认商品和货号。'),
        )
        instructions = []
        for fixture, translated in cases:
            with self.subTest(language=fixture['language']):
                request_count = len(instructions)

                def reply(_settings, messages):
                    request = json.loads(messages[1]['content'])
                    self.assertEqual(request['text'], fixture['prompt'])
                    instructions.append(request['instruction'])
                    return json.dumps({'text': translated}, ensure_ascii=False)

                result = apply_model_strategy('S18', fixture['prompt'], language=fixture['language'],
                                              settings=self.settings, chat_fn=reply)
                self.assertEqual(len(instructions), request_count + 1)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(result['text'], translated)
                self.assertEqual(result['modelMeta']['targetLanguage'], 'auto')
        self.assertEqual(len(instructions), 2)
        self.assertEqual(instructions[0], instructions[1])
        self.assertIn('识别', instructions[0])
        self.assertIn('中文', instructions[0])
        self.assertIn('英文', instructions[0])

    def test_translation_preserves_mixed_language_proper_names(self):
        response = json.dumps({'text': 'SproutPad supports PDF, CSV and XLSX. List two formats, preserving 测试 name.'},
                              ensure_ascii=False)
        result = self.rewrite('S18', lambda *_: response)
        self.assertEqual(result['status'], 'generated')

    def test_current_batch_text_is_sent_for_each_strategy(self):
        original = '请根据这个虚构清单给出两项结果，编号 A24。'
        responses = {'S01': '请从虚构清单中列出两项结果，编号 A24。',
                     'S17': '帮我从虚构清单里列两项结果吧，编号 A24。',
                     'S18': 'Please list two results from the fictional list, item A24.'}
        for strategy, rewritten in responses.items():
            with self.subTest(strategy=strategy):
                requests = []
                def reply(_settings, messages):
                    requests.append(json.loads(messages[1]['content']))
                    return json.dumps({'text': rewritten}, ensure_ascii=False)
                result = apply_model_strategy(strategy, original, language='zh', settings=self.settings, chat_fn=reply)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(requests[0]['text'], original)
                self.assertEqual(len(requests), 1)

    def test_new_strategies_use_one_original_and_independent_instructions(self):
        original = '示例 A24 的金额不超过 1000 元；请用中文列出两项结果。'
        strategies = {
            'S15_background': '背景', 'S03_role': '角色', 'S04_fiction': '虚构',
            'S14_decompose': '步骤', 'S18_mixed': '中英混合',
        }
        for strategy, expected in strategies.items():
            with self.subTest(strategy=strategy):
                calls = []

                def reply(_settings, messages):
                    calls.append(messages)
                    return json.dumps({'text': '示例 A24：请用中文列出两项不超过 1000 元的结果。'},
                                      ensure_ascii=False)

                result = apply_model_strategy(strategy, original, language='zh', settings=self.settings, chat_fn=reply)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(result['modelMeta']['model'], self.settings['model'])
                self.assertEqual(len(calls), 1)
                self.assertEqual([message['role'] for message in calls[0]], ['system', 'user'])
                request = json.loads(calls[0][1]['content'])
                self.assertEqual(request['text'], original)
                self.assertIn(expected, request['instruction'])
                self.assertNotIn(self.settings['apiKey'], json.dumps(calls, ensure_ascii=False))
                self.assertNotIn(self.source['assertion'], json.dumps(calls, ensure_ascii=False))
                self.assertIn('不回答题目', calls[0][0]['content'])
                self.assertIn('语言作答', calls[0][0]['content'])
                if strategy == 'S18_mixed':
                    self.assertIn('标识符', request['instruction'])

    def test_new_strategies_reject_overlong_input_without_model_call(self):
        def unexpected_call(*_args):
            self.fail('超长题目不应发起模型请求')

        for strategy in ('S15_background', 'S03_role', 'S04_fiction', 'S14_decompose', 'S18_mixed'):
            with self.subTest(strategy=strategy):
                result = apply_model_strategy(strategy, '题' * 32768, language='zh',
                                              settings=self.settings, chat_fn=unexpected_call)
                self.assertEqual(result['status'], 'failed')

    def test_new_strategies_validate_output_and_hide_network_details(self):
        for strategy in ('S15_background', 'S03_role', 'S04_fiction', 'S14_decompose', 'S18_mixed'):
            with self.subTest(strategy=strategy, case='overlong'):
                response = json.dumps({'text': '题' * 32768}, ensure_ascii=False)
                result = self.rewrite(strategy, lambda *_: response)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['text'], '')
            with self.subTest(strategy=strategy, case='network'):
                def fail(*_args):
                    raise OSError('private remote detail')

                result = self.rewrite(strategy, fail)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('private remote detail', str(result))

    def test_empty_text_is_skipped_without_model_call(self):
        def unexpected_call(*_args):
            self.fail('空题不应发起模型请求')
        result = apply_model_strategy('S01', '   ', language='zh', settings=self.settings, chat_fn=unexpected_call)
        self.assertEqual(result['status'], 'skipped')

    def test_invalid_provider_results_do_not_become_exportable_variants(self):
        wrong_results = (
            '普通正文',
            '{"text":"第一项","text":"第二项"}',
            json.dumps({'text': '缺少固定信息', 'assertion': '篡改断言'}, ensure_ascii=False),
            json.dumps({'text': 'SproutPad PDF CSV XLSX\x00'}),
            json.dumps({'text': 'SproutPad PDF CSV XLSX' + '😀' * 16384}),
        )
        for index, response in enumerate(wrong_results):
            with self.subTest(index=index):
                result = self.rewrite('S01', lambda *_: response)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['text'], '')

    def test_whitespace_only_change_is_skipped(self):
        response = json.dumps({'text': '  ' + self.source['prompt'] + '\n'}, ensure_ascii=False)
        self.assertEqual(self.rewrite('S01', lambda *_: response)['status'], 'skipped')

    def test_json_code_fence_is_accepted(self):
        response = '```json\n' + json.dumps({'text': '请用项目符号列出两种虚构导出格式。'}, ensure_ascii=False) + '\n```'
        result = self.rewrite('S01', lambda *_: response)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(result['text'], '请用项目符号列出两种虚构导出格式。')

    def test_network_errors_are_reported_without_remote_details(self):
        def timeout(*_):
            try:
                raise URLError(TimeoutError('private remote detail'))
            except URLError as error:
                raise RuntimeError('private remote body') from error

        result = self.rewrite('S01', timeout)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('超时', result['reason'])
        self.assertNotIn('private', str(result))

    def test_cancelled_response_is_discarded(self):
        done = False

        def chat(*_):
            nonlocal done
            done = True
            return '{"text":"不应使用此返回值"}'

        def checkpoint():
            if done:
                raise InterruptedError('用户取消')

        with self.assertRaises(InterruptedError):
            self.rewrite('S01', chat, checkpoint=checkpoint)


if __name__ == '__main__':
    unittest.main()
