# case_20_packout_estimate：估算成品订单的纸箱与托盘数量

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `packaging_planning`　 **难度：** `easy`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为包装计划员，我想按 SKU 包装规格把合成成品数量换算为满箱、尾箱和托盘估算，以便团队可以在人工审核时预估包装物料和托盘需求。

## 业务背景与输入

按 SKU 包装规格把合成成品订单数量换算成满箱、尾箱、总箱数和托盘数量，让计划团队可以人工估算包装资源。

| 合成输入 | 内容与用途 |
|---|---|
| [`finished_orders.csv`](../../benchmark/cases/case_20_packout_estimate/fixture/finished_orders.csv) | 合成订单 ID、SKU 和成品单位数。 |
| [`packaging_specs.json`](../../benchmark/cases/case_20_packout_estimate/fixture/packaging_specs.json) | 每 SKU 每箱单位数和每托盘箱数。 |

## 计算规则与结果契约

- `full_cartons = units // units_per_carton`，`partial_carton_units = units % units_per_carton`。
- 有余数的尾箱仍计一个箱位；托盘数按总箱数向上取整。
- 最后一托的箱数使用余数；整托时等于每托容量，零箱订单为 0。
- 按 `order_id` 排序，所有数量字段均为 JSON 整数。

- **唯一允许新增的文件：** `packout_estimate.json`（JSON 数组；每项仅包含 `order_id`、`sku`、`units`、`full_cartons`、`partial_carton_units`、`carton_count`、`pallet_count`、`cartons_on_last_pallet`）。
- **完整验收准则：**
  - **AC-01：** 每个订单恰好输出一条记录，字段仅为 order_id、sku、units、full_cartons、partial_carton_units、carton_count、pallet_count、cartons_on_last_pallet。
  - **AC-02：** full_cartons 和 partial_carton_units 按 units_per_carton 做商和余数；尾箱只要有余数就计作一箱。
  - **AC-03：** carton_count = full_cartons + (partial_carton_units > 0)；pallet_count 按每托盘箱数向上取整；最后一托箱数按余数计算，整除时为满托。
  - **AC-04：** 包装规格按 SKU 查找，订单按 order_id 升序；数量字段均为整数。
  - **AC-05：** 只新增 packout_estimate.json；不打印标签、不打包/发运实体货物、不调用 Shell 或外部系统。

## 人工复核重点

- 区分尾箱内的单位数和尾箱本身占用的箱位；有尾箱时总箱数加一。
- 检查托盘向上取整、满托余数为满载，以及零数量边界。
- 结果只估算数量，不包含堆码、重量、标签、承运或实际发运约束。

## 范围外与安全边界

- 优化托盘堆码或重量分布
- 打印或贴附标签
- 创建发运单或预约承运
- 修改生产订单或库存
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
python benchmark/runner.py --model local-27b --case case_20_packout_estimate
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_20_packout_estimate/case.json)
- [模型任务提示词](../../benchmark/cases/case_20_packout_estimate/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_20_packout_estimate/verify.py)
