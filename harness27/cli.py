import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

from .agent import Agent
from .client import LocalClient, ModelError
from .tools import Tools

TRACE_SCHEMA_VERSION = 1
LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


def label_arg(value):
    if not LABEL_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "标签只能包含小写字母、数字、下划线和连字符，且必须以字母或数字开头（最多 48 字符）")
    return value


def approve(name, args):
    print(f"\n请求权限：{name}\n{json.dumps(args, ensure_ascii=False, indent=2)}", file=sys.stderr)
    if not sys.stdin.isatty():
        print("非交互环境：自动拒绝。", file=sys.stderr)
        return False
    try:
        return input("仅输入 yes 允许此次操作：").strip() == "yes"
    except EOFError:
        return False


def parser():
    p = argparse.ArgumentParser(description="离线 27B 模型 Agent harness（本机 OpenAI 兼容服务）")
    p.add_argument("task", help="任务描述")
    p.add_argument("--model", required=True, help="服务中注册的模型名，不会下载权重")
    p.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    p.add_argument("--workspace", default="workspace", help="Agent 可访问的目录")
    p.add_argument("--task-id", type=label_arg,
                   help="可选的非敏感任务标签，供本地流程分析分组")
    p.add_argument("--task-category", type=label_arg,
                   help="可选的非敏感任务类别标签，供本地流程分析分组")
    p.add_argument("--config-id", type=label_arg,
                   help="可选的非敏感模型服务配置标签；不要填写 URL 或密钥")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--max-context-chars", type=int, default=100_000)
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--allow-shell", action="store_true", help="启用非沙箱 Shell，仍需逐次确认")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.max_steps < 1 or args.max_context_chars < 1 or not args.task.strip():
        p.error("任务不能为空，运行预算必须为正数")
    try:
        client = LocalClient(args.base_url, args.model, args.timeout, args.temperature,
                             args.max_tokens, os.environ.get("HARNESS27_API_KEY"))
        tools = Tools(args.workspace, args.allow_shell, approve)
        trace_dir = Path(".harness27/runs")
        trace_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = trace_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                            + "-" + uuid.uuid4().hex[:8] + ".jsonl")
        print(f"轨迹：{path.resolve()}", file=sys.stderr)
        if args.allow_shell:
            print("警告：Shell 可访问工作目录以外的文件和网络；建议只在隔离容器中启用。", file=sys.stderr)
        trace_labels = {key: value for key, value in {
            "task_id": args.task_id,
            "task_category": args.task_category,
            "config_id": args.config_id,
        }.items() if value is not None}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            def trace(event, data):
                if event == "start" and trace_labels:
                    data = {**data, **trace_labels}
                f.write(json.dumps({"trace_schema_version": TRACE_SCHEMA_VERSION,
                                    "time": datetime.now(timezone.utc).isoformat(),
                                    "event": event, **data}, ensure_ascii=False) + "\n")
                f.flush()
            result = Agent(client, tools, trace, args.max_steps, args.max_context_chars).run(args.task)
        print(result["answer"])
        print(f"状态：{result['status']} / 模型轮数：{result['steps']}", file=sys.stderr)
        return 0 if result["status"] == "completed" else 2
    except (ModelError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
