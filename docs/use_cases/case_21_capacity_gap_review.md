# case_21_capacity_gap_review：核对产品需求与产线可用分钟数

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `production_planning`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为产能计划员，我想把合成产品需求与对应产线的可用分钟数和标准节拍进行比较，以便团队可以在排产评审前识别产能余量或缺口，而不把估算结果误当成已确认计划。

## 业务背景与输入

将合成日期/SKU 需求与对应产线的可用分钟快照合并，估算运行分钟并显示非负容量缺口，作为排产评审的一个输入。

| 合成输入 | 内容与用途 |
|---|---|
| [`capacity_policy.json`](../../benchmark/cases/case_21_capacity_gap_review/fixture/capacity_policy.json) | 秒/分钟换算常量及整数分钟规则。 |
| [`line_capacity.csv`](../../benchmark/cases/case_21_capacity_gap_review/fixture/line_capacity.csv) | 对应日期/SKU/产线的可用分钟和标准节拍。 |
| [`production_demand.csv`](../../benchmark/cases/case_21_capacity_gap_review/fixture/production_demand.csv) | 合成工作日期、SKU、需求单位数。 |

## 计算规则与结果契约

- 按工作日期和 SKU 连接需求与产线能力。
- `required_run_minutes = ceil(demand_units × ideal_cycle_seconds / seconds_per_minute)`。
- `capacity_gap_minutes = max(required_run_minutes - available_minutes, 0)`；缺口为零标记 `capacity_sufficient`，否则为 `capacity_gap`。
- 每个日期/SKU 一条记录，按日期、SKU 排序；需求与分钟字段为整数。

- **唯一允许新增的文件：** `capacity_review.json`（JSON 数组；每项仅包含 `work_date`、`sku`、`line_id`、`demand_units`、`required_run_minutes`、`available_minutes`、`capacity_gap_minutes`、`status`）。
- **完整验收准则：**
  - **AC-01：** 每个日期与 SKU 恰好输出一条记录，字段仅为 work_date、sku、line_id、demand_units、required_run_minutes、available_minutes、capacity_gap_minutes、status。
  - **AC-02：** required_run_minutes = ceil(demand_units × ideal_cycle_seconds / 60)。
  - **AC-03：** capacity_gap_minutes = max(required_run_minutes - available_minutes, 0)；零缺口为 capacity_sufficient，否则为 capacity_gap。
  - **AC-04：** 按 work_date、sku 升序连接并输出，分钟数为整数。
  - **AC-05：** 只新增 capacity_review.json；不安排或释放工单、不调整班次、不调用 Shell 或生产系统。

## 人工复核重点

- 分钟换算要向上取整，不能把部分分钟截掉。
- 缺口非负；可用时间充足时不输出负“富余”值，而使用零缺口状态。
- 快照没有建模换型、停机、良率和人员限制；不自动分配产线或改排程。

## 范围外与安全边界

- 跨产线优化或重新分配需求
- 考虑未提供的换型、良率或人员因素
- 自动改排产或释放工单
- 连接 MES/APS 或控制设备
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
python benchmark/runner.py --model local-27b --case case_21_capacity_gap_review
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_21_capacity_gap_review/case.json)
- [模型任务提示词](../../benchmark/cases/case_21_capacity_gap_review/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_21_capacity_gap_review/verify.py)
