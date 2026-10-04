#!/usr/bin/env python3
"""Run the local 27B capability suite serially and save a compact JSON report.

The model endpoint must be a loopback IP (enforced by LocalClient). Model-generated
shell is disabled unless explicitly requested, and is never enabled for cases whose
metadata says shell access is disabled.
"""
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
import platform
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import uuid

# Ensure the repository root is importable when this file is run directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_ROOT = Path(__file__).resolve().parent / "cases"
DATA_ROOT = REPO_ROOT / ".harness27" / "benchmark"
sys.path.insert(0, str(REPO_ROOT))

from harness27.agent import Agent
from harness27.client import LocalClient
from harness27.tools import Tools

CASE_NAME = re.compile(r"case_[a-z0-9_]+\Z")
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_SHELL_POLICIES = {"disabled", "optional", "required"}
MAX_VERIFIER_OUTPUT = 8_192


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    path: Path
    prompt: str
    metadata: dict
    verify: object
    fingerprint: str


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _load_metadata(case_dir):
    metadata_path = case_dir / "case.json"
    if metadata_path.is_symlink():
        raise ValueError(f"用例元数据不允许是符号链接：{case_dir.name}")
    try:
        metadata = json.loads(metadata_path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"用例元数据无效：{metadata_path.name}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"用例元数据必须是 JSON 对象：{case_dir.name}")
    for key in ("title", "category"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError(f"用例 {case_dir.name} 缺少有效的 {key}")
    if metadata.get("difficulty") not in VALID_DIFFICULTIES:
        raise ValueError(f"用例 {case_dir.name} difficulty 必须是 easy/medium/hard")
    skills = metadata.get("skills")
    if (not isinstance(skills, list) or not skills
            or not all(isinstance(item, str) and item.strip() for item in skills)):
        raise ValueError(f"用例 {case_dir.name} skills 必须是非空字符串列表")
    if len(set(skills)) != len(skills):
        raise ValueError(f"用例 {case_dir.name} skills 不能重复")
    if metadata.get("shell") not in VALID_SHELL_POLICIES:
        raise ValueError(f"用例 {case_dir.name} shell 必须是 disabled/optional/required")
    return metadata


def _case_fingerprint(case_dir):
    """Hash all benchmark inputs so reports remain comparable after suite edits."""
    root = Path(case_dir)
    entries = [(root / name, "file") for name in ("case.json", "prompt.txt", "verify.py")]
    fixture = root / "fixture"
    for entry in fixture.rglob("*"):
        if entry.is_symlink():
            raise ValueError(f"fixture 不允许符号链接：{entry.relative_to(root)}")
        if entry.name == "__pycache__" or entry.suffix in {".pyc", ".pyo"}:
            continue
        if entry.is_dir():
            entries.append((entry, "directory"))
        elif entry.is_file():
            entries.append((entry, "file"))
        else:
            raise ValueError(f"fixture 只允许普通文件和目录：{entry.relative_to(root)}")

    digest = hashlib.sha256()
    for path, kind in sorted(entries, key=lambda item: item[0].relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes() if kind == "file" else b""
        digest.update(relative + b"\0" + kind.encode("ascii")
                      + b"\0" + str(len(content)).encode("ascii") + b"\0" + content)
    return digest.hexdigest()


def _harness_fingerprint():
    components = [
        Path(__file__).resolve(),
        REPO_ROOT / "harness27" / "agent.py",
        REPO_ROOT / "harness27" / "client.py",
        REPO_ROOT / "harness27" / "tools.py",
    ]
    digest = hashlib.sha256()
    for path in sorted(components, key=lambda item: item.relative_to(REPO_ROOT).as_posix()):
        relative = path.relative_to(REPO_ROOT).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(relative + b"\0" + str(len(content)).encode("ascii") + b"\0" + content)
    return digest.hexdigest()


def load_case(case_dir):
    """Load prompt, metadata, and verifier from a direct child of cases/."""
    case_dir = Path(case_dir)
    root = CASES_ROOT.resolve()
    if case_dir.is_symlink():
        raise ValueError("不接受符号链接形式的 benchmark 用例")
    try:
        resolved = case_dir.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"用例目录不存在：{case_dir}") from exc
    if resolved.parent != root or not resolved.is_dir():
        raise ValueError("benchmark 用例必须是 cases/ 下的直接子目录")
    if not CASE_NAME.fullmatch(resolved.name):
        raise ValueError(f"无效用例名称：{resolved.name}")

    prompt_path = resolved / "prompt.txt"
    verifier_path = resolved / "verify.py"
    fixture_path = resolved / "fixture"
    if (prompt_path.is_symlink() or verifier_path.is_symlink() or fixture_path.is_symlink()
            or not prompt_path.is_file() or not verifier_path.is_file() or not fixture_path.is_dir()):
        raise ValueError(f"用例 {resolved.name} 必须包含普通文件 prompt.txt、verify.py 和 fixture/")
    prompt = prompt_path.read_text("utf-8").strip()
    if not prompt:
        raise ValueError(f"用例 {resolved.name} 的 prompt.txt 不能为空")
    metadata = _load_metadata(resolved)
    fingerprint = _case_fingerprint(resolved)

    # Import every verifier before any model/tool execution. That keeps the
    # in-memory verifier fixed even when a shell-enabled task can modify files.
    module_name = f"_harness27_verify_{resolved.name}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, verifier_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载用例 {resolved.name} 的 verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ValueError(f"无法导入用例 {resolved.name} 的 verifier：{exc}") from exc
    verify = getattr(module, "verify", None)
    if not callable(verify):
        raise ValueError(f"用例 {resolved.name} verify.py 必须定义 verify(workspace_dir, trace_events=None)")

    return BenchmarkCase(resolved.name, resolved, prompt, metadata, verify, fingerprint)


def discover_cases(selected=None):
    """Discover all cases or load explicitly selected case names safely."""
    if selected:
        names = list(selected)
        if len(names) != len(set(names)):
            raise ValueError("--case 不应重复指定相同用例")
        for name in names:
            if not isinstance(name, str) or not CASE_NAME.fullmatch(name):
                raise ValueError(f"无效用例名 {name!r}；只能指定 cases/ 下的 case_* 名称")
        paths = [CASES_ROOT / name for name in names]
    else:
        if not CASES_ROOT.is_dir():
            raise ValueError(f"用例目录不存在：{CASES_ROOT}")
        paths = sorted((p for p in CASES_ROOT.iterdir()
                        if p.name.startswith("case_") and p.is_dir() and not p.is_symlink()),
                       key=lambda p: p.name)
    if not paths:
        raise ValueError("未找到 benchmark 用例")
    return [load_case(path) for path in paths]


def setup_workspace(case_dir: Path, target_dir: Path):
    """Copy a trusted fixture to a fresh workspace; never remove an existing one."""
    fixture_dir = case_dir / "fixture"
    if not fixture_dir.is_dir() or fixture_dir.is_symlink():
        raise ValueError(f"缺少普通 fixture 目录：{case_dir.name}")
    if target_dir.is_symlink():
        raise ValueError(f"拒绝使用符号链接 workspace：{target_dir}")
    if target_dir.exists():
        if not target_dir.is_dir() or any(target_dir.iterdir()):
            raise ValueError(f"拒绝覆盖非空 benchmark workspace：{target_dir}")
    else:
        target_dir.mkdir(parents=True, exist_ok=False)

    for entry in fixture_dir.rglob("*"):
        if entry.is_symlink():
            raise ValueError(f"fixture 不允许符号链接：{entry.relative_to(fixture_dir)}")
        if not (entry.is_file() or entry.is_dir()):
            raise ValueError(f"fixture 只允许普通文件和目录：{entry.relative_to(fixture_dir)}")
    shutil.copytree(
        fixture_dir, target_dir, dirs_exist_ok=True, copy_function=shutil.copy2,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _make_workspace(case, run_id, trial, keep_workspaces):
    workspace_root = DATA_ROOT / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        workspace_root.chmod(0o700)
    if keep_workspaces:
        target = workspace_root / run_id / f"{case.name}-trial-{trial:02d}"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        setup_workspace(case.path, target)
        return target, None

    temporary = tempfile.TemporaryDirectory(
        prefix=f"{case.name}-trial-{trial:02d}-", dir=workspace_root)
    target = Path(temporary.name)
    try:
        setup_workspace(case.path, target)
    except Exception:
        temporary.cleanup()
        raise
    return target, temporary


def _usage_totals(events):
    totals = Counter()
    for event, data in events:
        if event != "assistant" or not isinstance(data.get("usage"), dict):
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = data["usage"].get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
    return {key: totals.get(key, 0) for key in
            ("prompt_tokens", "completion_tokens", "total_tokens")}


def _tool_totals(events):
    names = Counter()
    errors = 0
    for event, data in events:
        if event != "tool":
            continue
        names[str(data.get("name", "unknown"))] += 1
        result = data.get("result")
        if isinstance(result, dict) and result.get("ok") is False:
            errors += 1
    return dict(sorted(names.items())), errors


def run_case(case, client, run_id, trial, *, max_steps=16,
             max_context_chars=60_000, allow_shell=False, shell_timeout=30,
             keep_workspaces=False):
    metadata = case.metadata
    base = {
        "case": case.name,
        "fingerprint_sha256": case.fingerprint,
        "title": metadata["title"],
        "category": metadata["category"],
        "difficulty": metadata["difficulty"],
        "skills": metadata["skills"],
        "trial": trial,
        "verified": None,
        "passed": None,
        "agent_status": "not_run",
        "steps_used": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "tool_names": {},
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "agent_seconds": 0.0,
        "verification_seconds": 0.0,
        "elapsed_seconds": 0.0,
        "agent_error": None,
        "verification_error": None,
        "verification_output": {"stdout": "", "stderr": ""},
        "workspace": None,
    }

    shell_policy = metadata["shell"]
    if shell_policy == "required" and not allow_shell:
        base.update({"status": "skipped", "skip_reason": "该用例要求 Shell；显式添加 --allow-shell 后才会运行"})
        return base
    shell_enabled = allow_shell and shell_policy in {"optional", "required"}

    events = []
    temporary = None
    workspace = None
    overall_started = time.monotonic()
    try:
        workspace, temporary = _make_workspace(case, run_id, trial, keep_workspaces)
        if keep_workspaces:
            base["workspace"] = str(workspace)
        tools = Tools(workspace, allow_shell=shell_enabled,
                      approve=lambda *_: True, shell_timeout=shell_timeout)
        agent_started = time.monotonic()
        try:
            result = Agent(client, tools, lambda event, data: events.append((event, data)),
                           max_steps=max_steps,
                           max_context_chars=max_context_chars).run(case.prompt)
            base["agent_status"] = result.get("status", "unknown")
        except Exception as exc:
            base["agent_status"] = "error"
            base["agent_error"] = f"{type(exc).__name__}: {exc}"[:2_000]
        base["agent_seconds"] = round(time.monotonic() - agent_started, 3)
        base["steps_used"] = sum(1 for event, _ in events if event == "assistant")
        base["tool_calls"] = sum(1 for event, _ in events if event == "tool")
        base["tool_names"], base["tool_errors"] = _tool_totals(events)
        base["token_usage"] = _usage_totals(events)

        verify_stdout, verify_stderr = io.StringIO(), io.StringIO()
        verification_started = time.monotonic()
        try:
            with redirect_stdout(verify_stdout), redirect_stderr(verify_stderr):
                verified = bool(case.verify(workspace, events))
            base["verified"] = verified
            base["passed"] = verified
        except Exception as exc:
            base["verification_error"] = f"{type(exc).__name__}: {exc}"[:2_000]
        base["verification_seconds"] = round(time.monotonic() - verification_started, 3)
        base["verification_output"] = {
            "stdout": verify_stdout.getvalue()[:MAX_VERIFIER_OUTPUT],
            "stderr": verify_stderr.getvalue()[:MAX_VERIFIER_OUTPUT],
        }
        if base["verification_error"] or (base["agent_status"] == "error" and not base["verified"]):
            # Do not score transport/protocol failures as model capability failures.
            base["status"] = "error"
        else:
            base["status"] = "passed" if base["verified"] else "failed"
    except Exception as exc:
        base["status"] = "error"
        base["verification_error"] = f"{type(exc).__name__}: {exc}"[:2_000]
    finally:
        base["elapsed_seconds"] = round(time.monotonic() - overall_started, 3)
        if temporary is not None:
            temporary.cleanup()

    return base


def _aggregate(rows):
    # Only verifier-backed pass/fail outcomes belong in the capability denominator;
    # transport/protocol/verifier errors are reported separately.
    evaluated = [row for row in rows if row.get("status") in {"passed", "failed"}]
    executed = [row for row in rows if row.get("status") != "skipped"]
    passes = sum(row.get("verified") is True for row in evaluated)
    completed = sum(row.get("agent_status") == "completed" for row in executed)
    token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    tokens = {key: sum(row.get("token_usage", {}).get(key, 0) for row in executed)
              for key in token_keys}
    return {
        "executed": len(executed),
        "attempts": len(evaluated),
        "verified_passes": passes,
        "success_rate": round(passes / len(evaluated), 4) if evaluated else None,
        "agent_completed": completed,
        "completion_rate": round(completed / len(executed), 4) if executed else None,
        "skipped": sum(row.get("status") == "skipped" for row in rows),
        "errors": sum(row.get("status") == "error" for row in rows),
        "agent_errors": sum(row.get("agent_status") == "error" for row in executed),
        "tool_calls": sum(row.get("tool_calls", 0) for row in executed),
        "tool_errors": sum(row.get("tool_errors", 0) for row in executed),
        "mean_steps": round(sum(row.get("steps_used", 0) for row in executed) / len(executed), 2)
                      if executed else None,
        "mean_elapsed_seconds": round(sum(row.get("elapsed_seconds", 0) for row in executed)
                                       / len(executed), 3) if executed else None,
        "token_usage": tokens,
    }


def build_summary(results):
    def groups_by(key):
        groups = {}
        for row in results:
            values = row.get(key, []) if key == "skills" else [row.get(key, "unknown")]
            for value in values:
                groups.setdefault(value, []).append(row)
        return {name: _aggregate(group) for name, group in sorted(groups.items())}

    return {
        "overall": _aggregate(results),
        "by_category": groups_by("category"),
        "by_difficulty": groups_by("difficulty"),
        "by_skill": groups_by("skills"),
    }


def write_report(path, report):
    """Atomically write a private report; report content excludes raw prompts/traces."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser():
    import argparse

    p = argparse.ArgumentParser(description="串行评测本机 27B 模型的实际任务能力边界")
    p.add_argument("--base-url", default="http://127.0.0.1:8000/v1", help="本机 OpenAI 兼容服务地址")
    p.add_argument("--model", default="qwen3.6-27b", help="服务中注册的模型名")
    p.add_argument("--case", action="append", help="只运行指定用例；可重复传入，默认运行全部")
    p.add_argument("--list-cases", action="store_true", help="列出用例后退出，不连接模型")
    p.add_argument("--repeat", type=int, default=1, help="每个用例重复次数（用于观察稳定性）")
    p.add_argument("--max-steps", type=int, default=16, help="单任务最大模型轮数")
    p.add_argument("--max-tokens", type=int, default=4096, help="单次补全最大 Token")
    p.add_argument("--temperature", type=float, default=0.6, help="采样温度")
    p.add_argument("--timeout", type=float, default=300, help="单轮本地 HTTP 请求超时秒数")
    p.add_argument("--max-context-chars", type=int, default=60_000, help="Agent 历史字符预算")
    p.add_argument("--allow-shell", action="store_true",
                   help="显式允许标记为 required/optional 的用例调用未沙箱化 Shell")
    p.add_argument("--shell-timeout", type=float, default=30, help="Shell 单条命令超时秒数")
    p.add_argument("--keep-workspaces", action="store_true", help="保留每次运行的独立工作区以便复盘")
    p.add_argument("--report", help="JSON 报告路径；默认写入 .harness27/benchmark/results/")
    return p


def _print_case_list(cases):
    print(f"{'用例':34} {'难度':8} {'类别':24} {'Shell':10} 标题")
    for case in cases:
        print(f"{case.name:34} {case.metadata['difficulty']:8} "
              f"{case.metadata['category']:24} {case.metadata['shell']:10} "
              f"{case.metadata['title']}")


def _print_result(row):
    status = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}.get(
        row["status"], row["status"].upper())
    print(f"[{status}] {row['case']} trial={row['trial']} "
          f"steps={row['steps_used']} tools={row['tool_calls']} "
          f"time={row['elapsed_seconds']:.2f}s")
    if row.get("skip_reason"):
        print(f"       {row['skip_reason']}")
    if row.get("agent_error"):
        print(f"       Agent error: {row['agent_error']}")
    if row.get("verification_error"):
        print(f"       Verifier error: {row['verification_error']}")
    output = row.get("verification_output", {}).get("stderr", "").strip()
    if row["status"] == "failed" and output:
        print(f"       {output[:500]}")


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.repeat < 1 or args.max_steps < 1 or args.max_tokens < 1 or args.max_context_chars < 1:
        p.error("repeat、运行预算和 max-tokens 必须为正数")
    if (not math.isfinite(args.timeout) or not math.isfinite(args.shell_timeout)
            or not math.isfinite(args.temperature) or args.timeout <= 0
            or args.shell_timeout <= 0 or not 0 <= args.temperature <= 2):
        p.error("timeout 必须为有限正数，temperature 必须是 0 到 2 之间的有限数")
    if not args.model.strip():
        p.error("model 名称不能为空")

    try:
        cases = discover_cases(args.case)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    if args.list_cases:
        _print_case_list(cases)
        return 0

    try:
        client = LocalClient(args.base_url, args.model, args.timeout, args.temperature,
                             args.max_tokens, os.environ.get("HARNESS27_API_KEY"))
    except (OSError, ValueError) as exc:
        print(f"模型客户端配置错误：{exc}", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    report_path = Path(args.report) if args.report else DATA_ROOT / "results" / f"{run_id}.json"
    config = {
        "python_version": platform.python_version(),
        "model": args.model,
        "base_url": args.base_url,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "timeout_seconds": args.timeout,
        "max_steps": args.max_steps,
        "max_context_chars": args.max_context_chars,
        "repeat": args.repeat,
        "shell_opt_in": args.allow_shell,
        "keep_workspaces": args.keep_workspaces,
    }
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "harness_fingerprint_sha256": _harness_fingerprint(),
        "status": "running",
        "started_at": utc_now(),
        "updated_at": utc_now(),
        "config": config,
        "selected_cases": [case.name for case in cases],
        "results": [],
        "summary": build_summary([]),
    }
    try:
        write_report(report_path, report)
    except OSError as exc:
        print(f"无法创建 benchmark 报告：{exc}", file=sys.stderr)
        return 1

    if args.allow_shell:
        print("警告：Shell 使用当前用户权限、自动批准且不是沙箱；仅用于隔离、无凭据环境。",
              file=sys.stderr)
    print(f"开始串行评测：{len(cases)} 个用例 × {args.repeat} 次；报告：{report_path}")
    try:
        for trial in range(1, args.repeat + 1):
            for case in cases:
                row = run_case(
                    case, client, run_id, trial,
                    max_steps=args.max_steps,
                    max_context_chars=args.max_context_chars,
                    allow_shell=args.allow_shell,
                    shell_timeout=args.shell_timeout,
                    keep_workspaces=args.keep_workspaces,
                )
                report["results"].append(row)
                report["summary"] = build_summary(report["results"])
                report["updated_at"] = utc_now()
                write_report(report_path, report)
                _print_result(row)
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["updated_at"] = utc_now()
        write_report(report_path, report)
        print(f"\n已中断；部分结果保存在 {report_path}", file=sys.stderr)
        return 130
    except OSError as exc:
        report["status"] = "error"
        report["updated_at"] = utc_now()
        write_report(report_path, report)
        print(f"benchmark 文件操作失败：{exc}", file=sys.stderr)
        return 1

    report["status"] = "completed"
    report["finished_at"] = utc_now()
    report["updated_at"] = report["finished_at"]
    report["summary"] = build_summary(report["results"])
    try:
        write_report(report_path, report)
    except OSError as exc:
        print(f"无法完成写入报告：{exc}", file=sys.stderr)
        return 1

    overall = report["summary"]["overall"]
    rate = "n/a" if overall["success_rate"] is None else f"{overall['success_rate']:.1%}"
    print(f"\n评测完成：验证成功率 {rate}（{overall['verified_passes']}/{overall['attempts']}），"
          f"跳过 {overall['skipped']}；报告：{report_path}")
    if report["summary"]["by_category"]:
        print("类别汇总：")
        for category, summary in report["summary"]["by_category"].items():
            category_rate = "n/a" if summary["success_rate"] is None else f"{summary['success_rate']:.1%}"
            print(f"  {category}: {category_rate} "
                  f"({summary['verified_passes']}/{summary['attempts']}, "
                  f"跳过 {summary['skipped']})")
    return 1 if overall["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
