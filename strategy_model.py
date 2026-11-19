"""对当前批次原题进行同义改写、文体转换和中英翻译。

复用设置页的文本模型。每次调用提交一条原题与对应改写要求，
返回可导出的文本和生成状态。原断言由调用方在本地保留。
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import question_generator
from strategy_export import _literal


_TEMPLATE_VERSION = '5'
MODEL_STRATEGIES = (
    {'id': 'S01', 'name': '同义改写', 'group': '模型改写', 'version': _TEMPLATE_VERSION, 'source': '模型改写'},
    {'id': 'S17', 'name': '文体转换', 'group': '模型改写', 'version': _TEMPLATE_VERSION, 'source': '模型改写'},
    {'id': 'S18', 'name': '中英翻译', 'group': '模型改写', 'version': _TEMPLATE_VERSION, 'source': '模型改写'},
)

_SYSTEM_MESSAGE = (
    '你负责编辑测试题的题面。根据要求改写题面，不回答题目。保留原题的任务、输入材料、事实、数字、标识符、'
    '限制和输出要求。题面明确要求使用某种语言作答时，请保留这项要求。'
    '只输出包含一个字符串字段 text 的 JSON 对象。'
)


def _request_failure(error: Exception) -> str:
    """按异常类型提供提示，避免把响应正文或接口地址写入结果。"""
    cause = error.__cause__ or error
    if isinstance(cause, TimeoutError) or (isinstance(cause, URLError) and isinstance(cause.reason, TimeoutError)):
        return '模型请求超时'
    if isinstance(cause, HTTPError):
        return f'模型接口返回 HTTP {cause.code}'
    return '模型接口调用失败，请检查模型配置或连接'


def apply_model_strategy(strategy_id, text, *, language, settings, checkpoint=None, chat_fn=None) -> dict:
    """请求一条变种并校验响应。取消时由窗口保留上次结果。"""
    def outcome(status, candidate='', reason=''):
        return {'status': status, 'text': candidate, 'reason': reason, 'modelMeta': dict(metadata)}

    model = settings.get('model', '')
    metadata = {'model': model, 'templateVersion': _TEMPLATE_VERSION}
    if checkpoint:
        checkpoint()
    if not isinstance(text, str) or not text.strip():
        return outcome('skipped', reason='原题为空')
    try:
        _literal(text)
    except ValueError as error:
        return outcome('failed', reason=str(error))

    if strategy_id == 'S01':
        metadata['strength'] = 'strong'
        instruction = ('换一种说法并重组句式，可以合并或拆分句子并调整信息顺序，让整段的表达明显不同。'
                       '保留原语言、任务、否定条件和所有输出要求。')
    elif strategy_id == 'S17':
        metadata.update(style='casual', strength='strong')
        instruction = ('使用自然口语表达，统一改写语气、措辞和句式，使文体差异明显。'
                       '保留原语言、任务、否定条件和所有输出要求。')
    elif strategy_id == 'S18':
        # 题目可能中英混合，翻译方向由模型依据原题主体语言判断。
        metadata['targetLanguage'] = 'auto'
        instruction = ('先识别当前题面的主要语言，再翻译整道题。中文题面译成英文，英文题面译成中文。'
                       '识别主要语言时忽略专名、编号和文件格式名，保留原题的任务、否定条件和所有输出要求。')
    else:
        return outcome('failed', reason='未知模型改写策略')

    if not settings.get('baseUrl') or not model:
        return outcome('failed', reason='请先在设置页配置文本模型')
    messages = [
        {'role': 'system', 'content': _SYSTEM_MESSAGE},
        {'role': 'user', 'content': json.dumps({'instruction': instruction, 'text': text}, ensure_ascii=False)},
    ]
    try:
        response = (chat_fn or question_generator.chat_completion)(settings, messages)
    except InterruptedError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        if checkpoint:
            checkpoint()
        return outcome('failed', reason=_request_failure(error))
    if checkpoint:
        checkpoint()

    # 用键值对解析 JSON 对象，避免把两个同名字段当成一个字符串字段。
    try:
        if isinstance(response, str):
            response = response.strip()
            lines = response.splitlines()
            if len(lines) >= 3 and lines[0].strip().lower() in ('```', '```json') and lines[-1].strip() == '```':
                response = '\n'.join(lines[1:-1])
        payload = json.loads(response, object_pairs_hook=tuple)
    except (ValueError, TypeError, RecursionError):
        payload = None
    if (not isinstance(payload, tuple) or len(payload) != 1 or payload[0][0] != 'text'
            or not isinstance(payload[0][1], str)):
        return outcome('failed', reason='模型回复须为只包含 text 字符串的 JSON 对象')

    candidate = payload[0][1]
    if not candidate.strip():
        return outcome('failed', reason='模型返回的变种为空')
    try:
        _literal(candidate)
    except ValueError as error:
        return outcome('failed', reason=str(error))
    candidate = candidate.strip()
    if candidate.split() == text.split():
        return outcome('skipped', reason='模型返回了原题')
    return outcome('generated', candidate)
