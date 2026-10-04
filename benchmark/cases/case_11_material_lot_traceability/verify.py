import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "component_usage.csv": "e0b785c7d0642278fd5372e5e9ed3d2d9438ed8d74089d362c0f4cda27e7c38a",
    "finished_lots.csv": "04356a4e0d16c9b0f54c227ec435f96b00e3670b9118040582b821e767469183",
    "shipments.csv": "496269a0d93964d1fe7600cd535f3661539c3818b98f6156fdd075dccfa22964",
    "trace_request.json": "82aec16f9cb0ec773f7b7bc5d5e98b74162a7a906bf7c924b52293610252bc74",
}
EXPECTED = {
    "component_lot": "CL-771",
    "component_sku": "MOTOR-8",
    "affected_finished_lots": [
        {"finished_lot": "FG-501", "work_order_id": "WO-501", "finished_sku": "ASSY-100",
         "produced_at_utc": "2026-10-10T08:30:00Z", "component_units": 2},
        {"finished_lot": "FG-502", "work_order_id": "WO-502", "finished_sku": "ASSY-100",
         "produced_at_utc": "2026-10-10T12:00:00Z", "component_units": 1},
        {"finished_lot": "FG-504", "work_order_id": "WO-504", "finished_sku": "ASSY-200",
         "produced_at_utc": "2026-10-11T10:45:00Z", "component_units": 2},
    ],
    "affected_shipments": [
        {"shipment_id": "SH-701", "finished_lot": "FG-501"},
        {"shipment_id": "SH-702", "finished_lot": "FG-501"},
        {"shipment_id": "SH-704", "finished_lot": "FG-504"},
    ],
    "unshipped_finished_lots": ["FG-502"],
}
EXPECTED_FIELDS = {
    "component_lot", "component_sku", "affected_finished_lots",
    "affected_shipments", "unshipped_finished_lots",
}
FINISHED_LOT_FIELDS = {
    "finished_lot", "work_order_id", "finished_sku", "produced_at_utc", "component_units",
}
SHIPMENT_FIELDS = {"shipment_id", "finished_lot"}


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
    if (actual_files != set(SOURCE_SHA256) | {"trace_report.json"}
            or actual_directories):
        return _fail("只能新增 trace_report.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        report = json.loads((workspace_dir / "trace_report.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"trace_report.json 不是合法 JSON: {exc}")
    if not isinstance(report, dict) or set(report) != EXPECTED_FIELDS:
        return _fail("追溯报告字段集合不正确")
    if (not isinstance(report["component_lot"], str)
            or not isinstance(report["component_sku"], str)):
        return _fail("组件批次和 SKU 必须是字符串")
    finished_lots = report["affected_finished_lots"]
    if (not isinstance(finished_lots, list)
            or any(not isinstance(item, dict) or set(item) != FINISHED_LOT_FIELDS
                   or any(not isinstance(item[field], str) for field in FINISHED_LOT_FIELDS - {"component_units"})
                   or type(item["component_units"]) is not int for item in finished_lots)):
        return _fail("affected_finished_lots 的记录格式不正确")
    if (not isinstance(report["unshipped_finished_lots"], list)
            or any(not isinstance(item, str) for item in report["unshipped_finished_lots"])):
        return _fail("unshipped_finished_lots 必须是字符串数组")
    if (not isinstance(report["affected_shipments"], list)
            or any(not isinstance(item, dict) or set(item) != SHIPMENT_FIELDS
                   or any(not isinstance(item[field], str) for field in SHIPMENT_FIELDS)
                   for item in report["affected_shipments"])):
        return _fail("affected_shipments 的记录格式不正确")
    lot_ids = [item["finished_lot"] for item in finished_lots]
    if (len(lot_ids) != len(set(lot_ids))
            or len(report["unshipped_finished_lots"])
            != len(set(report["unshipped_finished_lots"]))):
        return _fail("成品批次列表不能重复")
    if report != EXPECTED:
        return _fail("组件批次追溯范围、发运关联、未发运批次或排序不正确")

    print("SUCCESS: 组件批次追溯、成品去重、发运关联与未发运范围正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)
