## 独立结论

**PASS（技术门禁满足）**。在不修改任何实现、不读取真实凭证、不发起任何 preflight/36-run/付费 provider 调用的前提下，独立复算与反例复现均表明：第二轮审计（报告 SHA-256 `d47ee47e…79bba`）遗留的 B2/B3/B5/B6 已在 v3.8 真正关闭，B1/B4/B7 无回归，v3.5/v3.6/v3.7 冻结产物零漂移，三模型候选可见合同对称。因此 **v3.8 满足「3 模型身份预检 + 新 36-run」的技术门**。

该结论只是技术门禁判断，**不构成候选运行或付费授权**：`paid_calls_authorized` 在 bundle/plan/config 中均为 `false`，Stage 4 与 36 个付费验收单元仍须等待父议题记录新的明确授权后才能启动；本轮不生成任何排行榜、成绩或演示。

本结论不评价三个候选模型的能力或排名，只评价 v3.8 合同与 harness 是否足以生成可归责、可重算的证据。

## 冻结输入与完整性（全部独立重算）

以下为直接证据，均在 2026-08-12（UTC）从本地冻结文件独立重算，不依赖实现侧代码路径：

| 对象 | 实现侧声明 | 独立复算 | 结论 |
| --- | --- | --- | --- |
| v3.8 manifest 文件 SHA-256 | `b96539c7…cd20` | `b96539c78ba2425c265d3590995dc9cccabbc37896cf63011f4cabbc6bf4cd20` | 一致 |
| v3.8 artifact-list 内容 SHA-256 | `39a0853c…f609` | `39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609`；15/15 文件逐一哈希一致 | 一致 |
| v3.8 plan 文件 / 去 `plan_sha256` 规范内容 | `a98423bd…51d7` / `636d94fb…4c3d22` | `a98423bd0406a87e8b898695ca4644f54c04f41054fe9afeddd6153e9ea251d7` / `636d94fbb6d08d58adfd018dfba6115bb44ac193480a5380e3228c623a4c3d22` | 一致 |
| v3.8 config 文件 SHA-256 | `8f6ab9b7…8712` | `8f6ab9b76492248d4d0d841b8beb5fdbe679537ed7664c43e0b33f6dd2bf8712` | 一致 |
| v3.7 manifest / bundle | `9be10aff…fec6` / `354e8413…fc44` | 同值；20/20 artifact 零漂移 | 零漂移 |
| v3.6 manifest / bundle | `71397381…b293` / `afd1a163…c959` | 同值；33/33 artifact 零漂移 | 零漂移 |
| v3.5 manifest / 合并基础 bundle 承诺 | `8ff16f9c…6191` / `d24948f9…9cb8` | 同值；40/40 artifact 零漂移 | 零漂移 |
| supersedes 链 | v3.8→v3.7→v3.6 | 文件哈希与 bundle 承诺逐级一致，`retroactive_regrading=false` | 一致 |

运行身份：v3.5、v3.6、v3.7、v3.8 各 36 个唯一 run ID，且 `run_id == run_{sha256(run_identity)[:32]}` 全部推导一致；四个版本两两交集均为 0；v3.8 每模型 12 个，12 个 case 每个恰好每模型一次、共享同一 projection/tool_schema。

## B1–B7 复审

| 门 | 结论 | 独立证据 |
| --- | --- | --- |
| B1 CLI 与授权 fail-closed | PASS | 清空三个 `BENCH_BAILIAN_*` 变量，以 `{"paid_calls_authorized":false}` 独立授权文件运行 preflight，退出码 2、`separate paid preflight authorization is required`、未创建输出文件（`audit/should-not-exist-v3.8.json` 不存在）。 |
| B2 身份与哈希 | **PASS（本轮关闭）** | 见反例节：attempt 响应身份错配、429/500 冒充成功、首请求改 repair、交错 phase、同载荷重试被破坏、无响应失败伪造响应模型，均被 validator 拒绝。 |
| B3 证据/PIT/单位/方法/计算/权限/环境 | **PASS（本轮关闭）** | `calculate` 真实执行十进制有理运算（独立 Decimal 交叉验证）；模拟账本有状态且 validator 从空账本独立重放；unit/method/calculation 均由真实执行事件或冻结 snapshot 取得，不再回填。 |
| B4 秘密硬门 | PASS | validator 先于 schema 扫描 trace 及 companion；live writer 的 `atomicJson`/`checkpoint` 在持久化前 `assertSafePersisted`；fixture 扫描 3 文件 0 findings，秘密变体测试通过。未读取或输出真实凭证。 |
| B5 请求/attempt 勾稽与哈希绑定 | **PASS（本轮关闭）** | candidate/trace/grader 哈希互相绑定并与 trace 承诺一致；`calculation_correct=true` 必须存在匹配 operation/input/output/implementation 的真实 `calculate` 事件；空 `evidence_record_ids` 被拒。 |
| B6 schema 与 18 reason code / 证据充分性 | **PASS（本轮关闭）** | 证据充分性为 `cited ∩ observed ∩ material`，observed 需输出哈希匹配冻结 snapshot 的真实 evidence 事件；PIT、来源、单位承诺独立复算；敏感串扫描对 trace 与 companion candidate 均为 validator 硬门。 |
| B7 v3.5 隔离与全量回归 | PASS | v3.5/v3.6/v3.7/v3.8 完整性检查通过；全量 Python 164/164、全量 Node 48/48，无既有回归失败。 |

## 反例复现（B2/B3/B5/B6 逐项）

只读反例脚本 `audit/reproduce_stage3_v3_8_gate_checks.py`（SHA-256 `95f36044…2028`）对每个残留门构造必须被拒绝的变体；全部命中拒绝，运行尾部输出 `ALL_COUNTEREXAMPLES_REJECTED_AS_REQUIRED`：

```bash
uv run python -m audit.reproduce_stage3_v3_8_gate_checks
```

- **B2**：`attempt.response_model_id` 改为另一候选模型（HTTP 200）→ `attempt response model mismatch`；`http_status` 改 429/500 仍报 success → `HTTP classification mismatch`（分类由 `classify_attempt_v38` 从实际 HTTP 与 assistant action 推导，非自报）；首请求 phase 改 repair → `first request must be initial`；多请求 fixture 中 repair 后出现 initial → `phase order must be an initial prefix followed by repair suffix`；首个 attempt 非 provider failure 却出现第二次 attempt → `semantic retry forbidden`；重试 attempt 的 `payload_sha256` 与请求不一致 → `provider retry is not identical replay`；无响应失败（`http_status=null`）伪造 `response_model_id` → `attempt response model mismatch`；7 个 initial / 3 个 repair → `phase budget exceeded`（6+2 上限）。一致性 429 失败被接受但 `candidate_scored=false`、`provider_runtime_valid=false`，不进入计分。
- **B3**：对 `trace.ledger_restored.json` 独立重放——篡改 `resulting_quantity` → `ledger resulting quantity mismatch`；篡改中间 `state_before_sha256` → `ledger state chain mismatch`；删除恢复性 sell 事件 → `ledger terminal state mismatch`；恒写 `final_state_matches_initial=true` 且改终态根 → `ledger terminal state mismatch`。Node 侧 `executeDecimalCalculationV38` 对 add/subtract/multiply/divide/average/threshold 实算，`1/3→0.333333333333333333`、`0.1+0.2+0.3→0.6`、FKW 三值均值→`39.883139` 与独立 Python `Decimal(prec=34, ROUND_HALF_EVEN)` 完全一致；`applyLedgerOperationV38` 维护 Map 状态、before/after 根链一致、preview 不改状态、sell 清仓回到空账本根 `44136fa3…ff8a`。grader 侧：删除 calculate 事件 → `calculation_correct=false` 且 `method_correct=false`；伪造 calculate 输出哈希 → `calculation_correct=false`；伪造 `unit_basis_sha256` → `unit_correct=false`。
- **B5**：清空 candidate `evidence_record_ids` → `evidence_provenance_valid/evidence_sufficient/unit_correct` 均 false；candidate `uncertainty` 改 high 使其规范 SHA-256 `6a1a771d…4ef9` 与 trace 承诺 `9cc4b458…899f` 不一致 → `candidate_trace_bound=false`；grader `commitments` 中 candidate/trace/projection/snapshot 四哈希与独立重算一致，且 `grader_sha256` 等于对去除自身后 result 的规范哈希。
- **B6**：仅引用未读取/非 material 记录 → provenance 与 sufficient 双 false；evidence 事件 `output_sha256` 与冻结 snapshot 记录哈希不符 → sufficient false；篡改 observation `source_locator` → provenance false；`available_at` 晚于 cutoff → `pit_valid=false`；trace 注入 `Bearer …`、companion candidate 注入 `sk-…` → validator 均以 `secret-like persisted value` 拒绝。

## 三模型对称性

候选可见层面三模型共享同一 prompt 模板、工具 schema、预算、重试与 grader：`config.request_commitments.parameters_by_model` 中 glm-5.2 与 deepseek-v4-pro 参数哈希完全相同（`429e4c97…`），qwen3.8-max 仅多官方协议要求的 `enable_thinking=false`；`fairness.same_prompt_tools_budget_retry_grader=true`；12 个 projection 扫描无 `expected/oracle/answer_key/grader/gold` 键、无模型名泄漏；plan 任务哈希与 projection/snapshot 文件哈希逐一吻合，tool_schema 承诺可由 v3.7 builder 重算命中。此处“对称”只证明冻结配置对称，不证明实际 provider 执行对称。

## 可复现命令与结果

```bash
uv run python -m harness.acceptance_v3_8 verify-contracts
uv run python -m harness.acceptance_v3_8 verify-plan
uv run python -m harness.acceptance_v3_8 scan-fixtures
uv run python -m unittest tests.test_financial_acceptance_v3_8 -v
node --test tests/integration/financial_acceptance_v3_8.test.mjs
uv run python -m harness.acceptance_v3_7 verify-contracts
uv run python -m harness.acceptance_v3_6 verify-contracts
uv run python -m harness.acceptance_v3_5 verify-contracts
uv run python -m unittest discover -s tests -v
node --test tests/integration/*.test.mjs
node audit/driver_v3_8_synthetic_chain.mjs   # 独立合成产物链
```

结果：v3.8 focused Python 7/7、focused Node 6/6；全量 Python 164/164、全量 Node 48/48；verify-contracts/verify-plan 有效，scan-fixtures 3 文件 0 findings；历史 v3.5/v3.6/v3.7 verify-contracts/verify-plan 全部有效且哈希与声明一致。

合成产物链：以 synthetic transport 运行 `executeFrozenPlanV38`（驱动脚本 SHA-256 `42c98e54…a5c`），实际生成 36 candidate + 36 trace + 36 grader + 36 checkpoint，`counts={planned:36,candidates:36,traces:36,graders:36,accepted:36}`。随后用独立 Python 复核 36/36：validator 全通过、`grade_candidate_v38` 重算的 `grader_sha256` 与落盘逐一相等（确定性重算）、四个 commitment 绑定全部成立。6 个无 calculate 事件的 answer run 恰好是合同本身不含计算的 2 个 case（`direct`、`timeout_gate`）×3 模型，属预期而非漏检。未读取真实凭证、未发起 provider 调用。

## 限制与处置

- 未提供、读取或使用真实百炼凭证；未执行真实 provider 调用、交易、资金或生产系统变更。因此未验证真实 API 可达性、模型精确身份与 provider 参数兑现，这些只能在获得单独授权后由付费身份预检与 36-run 验证。
- 本轮不生成任何模型成绩、CSR、pass^3、置信区间、排名或演示。
- v3.5/v3.6/v3.7 冻结产物未被覆盖、未被重评；v3.8 为前瞻新版本。
- 即使本技术复审通过，Stage 4/受控付费运行仍须等待父议题元数据中的显式候选运行与付费授权；技术通过本身不构成授权。
- 本报告文件 SHA-256 由交付评论随附件发布，避免自引用改变文件哈希。
