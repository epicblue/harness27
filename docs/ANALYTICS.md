# 本地运行记录与过程分析工具

Harness27 CLI 已将每次 Agent 执行写为 `.harness27/runs/<UTC 时间>-<随机 ID>.jsonl`。本地分析器 `harness27.analytics` 可以把这些过程记录转成**不含任务正文/工具内容**的逐次摘要和汇总，并可选关联任务后问卷。分析在本机完成，不发送网络请求，也不引入第三方依赖。

> 原始 JSONL 是高敏感审计轨迹：可能含完整任务、模型回答、文件内容、工具参数、工具结果和 reasoning。分析报告只导出固定字段，但输入轨迹仍应按敏感数据保护和清理。

## 1. 给每次任务加安全标签

运行 CLI 时，可选填写非敏感的任务/配置标签：

```bash
python -m harness27 \
  --model local-27b \
  --task-id invoices_01 \
  --task-category data_transformation \
  --config-id q4_vllm_local \
  --workspace ./workspace/task-01 \
  '按要求处理本次任务……'
```

标签仅接受 48 字符以内的小写字母、数字、`_`、`-`，且以字母或数字开头。它们写入该次 trace 的 `start` 事件，不会加入模型提示词；不要把姓名、客户号、文件路径、URL、API key 或任务正文作为标签。每次运行开始时 CLI 会打印轨迹路径，文件名去掉 `.jsonl` 的部分就是 `session_id`，可用于关联任务后问卷。

未提供标签时仍会保存正常轨迹并计算未分组指标，未分类任务不会自动推断类别。旧版轨迹同样可分析；较旧工具事件若没有计时字段，工具耗时显示为缺失，而不是 0。旧 trace 若没有结构化 `approval` 决策，也不会推断批准次数；存在未知审批事件时相应计数为 `null`，并报告不完整 session 数。

## 2. 生成报告

从仓库根目录：

```bash
# 默认扫描 .harness27/runs，生成带唯一 ID 的本地 JSON 报告
python -m harness27.analytics

# 显式指定范围和输出；需要归档时使用唯一文件名
python -m harness27.analytics \
  --runs-dir .harness27/runs \
  --format json \
  --output .harness27/analytics/analysis-20261004-a.json

# 输出逐任务 CSV，便于在本机表格工具中进一步处理
python -m harness27.analytics \
  --format csv \
  --output .harness27/analytics/sessions-20261004-a.csv

# 将 JSON/CSV 写到 stdout（适合管道，但需自行保护接收端）
python -m harness27.analytics --format json --output -
```

如果安装了项目 CLI 入口，也可运行 `harness27-analyze --help`。报告默认写入 `.harness27/analytics/`；POSIX 下输出文件以 `0600` 创建，目录请求 `0700` 权限。指定已有报告路径会原子替换该报告；分析器会拒绝覆盖输入轨迹或问卷 CSV。自定义输出位置时，请自行检查父目录权限。

## 3. 指标和过程时间线

JSON 报告包含：

- `sessions[]`：每次运行的 session ID、任务标签、Agent 状态、步骤数、开始/结束时间和脱敏 `timeline`；
- `timeline[]`：按顺序记录 `start`、`assistant`、`tool`、`finish`、`error` 等事件，只保留事件类型、step、工具名、成功/拒绝状态和耗时等白名单字段；
- 模型请求耗时、工具调用/实际工具错误/审批拒绝分别计数、文件写入与 Shell 审批请求/批准/拒绝计数、工具名计数、服务返回的 token usage；
- `summary`：完成状态分布、中位 wall duration / step 数、工具错误率，以及（问卷/验证 CSV 提供时）任务结果和独立验证通过率；
- `by_task_category`、`by_config_id`：有填写标签时按任务类别和配置标签分组；
- `survey`：可选问卷的评分分布、中位数和 friction tag 计数；
- 数据质量计数：损坏 JSONL 行、不可读轨迹和未匹配问卷行。

时间口径：`duration_seconds` 是第一条到最后一条可解析 trace 时间戳的间隔；`assistant_seconds` 是每轮模型 HTTP 请求耗时之和，不等于 GPU 纯推理时间；`tool_seconds` 是工具参数解析、人工审批等待（若有）及工具执行的墙钟耗时之和，不是纯执行耗时。`prompt_tokens` 等仅汇总服务实际返回的 usage 字段，没有 usage 时保留为 `null`，不把缺失误记为零。

`tool_error_rate` 的分母是工具调用事件总数减去明确记录的审批拒绝；它包括参数/路径校验失败，拒绝操作单独统计，不算工具执行错误。`completed_rate` 只表示 Agent 返回 `completed` 的比例，**不代表任务正确率或用户满意度**。可在问卷 CSV 中填写受限枚举 `task_outcome` 与 `independent_verification`，分析器会分别汇总；CLI trace 本身没有独立 verifier。拒绝一次危险操作是安全行为，不应自动算作负面体验。

### 报告明确不会导出的字段

分析器不导出任务正文、模型回答、reasoning、模型别名、工具参数、文件路径、文件内容、工具输出和问卷开放文本。未知/自由文本 CSV 列会被忽略。任务分类只能由安全标签或问卷中的固定 ID 提供；分析器不通过模型猜测任务类别。

## 4. 关联任务后问卷

按[流程改进调查方案](PROCESS_IMPROVEMENT.md)收集问卷。保存为 UTF-8 CSV，至少包含 `session_id`；可选列如下。每个 session ID 一行，重复 ID 会报错。

```csv
session_id,task_id,task_category,config_id,task_outcome,independent_verification,q1_start_clarity,q2_progress_visibility,q3_approval_control,q4_result_checkability,q5_effort_time,q6_troubleshooting,q7_reuse,friction_tags
20261004T120000Z-a1b2c3d4,invoices_01,data_transformation,q4_vllm_local,completed,passed,4,5,4,3,4,3,5,tool_call;docs
```

`task_outcome` 接受 `completed`、`partial`、`failed`、`aborted`、`infrastructure_error`；`independent_verification` 接受 `passed`、`failed`、`not_available`、`pending`。两列由操作人员或独立 verifier 填写，不应由体验问卷的自我评价替代。七个评分列接受 `1`–`5`、空值或 `N/A`（“不适用”也可写空值）。`friction_tags` 使用分号分隔的固定代码：`setup`、`tool_call`、`file_ops`、`approval`、`latency_timeout`、`budget`、`docs`、`result_validation`、`safety_privacy`、`none`、`other`。问卷的开放题可保存在受限本机文件中供人工定性分析，但不会被分析器读取或并入报告。

```bash
python -m harness27.analytics \
  --runs-dir .harness27/runs \
  --survey-csv ./private-survey.csv \
  --output .harness27/analytics/analysis-with-survey-a.json
```

问卷行通过 `session_id` 与 trace 关联。无匹配的行只计数，不把其文本放进报告；若标签与 trace 冲突，保留 trace 标签并在质量计数中指出。共享报告前，仍应审查参与者自填的标签和输出路径。

## 5. 建议的每次任务工作流

1. 选择合成/脱敏 workspace；如要分析分组，传入 `--task-id`、`--task-category`、`--config-id`。
2. 运行任务并保管 CLI 输出的轨迹路径；不要把 JSONL 当作普通、可公开的运行日志。
3. 可选：参与者填入本次 `session_id` 并完成短问卷，CSV 保存在受限本机位置。
4. 运行分析器，查看任务时间线、状态、工具错误和按任务类别分组的数据；把 `completed` 与独立验证结果分开报告。
5. 根据[流程改进方案](PROCESS_IMPROVEMENT.md)登记问题和改动，下一轮使用同一任务/配置复测。
6. 按组织保留期限清理原始 trace、问卷和报告；不要提交到 Git、外部工单或未经批准的云端表单。

## 6. 当前限制

- 分析器只扫描 `--runs-dir` 的直接子目录中的 `*.jsonl`，不会递归搜索，也不会扫描 benchmark JSON 报告。
- 只有 Harness CLI JSONL 有标准时间戳和事件包装；通过 Python API 自定义的 trace 回调格式不一定能直接解析。
- 报告不做模型评分、归因或统计显著性检验；样本少时应把汇总当作流程诊断线索。
- 分析器不联网、不自动上传数据，也不生成网页仪表盘；如需共享/展示，先审查报告并使用组织批准的本地工具。
