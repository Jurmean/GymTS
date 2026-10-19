# GymTS 设计

## 总体框架

**GymTS 把一份时序实验计划运行成任务结果与可复核的记录，并按评价方案形成报告。**

整套设计的主线是：

**实验计划 → 环境观测与交互 → 任务结果及其证据 → 评价结论。**

![image\.png](图片和附件/image.png)

GymTS 内部以 **EnvironmentTS** 完成环境接入、实验运行与记录，以 **AutoBenchTS** 完成测试与评价。

算法、模型或 Agent 是运行中选定的调用对象；

LibraryTS 提供可复用的实现与制品；GymTS 按计划通过调用适配，将选定实现装配为本次 Run 的 Candidate。

## 阅读建议



