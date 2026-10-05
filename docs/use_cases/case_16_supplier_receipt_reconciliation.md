# case_16_supplier_receipt_reconciliation：核对采购订单与来料接收数量

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `supply_chain_operations`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为来料计划员，我想将采购订单行与多次收货记录汇总，区分已接收、拒收、未到和超收数量，以便团队可以在人工复核时发现交付差异，而不把拒收数量误当成合格库存。

## 业务背景与输入

把合成采购订单行与多次收货记录按稳定 ID 汇总，明确区分合格接收量、拒收量、未到数量和超收情况，供来料团队人工对账。

| 合成输入 | 内容与用途 |
|---|---|
| [`po_lines.csv`](../../benchmark/cases/case_16_supplier_receipt_reconciliation/fixture/po_lines.csv) | 合成采购订单行、SKU 和订购数量；ID 按字符串保留。 |
| [`receipts.csv`](../../benchmark/cases/case_16_supplier_receipt_reconciliation/fixture/receipts.csv) | 按订单行记录的多次接受/拒收数量。 |

## 计算规则与结果契约

- 按 `po_id`、`line_id` 关联；没有收货行时 accepted 和 rejected 均为 0。
- `received_qty = accepted_qty + rejected_qty`；拒收算已到货，但不算合格或可用库存。
- `outstanding_qty = max(ordered_qty - received_qty, 0)`；按总到货数量标记短收、完成或超收。
- 订单 ID、行 ID、SKU、状态为字符串；所有数量为 JSON 整数；每个订单行输出一次。

- **唯一允许新增的文件：** `receipt_reconciliation.json`（JSON 数组；每项仅包含 `po_id`、`line_id`、`sku`、`ordered_qty`、`accepted_qty`、`rejected_qty`、`received_qty`、`outstanding_qty`、`status`）。
- **完整验收准则：**
  - **AC-01：** 每个采购订单行恰好输出一条记录；按 po_id、line_id 升序。
  - **AC-02：** accepted_qty、rejected_qty 分别汇总该行所有收货记录；received_qty = accepted_qty + rejected_qty。
  - **AC-03：** outstanding_qty = max(ordered_qty - received_qty, 0)；received_qty 小于/等于/大于 ordered_qty 时分别为 short_received/complete/over_received。
  - **AC-04：** 输出数值均为整数，并保留 accepted 与 rejected 的区分。
  - **AC-05：** 只新增 receipt_reconciliation.json；不更新采购单、库存或供应商记录，不调用 Shell 或外部系统。

## 人工复核重点

- 无收货记录的订单行仍须保留在报告中，数量按零处理。
- 不能把拒收误计为合格库存，也不能让超收的未到数量变成负数。
- ID 是字符串，即使内容看起来像数字也不要转换成整数。

## 范围外与安全边界

- 自动验收或拒收实体物料
- 将接收数量入库
- 更新采购订单或供应商交期
- 联系供应商或连接 ERP/WMS
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
python benchmark/runner.py --model local-27b --case case_16_supplier_receipt_reconciliation
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_16_supplier_receipt_reconciliation/case.json)
- [模型任务提示词](../../benchmark/cases/case_16_supplier_receipt_reconciliation/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_16_supplier_receipt_reconciliation/verify.py)
