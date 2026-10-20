# 引用与复现实验

如果 GymTS 支持了你的研究或工程结果，请引用实际使用的软件版本或提交，并分别引用
所用模型、数据集、算法和上游项目。仓库提供 [CITATION.cff](../CITATION.cff)，目前
没有为 GymTS 指定可核实的论文、DOI 或归档发布日期。

GymTS 采用 [MIT License](../LICENSE)，`CITATION.cff` 的许可标识为 `MIT`。
引用软件不能替代保留版权与许可声明；所用第三方模型、数据和上游项目仍按各自条款处理。

## 软件引用

下面是当前工作树的引用模板；运行发布版本时，把版本、提交和访问日期替换为真实值。
不要把 `Unreleased` 工作树的结果归为未经核实的公开发行。

```bibtex
@software{gymts,
  author = {{GymTS contributors}},
  title = {GymTS: Time-series experiment execution and independent evaluation},
  version = {0.5.0},
  url = {https://github.com/Jurmean/GymTS},
  note = {Record the exact commit or source archive hash used in your experiment}
}
```

## 复现材料应包含什么

- GymTS、适配包和原生依赖的真实版本/提交，模型及数据制品摘要。
- 固定 ExperimentSpec / EvaluationSpec、解析计划、seed、执行限制和可见范围。
- 运行状态、全部预期单元、缺失/无效/失败计数，以及固定评分政策和独立参考版本。
- 封存 Run / CAS / Snapshot 与评价报告引用，或有权限访问这些材料的方法。
- 数据、模型和代码各自的使用/分发权限；不能将私有答案或访问令牌作为公开附件。

工程 Gate 通过不等于模型质量提升。复现说明需区分接口验证、训练参数更新、指标结果
和生产服务验收；保持原 Run 不变并为新评分创建新报告。详见[使用手册](user-guide.md)。
