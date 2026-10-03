import unittest
from calc import add, calculate_average

class TestCalc(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(1, 2), 3)

    def test_average_normal(self):
        self.assertEqual(calculate_average([1.0, 2.0, 3.0]), 2.0)

    def test_average_single(self):
        self.assertEqual(calculate_average([5.0]), 5.0)

    def test_average_empty(self):
        # 空列表时应当返回 0.0
        self.assertEqual(calculate_average([]), 0.0)

if __name__ == "__main__":
    unittest.main()
