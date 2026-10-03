from typing import List

def add(a: float, b: float) -> float:
    return a + b

def calculate_average(numbers: List[float]) -> float:
    # BUG: 未处理空列表情况，直接除以 len(numbers) 会导致 ZeroDivisionError
    return sum(numbers) / len(numbers)
