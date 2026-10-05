# case_19_downtime_duration_summary：汇总设备停机事件持续时间

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `operations_metrics`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为设备可靠性分析员，我想从合成停机事件的 UTC 起止时间计算各设备和原因码的累计分钟数与事件数，以便维护团队可以用可复核的统计摘要开展后续分析，而不依赖手工计时。

## 业务背景与输入

从合成停机事件的 UTC 起止时间计算持续分钟，并按设备与原因码形成汇总，帮助可靠性团队复核统计口径。

| 合成输入 | 内容与用途 |
|---|---|
| [`downtime_events.csv`](../../benchmark/cases/case_19_downtime_duration_summary/fixture/downtime_events.csv) | 合成设备 ID、原因码和 UTC 起止时间。 |
| [`downtime_policy.json`](../../benchmark/cases/case_19_downtime_duration_summary/fixture/downtime_policy.json) | 时间口径标记及聚合说明。 |

## 计算规则与结果契约

- 每条事件时长为 `end_utc - start_utc` 的整分钟数，且结束时间晚于开始时间。
- 按 `asset_id`、`reason_code` 分组；`event_count` 为行数，`downtime_minutes` 为分钟数总和。
- 结果按设备 ID、原因码排序，输出计数为整数。

- **唯一允许新增的文件：** `downtime_summary.json`（JSON 数组；每项仅包含 `asset_id`、`reason_code`、`event_count`、`downtime_minutes`）。
- **完整验收准则：**
  - **AC-01：** 每个 asset_id、reason_code 组合恰好一条记录，字段仅为 asset_id、reason_code、event_count、downtime_minutes。
  - **AC-02：** 每次持续分钟数等于 end_utc 与 start_utc 的时间差；总时长为同组各事件之和。
  - **AC-03：** event_count 为事件行数，downtime_minutes 为整数分钟。
  - **AC-04：** 按 asset_id、reason_code 升序输出，不遗漏事件或重复分组。
  - **AC-05：** 只新增 downtime_summary.json；不控制设备、不修改日志、不调用 Shell 或外部系统。

## 人工复核重点

- 按 UTC 解释时间戳，统一采用结束减开始，不用事件先后顺序猜时区。
- 先逐事件核对分钟差，再核对分组事件数与总分钟数。
- 该汇总不判断停机根因，不表示设备当前状态，也不生成维修工单。

## 范围外与安全边界

- 推断停机根因或设备责任
- 自动复位、启停或控制设备
- 创建维护工单或改生产计划
- 连接真实 PLC/MES/CMMS
- 只处理此用例目录中的合成 fixture；只在 Runner 创建的独立评测工作区生成指定 JSON。
- `shell` 为 `disabled`；Agent 不调用 Shell/网络工具，也不访问 PLC、打印机、MES、ERP、WMS、QMS、CMMS、APS 或其他外部系统。
- verifier 检查 fixture 完整性、输出 schema/内容、工作区文件边界及禁用工具轨迹；通过只表示通过此固定合成任务的自动校验。

## 复现与验证

离线运行新增用例的 verifier 单测（不连接模型服务）：

```bash
python -m unittest tests.test_benchmark.BenchmarkVerificationTests.test_cases_12_to_21_manufacturing_verifiers_are_deterministic_and_shell_free -v
```

如需通过 Runner 向已配置的本机兼容服务发起此 case，可将 `local-27b` 替换为服务实际注册的模型名：

```bash
python benchmark/runner.py --model local-27b --case case_19_downtime_duration_summary
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_19_downtime_duration_summary/case.json)
- [模型任务提示词](../../benchmark/cases/case_19_downtime_duration_summary/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_19_downtime_duration_summary/verify.py)
