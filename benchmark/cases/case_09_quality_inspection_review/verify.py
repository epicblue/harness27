import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "inspection_policy.json": "8656e951dda06ce1415f9dcf172a04943566d4c13bb26ff8259a96f90d89374c",
    "measurements.csv": "280b6584aab61f9ab0df218eb55ea0689ab0d0858e4b7cf209251cfe054d0724",
    "product_specs.json": "62b63b2001cf43625a03a45c94e6ff83e6aeacf4cf70e3f79726305dae82ffff",
}
EXPECTED = [
    {"lot_id": "LOT-901", "status": "pass_pending_human_approval", "checked_count": 3,
     "out_of_spec_measurement_ids": []},
    {"lot_id": "LOT-902", "status": "hold_for_quality_review", "checked_count": 3,
     "out_of_spec_measurement_ids": ["Q-902-B"]},
    {"lot_id": "LOT-903", "status": "insufficient_sample", "checked_count": 1,
     "out_of_spec_measurement_ids": []},
]
EXPECTED_FIELDS = {"lot_id", "status", "checked_count", "out_of_spec_measurement_ids"}


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
    if (actual_files != set(SOURCE_SHA256) | {"quality_review.json"}
            or actual_directories):
        return _fail("只能新增 quality_review.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        rows = json.loads((workspace_dir / "quality_review.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"quality_review.json 不是合法 JSON: {exc}")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        return _fail("摘要必须为每个批次生成且仅生成一条记录")

    lot_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {index + 1} 条记录字段集合不正确")
        if (not isinstance(row["lot_id"], str) or not isinstance(row["status"], str)
                or type(row["checked_count"]) is not int
                or not isinstance(row["out_of_spec_measurement_ids"], list)
                or any(not isinstance(item, str) for item in row["out_of_spec_measurement_ids"])):
            return _fail(f"第 {index + 1} 条记录字段类型不正确")
        lot_ids.append(row["lot_id"])

    if len(lot_ids) != len(set(lot_ids)):
        return _fail("lot_id 不能重复")
    if rows != EXPECTED:
        return _fail("规格判定、抽样状态、超差 ID 或排序不正确")

    print("SUCCESS: 测量规格边界、批次抽样、超差列表与人工复核状态正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
