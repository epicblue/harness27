# Harness27 使用说明

## 1. 项目是什么

Harness27 是一个 Python 3.10+、仅依赖标准库的本机 Agent 执行框架。它把用户任务、对话循环、受限文件工具和可选 Shell 组合起来，通过 OpenAI 兼容的 Chat Completions 接口调用**已经运行在本机的模型服务**。

它不下载或加载模型权重、不管理 GPU，也不验证服务背后模型是否真为 27B。推理服务、模型版本、量化、tokenizer、chat template 和工具解析器都由部署方负责。仓库的 benchmark runner 用于早期能力摸底；它不是完整行业基准，也不包含真实模型测量结果。

## 2. 系统要求

- Python 3.10 或更新版本。
- 一个能从 Harness 所在网络命名空间访问的本机模型服务。
- 服务实现 `POST /v1/chat/completions` 兼容协议，并支持原生工具调用：`tools`、`tool_choice: "auto"`、`assistant.tool_calls`、`role: "tool"` 和 `tool_call_id`。
- 需要在离线机器上运行时，模型、权重、推理引擎及其依赖必须提前准备好。本项目不会访问模型仓库，也不会自动安装依赖。

能生成普通文本不代表支持工具调用。不同模型和推理引擎需要不同的 chat template、工具调用 parser 或启动参数；必须按实际模型文档配置并实测，不要只凭“OpenAI compatible”推断工具调用可用。

## 3. 启动本机模型服务

以下是安装了 vLLM、权重已在本机的命令模板，不是所有 27B 模型都通用的配置：

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export MODEL_DIR=/absolute/path/to/your-27b-model
export TOOL_PARSER=your_model_supported_parser

vllm serve "$MODEL_DIR" \
  --served-model-name local-27b \
  --host 127.0.0.1 --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser "$TOOL_PARSER"
```

按模型和 vLLM 版本补充所需的 chat template、量化、多卡、上下文长度等设置。Harness 使用的 base URL 是 `http://127.0.0.1:8000/v1`，请求路径会追加为 `/chat/completions`。容器部署时，模型服务与 Harness 必须在可互通的网络命名空间中；回环地址只指向当前网络命名空间。

常见本机地址示例：

| 服务 | `--base-url` | `--model` |
|---|---|---|
| vLLM | `http://127.0.0.1:8000/v1` | `--served-model-name` 配置值 |
| Ollama | `http://127.0.0.1:11434/v1` | 本机服务中可用且支持 tools 的模型名 |
| llama.cpp | `http://127.0.0.1:8080/v1` | 服务注册的模型名；需配置兼容工具调用的模板 |

Harness 只接受 HTTP(S) **回环 IP 地址**，例如 `127.0.0.1` 或 `[::1]`。`localhost` 域名、主机名、远端地址、URL 凭据、query、fragment 和重定向都会被拒绝；代理环境变量被忽略。若容器不能访问 Harness 所在网络命名空间的 loopback，就不能仅靠把地址写成 `127.0.0.1` 解决，应调整容器网络部署方式。

## 4. 运行 Agent

在仓库根目录直接运行，不需要先安装：

```bash
mkdir -p workspace
python -m harness27 \
  --model local-27b \
  --base-url http://127.0.0.1:8000/v1 \
  --workspace ./workspace \
  '列出当前文件，然后创建一个带类型标注的 Python 斐波那契函数和测试文件。'
```

可通过 `python -m harness27 --help` 查看参数。安装命令行入口是可选的；它需要本机已有 setuptools / 构建依赖：

```bash
python -m pip install --no-index --no-build-isolation -e .
harness27 --model local-27b '查看工作目录里的文件'
```

### 4.1 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `task` | 必填 | 用户任务；建议明确目标文件、输出格式、禁止操作和验收标准。 |
| `--model` | 必填 | 推理服务中注册的模型名；只是服务端别名，不校验模型参数规模。 |
| `--base-url` | `http://127.0.0.1:8000/v1` | 本机 OpenAI 兼容 API 的 base URL。 |
| `--workspace` | `workspace` | 文件工具的根目录；目录不存在时会创建。 |
| `--task-id` | 不设置 | 可选、非敏感的任务标签，用于本地记录分析分组。 |
| `--task-category` | 不设置 | 可选、非敏感的任务类别标签，用于汇总比较。 |
| `--config-id` | 不设置 | 可选的服务配置标签；只能用短标签，勿填写 URL 或密钥。 |
| `--max-steps` | `12` | 单个任务允许的最大模型响应轮数。 |
| `--max-context-chars` | `100000` | Agent 消息历史的字符预算，不等于 tokenizer token 数。 |
| `--max-tokens` | `2048` | 每次模型响应的最大生成 token 数。 |
| `--temperature` | `0.2` | 采样温度，范围 `0` 至 `2`。 |
| `--timeout` | `120` 秒 | 单次 HTTP 请求超时。 |
| `--allow-shell` | 关闭 | 开启后向模型暴露未沙箱化 Shell；每次调用仍要求交互确认。 |

如服务要求 API key，设置环境变量而不是写入命令行参数：

```bash
export HARNESS27_API_KEY='本机服务所需的 key'
python -m harness27 --model local-27b '只读检查工作区文件'
```

Harness 不把该 key 写入 HTTP 错误或请求轨迹；但启用 Shell 后，模型生成的命令继承当前进程环境，因此仍可能读到此变量。不要在共享或不可信环境中启用 Shell，也不要让工作区包含凭据。

## 5. Agent 能使用的工具

工具 schema 会随每个模型请求发送。参数必须是字段精确匹配的 JSON 对象，工具调用由模型以 Chat Completions 原生 `tool_calls` 形式返回。

| 工具 | 能力 | 限制 |
|---|---|---|
| `list_files` | 列出工作区目录的直接子项。 | 最多返回 200 项，不递归；跳过名为 `.git` 和 `.harness27` 的直接子项。 |
| `read_file` | 读取 UTF-8 文件。 | 最多读取 32 KiB；无效 UTF-8 使用替换字符返回；越界/非普通文件报错。 |
| `write_file` | 新建或替换 UTF-8 文件，必要时创建父目录。 | UTF-8 编码后最多 32 KiB；每次都要审批；通过临时文件加 `os.replace` 替换，避免覆写已存在目标的硬链接内容。 |
| `shell` | 在 workspace 作为当前目录运行命令。 | 默认不提供；启用后每次要审批，单命令默认超时 30 秒，输出合并且最多返回 32 KiB。它不是沙箱。 |

文件路径会解析为绝对路径并检查仍处于 workspace 内；通过符号链接逃逸会被拒绝。文件工具禁止访问 workspace 内相对路径中含 `.git` 或 `.harness27` 的位置。没有删除文件的工具。

路径检查是应用层约束，不是操作系统级沙箱。它不能覆盖恶意并发替换、特殊文件系统竞争条件或所有预先放置的敏感硬链接场景。请使用新建、可信、专用的工作目录，不要将个人目录、凭据目录或包含不可信链接的项目目录直接作为 workspace。

### 5.1 写入和 Shell 审批

CLI 会显示完整的工具名称和参数。只有交互终端中输入精确字符串 `yes` 才批准当次操作；其他输入、EOF 和非交互环境一律拒绝。没有跳过审批的 CLI 开关。

```bash
python -m harness27 --model local-27b --workspace ./scratch \
  --allow-shell '检查项目并运行测试'
```

Shell 可访问 workspace 以外的文件、继承的环境变量、当前用户权限和网络，并可启动子进程。输出截断不限制命令本身写入临时磁盘的大小。超时后 POSIX 下会尝试清理同进程组子进程，但不能保证杀掉主动脱离进程组的进程。要评估可能不可信的模型，请使用外部容器/虚拟机，禁用网络与凭据，并施加 CPU、内存、磁盘和进程限制。提示词和人工审批不能替代隔离。

## 6. 运行预算和结束状态

- 一次模型响应算一轮；最多 `--max-steps` 轮。每轮最多接受 16 个工具调用，调用按顺序执行。
- 每轮请求前，用当前 `messages` 的 JSON 序列化字符数检查 `--max-context-chars`。此值不是 tokenizer 预算，不含精确的推理服务上下文占用；超出时不会自动删历史或伪造成功。
- 若模型无工具调用且返回 `finish_reason=length`，Agent 返回 `length_truncated`；无工具调用且回答为空则作为协议错误处理。
- 到达轮数上限或字符预算上限时，结果会明确标记为 `step_limit` 或 `context_limit`。没有自动重试，避免远端重试和已执行工具副作用被意外重复。

命令行退出码：

| 退出码 | 含义 |
|---:|---|
| `0` | Agent 返回最终答案（`completed`）；不代表答案已被独立验证。 |
| `1` | 模型连接、HTTP 协议、文件系统或配置错误。 |
| `2` | 参数错误，或 Agent 因预算/输出截断等非完成状态停止。 |
| `130` | 用户中断。 |

## 7. 轨迹和敏感信息

每次 CLI 运行都会在当前工作目录下创建 `.harness27/runs/<UTC 时间>-<随机 ID>.jsonl`，逐事件 flush，事件含 trace schema version、时间戳和运行过程；工具事件也记录工具耗时。可用 `--task-id`、`--task-category`、`--config-id` 附加通过格式校验的非敏感短标签。轨迹可能包含：完整任务、模型文本回答、原生工具调用参数、工具结果/文件内容、模型提供的 reasoning 内容、usage 和结束状态。POSIX 下文件以 `0600` 权限创建，运行轨迹默认已被 `.gitignore` 排除。

轨迹不支持自动恢复执行。使用前评估其中的个人数据、密钥片段、源码和模型输出；按组织要求保护、备份或删除。benchmark JSON 报告与 Agent 的 JSONL 轨迹是不同产物；报告不保存完整对话或工具参数，详情见[能力评测手册](BENCHMARK_GUIDE.md)。如需在本机分析任务状态、事件时间线、工具错误和问卷结果，可运行[本地运行记录与过程分析工具](ANALYTICS.md)；分析报告会过滤原始内容，但输入轨迹仍是敏感数据。

## 8. Python API

可以直接组合 `LocalClient`、`Tools` 与 `Agent`。以下示例故意默认拒绝写入和 Shell：

```python
import os

from harness27.agent import Agent
from harness27.client import LocalClient
from harness27.tools import Tools

client = LocalClient(
    "http://127.0.0.1:8000/v1",
    model="local-27b",
    timeout=120,
    temperature=0.2,
    max_tokens=2048,
    api_key=os.environ.get("HARNESS27_API_KEY"),
)
tools = Tools("./workspace")  # 默认拒绝写入和 Shell

events = []
result = Agent(
    client,
    tools,
    trace=lambda event, data: events.append((event, data)),
    max_steps=12,
    max_context_chars=100_000,
).run("列出工作区文件并总结用途")
print(result["status"], result["answer"])
```

若传入自定义 `approve(name, args)`，调用方必须自行提供真实授权机制。`trace(event, data)` 中可能包含敏感内容，不应默认写到公共日志。

## 9. 运行测试与常见问题

运行不访问互联网、不需要权重：

```bash
python -m unittest discover -s tests -v
```

常见问题：

- **拒绝 `localhost`**：安全策略只接受回环 IP；改用 `127.0.0.1` 或 `[::1]`。
- **HTTP 404 / 模型报工具参数错误**：检查 base URL 是否以正确 API 前缀结束、served model 名是否正确，以及推理服务是否配置了该模型匹配的工具 parser/template。
- **模型用代码块“调用工具”却没有生成文件**：当前 harness 只执行原生 `assistant.tool_calls`，不会把文本代码块当作命令执行。
- **写入没有发生**：在交互终端检查审批参数并输入 `yes`；非交互流程自动拒绝。
- **日志中含文件内容**：这是审计轨迹设计的一部分；限制轨迹目录访问并按需清理。不要将它提交到 Git。
- **“离线”并不等于全机断网**：HTTP 客户端只连 loopback；模型服务本身和启用的 Shell 必须另行用网络策略约束。

端到端实际任务示例见[使用场景实例](USE_CASES.md)；详细故障排查见[故障排查手册](TROUBLESHOOTING.md)，Shell 隔离和运行产物保护见[安全部署操作说明](SECURITY_OPERATIONS.md)；任务数据采集设计见[流程改进方案](PROCESS_IMPROVEMENT.md)，逐次轨迹分析见[本地分析工具说明](ANALYTICS.md)；评测流程、用例范围、报告结构和可比性限制见[能力评测手册](BENCHMARK_GUIDE.md)。
