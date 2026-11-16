# Third-party notices

## Promptfoo

`strategy_engine.py` 的 R06、R07、R08、R09 分别参考并移植／适配 Promptfoo 0.125.1 的 `toCamelCase`、`toMorseCode`、`toPigLatin`（含 `pigLatinWord`）与 `toEmojiEncoding`，由 TypeScript 改写为 Python。R06 处理全文中的连续英文词组；R07 对不支持字符跳过，而上游会保留原字符；R08 处理全文中的英文词；R09 使用相同字节映射并新增严格解码校验。项目未包含完整 Promptfoo，也不依赖 Node。其他规则为 Python 标准库或本项目实现。来源：

- https://github.com/promptfoo/promptfoo/blob/0.125.1/src/redteam/strategies/otherEncodings.ts
- https://github.com/promptfoo/promptfoo/blob/0.125.1/LICENSE

MIT License

Copyright (c) Promptfoo 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
