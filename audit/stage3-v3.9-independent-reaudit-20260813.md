## Stage 3C-3（PER-51）v3.9 superseding 合同独立复审

审计人：独立评分与统计审计师（与出题、oracle、harness 实现职责隔离）
审计对象：v3.9 冻结合同 bundle（21 artifact）、plan、config、两份修复 projection 及新「oracle 期望 ⊆ 候选可见合同」门禁；v3.5–v3.8 冻结产物只读对照
审计日期：2026-08-13（UTC）
被审交付声明：PER-48 评论 `7a42b3ce-58cc-402b-ae86-dd8b260a30f1`

## 独立结论

**FAIL（低严重度，单一最小修复）**。交付审计要求的全部实质项——方案 A 关闭 fkw-03 缺陷、fkw-07 同型披露、新门禁正反例与 v3.8 冻结集精确复现、仅披露且零追溯重评、全量 36-run 预登记重跑范围、三模型对称、历史版本零漂移、全量测试——均独立复核通过（独立审计脚本 96 项检查中 95 项通过）。唯一失败项：v3.9 config 的 `semantic_bindings.calculation` 仍声明 `executed_decimal_rational_v3_8`，而同 bundle 内 grader/运行时/fixture 强制执行的实现标签已升级为 `decimal_rational_v3_9`——冻结合同内部「声明 vs 强制」不一致，与本修复轮所要根除的缺陷同族。退回原实现者（Harness 工程师）做单字符串修复并确定性重冻；修复前不得派发新一轮 36-run。

## 一、冻结输入独立复算（canonical-hash 独立重写，不复用实现侧哈希代码）

| 对象 | PER-48 声明 | 独立复算 | 结论 |
| --- | --- | --- | --- |
| v3.9 合同 bundle（artifact-list 内容哈希） | `f4461964…188d` | 一致；21/21 artifact 文件哈希逐一吻合 | 一致 |
| v3.9 plan（去 `plan_sha256` 规范内容） | `e5ca961f…e9b6` | 一致；`plan_core_sha256=e3b7eeb7…bed73` 按 core 公式（contract_version/config_sha256/models/task_inputs）独立重构一致 | 一致 |
| v3.9 config 文件 | `f9702fa6…192c` | 一致，且与 plan core 的 config_sha256 绑定一致 | 一致 |
| fkw-03 / fkw-07 修复 projection | `9a1cb68f…e4f2` / `9d7605a5…483a` | 一致 | 一致 |
| v3.5 / v3.6 / v3.7 / v3.8 bundle | `d24948f9…` / `afd1a163…` / `354e8413…` / `39a0853c…` | 4/4 bundle 哈希与全部 artifact（8/33/20/15）逐一零漂移 | 零漂移 |
| v3.8 plan | `636d94fb…3d22`（core `f272700e…66ae`） | 一致 | 一致 |
| supersedes 链 | v3.9 bundle/plan/config/projection → v3.8（projection → v3.6 源），历史 bundle 链 v3.5←v3.6←v3.7←v3.8 | 全部文件哈希与内容哈希衔接一致；preserved 块钉住四个历史 bundle 哈希且 `retroactive_regrading=false` | 一致 |
| run identity | 36 run | 36/36 `run_id == run_{sha256(run_identity)[:32]}`，identity 内 plan_core/config 绑定、benchmark_id、repeat 均正确；v3.8∩v3.9 run id = ∅；(model_id, seed) 多重集与 v3.8 完全一致 | 一致 |

## 二、fkw-03/fkw-07 修复内容核验（方案 A）

- **独立 Decimal 复算**：35215.003535366 / 1e9 按 prec-34 求商、quantize 1e-6 ROUND_HALF_EVEN = `0.000035`；fkw-07 三年均值同法 = `6.073667`。两者与冻结 v2 case card 注册期望值（FKW-03/FKW-07 single_factor_perturbation）逐一相等。
- **约定来源非反推**：case card 生成于 2026-08-11T02:00Z（早于 v3.8 执行窗口 2026-08-12 13:54–14:13 UTC）；`cases/public/oracle.py` 文件哈希 == case card 注册的 `implementation_sha256`（`9097915075…`，quantize 1e-6 ROUND_HALF_EVEN 源码在案）；v3.8 三模型 fkw-03 答案均为精确商 `0.000035215003535366`，与披露值 `0.000035` 不同——披露不可能由候选答案反推。
- **与 FKW-12 同构**：两份新 `decimal_output_contract` 与冻结 v3.6 FKW-12 合同逐字段同构（6 位、ROUND_HALF_EVEN、`^-?\d+\.\d{6}$`、容差 `0.0000005`、`tolerance_does_not_waive_lexical_schema=true`、≥34 位、无中间舍入、完整十进制输入），另有按案型的 basis/echo 键与 `value_field`；词法 schema pattern 同步收紧为同一 pattern（未豁免）。容差 0.0000005 恰为 1e-6 量子的二分之一，与半偶舍入金融语义一致。
- **三模型对称**：披露为 per-case（无模型维度）；plan.fairness 声明 same prompt/tools/budget/retry/grader；每案恰 3 run 覆盖 3 模型；per-model 参数承诺与 v3.8 逐字节一致；`harness/acceptance_v3_9.py` 中模型 ID 仅出现于 MODELS 常量、schema 守卫与合成 fixture 构造，无语义特判。

## 三、仅披露与零追溯

- 程序化 diff（独立实现）：两份 projection 相对 v3.6 源，除 `contract_version`/`supersedes`/新增 `decimal_output_contract` 外零变更；`answer_value_schema` 仅量化字段的 `pattern` 一项由宽松（接受任意小数位，含精确商）收紧为 6 位 pattern。
- 12/12 case 的 clean-room oracle 期望值在 v3.8 时代 projection 与 v3.9 projection 下 canonical 逐字节相等；snapshot 未移动。v3.7/v3.8 plan 全部引用同一 `cases/candidate_v3_6/` projection，oracle 模块 `harness/acceptance_v3_7.py` 哈希锁于冻结 v3.7 bundle——期望值自 v3.7 起逐字节未变。
- v3.8 式精确商答案在 v3.9 grader 下仍失败（收紧后的词法 schema 直接拒绝，`structure_parsed=false`）——无追溯放宽；合规 6 位答案通过（fixture 复算）。

## 四、门禁正反例与 v3.8 冻结集复现

- **独立清洁室探针**：对 v3.6 fkw-03 以 3 个扰动探针（含平局探针 2.0000025→2.000002，区分 HALF_EVEN 与 HALF_UP）证实 oracle 按 6 位 HALF_EVEN 渲染，而 v3.6 projection 无任何披露——缺陷真实。
- **门禁重跑 v3.8 冻结任务集**：违反恰为 fkw-03 与 fkw-07，均为 `undisclosed_quantization_convention`，精确复现交付审计发现；其余 10 case 通过。
- **v3.9 正例**：12/12 visible，独立重跑与冻结 fixture `oracle_visibility.report.json` 一致。
- **反例**：5/5 捕获（v3.6 fkw-03 原缺陷、v3.6 fkw-07 同型缺陷、位数不一致、舍入模式不一致、词法豁免），独立重跑与冻结 fixture `oracle_visibility.negative.json` 一致。
- fkw-07 披露为门禁直接产出且必要：门禁对 v3.8 冻结集独立检出该案；不披露则 v3.9 冻结验证（verify-contracts 内置该门禁）无法通过。

## 五、重跑范围与授权结构

- plan_core 输入增量经逐字段归因：仅 fkw-03/fkw-07 的 projection_sha256 与其 tool_schema_sha256 变化（tool schema 内嵌 answer schema），其余 10 case 的 source/projection/snapshot/tool 哈希与 v3.8 全等，12 案 snapshot 哈希全未变；config 哈希因新版本 config 变化。plan_core 变化 ⇒ 36 个 run identity 全部失效并全量更新（v3.8∩v3.9=∅），「仅重跑受影响 3×2」在本 plan 下不可能——预登记全量 36 run 是唯一一致范围，已写入 plan（`rerun_scope_preregistration`）。
- 绑定结构不变：`separate_plan_bound_authorization_required=true`、`passing_identity_preflight_required=true`、`paid_calls_authorized=false`、`execution_state=offline_validation_only`；bundle/config/plan 三处一致。
- config 相对 v3.8 的增量仅限 contract_version/supersedes/semantic_bindings/contract_repair；execution 块（重试、预算、付费开关）逐字节未动（v3.8 即为 paid=false、offline=true）。

## 六、全量离线复跑结果

| 项目 | 结果 |
| --- | --- |
| `harness.acceptance_v3_9 verify-contracts` | 通过（bundle `f4461964…188d`） |
| `harness.acceptance_v3_9 verify-plan` | 通过（plan 可复现，`e5ca961f…e9b6`） |
| `harness.acceptance_v3_9 scan-fixtures` | 7 文件 0 findings |
| Python 全量（unittest discover） | 176/176 通过 |
| Node 全量（node --test integration） | 55/55 通过（含 36-run 合成链路端到端） |
| v3.5/v3.6/v3.7/v3.8 verify-contracts | 4/4 通过，bundle 哈希与声明一致 |
| v3.8 交付审计机制层脚本复跑 | 50/50，AUDIT_VERDICT=PASS（v3.8 冻结证据未受影响） |
| v3.9 fixture 秘密扫描（独立重跑） | 0 findings |

## 七、唯一失败项（退回事项）

**v3.9 config 声明与强制执行的计算绑定不一致（低严重度）**

- 事实：`contracts/run_trace_harness_config.v3.9.json:115` 声明 `"calculation": "executed_decimal_rational_v3_8"`；同 bundle 的 `harness/acceptance_v3_9.py:71` 将 `CALCULATION_IMPLEMENTATION` 升级为 `decimal_rational_v3_9`，grader（`implementation == CALCULATION_IMPLEMENTATION`）、`harness/live_acceptance_v3_9.mjs:257` 与全部 v3.9 fixture 均强制/使用新标签。v3.8 中该声明与强制标签严格对应（`executed_decimal_rational_v3_8` ↔ `decimal_rational_v3_8`），v3.9 未随升级更新。
- 复现命令：
  ```bash
  uv run python -m audit.audit_stage3_v3_9_delivery   # E3c 失败项；total checks=96 failures=1
  grep -n '"calculation"' contracts/run_trace_harness_config.v3.9.json
  grep -n 'CALCULATION_IMPLEMENTATION =' harness/acceptance_v3_9.py
  ```
- 影响面：功能性影响为零——强制路径（grader 常量、运行时、fixture）内部一致，不影响候选可见合同、判分、三模型对称或重跑范围逻辑；但该 config 是冻结合同的规范性声明，且 plan_core 绑定其哈希。若带着错误声明进入正式 36-run，下一轮交付审计在勾稽「config 声明 ↔ trace implementation 标签」时必然复现本不一致，可能危及整批付费证据的审计结论。与本轮修复所要根除的「声明与强制脱节」同族，故不予签署。
- 严重度：低。
- 最小修复：`harness/acceptance_v3_9.py::_config()` 中将 `source["semantic_bindings"]["calculation"]` 置为 `"executed_decimal_rational_v3_9"`，重跑 `freeze-contracts`（确定性：config 哈希 → plan_core → 36 run identity → bundle 哈希全量更新），重跑本审计脚本至 `AUDIT_VERDICT=PASS`。除此之外无任何其他需要改动项。

## 八、限制

- 全程离线：未读取或记录任何凭据，未发起任何 preflight/付费/候选模型调用；审计仅基于冻结产物、哈希锁定代码的确定性重算与合成 fixture。
- 未重跑 `freeze-contracts`（会覆写冻结产物，违反只读审计）；可复现性由 verify-plan 的 write=False 全等重建、披露 projection 的确定性重建校验与全量哈希复算共同确立。
- 本审计不生成排行榜、CSR、pass^3 或演示；在修复复审通过前，否决基于 v3.9 合同启动任何新一轮执行。
- n=1/模型/case 的统计限制在重跑后仍适用（与 v3.8 交付审计相同口径）。

## 九、审计哈希

- 独立审计脚本：`audit/audit_stage3_v3_9_delivery.py`，SHA-256 `9cf92f235c1fd306354a3bbc4175c3a12ede8c6186f9bfc38d37dcf4b19a561d`（96 项检查：95 通过 / 1 失败，失败项即第七节）
- 本报告文件 SHA-256 由交付评论随附件公布（避免自引用改变文件哈希）。
