## Financial Agentic Index 报告契约 v1

本阶段只冻结输入、输出、验证和演示隔离规则，不制作最终榜单。报告生成器只接受独立审计已签署且结果哈希已冻结的输入；所有结论绑定报告 ID、不可变模型 ID、框架版本、数据快照、评测日期与六类上游 SHA-256。

### 发布边界

- 主榜只使用 Gold，知识工作与工具工作严格各占 `0.500000`。Silver 只能进入诊断附录；成本和延迟只展示，不进入排名。
- 只有完整矩阵才能发布主榜。失败、阻塞、排除和缺失必须由 `state_counts` 显式覆盖；部分运行必须附 `INCOMPLETE_MATRIX` 限制并给出 withheld 原因，不能把未运行单元当作零错误。
- `run_records` 是已经运行单元的机器可读明细；`missing` 是预期矩阵与明细之差，并在 failures ledger 中以一个带精确数量和证据引用的汇总条目保存。失败与阻塞逐 run 保存失败代码、证据引用和失败步骤。
- HTML 与 Markdown 来自同一 bundle，生成过程不读取当前时间或网络，因而相同输入产生逐字节稳定输出。HTML 使用 `lang`、跳转链接、语义化 `main`、表格 caption 和列标题 scope，且状态含文本标签。

### 说明性案例隔离

每份报告选择 6–8 个案例，允许按典型差异、失效模式、不确定性校准或成本延迟权衡进行说明性选择。选择必须在模型身份揭盲前完成并承诺案例顺序哈希；揭盲记录保留时间、保管人和 blind ID 到不可变模型 ID 的映射。

每个案例必须并排展示所有候选的最终答案、工具轨迹引用、证据链引用、环境状态引用、失败步骤、成本、延迟和不确定性。报告及每个案例都固定 `illustrative_only=true`、`affects_ranking=false`，且 `selection_weight_override=false`；验证器拒绝演示调权或把案例选择反向用于综合分。

### 字段与 provenance

规范文件是 `reporting/spec.report.v1.json`，结构 schema 是 `contracts/report_bundle.schema.v1.json`，机器语义由 `reporting/report.py` 进行严格验证。核心字段如下：

| 区块 | 作用 |
| --- | --- |
| `report_identity` | 报告、框架、快照与日期身份 |
| `audit` | 独立签署人、签署时间与冻结结果哈希 |
| `provenance` | 结果、评分政策、预注册、Harness、运行清单与数据快照哈希 |
| `run_coverage` / `run_records` | 完整或部分运行状态及逐运行事实 |
| `ranking` / `model_reports` | Gold 主榜门控与能力、可靠性、安全、成本、延迟、不确定性 |
| `failures` / `limitations` | 失败证据、阻塞、缺失和适用限制 |
| `demonstrations` | 选择、盲化/揭盲审计与 6–8 个并排回放 |
| `reproduction` | 可执行复现步骤和产物清单 |

### 验证与复现

```bash
python3 reporting/report.py validate tests/fixtures/reporting/report.partial.valid.json
python3 reporting/report.py render tests/fixtures/reporting/report.partial.valid.json \
  --markdown tests/expected/reporting/report.partial.valid.md \
  --html tests/expected/reporting/report.partial.valid.html
python3 -m unittest discover -s tests -v
python3 reporting/report.py verify-freeze
```

fixture 是明确标为 partial 的结构示例，故主榜必须被 withheld。它不代表任何真实模型结果，也不能用于对外结论。
