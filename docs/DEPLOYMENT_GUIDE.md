# 本机推理服务部署与兼容性指南

本文补充如何判断一个本机模型服务能否与 Harness27 配合。文中的服务地址和命令是**配置示例，不是经过本项目逐版本认证的兼容性承诺**；具体行为取决于推理引擎、模型、量化、chat template、tool parser 和部署参数。

Harness27 不下载或启动权重、不探测服务端模型身份，也不替推理引擎选择模板或工具解析器。请把模型服务配置和 Harness 的客户端参数分别记录。

## 1. Harness27 需要的接口

### 网络地址

Harness27 请求 `POST {base_url}/chat/completions`。例如：

```text
base_url: http://127.0.0.1:8000/v1
request:  POST http://127.0.0.1:8000/v1/chat/completions
```

客户端只接受字面回环 IP 地址（如 `127.0.0.1`、`[::1]`），不接受 `localhost`、主机名或远端 IP；也会拒绝 URL 凭据、query、fragment 和 HTTP 重定向，并忽略代理环境变量。`--base-url` 应填写 API 前缀，不要把 `/chat/completions` 本身作为 base URL，否则路径会重复。

### Chat Completions 与原生工具调用

服务需接受这些请求字段：`model`、`messages`、`temperature`、`max_tokens`、`stream: false`、`tools` 和 `tool_choice: "auto"`。服务还必须能够：

1. 在 assistant 响应中返回原生 `tool_calls`，而不是仅把工具调用意图写成普通文本或代码块；
2. 为每个调用返回唯一非空 `id`、`type: "function"`、函数名，以及**JSON 字符串**形式的 `function.arguments`；
3. 接收 Harness 后续发回的 assistant 工具调用和对应 `role: "tool"` / `tool_call_id` 结果消息；
4. 返回 `choices[0].message`，其 `role` 为 `assistant`，文本 `content` 为字符串或空值。

一轮最多接受 16 个工具调用；Harness 按顺序执行它们。HTTP 状态码正常、普通文本能生成，并不表示原生工具调用协议可用。模型服务返回的 `finish_reason` 和 `usage` 会用于状态与评测统计；没有 `usage` 时不代表实际 token 消耗为零。

## 2. 常见本机服务的配置核对表

| 服务 | 常见本机 base URL 示例 | `--model` 应填 | 必须按实际部署核对 |
|---|---|---|---|
| vLLM | `http://127.0.0.1:8000/v1` | `--served-model-name` 的注册值 | 已安装版本是否支持该模型对应的 auto tool choice、tool parser 和 chat template；权重/量化与并行配置。 |
| Ollama | `http://127.0.0.1:11434/v1` | Ollama 服务中可用的模型名 | 当前版本与具体模型是否通过 OpenAI 兼容路由返回所需的原生 `tool_calls`，以及 `tool_call_id` 往返格式。 |
| llama.cpp server | `http://127.0.0.1:8080/v1` | 服务注册的模型名 | 当前构建、模型 chat template 和工具调用格式是否配套；确认服务接受并返回本指南列出的字段。 |

这些是常见默认地址，端口与路由可被部署配置改变。该表不表示所有版本、模型或启动参数均已由 Harness27 验证。首选做法是先在不启用 Shell 的前提下完成下面的最小工具调用检查。

## 3. vLLM 命令模板

以下模板适用于“权重已在本机、已安装 vLLM”的起点；必须把模型目录和 parser 替换为**该模型及当前 vLLM 版本明确支持**的值，并按需配置 chat template、量化、上下文长度和多卡参数。

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export MODEL_DIR=/absolute/path/to/your-model
export TOOL_PARSER=your_model_supported_parser

vllm serve "$MODEL_DIR" \
  --served-model-name local-model \
  --host 127.0.0.1 --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser "$TOOL_PARSER"
```

不要照抄一个与模型不匹配的 parser/template：这可能导致服务启动失败、工具调用变成文本，或产生不符合 Chat Completions 结构的响应。其他服务请使用其对应版本的官方启动参数；Harness27 不会替这些服务配置权重或推理选项。

## 4. 最小端到端检查

先用一个新建的、无敏感数据的目录放置探针文件，并保持 Shell 关闭：

```bash
mkdir -p ./workspace/deployment-smoke
printf 'probe marker 27\n' > ./workspace/deployment-smoke/probe.txt
python -m harness27 \
  --model local-model \
  --base-url http://127.0.0.1:8000/v1 \
  --workspace ./workspace/deployment-smoke \
  '请用文件工具读取 probe.txt，并准确复述其中的内容；不要写文件，也不要运行命令。'
```

检查以下证据，而不仅是“模型回答看起来正常”：

- Harness 返回完成状态，且最终回答与文件内容一致；
- `.harness27/runs/` 中该次 JSONL 轨迹包含 `assistant` 事件里的原生 `tool_calls`，以及成功的 `read_file` 工具事件；
- `probe.txt` 没有改变。

工具调用由模型选择，单次任务不保证模型一定采用工具。若它只凭提示词复述、未产生 `read_file` 事件，这次检查不能证明原生工具调用链路正常。轨迹可能含完整提示词和工具数据，完成排查后按组织策略保护或清理。

也可先运行 `python benchmark/runner.py --list-cases` 确认本地用例被发现；此命令不连接模型。首次实际评测优先选择 `case_04_csv_reconciliation` 等禁用 Shell 的用例，评测说明见[能力评测手册](BENCHMARK_GUIDE.md)。

## 5. 网络命名空间与离线边界

Harness 的模型客户端只能连接**当前网络命名空间的回环地址**。若 Harness 和推理服务在互不共享网络命名空间的容器中，容器里的 `127.0.0.1` 通常分别指向各自容器；改成宿主机 IP 或容器 DNS 名称又会被 Harness 拒绝。部署时应设计可验证的本机连接方式（例如让两进程共享受控网络命名空间），并在启用 Shell 前另行隔离网络。

“客户端只访问 loopback”不等于整台机器断网：推理服务自身、模型加载器和可选 Shell 的网络行为需要由操作系统、容器或虚拟机策略分别控制。服务若使用 API key，可通过 `HARNESS27_API_KEY` 环境变量传入；启用 Shell 时该环境变量会被子命令继承，故不应在带凭据的环境中启用 Shell。

## 6. 建议记录的部署信息

进行故障排查或比较评测时，至少记录：

- 模型准确标识、权重来源/版本及量化；不要只写“27B”；
- 推理引擎及版本、服务端模型别名、tokenizer、chat template、tool parser；
- 硬件、GPU 并行/显存设置、上下文长度与服务端采样配置；
- Harness 分支/commit、Python 版本、完整非敏感 CLI 参数；
- 工具调用探针是否出现 `tool_calls`，以及测试日期和报告路径。

Chat Completions API 通常不会向 Harness 证明权重或服务端配置，因此这些信息需要部署/实验操作员自行维护。安全运行要求见[安全部署操作说明](SECURITY_OPERATIONS.md)，常见错误排查见[故障排查手册](TROUBLESHOOTING.md)。
