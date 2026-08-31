"""集成测试：配额拆分与小类轮转分配的纯函数行为（比例边界、余数、求和不变量）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import allocate, split_language_quota


class SplitQuotaTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(split_language_quota(10, 80), (8, 2))
        self.assertEqual(split_language_quota(155, 80), (124, 31))

    def test_edges(self):
        self.assertEqual(split_language_quota(5, 0), (0, 5))
        self.assertEqual(split_language_quota(5, 100), (5, 0))
        self.assertEqual(split_language_quota(0, 50), (0, 0))
        self.assertEqual(split_language_quota(1, 50), (1, 0))
        self.assertEqual(split_language_quota(3, 50), (2, 1))


class AllocateTests(unittest.TestCase):
    def test_remainder_front(self):
        self.assertEqual(allocate(7, ["a", "b", "c"]), [3, 2, 2])
        self.assertEqual(allocate(2, ["a", "b"]), [1, 1])

    def test_sum_invariant(self):
        for total, n in [(155, 31), (1, 3), (7, 5), (0, 4)]:
            values = allocate(total, [f"r{i}" for i in range(n)])
            self.assertEqual(sum(values), total)

    def test_edges(self):
        self.assertEqual(allocate(0, ["a"]), [0])
        self.assertEqual(allocate(5, []), [])


if __name__ == "__main__":
    unittest.main()
