# case_18_scrap_reason_summary：按报废原因码汇总合成损耗数量

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `quality_operations`　 **难度：** `easy`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为制造质量分析员，我想按产品和报废原因码汇总合成损耗数量及事件数，并标记未映射原因码，以便团队可以看见待复核的损耗分布，而不让模型臆测根本原因。

## 业务背景与输入

对合成报废事件按 SKU 与原因码做数量和事件数汇总，以便质量团队看见分布并单独复核未映射代码，而不由模型猜根因。

| 合成输入 | 内容与用途 |
|---|---|
| [`scrap_events.csv`](../../benchmark/cases/case_18_scrap_reason_summary/fixture/scrap_events.csv) | 合成 SKU、reason code 和报废数量事件。 |
| [`scrap_reason_map.json`](../../benchmark/cases/case_18_scrap_reason_summary/fixture/scrap_reason_map.json) | 已知原因码到类别的显式映射。 |

## 计算规则与结果契约

- 按 SKU、原因码分组；报废单位数为数量之和，事件数为行数。
- 类别只使用 JSON 映射；未知原因码标成 `unmapped`，不推断类别。
- 结果按 SKU、原因码排序；数值字段输出为整数。

- **唯一允许新增的文件：** `scrap_summary.json`（JSON 数组；每项仅包含 `sku`、`reason_code`、`category`、`scrap_units`、`event_count`）。
- **完整验收准则：**
  - **AC-01：** 按 sku、reason_code 分组，scrap_units 为 quantity 总和，event_count 为记录条数。
  - **AC-02：** category 严格使用 scrap_reason_map.json 映射；未映射代码标为 unmapped，不猜测类别。
  - **AC-03：** 每个分组恰好一条记录，字段仅为 sku、reason_code、category、scrap_units、event_count。
  - **AC-04：** 按 sku、reason_code 升序；数量和事件数为正整数。
  - **AC-05：** 只新增 scrap_summary.json；不改变工艺、物料或生产记录，不调用 Shell 或外部系统。

## 人工复核重点

- 复核分组后的单位总和和事件数，避免只统计数量或只统计行数。
- 未知代码必须保留并标记 `unmapped`，不可从名称推测原因。
- 汇总不构成根因分析、纠正措施、库存调整或真实 QMS/MES 记录。

## 范围外与安全边界

- 推断或确认根本原因
- 变更设备参数、工艺或供应商
- 自动报废/返工或调整库存
- 写入真实 QMS/MES
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
python benchmark/runner.py --model local-27b --case case_18_scrap_reason_summary
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_18_scrap_reason_summary/case.json)
- [模型任务提示词](../../benchmark/cases/case_18_scrap_reason_summary/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_18_scrap_reason_summary/verify.py)
