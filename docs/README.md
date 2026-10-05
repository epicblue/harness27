# 项目文档

Harness27 使用本机已部署的模型服务运行受限 Agent 任务，并通过小型、可复跑的 benchmark 摸清实际能力边界。按目的查看：

## 上手与运行

- [使用说明](USER_GUIDE.md)：环境准备、Agent 参数、工具审批、Python API 和基础常见问题。
- [本机服务部署与兼容性指南](DEPLOYMENT_GUIDE.md)：Chat Completions/原生工具调用要求、vLLM/Ollama/llama.cpp 配置核对和最小连通性检查。
- [故障排查手册](TROUBLESHOOTING.md)：按错误表现排查地址、连接、协议、工具调用、预算和评测状态。
- [安全部署操作说明](SECURITY_OPERATIONS.md)：安全边界、workspace/轨迹保护，以及启用 Shell 时的外部隔离核对清单。

## 使用与评测

- [使用场景实例](USE_CASES.md)：配置提取、敏感约束、CSV 对账、库存补货、软件安装顺序计划、支持工单分派、会议室分配、制造批次质检、生产物料齐套、组件批次追溯、OEE、设备校准、维修分级、换型、来料对账、标签审核、报废汇总、停机统计、包装估算、产能核对、代码修复和只读巡检的端到端示例。
- [能力评测手册](BENCHMARK_GUIDE.md)：用例、CLI 参数、Shell 权限、报告解读、扩展用例和实验规范。
- [制造业 benchmark 用户故事详解](use_cases/README.md)：case 12–21 的独立故事页，含合成输入、验收契约、复核重点和非操作范围。

## 流程改进

- [数据采集与调查方案](PROCESS_IMPROVEMENT.md)：隐私优先的任务指标、短问卷、可选访谈和复测闭环。
- [本地运行记录与过程分析工具](ANALYTICS.md)：按任务生成脱敏事件时间线和汇总报告，可关联问卷评分。

## 架构与边界

- [系统设计文档](DESIGN.md)：模块架构、类图、交互式 Harness 与 benchmark 时序图、协议、安全模型和已知限制。
- 根目录的 [README](../README.md) 是项目简介和快速入口。

权重、推理服务和实际部署配置不包含在本仓库中。当前二十一用例 suite 属早期 smoke suite；在真实 27B 服务上运行并记录配置前，不应将仓库测试结果解释为模型实测结论。
