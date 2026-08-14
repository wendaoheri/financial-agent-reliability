# Stage 3C-8 独立门禁复审报告：v3.11.1 单单元覆盖计划（PER-78）

日期：2026-08-14 · 审计方：独立评分与统计审计师（与出题、oracle、harness 实现职责隔离）
审计方式：全程离线；未读取任何密钥/凭据，未发起 preflight、覆盖运行或任何付费模型调用；未修改任何 v3.5–v3.11 冻结产物、授权工件与执行门状态；未生成排行榜或演示。语义层独立复审以本轮为准。

## 一、结论

**判定：PASS。** v3.11.1 满足「单单元覆盖运行」技术门。

1. 计划仅升版（plan_version 3.11.1，contract_version 保持 3.11.0），`supersedes` 精确指向 v3.11 续跑计划；计划恰含 1 个任务/1 个 run，cap=1，单元即 seq 268 作废单元（case-synthetic-ftw-14-normal-v3 × deepseek-v4-pro × repeat 2）。
2. 合同零改动：v3.11 bundle/config 逐字节不变（文件哈希 + artifact-list 双重校验），v3.5–v3.10 全部冻结 bundle 与 artifact 零漂移；prompt、oracle、判分阈值、reason 语义、案例材料未动。
3. 无事后选择：覆盖 identity 相对 seq 268 identity 的差异**仅** `plan_core_sha256`；seed 由既有公式+master_seed 20260813 独立重推吻合（738396034）；覆盖 run_id 与 v3.5–v3.11 全部 1540 个历史 plan run id 零交集；seq 268 run_id 列入 `denied_run_ids`，取证永久保留、覆盖不替换。
4. 授权工件恰绑定 1 个预登记 run id，哈希绑定全部复算吻合，preflight carry-over 链（v3.10 `669cbd04…` → v3.11 `a1abbba9…` → v3.11.1 `b03a9a71…`）逐跳自哈希复算成立，零付费 preflight；`execution_gate` 保持 **pending**（本轮未改动）。
5. 构建器幂等（重跑逐字节一致）、清洁室脚本结构性独立（仅标准库）；离线门与全量测试全绿（Python 239/239、Node 78/78）。

父议题常设付费授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`，元数据在案）下，pass 后由交付负责人直接派发覆盖运行，无需再次请求授权。

## 二、审计方法

不采信实现侧脚本为黑盒：审计师以自建清洁室脚本 `audit/per78_gate_review_v3_11_1.py`（仅标准库，不 import 任何 harness/contracts 模块，canonical JSON 按冻结定义自行实现）对全部哈希、种子、run_id、自哈希从冻结原语独立复算，共 **100 项检查全部通过（RESULT: PASS）**；随后按预登记复现命令复跑实现侧与清洁室脚本、离线门与全量测试作交叉印证。

## 三、计划哈希、结构与 supersedes 链（独立复算）

| 产物 | SHA-256 | 复算 |
|---|---|---|
| plan_sha256（v3.11.1，去自引用字段 canonical 哈希） | `64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b` | ✓ |
| plan_core_sha256（{contract_version, config_sha256, models, task_inputs[5 键]} 独立重建） | `c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b` | ✓ |
| v3.11 plan_sha256（自哈希重算，证明该文件未被本轮触碰） | `c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c` | ✓ |
| v3.11 plan_core_sha256 | `559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604` | ✓ |
| 覆盖 run_id（identity canonical 哈希前 32 位独立重推） | `run_0e1e8f4400e16f22f6581e0bb0d9c54d` | ✓ |
| 覆盖 seed（公式独立重推） | `738396034`（= seq 268 seed） | ✓ |

- `supersedes` 指向 `contracts/stage3_acceptance_plan.v3.11.json`：指针 sha256 = 该文件实测哈希；指针 plan_sha256 = 该文件内容自哈希重算值。
- 计划链 v3.11.1→v3.11→v3.10→…→v3.5 共 7 跳逐跳核验：每一跳的文件哈希与内容自哈希（v3.6–v3.10 另与父议题元数据基线 plan 哈希逐一比对）全部吻合，v3.5 `supersedes=null` 为根。
- 计划恰 1 任务/1 run：task/run 单元字段 = seq 268 单元；`coverage_run_cap=registered_total_run_cap=1`；run 行绑定的 run_id 即覆盖 run_id。

## 四、合同零改动核验

- v3.11 config 文件哈希 `bc19cdaf…40f9e` ✓；bundle_sha256 `b62f96d8…6d9d` 字段值 ✓ 且 = artifact-list canonical 哈希重算值 ✓（双重校验）；111 个 artifact 逐一与磁盘字节比对，0 漂移。
- v3.5–v3.10 零漂移：v3.6（33 artifacts）/v3.7（20）/v3.8（15）/v3.9（21）/v3.10（111）/v3.5（8）各冻结 bundle 的 bundle_sha256 与父议题元数据基线（v3.6–v3.10）及世系基线（v3.5）一致，artifact-list 自洽重算一致，全部 artifact 文件对盘哈希一致。
- prompt、oracle、判分阈值、reason 语义、案例材料：全部承载文件（config/schema/reason_codes/output/wire/validator/harness/projections/fixtures）均在 bundle artifact-list 内，哈希锚定即逐字节未动；覆盖案例任务行 11 个字段与 v3.11 冻结任务行逐一相等，源案例卡/projection/snapshot 三类材料对盘哈希吻合。
- 变更面核验：工作树仅 pyproject.toml/uv.lock 两个已跟踪文件有改动（mtime 2026-08-12 19:30，早于 Stage 3 各轮、与冻结产物无关，PER-62 审计已披露）；其余全部为未跟踪新增，无任何已跟踪冻结产物被修改。

## 五、无事后选择核验

- identity 差异：覆盖 identity 与 seq 268 identity（取自 v3.11 plan seq 268 行与 forensics，两处互相吻合）逐键比对，差异集合恰为 `{plan_core_sha256}`；case/model/repeat/seed/variant/config 全同。
- seed：`int(sha256(canonical({benchmark_id, case_id, master_seed, repeat, requested_model_id}))[:16],16) mod 2^32`，benchmark_id=`financial-agent-reliability-v3.11`、master_seed=20260813，独立重推 = 738396034。
- 兄弟记录种子同一公式旁证：repeat 1（v3.10 轮 benchmark id）=1292484141、repeat 3（v3.11）=1339675819，均与已冻结 trace 记录吻合；两条兄弟 trace 对盘哈希、status=succeeded、identity 逐一核验通过；seq 268 无 trace 文件（中途被 teardown，与取证一致）。
- 零交集：v3.5–v3.9 各 36 + v3.10 810 + v3.11 550 = **1540** 个历史 plan run id，内部互异；覆盖 run_id 不在其中；seq 268 id 在其中且被列入授权 `denied_run_ids`。
- 取证保留：`invalidated-runs.json`（文件哈希 `7fd165fa…`、报告自哈希 `3a5189e7…` 重算吻合）、`pending-invalidations.json`（`61c7baec…`）、checkpoint 残留（`68f0e738…`，仅 1 条 run_started 事件，payload 绑定 v3.11 plan 哈希与本案例 tool_schema 向量 `118f9266…`）全部在盘且哈希吻合；`replaced_or_reexecuted=false`；plan/coverage_map/授权工件三处 `coverage_replaces_or_reexecutes_invalidation=false`、`invalidated_run_id_reuse_forbidden=true`。
- 轮次计数旁证：v3.11 冻结 trace=549、v3.10 冻结 trace=260，与「549frozen_1invalidated」及 v3.10 260 有效记录一致。

## 六、授权工件与 preflight carry-over

- 授权自哈希 `a93d80fc…` 重算吻合；kind、`authorized_run_ids` 恰为覆盖 run_id、`authorized_run_count=1`、`maximum_runs=1`、`exact_model_ids=[deepseek-v4-pro]`、`authorized_unit` 恰为覆盖单元、`denied_run_ids=[seq 268 id]`、范围外拒绝策略在案。
- 绑定哈希全部与独立复算值一致：plan/plan_core/bundle/config/preflight；`maximum_model_requests_per_run=8` = 冻结 config `max_model_requests`（资源公平）。
- `execution_gate`：独立复审必需 + 状态 **pending** + 需交付负责人派发——本轮未改动该状态。
- preflight carry-over 链逐跳复算：v3.10 `669cbd04…`（3/3）→ v3.11 `a1abbba9…`（carry-over）→ v3.11.1 `b03a9a71…`（1/1，deepseek），各自哈希重算吻合；v3.11.1 结果对象与 v3.11 源中 deepseek 结果逐字节相等，v3.10→v3.11 同结果亦逐字节相等；deepseek 参数承诺 `429e4c97…` = 未变 config 的承诺值；endpoint_id 链上一致；`paid_calls_in_this_round=0`。
- 授权依据：PER-77、父议题 ID、常设授权范围与父议题元数据在案一致（`candidate_runs_allowed=true`、`stage3_acceptance_runs_authorized=true`、`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`）。
- 轮目录冻结副本（plan/config/bundle）与 contracts/ 原件逐字节一致。

## 七、幂等、独立性与回归

- 构建器 `audit/build_stage3_v3_11_1_execution_artifacts.py` 重跑：RESULT: PASS，轮目录全部工件与导出件重跑前后逐字节一致（幂等成立）；脚本仅标准库、无网络/子进程/env 旁路。
- 清洁室脚本 `audit/verify_v3_11_1_coverage_pre_execution.py`：仅标准库（结构性独立于 harness），52/52 全绿，RESULT: PASS。
- 离线门复跑：`acceptance_v3_11_1 verify-plan/verify-contracts` valid（含覆盖案例 oracle 可见性门）；`acceptance_v3_11 verify-plan/verify-contracts` valid（合同零漂移）。
- 回归：Python 全套 **239/239 OK**（含新增 `test_financial_acceptance_v3_11_1.py` 17 项，覆盖可复现性/零漂移/种子连续/identity 差异/零交集/取证保留/授权绑定等门属性）；Node 集成全套 **78/78 pass**（其中 v3.11 套件 13/13）。
- 覆盖 run_id 全仓引用面核验：仅出现在计划、授权工件、轮目录冻结副本、builder/verifier 与审计/预登记文档中——纯预登记状态，无任何 trace/结果/执行旁路引用；`harness/live_acceptance_v3_11.mjs` 未内嵌 v3.11.1 路径。

## 八、限制、疑点与建议（全部低危，不影响判定）

1. 授权工件 `authorization_basis.delivery_decision_metadata` 引用的 `stage3_next_decision` 值为派发决策语义（`per64_single_unit_coverage_then_per32`），父议题元数据现值已更新为 `await_stage3c8_v3_11_1_coverage_gate_audit`（等待本门禁）——属时点差异的历史引用，非绑定字段漂移；建议派发后由交付负责人回写决策值。
2. v3.6 计划对 v3.5 的 supersedes 指针仅含 path+sha256（无 plan_sha256 字段），本轮以文件实测哈希锚定；v3.5 bundle 采用历史口径——均与 PER-62 审计记录一致，版本链完整性不受影响。
3. v3.5–v3.10 计划体无 `plan_version` 字段，链核验以「指针哈希+内容自哈希重算+元数据基线」三重锚定替代，结论不受影响。
4. 覆盖运行执行时，建议执行驱动在任何 provider 请求前按授权工件 `out_of_scope_policy` 拒绝不在 `authorized_run_ids` 内的 run_id（含全部 1540 个历史 id 与被拒的 seq 268 id），并在运行后对 trace 的 run_identity 与本计划声明逐键比对。

## 九、复现命令

```bash
uv run python audit/per78_gate_review_v3_11_1.py             # 100/100 独立复算 PASS
uv run python audit/verify_v3_11_1_coverage_pre_execution.py # 52/52 清洁室 PASS
uv run python audit/build_stage3_v3_11_1_execution_artifacts.py  # 幂等重建 PASS
uv run python -m harness.acceptance_v3_11_1 verify-plan      # valid
uv run python -m harness.acceptance_v3_11_1 verify-contracts # valid
uv run python -m harness.acceptance_v3_11 verify-plan        # valid
uv run python -m harness.acceptance_v3_11 verify-contracts   # valid
uv run python -m unittest discover -s tests                  # 239 OK
node --test tests/integration/*.test.mjs                     # 78 pass
```

## 十、判定与授权

**PASS**——v3.11.1 满足「单单元覆盖运行」技术门：仅计划升版、合同零改动、无事后选择、授权恰绑定唯一预登记 run id、执行门 pending 待派发。按父议题常设授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`），由交付负责人直接派发覆盖运行，无需再次请求授权。本轮未生成排行榜或演示；v3.5–v3.11 冻结产物未覆盖、未重评、未重分级。
