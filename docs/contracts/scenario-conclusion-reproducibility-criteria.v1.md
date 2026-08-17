# 场景与结论可复现可追溯验收口径（历史轨迹日志复盘）

- contract_type: `scenario_conclusion_reproducibility_criteria`
- criteria_version: `1.0.0`（口径 v1）
- status: `frozen`
- frozen_by_issue: PER-317（父议题 PER-316，Stage 1 双轨之一）
- frozen_at: 2026-08-17（以冻结提交的 git commit 为冻结锚点，见附录 A）
- mutation_policy: 本口径只增版本、不改写。修订须另起 `*.v2.md` 新版本文件并附书面理由；
  任何候选结果、排名诉求或复盘便利性都不得反向修改本口径。
- 上位依据：
  - PER-316-D1（用户已确认）：验收口径调整为"场景与结论可复现可追溯（历史轨迹日志复盘）"，
    代码级可复现重放不作要求。
  - PER-316-D2（agent 推断，已按本口径固化）：PER-257-D4/D8 的"重跑"预期被上述指令取代，
    暂不全量重跑；PER-257-D6 历史基线纪律（旧冻结产物内容不改不删）继续有效。
  - PER-85-D6：旧 v3.x 冻结血缘降级为历史基线；路径/哈希钉住不再构成重构与验收阻塞，
    其处置由 `financial_agent_reliability/relocation.py` 放行清单机制承担。

## 0. 定位与适用范围

本口径定义"一次评测运行的验收与事后复盘以什么为准"的标准，供 Stage 2 复盘建设与
Stage 3 独立审计直接执行，无需口头补充。它**不修改任何已冻结产物**（contracts/、
preregistration/、snapshots/、runs/、evidence/、audit/、reports/、catalog/、cases/
均按 AGENTS.md 冻结纪律原样保留），也不新增契约版本；发布新契约版本仍属评测交付负责人
裁决权限。

适用对象：

- 历史运行：已以 v3.x 契约执行、证据 bundle 落盘于 `evidence/` 的全部运行；
- 未来运行：本口径生效后新执行的运行，必须在运行期即满足第 2 节全部节点的落盘要求。

不适用：对候选模型行为的"再次执行并比对输出"。模型输出的确定性重放不是本口径的
验证手段（见 1.3）。

## 1. 定义与边界

### 1.1 场景可复现（Scenario Reproducibility）

对任一历史运行，其**评测场景输入**可以由冻结产物原样重建，重建结果与运行时实际使用的
输入逐字节一致（以 sha256 为准）。场景输入包括：

1. 用例投影卡（candidate case card，`cases/candidate_vX/case-*.json`），其内容由冻结的
   v2 case card（`case_card.schema.v1.json`，contract_version `1.0.0`）与登记的
   reason/decimal 契约确定性投影而来；
2. 数据快照（`snapshots/**/data_snapshot.*.json`，`data_snapshot.schema.v1.json`，
   contract_version `1.0.0`），即时点冻结的只读证据数据；
3. 运行构成件：harness 配置（`contracts/run_trace_harness_config.vX.json`）、验收计划
   （`contracts/stage3_acceptance_plan.vX.json`）、验收契约 bundle
   （`contracts/stage3_acceptance_contracts.frozen.vX.json`）与 seed 推导规则。

判定基准："场景可复现"等价于**上述工件存在、版本明确、内容哈希可逐一对上**；
不要求重新执行 agent。

### 1.2 结论可追溯（Conclusion Traceability）

对任一历史运行，其**评分与排名结论**可以由已落盘的历史轨迹日志与冻结评分件重算推导，
且重算结果与当时发布的结论一致。结论链条为：

`场景输入 → agent 运行轨迹（run_trace/会话日志）→ grader 输入输出 → 评分与排名结论`

判定基准：链条上每一节点均有落盘工件与版本标识（第 2 节），且**确定性重算**通过——
用冻结的 grader 实现与政策对落盘的候选输出重新评分，逐行等于落盘评分结果；用预注册
登记的指标定义对评分行重新聚合，等于发布的统计与排名结论。"可追溯"等价于**结论可以
从历史记录重新算出来**，而不是"结论当时被记录过"。

### 1.3 与代码级可复现重放的边界

本口径**明确不要求**以下三项（PER-316-D1 的边界落地）：

1. **模型输出确定性重放**：不要求以相同 seed/参数再次调用模型得到逐字节一致的响应。
   run_trace 中的 `seed`、`payload_sha256`、`parameters_sha256` 继续作为**身份与请求
   记录**保留，但不承担"重放后必须一致"的验收职能。提供商侧非确定性、端点演进、
   模型版本更替不构成运行失效理由。
2. **代码 + 环境依赖逐哈希重放**：不要求重建与运行时逐字节一致的虚拟环境、
   node_modules、操作系统与依赖树来"原样重跑"。源码与依赖的哈希钉住仅作为
   历史基线记录（见 4.2），不作为复盘的前置重建条件。
3. **网络/提供商端点重放**：不要求重新访问运行时的提供商端点或外部数据源。
   运行时即已约束 `network_scope ∈ {none_offline_fixture, bailian_inference_only}`、
   数据只读冻结快照（`environment.dataset_access = frozen_read_only`），复盘只依赖落盘件。

相应地，本口径**继续要求**：落盘证据的内容完整性（逐 sha256 校验）与评分/聚合环节的
确定性重算（grader 与指标计算是纯函数，见 `grader_contract.frozen.v2.json` 的
mutation_policy）。放弃的是"重放执行"，不放弃的是"证据完整 + 结论可重算"。

### 1.4 对象单位

| 单位 | 定义 | 身份标识 |
| --- | --- | --- |
| 运行（run） | 一次 `(case_id, variant_id, requested_model_id, repeat)` 的完整执行 | `run_id = run_ + sha256(canonical(run_identity))[:32]` |
| 证据 bundle | 一次验收集批运行的落盘证据目录 | `evidence/stageN/<运行目录名>/`，以 `bundle.manifest.json` 为入口 |
| 结论 | 评分行、统计量、排名与验收判定 | 以 bundle 内 `summary.json`、grader 行与报告 bundle 为准 |

## 2. 必备证据要素：全链路最小证据字段与版本标识

对照现行 `contracts/` 契约族（case_card、data_snapshot、grader、run_trace、acceptance
五类加报告契约），一次"可复现可追溯"运行必须落盘以下六个节点。每个节点给出**最小证据
字段**与**版本标识**；缺任何一项即触发 3.4 的降级标注。

### 节点 N0：场景输入（case_card + data_snapshot）

| 最小证据字段 | 契约对照 |
| --- | --- |
| `case_id`、`revision`、`status=frozen`、`task`（domain/prompt/inputs/required_tools/permissions/initial_state）、`temporal`（event_time/as_of/available_at_cutoff）、`oracle`（spec_version、implementation、implementation_sha256、expected_status、expected_value、reason_codes）、`evidence_refs[]`（snapshot_id、record_ids、snapshot_sha256、evidence_type）、`quality`（tier、ranking_eligible、independently_recomputable）、`integrity.content_sha256` | `contracts/case_card.schema.v1.json`（contract_version 1.0.0） |
| `snapshot_id`、`revision`、`source`、`access`（public_read_only、prohibited_scopes）、`temporal`（event_time/as_of/available_at/retrieved_at）、`records[]`（record_id、evidence_type、source_locator、payload）、`lineage`（collector_version、query_args、raw_response_sha256、code_revision）、`integrity.content_sha256` | `contracts/data_snapshot.schema.v1.json`（contract_version 1.0.0） |
| 用例数据捆扎校验结论 | `contracts/case_data_contracts.frozen.v1.json`、`contracts/validate_case_data.py` |

版本标识：`contract_version`（卡/快照均为 1.0.0）、`revision`、`integrity.content_sha256`
（规范化算法 `financial-agent-c14n-json-v1` + sha256）。时点纪律
（`future_information_prohibited = true`、available_at_cutoff）是场景可复现的金融语义
基础，随本口径继续强制。

### 节点 N1：运行构成（验收契约 bundle + 配置 + 计划 + seed）

| 最小证据字段 | 契约对照 |
| --- | --- |
| `benchmark_id`、契约 bundle 全量 artifacts 清单（逐文件 path+sha256）与 `bundle_sha256`、`supersedes`/`preserved` 链、`retroactive_regrading=false` | `contracts/stage3_acceptance_contracts.frozen.vX.json`（当前最新 v3.11） |
| harness 配置全文与 sha256（含工具 schema、`package.json` 根相对钉住、离线/网络边界） | `contracts/run_trace_harness_config.vX.json` |
| 计划全文与 `plan_core_sha256`（任务清单、投影路径、快照路径、repeat 矩阵） | `contracts/stage3_acceptance_plan.vX.json` |
| seed 推导规则（`seed = int(sha256(canonical_json({benchmark_id, case_id, master_seed, repeat, requested_model_id}))[:16], 16) mod 2^32`，order-independent） | 登记于计划与 run_trace 契约 |

版本标识：`contract_version`（如 3.11.0）、`bundle_sha256`、`harness_config_sha256`、
`plan_core_sha256`。

### 节点 N2：agent 运行轨迹（run_trace）

| 最小证据字段 | 契约对照 |
| --- | --- |
| `run_id`、`run_identity`（benchmark_id、case_id、harness_config_sha256、plan_core_sha256、repeat、requested_model_id、seed、variant_id） | `contracts/run_trace.schema.vX.json`（当前最新 v3.11） |
| `provider`（name、requested_model_id、response_model_id、endpoint_id） | 同上 |
| `logical_requests[]`：phase、model_id、seed、payload_sha256、tool_schema_sha256、parameters_sha256、retries_used、classification、attempts[]（http_status、response_model_id、时间戳、tokens、provider_error_code、assistant_action_valid） | 同上 |
| `tool_events[]`：sequence、tool_name、success、input_sha256、output_sha256、operation、record_id、state_before/after_sha256、ledger_transition（可由轨迹独立重放账本状态链） | 同上 |
| `environment`（dataset_access=frozen_read_only、ledger_mode=simulated、real_side_effects=false、network_scope、initial/final_ledger_sha256）、`permission`（declared_permissions、observed_operations、violations）、`redaction`（applied=true、secret_leakage_detected=false） | 同上 |
| `checkpoint`（event_count、final_event_sha256）、`status`、`failure`（class/code）、`result`（candidate_scored、structured_output_valid、candidate_output_sha256） | 同上 |

版本标识：`contract_version`（与 schema 版本一致）+ 与之配套的校验器
`contracts/run_trace_validator_vX.py`（v3.11 对应 `run_trace_validator_v3_11.py`，
src 布局下同名实现位于 `src/financial_agent_reliability/harness/acceptance_vX.py`）。
轨迹以 `evidence/<bundle>/traces/run_<id>.json` 落盘，并被 bundle manifest 逐件钉住。

### 节点 N3：候选输出（candidate output）

| 最小证据字段 | 契约对照 |
| --- | --- |
| 结构化候选答案全文与 sha256（与 trace 的 `result.candidate_output_sha256` 一致） | `contracts/candidate_output_contracts.vX.json`、`contracts/candidate_submission_wire_contract.vX.json` |
| 提交动作（submit_candidate_answer / submit_candidate_non_answer）与理由码词汇 | `contracts/reason_codes.vX.json` |

版本标识：输出契约 `contract_version` + `candidate_sha256`。落盘位置
`evidence/<bundle>/candidates/run_<id>.json`。注意现行轨迹契约规定
`raw_provider_response_stored = false`（脱敏纪律）：复盘锚点是**落盘的候选输出**，
不是提供商原始响应——这与 1.3 第 1 条一致。

### 节点 N4：grader 输入输出

| 最小证据字段 | 契约对照 |
| --- | --- |
| grader 捆扎：grader_policy.v1.json、grader.py、grader_v2.py、sealed_row_bridge_v2.py、grader_result.schema.v1.json、预注册 v1/v1.1、验收清单与对应测试的逐件 sha256 及 `contract_bundle_sha256`；mutation_policy（append-only，候选表现永不改捆扎） | `contracts/grader_contract.frozen.v2.json` |
| 逐运行独立评分行：`commitments`（candidate_sha256、trace_sha256、projection_sha256、snapshot_sha256）、checks 组、derived_reason_codes、状态/值/理由码判定 | `contracts/stage3_independent_grader_result.schema.vX.json`（当前最新 v3.11） |
| 汇总行束：family_id、variant_id、model_label、repeat、critical_invariants、end_to_end_complete、evidence_correct/required、expected_action/actual_action、max_loss_level、total_cost_usd、latency_ms、excluded(+exclusion)、`preregistration_sha256`、model_manifests | `contracts/grader_result.schema.v1.json` |

版本标识：grader 捆扎 `manifest_version`（2.0.0）+ `contract_bundle_sha256`；
评分 schema `contract_version`；`preregistration_sha256`。落盘位置
`evidence/<bundle>/graders/run_<id>.json`。`commitments` 四哈希是 grader 结论回指
N0–N3 的链锚：复盘时必须逐一回验。

### 节点 N5：评分与排名结论

| 最小证据字段 | 契约对照 |
| --- | --- |
| 批级汇总：counts、by_model、frozen_input_hashes（bundle_content_sha256、plan_sha256、config_sha256）、authorization_basis | `evidence/<bundle>/summary.json`（contract_type stage3_financial_acceptance_summary） |
| 指标定义与排名纪律：Gold CSR、correct_abstention_rate、pass^k、排除规则、显著性与门槛、主假设判据 | `preregistration/benchmark_preregistration.v1.json` / `v1.1.json`（以 `preregistration_sha256` 引用） |
| 对外发布报告：报告捆扎逐件 sha256 与 `contract_bundle_sha256`、mutation_policy | `contracts/report_contract.frozen.v1.json`（含 `reporting/spec.report.v1.json`、`contracts/report_bundle.schema.v1.json`） |

版本标识：summary `contract_version`、预注册版本 + sha256、报告捆扎
`contract_bundle_sha256`。

### 节点 NB：证据 bundle 链锚（横切 N0–N5）

`evidence/<bundle>/bundle.manifest.json`：contract_type/contract_version、status=frozen、
plan_sha256、config_sha256、contract_bundle_sha256、preflight_sha256、
authorization_basis（授权评论/议题指引）、`artifacts[]`（逐文件 path+sha256）。
它是复盘入口：manifest 钉住目录内全部落盘件，完整性校验自它展开。

## 3. 复盘验证方法

### 3.1 复盘对象与入口

复盘单位 = 一个证据 bundle（批级）或其中一条 run（单运行级）。入口：

1. 确定 `evidence/stageN/<运行目录名>/`；
2. 读 `bundle.manifest.json` 获取 contract_version 与全部钉住件；
3. 按 contract_version 选定对应的 schema 与校验器版本（v3.x 系列逐版本配套，
   不跨版本混用校验器）。

### 3.2 最小步骤

- **R1 完整性**：对 manifest `artifacts[]` 逐文件重算 sha256，与登记值比对；
  目录内存在但未被 manifest 登记的文件一律视为污染，复盘结论标注"完整性存疑"。
- **R2 场景重建**：按 manifest 与计划中的 case/snapshot 路径定位场景输入；重算
  case/snapshot 的 `integrity.content_sha256`（c14n 规范化后）并与文件内登记值比对；
  校验 case 卡 `evidence_refs[].snapshot_sha256` 与对应快照文件一致；
  校验 case/snapshot 文件 sha256 与验收契约 bundle `artifacts` 登记一致。
  可执行：`uv run python contracts/validate_case_data.py validate-bundle <fixtures_dir>`。
- **R3 轨迹校验**：对每条 `traces/run_<id>.json` 用配套版本校验器校验
  （`uv run python -m financial_agent_reliability.harness.acceptance_v3_11 validate-trace --trace <path>`
  或直接调用 `contracts/run_trace_validator_v3_11.py` 对应实现）。校验器除 schema
  一致性外还独立重放账本状态链（state_before/after_sha256、ledger_transition 逐笔
  复算）、核对终态与分类映射——这是"轨迹内部自洽"的可执行证据。
- **R4 链锚回验**：逐运行核对
  `run_identity.harness_config_sha256 == sha256(harness config)`、
  `plan_core_sha256 == sha256(plan core)`、
  `result.candidate_output_sha256 == sha256(candidates/run_<id>.json)`、
  grader 行 `commitments`（candidate/trace/projection/snapshot 四哈希）与落盘件一致。
- **R5 结论重算**：先用 `uv run python contracts/grader_v2.py verify-freeze` 校验
  grader 捆扎 sha256 与冻结登记一致，再对落盘候选输出重新评分：
  `uv run python contracts/grader_v2.py validate-results <results>` 与
  `uv run python contracts/grader_v2.py score <results>`；逐行比对与落盘 grader 结果
  相等。再按预注册指标定义对评分行重新聚合（CSR、pass^k、排除规则、门槛），
  与 `summary.json` 及对外报告发布的数字逐一比对。确定性重算要求**逐位相等**，
  不接受容差。
- **R6 判定与标注**：按 3.3 判定项输出通过/失败清单；按 3.4 对缺失/降级打标注。
  复盘产物本身落入 `audit/` 之外的工作目录（不得向冻结目录新增文件），
  并在议题评论中给出复盘记录。

### 3.3 判定项

**证据链完整性（A 组）**

- A1 manifest 逐件 sha256 相符，无未登记文件；
- A2 case/snapshot 内容哈希、c14n 规范化一致，时点字段齐备且
  `available_at_cutoff`/`future_information_prohibited` 纪律未被违反；
- A3 run_trace 通过配套版本校验器（含账本重放、终态映射、redaction 与
  secret_leakage_detected=false）；
- A4 链锚四向一致（R4 全部相等）；
- A5 grader 捆扎与预注册、报告捆扎的 sha256 与冻结登记一致。

**结论一致性（B 组）**

- B1 逐运行重评分 = 落盘评分行（状态、值语义、理由码、checks、loss level、excluded）；
- B2 批级统计重算 = summary.json（counts、by_model、frozen_input_hashes 引用一致）；
- B3 对外报告结论 = 重算统计（排名、门槛判定、排除名单逐项一致）；
- B4 排除规则应用一致：被排除运行不得进入排名分母，排除理由登记在案；
- B5 仅 `quality.ranking_eligible = true` 且可程序验证的 Gold 任务进入主排名；
  Silver 仅作诊断——该纪律由 case 卡携带，复盘时复核而非重设。

### 3.4 缺失/降级标注规则

复盘结论三档，逐运行、逐批分别标注，不允许整批掩盖单点缺失：

1. **可追溯（traceable）**：A1–A5、B1–B5 全部通过。
2. **部分可追溯（partially_traceable）**：完整性通过但个别判定项缺失或降级
   （如某运行缺 grader 行、统计重算仅覆盖部分模型）。必须点名缺失节点与受影响结论；
   受影响结论**退出其声称的用途**（如退出排名），其余结论照常成立。
3. **不可追溯（untraceable）**：任一链锚断裂（哈希不符、manifest 缺件、轨迹未过
   校验器、重算与落盘不一致且无法解释）。该运行/批次结论作废，不得以"当时记录过"
   为由保留其效力。

补充纪律：

- **缺失 ≠ 失败 ≠ 通过**。缺证据只标"不可追溯/部分可追溯"，不得推断结果好坏，
  不得补造数据、不得以重跑结果回填历史结论（重跑若发生，属于新运行、新血缘，
  按第 4.4 节另立记录）。
- **不一致优先于缺失**：重算与落盘冲突时，先按不可追溯处理并立案调查
  （属于 grader 缺陷、记录错误还是篡改嫌疑），在查明前相关结论冻结引用。
- **降级必须留痕**：每次降级标注附复现命令、受影响面（哪些 run/结论）、严重度
  与最小修复建议；不得静默跳过。

## 4. 与现行冻结体系的关系

### 4.1 口径定位

本口径是**验收与复盘的判读标准**：它回答"拿什么证据、按什么规则判定一次历史运行
及其结论是否成立"。它不修改任何已冻结产物，不发布新契约版本，也不解除任何冻结
纪律中仍然成立的部分。与冻结产物冲突时，以证据血缘完整性为准（AGENTS.md 总纲）。

### 4.2 旧 v3.x 冻结体系中在新口径下自然失效的要求

以下要求在新口径下不再构成**验收或复盘的前置条件**（它们的记录本身仍按历史基线
原样保留、逐字节校验其文档完整性）：

1. **源码与依赖哈希钉住作为重建前提**。`stage3_acceptance_contracts.frozen.vX.json`
   的 artifacts 对 harness/acceptance 实现、validator、测试、以及 v3.7 起对
   `pyproject.toml`/`uv.lock` 的 sha256 钉住，不再要求复盘者重建同版本运行环境
   "原样重跑"；它们退化为历史基线记录，路径迁移按 `relocation.py` 放行清单解析
   （PER-85-D6）。评分/校验**代码的确定性**改由 4.3 的捆扎哈希 + 重算保证，
   而不是由环境重建保证。
2. **以全量重跑取代旧血缘的预期**。PER-257-D4（所有实验重跑）与其后排期安排
   （PER-257-D8）被 PER-316-D1 取代：历史运行以轨迹日志复盘验收，暂不全量重跑。
   若未来决策重启重跑，重跑产物按新运行、新血缘处理，不回写旧 bundle。
3. **提供商响应可重放假设**。seed/payload/parameters 哈希继续登记，但不再承担
   "重放必须逐字节一致"的职能；`raw_provider_response_stored = false` 现状下，
   任何依赖提供商原始响应的验收要求自动失效。
4. **跨契约版本追溯重评**。旧 bundle 已声明 `retroactive_regrading = false`：
   新口径同样不追溯改写旧 bundle 的评分与结论；旧 bundle 按其自身版本复盘。

### 4.3 旧冻结体系中继续有效的要求

1. **场景输入冻结链**：case_card / data_snapshot 的内容哈希、revision、时点纪律
   （as_of / available_at_cutoff / future_information_prohibited）、只读访问纪律
   （public_read_only、prohibited_scopes）——场景可复现的根基，全部继续强制。
2. **grader 确定性与冻结捆扎**：`grader_contract.frozen.v2.json` 的 mutation_policy
   （append-only、候选表现永不改捆扎）、评分/权重/阈值不改写；结论可追溯依赖 grader
   是纯函数，可独立重算（`grader_v2.py validate-results/score`）。Gold 结论的独立重算要求
   （case 卡 `independently_recomputable`）继续有效。
3. **run_trace 契约与逐版本校验器**：schema、validator、harness config、plan 的
   版本配套关系继续有效；复盘必须使用配套版本校验。
4. **证据 bundle manifest 完整性**：逐件 sha256 登记、authorization_basis 留痕，
   是复盘入口，继续强制。
5. **预注册指标与排名纪律**：指标定义、排除规则、显著性门槛、Gold-only 主排名、
   `retroactive_regrading=false` 继续有效；本口径不改任何门槛数值——门槛调整属于
   需要独立裁决的新版本事项，不得借复盘流程夹带。
6. **脱敏与密钥纪律**：redaction 契约门（`scan_persisted_value_for_secrets`）、
   密钥仅限环境变量、日志产物脱敏，继续有效。
7. **旧血缘内容不改不删**（PER-257-D6）：❄️ 目录原样保留、不新增文件；本口径文档
   因此落于 `docs/contracts/` 而非 `contracts/`。

### 4.4 对未来运行的约束

本口径生效后执行的任何新运行，从运行期起必须满足第 2 节六节点全部落盘要求，并在
验收时按第 3 节流程执行一次自评复盘；其证据 bundle 按既有目录纪律落
`evidence/stageN/<运行目录名>/`。新契约版本（如 v4 世代）发布时，须把本口径的
六节点字段作为最小集纳入新契约，或书面说明差异并另起口径版本。

## 5. 验收门（新口径下的交付判定）

一次批级交付在新口径下通过验收，当且仅当：

- G1 六节点（N0–N5）工件齐备，版本标识明确，manifest 登记完整；
- G2 A 组（证据链完整性）全部通过；
- G3 B1–B3 确定性重算逐位一致；
- G4 排除规则与 Gold-only 排名纪律复核通过（B4、B5）；
- G5 全部降级标注按 3.4 留痕，且受影响结论已退出其声称用途。

任一 G 不满足：交付判定失败或按降级口径部分接受（仅限 G5 情形且已留痕）；
不得因排名或结论不符合预期而放宽任一 G。

## 6. 已知残余风险与边界

1. **行为不可再执行验证**：候选模型的错误行为只能依据落盘轨迹复盘，不能通过重跑
   复现或证实其消失。涉及"模型是否仍会犯同类错误"的新问题，必须立新运行解决，
   不属于本口径的复盘范围。
2. **原始提供商响应未落盘**：脱敏纪律下 raw response 不留存。若未来争议涉及
   候选输出与提供商响应的映射关系，现有 payload/parameters 哈希只能证明请求内容，
   不能重放响应；此为口径的明示边界。
3. **复盘工具链自身的版本风险**：复盘依赖的校验器/grader 是现环境代码，其捆扎哈希
   校验只保证与冻结登记一致，不保证运行环境未被更广泛地篡改。独立审计（Stage 3）
   应在干净检出上先复验捆扎哈希再执行重算。
4. **口径版本演进**：本口径 v1 以现行 v3.x 契约为对照基线。未来新契约世代若改变
   节点字段（如新增原始响应摘要落盘），应同步升版本，不做追溯改写。

## 附录 A：决策日志与冻结记录

| 决策编号 | 内容 | 来源 |
| --- | --- | --- |
| PER-316-D1 | 验收口径调整为"场景与结论可复现可追溯（历史轨迹日志复盘）"，代码级可复现重放不作要求 | 用户已确认（PER-316 用户请求） |
| PER-316-D2 | PER-257-D4/D8 的"重跑"预期被 D1 取代，暂不全量重跑；PER-257-D6 历史基线纪律继续有效 | agent 推断（本口径固化，待评审） |
| PER-257-D6 | 旧 v3.x 冻结产物降级为历史基线：内容不改不删，路径/哈希钉住不阻塞重构与验收 | 历史决策（继续有效） |
| PER-257-D8 | 重跑不立即排期；本口径下进一步被"复盘替代重跑"承接 | 用户已确认（历史决策） |
| PER-85-D6 | 旧血缘路径钉住按 relocation 放行清单解析，放行逐条点名、不静默 | 历史决策（继续有效） |

冻结锚点：本文件以冻结提交（git commit，见 PER-317 交付评论）为冻结锚点；
文件内容 sha256 随交付评论登记。此后修订一律另起新版本文件。


---

**PER-323 历史说明(2026-08-17,Stage 2 追加)**:本文引用的冻结目录路径(`contracts/`、`cases/`、`catalog/`、`snapshots/`、`preregistration/`、`evidence/`、`audit/`、`reports/` 及 gitignore 的 `runs/` 等基线 v1 目录)已按 PER-323 冻结清理清单 v1 删除;原文内容可按 `docs/per323-stage2-deletion-record.md` 所载各目录回滚索引 SHA 从 git 历史找回(`runs/` 的删除前归档见该记录 §2)。本文原文与结论作为历史记录保留,未改写。