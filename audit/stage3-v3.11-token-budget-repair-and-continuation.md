# PER-61 交付报告：v3.11 token 预算一致性修复 + 续跑计划预登记（Stage 3B-5）

日期：2026-08-13 · 全程离线，零付费调用，零候选/模型请求，零密钥读取。

## 一、结论一览

| 项 | 值 |
|---|---|
| 修复方向 | **方向 (a)**：schema 累计上限改为反映会话累计语义（运行时请求数强制不变） |
| 累计 token 上限 | `max_model_requests × single_request_context_window` = **8 × 32768 = 262144** |
| 上限是否由观测用量反推 | **否**（budget-design 推导；观测 35,484–39,795 远低于该上限，仅作参考不作拟合） |
| 三模型对称 | 是（模型无关的 config `resource_budget` + 模型无关的 schema `usage`） |
| 续跑计划 | **550** 新 run identity = 10 作废 repeat-1 覆盖 + 90×3 repeat 2–3（540） |
| 与 v3.5–v3.10 历史 run id 交集 | **∅**（对 990 个历史 plan id 全量核验为 0） |
| v3.10 作废取证 | 永久保留（`invalidated-runs.json` 文件哈希绑定；覆盖运行不替换） |
| 可恢复执行路径 | **checkpoint/resume 内建于冻结 harness**（`live_acceptance_v3_11.mjs`），无外部驱动 |
| v3.5–v3.10 冻结产物 | 零漂移（bundle 逐 artifact 复算通过） |

## 二、根因与修复（方向 a，文档化）

**缺陷（10/10 同一类）**：`run_trace.schema.v3.10` 把累计 `usage.total_tokens` 上限钉在 32768（= 单请求 context window），而冻结执行循环只强制**请求数**预算（8）与单请求 wall-clock，从不强制累计 token 预算。多请求会话的累计 token 是逐请求 input+output 之和（上下文逐轮重发、随轮增长），8 请求长上下文会话合法累计 35,484–39,795 后产生不可冻结的 trace，冻结 validator 依 schema 拒绝。

**修复（方向 a）**：schema 的 `usage.total_tokens` 上限改为反映**会话累计**语义，取 budget-design 乘积：

```
max_total_tokens = max_model_requests × single_request_context_window = 8 × 32768 = 262144
```

- 每个请求的 input+output 受单请求 context window（32768，冻结传输层对三候选模型统一声明）约束；运行时强制请求数预算（8）。因此 262144 是「被强制的预算所能产生的累计用量」的一致上界——schema 上限与运行时强制由此一致。
- **该值不是从本轮观测到的 35k–40k 反推**：它是 8×32768 的设计乘积，对观测峰值有 >6× 裕量。config 中 `max_total_tokens_derivation.back_derived_from_observed_usage = false` 显式声明。
- config `resource_budget` 同时新增 `single_request_context_window: 32768` 字段并把推导块 `max_total_tokens_derivation` 写入冻结合同，保证推导**合同可见、可独立复核**。
- 三模型对称：上限位于模型无关的 `resource_budget` 与模型无关的 schema `usage`，对三候选模型完全相同；无任何按模型 ID 的语义特判。

**未选方向 (b) 的理由**：方向 (b) 需在执行循环新增累计 token 强制，会在触顶时截断长会话并改写作废/记录语义，属对执行行为的实质改动，且长上下文案例会被系统性截断，违背「最小变更」与长上下文评测目的。方向 (a) 仅改上限语义，行为保持。

## 三、变更范围最小化（程序化 diff）

程序化 diff 由 `audit/build_stage3_v3_11_diff.py` 生成，产物 `audit/stage3_v3_11_v3_10_programmatic_diff.json`。逐文件叶子级差异如下，全部落在允许范围：

| 文件 | 差异（仅列） |
|---|---|
| `run_trace_harness_config` | `resource_budget.max_total_tokens`(32768→262144)、新增 `resource_budget.single_request_context_window`、新增 `resource_budget.max_total_tokens_derivation`、新增 `token_budget_repair`、`execution.planned_run_cap`(810→550)、`contract_extension.*`、`contract_version`、`supersedes` |
| `run_trace.schema` | `usage.total_tokens.maximum`(32768→262144)、`run_identity.repeat`(const 1 → enum [1,2,3])、`$id`、`contract_version`、`run_identity.benchmark_id` |
| `reason_codes` | 仅 `contract_version`、`supersedes`（definitions 与 case_sets 逐字节不变） |
| `candidate_output_contracts` | 仅 `contract_version`、`supersedes` |
| `candidate_submission_wire_contract` | 仅 `contract_version`、`supersedes` |
| `stage3_independent_grader_result.schema` | 仅 `$id`、`contract_version` |
| 90 个 projection | 顶层仅 `contract_version`、`supersedes`；**非版本字段差异 = 0** |

`repeat` 从 const 1 放宽为 enum [1,2,3] 是续跑（repeat 2–3）可执行所必需的身份模式变更，不涉及 prompt/oracle/阈值/reason/案例材料。

**不变的判分相关面**（由测试逐一断言）：`system_prompt`、`tool_names`、`provider_retry_policy`、`security`、`fairness`、`request_commitments`；`resource_budget` 除 token 上限/推导/单请求窗口外逐字段相等；reason 定义与 90 case_sets；全部 projection 的 prompt/inputs/permissions/answer schema/evidence contract/reason contract；tool schema 哈希、snapshot 哈希、源案例哈希；clean-room oracle 对全部 90 案例的期望；grader 各检查（v3.11 与 v3.10 对同一输入输出相同 checks/failed_checks/derived_reason_codes）。

## 四、续跑计划（550 identity）

`contracts/stage3_acceptance_plan.v3.11.json`：

- **覆盖块（sequence 1–10，repeat=1）**：10 个作废 (案例,模型) 单元，按其 v3.10 执行序列排序。每个覆盖 run 通过 `plan.coverage_map` 映射到其作废的 v3.10 run_id/sequence；覆盖 run 是新 v3.11 identity（benchmark_id=v3.11、config/plan_core 为新哈希），与作废的 v3.10 run_id 不同。
- **扩展块（sequence 11–550，repeat 2–3）**：90 任务 × 3 模型 × 2 repeat = 540，repeat-major、case_id、固定模型序（与 v3.10 blocking 一致）。
- **种子公式延续**：`seed = int(sha256(canonical_json({benchmark_id, case_id, master_seed, repeat, requested_model_id}))[:16],16) mod 2^32`，master_seed=20260813 不变，仅 benchmark_id 升为 v3.11；order-independent。550/550 已在清洁室逐一重推（seed+run_id+identity 精确相等）。
- **零交集**：对 v3.5–v3.10 全部 plan（990 个历史 run id，含已执行 450 与 v3.10 预登记未执行部分）交集 ∅。
- **作废取证永久保留**：`replication_design.v3_10_invalidation_forensics` 绑定 `invalidated-runs.json` 文件哈希 `e6cf5d98…`、report_sha256 `657761b1…`、entry_count=10、`grading-failures/` 目录；`coverage_replaces_or_reexecutes_invalidation=false`。覆盖运行绝不静默替换或重评作废单元。

## 五、可比性声明（260 个 v3.10 冻结单元）

**结论：260 个 v3.10 冻结单元在 v3.11 下保持有效且可比。** 供独立审计核验的具体项目：

1. v3.10 冻结产物（trace/grader/checkpoint）继续按其原 v3.10 合同冻结，不被重评、不被重算（`retroactive_regrading=false`，bundle 逐 artifact 零漂移）。
2. v3.11 相对 v3.10 的唯一语义变化是**累计 total_tokens 上限**；该字段不参与任何判分检查（status/reason/value/证据/计算/权限/终态等均与 token 无关）。
3. clean-room oracle 对全部 90 案例在 v3.10 与 v3.11 projection 下输出**完全一致**（测试 `test_oracle_and_grader_outputs_are_identical_to_v310_for_all_90_cases`）。
4. grader 对同一 candidate/projection/snapshot/trace 在 v3.10 与 v3.11 下产生**相同 checks、failed_checks、derived_reason_codes**（仅 contract_version 标签与 grader_sha256 不同）。
5. tool schema、snapshot、源案例哈希在 v3.10 与 v3.11 之间逐字节相等（测试 `test_tool_schema_commitments_are_identical_to_v310`）。
6. 260 个 v3.10 冻结 trace 的 total_tokens 均 ≤32768，天然落在 v3.11 的 262144 上限内——即便以 v3.11 schema 复核也全部可冻结。

**不可比项：无。** 因此不存在版本混版或需要处置的不可比单元；260 个 v3.10 单元与后续 550 个 v3.11 单元可在同一判分口径下合并分析（合并分析属后续报告阶段，且须声明合同版本）。

## 六、可恢复执行路径（决策：内建于冻结 harness）

v3.11 选择**将 checkpoint/resume 语义纳入冻结 harness**（方向 a），不再依赖外部驱动：`harness/live_acceptance_v3_11.mjs` 原生提供

- **finalized-skip**：trace/grader/candidate/checkpoint 齐备且 checkpoint 哈希链复算至 run_completed 终态、与 trace 终态一致的单元原样跳过、产物零改动；
- **partial/inconsistent 硬停止**：任何非终态残留一律硬停止，绝不静默重跑；
- **作废通道（report-only）**：仅对显式声明、且磁盘状态为已消耗但不可冻结的单元记录取证并继续；guard rail 拒绝对 pending/finalized 单元的作废请求；
- **判分失败取证持久化**（`grading-failures/`，脱敏）。

上述语义由 Node 集成测试直接验证（finalized-skip、partial 硬停止、550-run 合成端到端）。外部驱动 `audit/driver_v3_10_live_resume.mjs` 属 v3.10 轮历史产物，保留供审计对照，不用于 v3.11。

## 七、零漂移与离线门

- v3.5–v3.10 bundle 及其全部 artifact 逐一复算通过（`verify-contracts`，valid=true，errors=[]）。
- 离线门全绿：`verify-contracts`、`verify-plan`、`scan-fixtures`(0 findings)、`gold-report`(valid)、`gate-report`(90/90 visible)。
- 回归：Python 222/222（198 既有 + 24 新增 v3.11）；Node 78/78（65 既有 + 13 新增 v3.11）。
- 清洁室预执行核验 `audit/verify_v3_11_continuation_pre_execution.py`：21/21 PASS（哈希复算 + plan_core 独立重构 + 550 identity 重推 + 取证映射 + 零交集 + 授权清单导出）。

## 八、冻结哈希

| 产物 | SHA-256 |
|---|---|
| **bundle**（`bundle_sha256`，content-hash） | `b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d` |
| bundle 文件哈希 | `760a32cccedfdcc5126dd6f78d8ad024e00216e24e0b0b23c69689a174a171c1` |
| **plan_sha256** | `c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c` |
| plan 文件哈希 | `83b3710b91814c930897fced1d9d27e26627e47ab17d72fc52f4dc17e792c7a8` |
| **plan_core_sha256** | `559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604` |
| **config 文件哈希** | `bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e` |
| run_trace.schema.v3.11.json | `fb14da23222b19f82b7157fa551ebacf0b0697e8ffbd4d118b4b6f7e90d02027` |
| reason_codes.v3.11.json | `f16f47059c95b6d083afef57ece3979519abdd8d25c989d4d8e8185f0ced31ee` |
| candidate_output_contracts.v3.11.json | `817db749da451fb8dcccc427f0ef7271d623fa5951f124c99434cb739563deb0` |
| candidate_submission_wire_contract.v3.11.json | `0596d6b08593fd5e33f7e6fcd49da7197f30f04974f8c9f862aaf8682d2808d4` |
| stage3_independent_grader_result.schema.v3.11.json | `7f7cdd9fa47420d014da8e7f8fbe4214f5111b7a76dcbe8cd9ac1aa1c3654383` |
| run_trace_validator_v3_11.py | `4bda365768e6044da24a23de93e284e9fd52e3c2dee66c2fc3a2bf2c5568b0bd` |
| harness/acceptance_v3_11.py | `ecf1af3ac1ab779042986fd527a5cda3c5c0e12948f9f482732104c52eaa651b` |
| harness/live_acceptance_v3_11.mjs | `5f8c99520f0ff7203be1a73b1b646b46395fe35bd292c8500243f0178a296fec` |
| v3.10 invalidated-runs.json（取证，保留） | `e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1` |

## 九、可复现命令

```bash
# v3.11 离线门
uv run python -m harness.acceptance_v3_11 verify-contracts
uv run python -m harness.acceptance_v3_11 verify-plan
uv run python -m harness.acceptance_v3_11 scan-fixtures
uv run python -m harness.acceptance_v3_11 gold-report
uv run python -m harness.acceptance_v3_11 gate-report

# 程序化 diff（v3.10 -> v3.11）
uv run python audit/build_stage3_v3_11_diff.py

# 清洁室预执行核验（550 identity / 取证映射 / 零交集）
uv run python audit/verify_v3_11_continuation_pre_execution.py

# 回归（Python 222 / Node 78）
uv run python -m unittest discover -s tests
node --test tests/integration/*.test.mjs
```

## 十、禁止项遵守情况

- 本轮**未**发起 preflight、任何候选/付费模型请求；未读取/记录任何密钥（全部持久化产物经递归密钥扫描 0 findings）；未进行真实交易。
- **未**覆盖或重评 v3.5–v3.10 冻结产物（逐 artifact 零漂移）；**未**按模型 ID 写语义特判；**未**按候选观测用量或历史答案校准预算/oracle/阈值（上限为 budget-design 推导，oracle/阈值/案例材料不变）。
