import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "existing_bookings.csv": "ce27c4fdc3e00db5dc4b952d1b25828787158bd602f5d8641775d3373abf7038",
    "meeting_requests.csv": "8406fca1e1cf5727cb5713ea9773d57e870f7b8a65001d663cbffc37648e0322",
    "room_allocation_policy.json": "f390519ff5576191841ec6fb2c37d88e1fdd9c154a47cf7f89fc54e055d215d6",
    "room_inventory.json": "5b98d5732c6607dbf658cd2cf6a1ca0cb821853b29a3b24506b47a360e19b06d",
}
EXPECTED = [
    {"meeting_id": "M-201", "room_id": "R-105", "status": "assigned", "reason": ""},
    {"meeting_id": "M-202", "room_id": "R-106", "status": "assigned", "reason": ""},
    {"meeting_id": "M-203", "room_id": "R-102", "status": "assigned", "reason": ""},
    {"meeting_id": "M-204", "room_id": "R-103", "status": "assigned", "reason": ""},
    {"meeting_id": "M-205", "room_id": "", "status": "unassigned",
     "reason": "no_eligible_room"},
    {"meeting_id": "M-206", "room_id": "R-102", "status": "assigned", "reason": ""},
    {"meeting_id": "M-207", "room_id": "R-104", "status": "assigned", "reason": ""},
    {"meeting_id": "M-208", "room_id": "R-103", "status": "assigned", "reason": ""},
]
EXPECTED_FIELDS = {"meeting_id", "room_id", "status", "reason"}


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
    if (actual_files != set(SOURCE_SHA256) | {"room_plan.json"}
            or actual_directories):
        return _fail("只能新增 room_plan.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        rows = json.loads((workspace_dir / "room_plan.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"room_plan.json 不是合法 JSON: {exc}")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        return _fail("计划必须为每个会议请求生成且仅生成一条记录")

    meeting_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {index + 1} 条记录字段集合不正确")
        if any(not isinstance(row.get(field), str) for field in EXPECTED_FIELDS):
            return _fail(f"第 {index + 1} 条记录的字段必须都是字符串")
        meeting_ids.append(row["meeting_id"])

    if len(meeting_ids) != len(set(meeting_ids)):
        return _fail("meeting_id 不能重复")
    if meeting_ids != [row["meeting_id"] for row in EXPECTED]:
        return _fail("会议必须按开始时间和 meeting_id 顺序输出")
    if rows != EXPECTED:
        return _fail("房间选择、冲突检查或未分配结果与规则不匹配")

    print("SUCCESS: 房间容量、设备、预订冲突、确定性分配与未分配原因正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
