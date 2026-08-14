## 独立结论

**FAIL（门禁阻断）**。v3.7 的冻结哈希、离线授权阻断、三模型表面对称、秘密扫描、18 个 reason code 覆盖和全量回归均通过；但合同仍允许模型身份、provider 状态、请求阶段、证据引用和被评分候选之间的不一致记录通过，而且 live harness 没有实际执行其声明的确定性计算，也没有验证模拟账本终态。因此 B2、B3、B5、B6 未关闭，36 个付费验收单元、排行榜和演示均不得启动。

本结论不评价三个候选模型的能力或排名，只评价 v3.7 合同与 harness 是否足以生成可归责、可重算的证据。

## 冻结输入与完整性

以下为直接证据，均在 2026-08-12（UTC）从本地冻结文件独立重算：

| 对象 | 独立结果 |
| --- | --- |
| v3.7 manifest 文件 SHA-256 | `9be10affeed2a69c0ce0eb6af0442dc0d2788ab9e6e434fc8aa0a2471d56fec6` |
| v3.7 20 项 artifact-list 内容 SHA-256 | `354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44`；20/20 文件哈希一致 |
| v3.7 plan 文件 / 去除 `plan_sha256` 后规范内容 | `e923ca28cc882815fcf2a1c2f2326c5906fb43a0fc0a94f7d4c433a74ea4c72f` / `aa17d6bedb283663b24d50b42ac475c9bba61597a183f7524314b65cad90acd3` |
| v3.7 config 文件 SHA-256 | `5096ccc9c5167c6d40a15ecf27dd9bfcbad6160e6b624002043b47177c9a9d43` |
| v3.6 manifest 文件 / artifact-list 内容 | `7139738164c2ef5bbf65043e19fc68f1e78faa0e12cd4a085e672496c3afb293` / `afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959`；33/33 一致 |
| v3.5 manifest 文件 / 合并基础 bundle 后的承诺 | `8ff16f9c99ff967d1e950135a19296ebb728c391622b355958e8f53706b76191` / `d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8`；40/40 一致 |
| 运行身份 | v3.5、v3.6、v3.7 各 36 个唯一 run ID；版本间交集均为 0；v3.7 每模型 12 个 |

v3.7 的 12 个 projection 未命中 `expected/oracle/grader/answer_key` 或模型名；三模型共享 prompt、工具、预算、重试和 grader。请求参数去除官方协议要求的 Qwen-only `enable_thinking=false` 后完全相同。这里的“对称”只证明冻结配置对称，不证明实际 provider 执行对称。

## B1–B7 复审

| 门 | 结论 | 独立证据 |
| --- | --- | --- |
| B1 CLI 与授权 fail-closed | PASS | 清空三个 `BENCH_BAILIAN_*` 变量，以 `paid_calls_authorized=false` 的独立授权文件运行 preflight，退出码 2，输出 `separate paid preflight authorization is required`，且未创建输出文件。 |
| B2 身份与哈希 | **FAIL** | manifest/plan/config/run membership 哈希通过；但单个 provider attempt 的 `response_model_id` 改成另一候选模型后，validator 仍接受。 |
| B3 证据/PIT/单位/方法/计算/权限/环境 | **FAIL** | PIT、读取记录和静态权限检查存在；但 `calculate` 只返回输入哈希、不计算结果；单位和方法由 projection 回填，计算输出哈希由候选值回填；无 `calculate` 操作仍获 `calculation_correct=true`；模拟账本无状态，终态安全恒写为 true。 |
| B4 秘密硬门 | PASS | validator 在 schema 前扫描 trace 及 companion，live writer 在持久化前扫描 trace/grader/checkpoint/summary；fixture 扫描 4 文件、0 findings，秘密变体测试通过。未读取或输出真实凭证。 |
| B5 8 个逻辑请求、每请求最多 2 次 provider attempt | **FAIL** | 数量和重试记账存在；但 `HTTP 429 + classification=success` 及首请求 `phase=repair` 均被接受，状态分类和 6+2 阶段预算可被自报字段绕过。 |
| B6 schema 与 18 reason code | **FAIL** | 18 个 reason code 的正负变体均通过测试；但空 `evidence_record_ids` 仍同时通过 provenance/sufficiency，且候选内容哈希与 trace 不一致时 grader 仍全通过。语法严格不能替代语义绑定。 |
| B7 v3.5 隔离与全量回归 | PASS | v3.5/v3.6/v3.7 完整性检查通过；Python 157/157、Node 42/42 通过，未发现现有回归失败。 |

## 阻断发现

### H1 — 计算、方法、单位和环境状态不是可观察事实（High，影响全部 36 个单元）

直接证据：

- `harness/live_acceptance_v3_7.mjs:200` 的 `calculate` 仅返回 `operation`、`inputs_sha256` 和 `deterministic:true`，没有执行 add/subtract/multiply/divide/average/threshold，也没有返回数值。
- `harness/live_acceptance_v3_7.mjs:301` 从 projection 的输出 schema/operation 填入 unit/method，从候选 `value` 填入 calculation output hash，并恒写 `final_state_matches_initial:true`。
- `harness/live_acceptance_v3_7.mjs:201-205` 的 simulated ledger 不保存或变更任何内存状态，只返回声明。
- 基线 trace 的 observed operations 只有 `read_frozen_case`、`read_frozen_evidence`，grader 仍返回 `calculation_correct=true`。

影响推断：这些字段不能证明模型使用了正确单位/方法、工具算出了候选数值或模拟状态被恢复；它们是 projection/候选答案的派生回声。任何依赖这些独立门的通过率、CSR、pass^3 或排名均不可靠。

最小修复：用 Decimal 实际执行并记录规范化输入、operation、数值输出和事件哈希；grader 从冻结 snapshot 独立重算并与真实工具事件比较；unit/method 必须由执行事件或候选显式声明取得；模拟账本维护 before/after 状态根并实际比较，禁止硬编码终态安全。

### H2 — 每次 provider attempt 的响应身份未绑定（High，影响归因与公平性）

直接证据：schema 允许 attempt 的 `response_model_id` 为三个候选 ID 中任意一个；`contracts/run_trace_validator_v3_7.py:91-95` 只核对 attempt 的请求 `model_id`，未核对 attempt 的 `response_model_id`。将 Qwen 基线 attempt 的响应模型改为 `deepseek-v4-pro`，同时保持顶层 provider 身份不变，validator 接受。

影响推断：中间请求发生 fallback/路由错配时，trace 可仍归因给计划模型，破坏三模型可比性和责任链。

最小修复：每个 attempt 强制 `response_model_id == run_identity.requested_model_id == request.model_id`；无可核验响应身份时分类为 invalid/indeterminate，候选不得计分；增加跨三个模型的负向变体。

### H3 — grader 未绑定实际候选与证据引用（High，影响可重算性和证据血缘）

直接证据：

- 将候选 `evidence_record_ids` 清空，grader 仍返回 `evidence_provenance_valid=true`、`evidence_sufficient=true` 和全通过。`harness/acceptance_v3_7.py:238-250` 只要求 cited IDs 是 observed IDs 的子集，而 sufficiency 只数 observed material evidence，未要求候选引用它。
- 改变候选 `uncertainty` 后，其规范 SHA-256 为 `6a1a771d0bab17d9453467da49917107a0e30e547af67ae3d3ffb46ea4ee4ef9`，与 trace 的 `candidate_output_sha256=9cc4b458c88c3de8ee7524acfa597731c0077328048951c08dac45c1232e899f` 不同，grader 仍全通过；`grade_candidate_v37` 没有核对两者。

影响推断：grader result 不能证明它评分的是 trace 所承诺的候选，也不能证明候选实际引用了被读取的 material evidence。持久化后的独立重算和争议复核会失去关键绑定。

最小修复：在不保存原始 provider 响应的前提下，持久化脱敏后的 canonical candidate artifact；grader 入口先验证其哈希等于 trace 承诺，并在 grader result 中承诺 candidate/trace/snapshot/projection 哈希；evidence sufficiency 应计数 `cited ∩ observed ∩ material`，且每个 cited ID 必须有完整 provenance。

### M1 — HTTP 分类与 6+2 阶段语义未验证（Medium，影响失败分母和预算公平性）

直接证据：将成功 attempt 的 `http_status` 改为 429，或将首个请求 phase 改为 repair，validator 均接受。`contracts/run_trace_validator_v3_7.py:126-159` 只核对自报 classification、索引、重试和总数，不建立 HTTP/异常到分类的独立映射，也不校验请求 1–6/7–8 的阶段顺序。

最小修复：冻结并执行 HTTP/异常分类表；成功只能来自明确成功状态与有效 assistant action；强制 initial 前缀最多 6、repair 后缀最多 2，禁止交错与提前越界；相关负向测试必须从当前 ACCEPTED 变为 REJECTED。

## 可复现命令与结果

反例脚本是只读的，不发网络请求、不修改冻结文件：

```bash
uv run python -m audit.reproduce_stage3_v3_7_gate_gaps
```

当前输出证明三个 trace 变体被接受、空证据引用全通过、候选哈希不匹配仍全通过、没有 calculate 操作仍通过 calculation check。

其余执行命令：

```bash
uv run python -m harness.acceptance_v3_7 verify-contracts
uv run python -m harness.acceptance_v3_7 verify-plan
uv run python -m harness.acceptance_v3_7 scan-fixtures
uv run python -m unittest tests.test_financial_acceptance_v3_7 -v
node --test tests/integration/financial_acceptance_v3_7.test.mjs
uv run python -m audit.build_stage3_v3_6_adjudication verify
uv run python -m harness.acceptance_v3_6 verify-contracts
uv run python -m harness.acceptance_v3_6 verify-plan
uv run python -m harness.acceptance_v3_5 verify-contracts
uv run python -m unittest discover -s tests -v
node --test tests/integration/*.test.mjs
```

结果：v3.7 focused Python 13/13、focused Node 6/6、全量 Python 157/157、全量 Node 42/42；合同、计划、fixture scan 均通过。绿色回归与上述反例并存，说明测试覆盖未对这些语义约束形成否证能力。

授权负向命令（使用仅含 `{"paid_calls_authorized":false}` 的临时文件）退出码 2，且无输出文件：

```bash
env -u BENCH_BAILIAN_API_KEY -u BENCH_BAILIAN_BASE_URL -u BENCH_BAILIAN_MODEL_IDS node harness/live_acceptance_v3_7.mjs --mode preflight --plan contracts/stage3_acceptance_plan.v3.7.json --authorization audit/unauthorized-v3.7.json --output audit/should-not-exist-v3.7.json
```

## 限制与处置

- 未提供、读取或使用真实百炼凭证；未执行真实 provider 调用、交易、资金或生产系统变更。因此未验证真实 API 可达性、模型精确身份和 provider 参数兑现，这些只能在合同修复且获得单独授权后验证。
- 本轮不生成任何模型成绩、CSR、pass^3、置信区间、排名或演示。
- 技术门禁未满足。将最小修复退回 PER-41 原实现者；修复必须形成新的前瞻版本和新哈希，不得覆盖 v3.5/v3.6/v3.7，不得重评既有结果。
- Stage 4/受控付费运行继续保持 backlog；即使后续技术复审通过，也仍需父议题元数据中的显式候选运行与付费授权，技术通过本身不构成授权。

本报告文件 SHA-256 由交付评论随附件发布，避免自引用改变文件哈希。
