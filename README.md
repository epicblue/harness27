# Harness27

基于 **Python 3.10+** 的离线 Agent 执行框架，通过本机 OpenAI 兼容的 `POST /v1/chat/completions` 接口调用已部署的 27B 模型。Python 运行时仅使用标准库，无云端 SDK、遥测或自动下载。

> 这是 Agent harness，不是模型训练或基准评测程序。权重加载和 GPU 推理由 vLLM、Ollama、llama.cpp 等独立服务负责。模型规模不被客户端强制校验，实际使用的 27B 模型由服务端决定。

## 快速开始

### 1. 准备本机模型服务

需提前准备推理引擎、依赖、模型权重与 tokenizer。断网机器应事先完成传输；本仓库不包含权重。服务必须支持：

- Chat Completions 消息协议；
- `tools`、`tool_choice: auto` 和原生 `assistant.tool_calls`；
- 接收 `role: tool` 和 `tool_call_id` 工具结果。

仅能生成文本、但不能生成原生工具调用的模型/聊天模板不能直接用于本应用。不同模型的工具解析器不同，需要依照所安装推理引擎及模型的说明配置，不要仅凭“OpenAI 兼容”判断其支持工具调用。

**vLLM 示例模板（Linux，已安装 vLLM 和本地权重）：**

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
# 必须将下面两个值改成你的本地权重目录及该模型适用的解析器。
export MODEL_DIR=/absolute/path/to/your-27b-model
export TOOL_PARSER=your_model_supported_parser
vllm serve "$MODEL_DIR" \
  --served-model-name local-27b \
  --host 127.0.0.1 --port 8000 \
  --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER"
```

这不是适用于所有 27B 模型的通用启动命令：有些模型还需要专用 chat template、量化参数、上下文长度和多卡设置。27B 的 FP16/BF16 权重约 54 GB（十进制），INT4 理论权重约 13.5 GB；实际运行还需量化元数据、KV cache 和其他内存，不能据此保证某张显卡能运行。

其他本机服务的连接参数：

| 服务 | `--base-url` 示例 | `--model` |
|---|---|---|
| vLLM | `http://127.0.0.1:8000/v1` | `--served-model-name` 的值 |
| Ollama | `http://127.0.0.1:11434/v1` | 已在本机安装且支持 tools 的模型名 |
| llama.cpp | `http://127.0.0.1:8080/v1` | 该服务注册的模型名；需启用适配的工具调用模板 |

### 2. 运行 harness

在仓库根目录直接运行，无需安装依赖：

```bash
mkdir -p workspace
python -m harness27 \
  --model local-27b \
  --base-url http://127.0.0.1:8000/v1 \
  --workspace ./workspace \
  '列出当前文件，然后创建一个带类型标注的 Python 斐波那契函数和测试文件。'
```

写入文件会显示完整参数，并要求在交互终端中输入 `yes`。非交互运行自动拒绝写入和命令执行，不提供绕过审批的 CLI 开关。

可选安装 CLI 入口（需事先具备 setuptools 等构建依赖）：

```bash
python -m pip install --no-index --no-build-isolation -e .
harness27 --model local-27b '查看工作目录里的文件'
```

启用命令工具：

```bash
python -m harness27 --model local-27b --workspace ./workspace \
  --allow-shell '检查当前 Python 项目，运行测试并分析结果。'
```

每条 Shell 命令仍需人工确认。**Shell 不是沙箱**，启用前请阅读安全说明。

如本地服务要求 API key，可设置环境变量 `HARNESS27_API_KEY`；不会把 key 写进请求轨迹。环境变量本身仍可能被启用的 Shell 读取。

## 功能与预算

- 多轮 `模型 → 工具 → 模型` 执行，串行处理每轮工具调用，最多 16 个。
- 工具：`list_files`、`read_file`、`write_file`；可选 `shell`。
- 路径限制在指定 workspace 内，包括解析符号链接；禁止文件工具访问 `.git`、`.harness27`。
- 文件读写及 Shell 返回文本上限 32 KiB；目录单次最多列出 200 项。
- Shell 默认关闭；启用后单条命令超时为 30 秒。在 POSIX 上清理同进程组子进程。
- 模型参数：`--temperature 0.2`、`--max-tokens 2048`、`--timeout 120`。
- 执行预算：`--max-steps 12`、`--max-context-chars 100000`。
- 超预算明确停止，不自动丢弃历史或伪造成功；字符预算不等价于 tokenizer 的 token 数，需根据实际模型上下文调整。
- 无自动重试，避免请求重试与工具副作用造成意外重复执行。

完整参数：`python -m harness27 --help`。

## 轨迹与返回值

每次运行写入当前目录的 `.harness27/runs/<时间>-<ID>.jsonl`，逐条 flush，包含任务、模型输出、工具结果、推理耗时和结束状态。文件以 `0600` 权限创建（POSIX）。可用于审计和定位失败，不支持自动恢复执行。

退出码：

| 代码 | 含义 |
|---|---|
| 0 | 模型给出了最终回答，不代表已通过独立正确性验证 |
| 1 | 模型连接、协议、文件系统或配置错误 |
| 2 | 轮数/上下文预算耗尽，或 CLI 参数错误 |
| 130 | 用户中断 |

## 离线与安全边界

1. 客户端只允许回环 **IP**（`127.0.0.1` / `[::1]` 等），拒绝域名、远程 IP 和 HTTP 重定向，并忽略代理环境变量。容器部署时 harness 必须能在同一网络命名空间连接模型服务。
2. 这些限制只约束模型 HTTP 客户端。模型服务自身是否联网需单独配置；启用的 Shell 也可能联网。真正断网请使用主机/容器网络策略。
3. 文件工具的路径校验不是 OS 级沙箱，不能抵御恶意并发修改目录/符号链接、预先放置的敏感硬链接或所有特殊文件系统场景。只使用专门的、可信的工作目录，不要挂载凭据或个人文件。
4. Shell 使用当前用户权限，可访问工作目录外的文件、继承环境变量并启动进程。应在无凭据、无网络、限制 CPU/内存/磁盘的隔离容器中运行，并检查每次审批内容。命令输出先落临时文件，返回值虽然截断，临时磁盘占用仍需 OS 配额约束。POSIX 进程组清理不保证清除主动脱离进程组的进程。
5. 轨迹含任务、文件内容及模型输出，可能包含敏感信息；请设置合适的存储权限并定期清理。`.gitignore` 默认排除轨迹、workspace 和 models。
6. 模型输入、工具输出和生成的代码均不可信；人工审批与提示词不能替代安全隔离。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试不依赖模型权重，也不访问互联网；包含模拟多轮 Agent 和真实回环 HTTP 测试服务。覆盖文件审批、路径穿越/符号链接、硬链接覆写保护、无效工具参数、调用结构验证、预算、读文件截断、Shell 超时以及远程 URL/重定向拒绝。

尚未在实际 27B 模型上完成端到端验证。接入实际服务后，建议先执行只读任务，再验证文件写入审批与工具结果回传。

## 代码结构

```text
harness27/
  client.py     本机推理接口与响应校验
  agent.py      多轮 Agent 状态循环与预算
  tools.py      工作目录文件工具、审批、可选 Shell
  cli.py        命令行、轨迹记录、退出状态
  __main__.py   python -m harness27 入口
tests/
  test_harness.py
```

在 Python 中也可直接组合 `LocalClient`、`Tools` 和 `Agent`。`Tools` 默认拒绝任何写入和 Shell 操作；若自定义 `approve(name, args)` 回调，调用方负责实现真实的授权机制。`trace(event, data)` 回调可用于接入自定义审计存储。
