import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "label_audit.json"
SOURCE_SHA256 = {
    "label_policy.json": "904db26fdf192b4d18bd6723858cbeccee2168492db13fdf21714de729506cf3",
    "printed_labels.csv": "22849f948c6a036e39d7a24fb373176bc8b5bb4283d3c887044d3189c953a112",
    "work_orders.csv": "1141ada4c3855e6cf00520a830851cb66c57ce677ae063e28c1c066e5777988c",
}
EXPECTED = [
    {"label_id": "LBL-701", "work_order_id": "WO-701", "status": "match", "mismatch_fields": []},
    {"label_id": "LBL-702", "work_order_id": "WO-702", "status": "mismatch", "mismatch_fields": ["lot"]},
    {"label_id": "LBL-703", "work_order_id": "WO-703", "status": "mismatch", "mismatch_fields": ["label_revision"]},
    {"label_id": "LBL-704", "work_order_id": "WO-999", "status": "unknown_work_order",
     "mismatch_fields": ["work_order_id"]},
    {"label_id": "LBL-705", "work_order_id": "WO-702", "status": "mismatch",
     "mismatch_fields": ["sku", "lot", "label_revision"]},
]


def _same_typed(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys()
                and all(_same_typed(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list):
        return (len(actual) == len(expected)
                and all(_same_typed(left, right) for left, right in zip(actual, expected)))
    return actual == expected


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
    files = {path.relative_to(workspace_dir).as_posix() for path in paths if path.is_file()}
    directories = {path.relative_to(workspace_dir).as_posix() for path in paths if path.is_dir()}
    if files != set(SOURCE_SHA256) | {OUTPUT_FILENAME} or directories:
        return _fail(f"只能新增 {OUTPUT_FILENAME}，不得创建其他文件或目录")
    if trace_events is not None and any(
        isinstance(event, (tuple, list)) and len(event) == 2 and event[0] == "tool"
        and isinstance(event[1], dict) and event[1].get("name") == "shell"
        for event in trace_events
    ):
        return _fail("本用例禁止调用 Shell")
    try:
        actual = json.loads((workspace_dir / OUTPUT_FILENAME).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"{OUTPUT_FILENAME} 不是合法 JSON: {exc}")
    if not _same_typed(actual, EXPECTED):
        return _fail("标签工单连接、SKU/批次/版本差异或排序不正确")
    print("SUCCESS: 标签与工单主数据匹配、未知工单和差异字段正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
