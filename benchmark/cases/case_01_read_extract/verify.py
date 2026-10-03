import json
import sys
from pathlib import Path

def verify(workspace_dir: Path):
    target = workspace_dir / "ports.json"
    if not target.exists():
        print(f"FAILED: {target} 未生成", file=sys.stderr)
        return False
    try:
        data = json.loads(target.read_text("utf-8").strip())
    except Exception as exc:
        print(f"FAILED: ports.json 不是合法 JSON: {exc}", file=sys.stderr)
        return False
    
    expected = [8000, 8080, 9090, 9200]
    if data != expected:
        print(f"FAILED: 数据不匹配。期望: {expected}, 实际: {data}", file=sys.stderr)
        return False
    print("SUCCESS: 端口提取与排序完全正确")
    return True

if __name__ == "__main__":
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(ws) else 1)
