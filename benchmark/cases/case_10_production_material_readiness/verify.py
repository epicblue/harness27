import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "bill_of_materials.csv": "8b703dd1d08ab7025a259dafc6d3b917332a470ba87f2a41ecae0aa15435c7a6",
    "material_allocations.csv": "a5ef47d541d49cd5e87f4fd00239f2c19fcf23a2b48a41bcf513d03305bfb5ae",
    "production_policy.json": "161edef3bc40191cd4de6d57db19849559ac376c624813abd42810042c358585",
    "work_orders.csv": "c1a645c875ff58c48b141331aa0d68036a20939d54549d8c3916776c157752c3",
}
EXPECTED = [
    {"work_order_id": "WO-311", "status": "ready", "shortages": []},
    {"work_order_id": "WO-310", "status": "ready", "shortages": []},
    {"work_order_id": "WO-312", "status": "blocked", "shortages": [
        {"component_sku": "MAT-03", "required_units": 24,
         "allocated_units": 20, "shortage_units": 4},
    ]},
    {"work_order_id": "WO-314", "status": "blocked", "shortages": [
        {"component_sku": "MAT-01", "required_units": 6,
         "allocated_units": 5, "shortage_units": 1},
        {"component_sku": "MAT-02", "required_units": 3,
         "allocated_units": 0, "shortage_units": 3},
    ]},
]
EXPECTED_FIELDS = {"work_order_id", "status", "shortages"}
SHORTAGE_FIELDS = {"component_sku", "required_units", "allocated_units", "shortage_units"}


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
    if (actual_files != set(SOURCE_SHA256) | {"readiness_plan.json"}
            or actual_directories):
        return _fail("只能新增 readiness_plan.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        rows = json.loads((workspace_dir / "readiness_plan.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"readiness_plan.json 不是合法 JSON: {exc}")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        return _fail("齐套计划必须为每张工单生成且仅生成一条记录")

    order_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {index + 1} 条记录字段集合不正确")
        if (not isinstance(row["work_order_id"], str)
                or not isinstance(row["status"], str)
                or not isinstance(row["shortages"], list)):
            return _fail(f"第 {index + 1} 条记录字段类型不正确")
        order_ids.append(row["work_order_id"])
        component_ids = []
        for shortage in row["shortages"]:
            if not isinstance(shortage, dict) or set(shortage) != SHORTAGE_FIELDS:
                return _fail(f"第 {index + 1} 条记录的短缺字段不正确")
            if (not isinstance(shortage["component_sku"], str)
                    or any(type(shortage[field]) is not int for field in (
                        "required_units", "allocated_units", "shortage_units"))):
                return _fail(f"第 {index + 1} 条记录的短缺字段类型不正确")
            component_ids.append(shortage["component_sku"])
        if len(component_ids) != len(set(component_ids)):
            return _fail(f"第 {index + 1} 条记录的组件不能重复")

    if len(order_ids) != len(set(order_ids)):
        return _fail("work_order_id 不能重复")
    if rows != EXPECTED:
        return _fail("BOM 需求、分配数量、短缺计算、状态或排序不正确")

    print("SUCCESS: BOM 需求、工单物料分配、短缺计算与优先级顺序正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
