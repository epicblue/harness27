"""Constrained filesystem tools; optional shell is NOT a security sandbox."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile

MAX_BYTES = 32_768


def schema(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


class Tools:
    def __init__(self, workspace, allow_shell=False, approve=None, shell_timeout=30):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow_shell = allow_shell
        self.approve = approve or (lambda name, args: False)
        self.shell_timeout = shell_timeout

    @property
    def schemas(self):
        string = {"type": "string"}
        result = [
            schema("list_files", "List up to 200 immediate entries in a workspace directory.",
                   {"path": string}, ["path"]),
            schema("read_file", "Read a UTF-8 workspace file, at most 32768 bytes.",
                   {"path": string}, ["path"]),
            schema("write_file", "Write a UTF-8 workspace file; requires user approval.",
                   {"path": string, "content": string}, ["path", "content"]),
        ]
        if self.allow_shell:
            result.append(schema("shell", "Run a shell command after user approval. Not sandboxed.",
                                 {"command": string}, ["command"]))
        return result

    def path(self, value):
        if not isinstance(value, str):
            raise ValueError("path 必须是字符串")
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("路径超出了工作目录（包括符号链接）")
        relative = path.relative_to(self.root)
        if any(part in {".git", ".harness27"} for part in relative.parts):
            raise ValueError("禁止访问 .git 和 .harness27 内部目录")
        return path

    def execute(self, name, args):
        approval_decision = "not_requested" if isinstance(name, str) and name in {"write_file", "shell"} else None
        try:
            spec = next((s["function"]["parameters"] for s in self.schemas
                         if s["function"]["name"] == name), None)
            if spec is None:
                raise ValueError("未知或未启用的工具")
            if (not isinstance(args, dict) or set(args) != set(spec["required"])
                    or not all(isinstance(v, str) for v in args.values())):
                raise ValueError("工具参数字段或类型错误")
            if name == "shell":
                if not self.approve(name, args):
                    return {"ok": False, "error": "用户拒绝执行命令", "approval": "denied"}
                approval_decision = "approved"
                result = self.shell(args["command"])
                result["approval"] = approval_decision
                return result
            path = self.path(args["path"])
            if name == "list_files":
                entries = []
                for child in path.iterdir():
                    if child.name in {".git", ".harness27"}:
                        continue
                    entries.append(child.name + ("/" if child.is_dir() else ""))
                    if len(entries) == 200:
                        break
                return {"ok": True, "entries": sorted(entries), "limit": 200}
            if name == "read_file":
                if not path.is_file():
                    raise ValueError("不是普通文件")
                with path.open("rb") as f:
                    data = f.read(MAX_BYTES + 1)
                return {"ok": True, "content": data[:MAX_BYTES].decode("utf-8", errors="replace"),
                        "truncated": len(data) > MAX_BYTES}
            data = args["content"].encode("utf-8")
            if len(data) > MAX_BYTES:
                raise ValueError("写入内容超过 32768 字节")
            if not self.approve(name, args):
                return {"ok": False, "error": "用户拒绝写入", "approval": "denied"}
            approval_decision = "approved"
            path = self.path(args["path"])
            if path.exists() and not path.is_file():
                raise ValueError("不是普通文件")
            path.parent.mkdir(parents=True, exist_ok=True)
            # Replace rather than follow hardlinks when overwriting existing files.
            fd, temporary = tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"ok": True, "bytes_written": len(data), "approval": approval_decision}
        except (OSError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
            if approval_decision is not None:
                result["approval"] = approval_decision
            return result

    def shell(self, command):
        # A tempfile prevents unbounded RAM use. Use a container for disk/process limits.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, shell=True, cwd=self.root,
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            timed_out = False
            try:
                process.wait(timeout=self.shell_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Also kill background children left by the command on POSIX.
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.poll() is None:
                    process.kill()
                process.wait()
            output.seek(0)
            data = output.read(MAX_BYTES + 1)
        return {"ok": process.returncode == 0 and not timed_out,
                "returncode": process.returncode, "timed_out": timed_out,
                "output": data[:MAX_BYTES].decode("utf-8", errors="replace"),
                "truncated": len(data) > MAX_BYTES}
