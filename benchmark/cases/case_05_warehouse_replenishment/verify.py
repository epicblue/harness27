import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "purchase_orders.csv": "ae2f40f076446ef50641a1f8f4b656dab82f95a2ef54b6872d73bdedee2e49e5",
    "stock_levels.csv": "a7d7e0430c59fef95854ec07435c587858707ab2237ac5d26fb0fc7cbfcf6212",
}
EXPECTED = [
    {"sku": "SKU-A", "on_hand": 12, "open_order_units": 13,
     "available_units": 25, "target_stock": 40, "recommended_order_qty": 15},
    {"sku": "SKU-B", "on_hand": 5, "open_order_units": 7,
     "available_units": 12, "target_stock": 20, "recommended_order_qty": 8},
    {"sku": "SKU-D", "on_hand": 0, "open_order_units": 0,
     "available_units": 0, "target_stock": 12, "recommended_order_qty": 12},
    {"sku": "SKU-F", "on_hand": 8, "open_order_units": 4,
     "available_units": 12, "target_stock": 16, "recommended_order_qty": 4},
]
EXPECTED_FIELDS = {
    "sku", "on_hand", "open_order_units", "available_units",
    "target_stock", "recommended_order_qty",
}
INTEGER_FIELDS = EXPECTED_FIELDS - {"sku"}


def _fail(message):
    print(f"FAILED: {message}", file=sys.stderr)
    return False


def verify(workspace_dir: Path, trace_events=None):
    workspace_dir = Path(workspace_dir)
    if workspace_dir.is_symlink() or not workspace_dir.is_dir():
        return _fail("workspace 必须是普通目录")

    for filename, expected_hash in SOURCE_SHA256.items():
        path = workspace_dir / filename
        if (path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash):
            return _fail(f"输入文件缺失或被修改: {filename}")

    paths = list(workspace_dir.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return _fail("workspace 不允许符号链接")
    actual_files = {path.relative_to(workspace_dir).as_posix()
                    for path in paths if path.is_file()}
    actual_directories = {path.relative_to(workspace_dir).as_posix()
                          for path in paths if path.is_dir()}
    expected_files = set(SOURCE_SHA256) | {"reorder_plan.json"}
    if actual_files != expected_files or actual_directories:
        return _fail("只能新增 reorder_plan.json，不得创建其他文件或目录")

    target = workspace_dir / "reorder_plan.json"
    try:
        rows = json.loads(target.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"reorder_plan.json 不是合法 JSON: {exc}")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        return _fail("JSON 顶层必须是仅包含需补货 SKU 的数组")

    actual_skus = []
    for index, (row, expected) in enumerate(zip(rows, EXPECTED), start=1):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {index} 行的字段集合不正确")
        if not isinstance(row.get("sku"), str):
            return _fail(f"第 {index} 行的 sku 必须是字符串")
        if any(type(row.get(field)) is not int for field in INTEGER_FIELDS):
            return _fail(f"{row['sku']} 的数量字段必须是 JSON 整数")
        actual_skus.append(row["sku"])
        if row != expected:
            return _fail(f"{row['sku']} 的在途量或建议补货数不正确")

    if actual_skus != sorted(actual_skus) or len(actual_skus) != len(set(actual_skus)):
        return _fail("SKU 必须升序排列且不能重复")

    print("SUCCESS: 在途采购筛选、库存汇总与补货建议正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
