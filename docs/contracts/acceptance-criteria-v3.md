# 场景与结论可复现可追溯验收口径 v3（基线 v3 世代）

- contract_type: `scenario_conclusion_reproducibility_criteria`
- criteria_version: `3.0.0`
- status: `frozen`
- frozen_by_issue: PER-328（父议题 PER-323，C-323-16）
- mutation_policy: 只增版本、不回写；候选表现、排名诉求和演示案例不得反向改变
  权重、阈值、案例或排除规则。

## 0. 结论血缘与适用范围

**直接证据**：PER-330 复现了 v2 grader 的宽松 mapping、对象密钥扫描旁路、
policy invariant 缺实现，以及两份许可元数据为 `redistributable=false` 的行情原始
响应。C-323-16 选择发布 baseline v3 / 口径 v3。

**基于证据的工程结论**：v2 的通过结论失效，只保留为历史失败证据；本口径仅约束
v3 新运行和 v3 冻结验收，不追溯改写 v2。v3 继续采用「证据完整 + 结论可重算」
边界，不要求模型输出、提供商端点或环境的确定性重放。

**说明性案例**：`project_synthetic` 快照只用于验证工具参数、权限和状态控制，
不得当作真实证券价格或任何投资判断证据。

## 1. 六节点证据链

| 节点 | 冻结锚点 | 验收 |
| --- | --- | --- |
| N0 场景输入 | `baseline/v3/cases/`、`snapshots/` | 内容哈希、时点、许可、引用通过 `validate-bundle` |
| N1 运行构成 | `configs/inference.json`、`configs/harness_contract.v1.json`、v3 bundle hash | trace 绑定实算配置与不可变 bundle |
| N2 运行轨迹 | `run_trace.schema.v5.json` | 身份、权限、预算、状态、redaction 与 run_id 可校验 |
| N3 候选输出 | submission 原对象 | 结构校验后直接执行对象级密钥扫描 |
| N4 grader | `grader_contract.frozen.v3.json`、`graders/baseline_v3.py` | 纯函数重评分逐字段一致 |
| N5 结论 | v3 policy 的 Gold-only CSR；Silver 仅诊断 | 汇总可由 N4 重算，排除与分母一致 |

运行证据 bundle 的 `bundle.manifest.json` 是 NB 入口，逐件 sha256 自证；代码级
重放、付费端点重放和真实交易不在本口径授权或验收范围内。

## 2. 核心判定

1. **时点与口径**：只使用 cutoff 前可得记录；十进制字符串、单位、会计与价格
   口径逐位一致。
2. **证据血缘**：material 记录引用达到预注册最低数；capture → snapshot → case →
   trace → grader commitments 链完整。
3. **结论验证**：mapping 采用严格键集合和递归全对象相等，禁止用期望对象的真子集
   匹配含附加字段的 submission；Gold 期望由生产/独立 oracle 双算一致。
4. **方法适用性**：submission `method_id` 必须等于案例预注册方法；否则 invariant
   失败，不能以值碰巧相同放行。
5. **弃权与升级**：非答案动作与理由码执行精确集合；正确弃权为正向结果，错误弃权
   单独报告。
6. **权限与最终状态**：observed operations 无重复且为 allowed operations 子集；
   final environment state 与预注册完整对象相等。
7. **密钥纪律**：直接扫描 submission 对象；字段名与值形状任一命中均使
   `no_sensitive_data_disclosure=false`。

policy 允许的八项 invariant 必须与 grader `SUPPORTED_INVARIANTS` 完全一致；未知、
重复或未实现 invariant 是契约错误，不得降级为候选失败。

## 3. 数据许可与三层证据标注

- v3 只接受 `sec_edgar` 公有领域数据与 `project_synthetic` 项目自编 CC0 fixture；
  capture、snapshot、case 的许可元数据必须一致且 `redistributable=true`。
- `redistributable=false` 的内容不得进入 v3，即使访问本身是公开只读。
- 研究类答案必须逐主张标注 `research_direct_evidence`、`financial_inference` 或
  `illustrative_case`；合成数据结论固定属于说明性案例，不得外推为市场事实。

## 4. A/B/G 验收门

- A1：manifest 无缺件、无未登记件，逐件 sha256 与 bundle hash 相符。
- A2：case/snapshot 内容哈希、时点、许可、变体与引用语义全部通过。
- A3：run_trace v5 的身份、权限、状态、redaction 与密钥门通过。
- A4：配置/hash/commitments 回指实际使用的 N0–N3 工件。
- A5：grader contract 的逐件 hash 与聚合 hash 重算一致。
- B1：逐运行重评分与落盘评分行逐字段一致。
- B2/B3：批级统计与报告可从 Gold grader 行确定性重算；Silver 不进入主排名。
- G1–G5：A/B 全过、降级留痕、受影响结论退出声称用途。
- G6-v3：双 oracle 一致、八 invariant 可执行、三组审计负例先失败后通过、v2 固定
  哈希零漂移、许可清单全为可再分发、无密钥/付费调用/真实交易。

任一门失败即不得冻结或发布排名。`traceable / partially_traceable / untraceable`
三档沿用口径 v1：不一致优先于缺失，缺失不等于失败也不等于通过。

## 5. 残余边界

- 最小 v3 只有 4 族，不主张地域、语言、会计准则或全场景代表性。
- 未注册统计显著性阈值，模型比较只具诊断意义，不得发布可靠全局排名。
- SEC 后续修订另起 snapshot revision；不回写冻结件。
- provider 线上身份与可用性须在另行授权的只读预检中验证，本基线不执行付费调用。

冻结锚点由 `baseline/v3/baseline_manifest.frozen.v3.json` 的版本、`frozen_at`、
`build_source_commit` 和 `bundle_sha256`，以及 PER-328 完成评论中的最终提交 SHA 共同组成。
