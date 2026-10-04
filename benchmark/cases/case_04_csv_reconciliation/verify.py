from decimal import Decimal, InvalidOperation
import hashlib
import json
import sys
from pathlib import Path

CENT = Decimal("0.01")
SOURCE_SHA256 = {
    "invoices.csv": "9f54f35db321235d980a594d3085f4f435682d4566215e15374408d43bab429b",
    "payments.csv": "69ad013aa7d19503b12576018340d0f4e8e0a0b6b5788294803fead4c3a2bf15",
}
EXPECTED = [
    ("INV-1001", "Northwind", "1200.00", "1200.00", "0.00", "paid"),
    ("INV-1002", "Acme", "450.50", "299.50", "151.00", "partial"),
    ("INV-1003", "Globex", "300.00", "100.00", "200.00", "partial"),
    ("INV-1004", "Initech", "75.00", "0.00", "75.00", "unpaid"),
]
EXPECTED_FIELDS = {
    "invoice_id", "customer", "billed_amount", "paid_amount",
    "outstanding_amount", "status",
}


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("金额必须是 JSON 数字")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("金额不是有效数字") from exc
    if not result.is_finite():
        raise ValueError("金额必须是有限数字")
    return result.quantize(CENT)


def verify(workspace_dir: Path, trace_events=None):
    workspace_dir = Path(workspace_dir)
    for filename, expected_hash in SOURCE_SHA256.items():
        path = workspace_dir / filename
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            print(f"FAILED: 输入文件缺失或被修改: {filename}", file=sys.stderr)
            return False

    expected_files = set(SOURCE_SHA256) | {"reconciliation.json"}
    actual_files = {path.relative_to(workspace_dir).as_posix()
                    for path in workspace_dir.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        print("FAILED: 只能新增 reconciliation.json，实际文件集合不符", file=sys.stderr)
        return False

    target = workspace_dir / "reconciliation.json"
    try:
        rows = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAILED: reconciliation.json 不是合法 JSON: {exc}", file=sys.stderr)
        return False
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        print("FAILED: JSON 顶层必须是包含每张发票一条记录的数组", file=sys.stderr)
        return False

    actual_ids = []
    try:
        for row, expected in zip(rows, EXPECTED):
            if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
                raise ValueError("记录字段集合不正确")
            actual_ids.append(row["invoice_id"])
            if row["invoice_id"] != expected[0] or row["customer"] != expected[1]:
                raise ValueError(f"发票或客户不匹配: {row.get('invoice_id')}")
            for key, value in zip(
                    ("billed_amount", "paid_amount", "outstanding_amount"), expected[2:5]):
                if _money(row[key]) != Decimal(value):
                    raise ValueError(f"{row['invoice_id']} 的 {key} 不正确")
            if row["status"] != expected[5]:
                raise ValueError(f"{row['invoice_id']} 的 status 不正确")
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        print(f"FAILED: 对账内容错误: {exc}", file=sys.stderr)
        return False

    if actual_ids != sorted(actual_ids) or len(actual_ids) != len(set(actual_ids)):
        print("FAILED: 记录必须按 invoice_id 升序且不能重复", file=sys.stderr)
        return False

    print("SUCCESS: 多文件汇总、付款状态筛选、金额计算与排序均正确，输入文件未修改")
    return True


if __name__ == "__main__":
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(ws) else 1)
