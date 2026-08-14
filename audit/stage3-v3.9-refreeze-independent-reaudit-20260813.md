## Stage 3C-5（PER-54）v3.9 重冻独立复审（PER-52 修复闭环）

审计人：独立评分与统计审计师（与出题、oracle、harness 实现职责隔离）
审计对象：PER-52 重冻后的 v3.9 合同 bundle（21 artifact）、plan、config、实现侧审计脚本改动范围；v3.5–v3.8 冻结产物只读对照
审计日期：2026-08-13（UTC）
被审交付声明：PER-52 评论 `12939662-0b46-491b-96e5-344b221f3344`；前序 PER-51 复审 FAIL（唯一失败项 E3c）报告 SHA-256 `ace632903f4c7bc3c94335910453e8abd9bb78518226f2df7c1886dcadb3a1b3`

## 独立结论

**PASS。** PER-51 唯一失败项（config `semantic_bindings.calculation` 陈旧声明）确认关闭：声明 `executed_decimal_rational_v3_9` 与强制标签 `decimal_rational_v3_9` 严格对应。修复范围经字节级取证确认为最小且无夹带：生产代码仅 `harness/acceptance_v3_9.py::_config()` 插入 PER-51 指定的那一行；实现侧审计脚本仅 DECLARED 声明块重声明（4 个 v3.9 哈希 + 块首注释行 + 3 行说明注释），92 项检查代码与全部判定逻辑逐字节未动。projection、oracle、判分阈值、门禁逻辑、12 case 期望值全部未变；v3.5–v3.8 零漂移；36 个新 run identity 推导正确且与 v3.8 轮零交集；`retroactive_regrading=false`；三模型对称性不受影响。独立审计脚本 56/56 通过，实现侧 96/96 通过，全量离线测试通过。**v3.9 满足「3 模型身份预检 + 新一轮全量 36-run」的技术门**，可按常设授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`）由交付负责人直接派发重跑。

## 一、冻结输入独立复算（canonical-hash 清洁室独立重写，不复用实现侧哈希代码）

| 对象 | PER-52 声明 | 独立复算 | 结论 |
| --- | --- | --- | --- |
| v3.9 合同 bundle（artifact-list 内容哈希） | `77aea093…d030` | 一致；21/21 artifact 文件哈希逐一吻合磁盘 | 一致 |
| v3.9 plan（去 `plan_sha256` 规范内容） | `235b0415…e185` | 一致 | 一致 |
| v3.9 plan_core | `bf1d1ed4…4ebd` | 按 core 公式（contract_version/config_sha256/models/12×task_inputs）从磁盘输入独立重构一致 | 一致 |
| v3.9 config 文件 | `e06b3fae…0cfa` | 一致，且 manifest 与 plan_core 绑定同一 config 哈希 | 一致 |
| 实现侧审计脚本文件 | `f4afe6e6…5978` | 一致 | 一致 |
| fkw-03 / fkw-07 修复 projection | `9a1cb68f…e4f2` / `9d7605a5…483a` | 与 PER-51 时代声明逐字节一致（重冻未触碰） | 一致 |
| v3.5 / v3.6 / v3.7 / v3.8 bundle | `d24948f9…` / `afd1a163…` / `354e8413…` / `39a0853c…` | 4/4 bundle 哈希与全部 artifact（8/33/20/15）逐一零漂移 | 零漂移 |
| v3.8 plan | `636d94fb…3d22`（core `f272700e…66ae`） | 独立复算一致 | 一致 |
| supersedes 链 | v3.9 bundle/plan/config → v3.8（文件哈希+内容哈希）；projection → v3.6 源；历史链 v3.5←v3.6←v3.7←v3.8 | 全部衔接一致；preserved 块钉住四个历史 bundle 哈希且 `retroactive_regrading=false` | 一致 |

## 二、唯一失败项关闭核验

- `contracts/run_trace_harness_config.v3.9.json:115` 现声明 `"calculation": "executed_decimal_rational_v3_9"`。
- 强制路径全部使用新标签：`harness/acceptance_v3_9.py:71` `CALCULATION_IMPLEMENTATION = "decimal_rational_v3_9"`；grader 以 `item.get("implementation") == CALCULATION_IMPLEMENTATION` 绑定；`harness/live_acceptance_v3_9.mjs:257` 发射 `implementation: "decimal_rational_v3_9"`；4 个含 implementation 标签的 v3.9 fixture 全部使用新标签。
- v3.9 强制面（config/harness py/mjs/validator/fixture）对旧标签 `decimal_rational_v3_8` 的全文扫描：0 次出现。
- 配对约定与 v3.8 同构（v3.8：声明 `executed_decimal_rational_v3_8` ↔ 强制 `decimal_rational_v3_8`）。
- 实现侧 96 项审计中原失败项 E3c 现通过（semantic_bindings 增量恰为 calculation 标签升版 + 可见性门禁两项）。

## 三、无夹带核验（含字节级取证）

- **config 增量**：v3.9 相对 v3.8 顶层差异恰为 `contract_repair / contract_version / semantic_bindings / supersedes`；execution 块（重试、预算、付费开关）逐字节未动且保持 `paid_calls_authorized=false / offline_validation_only=true`；per-model 参数承诺与 v3.8 逐字节一致且恰覆盖 3 模型。
- **projection/oracle/期望值**：fkw-03/fkw-07 v3.9 projection 哈希与 PER-51 声明一致（未被重冻改动）；`cases/public/oracle.py` 哈希 == PER-28 注册值；12/12 case 的 clean-room oracle 期望值在 v3.8 时代与 v3.9 projection 下 canonical 逐字节相等，snapshot 未移动。判分阈值只存在于披露合同与哈希锁定的 grader 逻辑，均未变。
- **harness 取证**：重冻为确定性过程，freeze 写入集（config/reason/wire/output/schema×2/plan/fixture×7/projection×2/bundle）全部由模块代码从 v3.8 输入派生；`_config()` 内对 semantic_bindings 的赋值恰为 calculation + 可见性门禁两条。本机运行记录（Multica 会话 transcript）显示 PER-52 会话对生产文件的改动恰为两处：`harness/acceptance_v3_9.py` 单次 Edit（插入且仅插入 PER-51 指定的一行）与审计脚本 DECLARED 块单次 Edit；无任何其他生产文件写入。
- **审计脚本字节级 diff**：以 PER-51 审计会话的原始 Write+4 次 Edit 记录重建旧脚本，SHA-256 == `9cf92f23…`（与 PER-51 报告公布值吻合）；对当前文件逆向施加 PER-52 记录在案的单次 Edit 得到同一字节序列；正向施加则逐字节得到当前文件（SHA-256 == `f4afe6e6…`）。闭环证明改动范围恰为：4 个 v3.9 声明哈希、块首注释行改写（去掉 "from PER-51" 字样）、新增 3 行说明注释——全部位于 DECLARED 声明块内；92 项检查代码与判定逻辑零改动。
  - 观察（非缺陷）：PER-52 交付评论将改动表述为「仅 4 个声明哈希更新」，实际另含同一声明块内注释行的改写；其「该块随本次交付重新声明、其余检查代码逐字节未动」的表述与事实一致。

## 四、run identity 与重跑范围

- 36/36 `run_id == run_{sha256(run_identity)[:32]}`（清洁室独立重算），identity 内 plan_core/config 绑定、benchmark_id、repeat=1 均正确；与 PER-52 交付评论公布的 36 行（seq/model/run_id）逐一吻合。
- v3.8 ∩ v3.9 run id = ∅（36 个身份全量更新）；(model_id, seed) 多重集与 v3.8 完全一致；每案恰 3 run 覆盖 3 模型；task.run_ids 与 plan.runs 为同一 36 个唯一 id。
- 全部 identity 嵌入新 plan_core，plan 预登记 `rerun_scope_preregistration = all 36 runs`——全量重跑是唯一一致范围。
- `preserved.retroactive_regrading = false`；v3.8 式精确商答案在 v3.9 grader 下仍失败（无追溯放宽，实现侧 E4 组复核通过）。

## 五、三模型对称性

- plan.fairness 声明 same prompt/tools/budget/retry/grader，models 恰为注册的 3 模型；per-model 参数承诺与 v3.8 逐字节一致。
- `harness/acceptance_v3_9.py` 中模型 ID 仅出现于 MODELS 常量、schema 守卫与合成 fixture 构造（3 处引用），无按模型 ID 的语义特判。
- synthetic provider/fixture 验证：Node 集成测试 55/55 通过（含 36-run 合成链路端到端）；v3.9 grader 对合规 6 位 fixture 现场复评通过。全程未读取任何凭据、未发起任何候选模型调用。

## 六、全量离线复跑结果

| 项目 | 结果 |
| --- | --- |
| 独立复审脚本 `audit.stage3_v3_9_refreeze_independent_audit` | 56/56 通过，INDEPENDENT_VERDICT=PASS |
| 实现侧 `audit.audit_stage3_v3_9_delivery` | 96/96 通过，AUDIT_VERDICT=PASS（原失败项 E3c 通过） |
| `harness.acceptance_v3_9 verify-contracts` | 通过（bundle `77aea093…d030`） |
| `harness.acceptance_v3_9 verify-plan` | 通过（write=False 全等重建，`235b0415…e185`） |
| `harness.acceptance_v3_9 scan-fixtures` | 7 文件 0 findings |
| Python 全量（unittest discover） | 176/176 通过 |
| Node 全量（node --test integration） | 55/55 通过 |
| v3.5/v3.6/v3.7/v3.8 verify-contracts | 4/4 通过，bundle 哈希与声明一致 |
| v3.8 交付审计机制层脚本复跑 | 50/50，AUDIT_VERDICT=PASS（v3.8 冻结证据未受影响） |

## 七、技术门判定

v3.9 重冻版本满足「3 模型身份预检 + 新一轮全量 36-run」的技术门：冻结合同内部声明与强制一致、plan_core/run identity 推导完整可复算、预检与付费授权结构完好（`separate_plan_bound_authorization_required=true`、`passing_identity_preflight_required=true`、`paid_calls_authorized=false`、`execution_state=offline_validation_only`）。父议题常设付费授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`）有效，pass 后由交付负责人直接派发全量 36-run 重跑，无需再次请求授权。

## 八、限制

- 全程离线：未读取或记录任何凭据，未发起任何 preflight/付费/候选模型调用；未重跑 `freeze-contracts`（避免覆写冻结产物），确定性由 verify-plan 全等重建与全量哈希复算确立。
- 本机文件 mtime 显示冻结产物最后一次写入为 2026-08-12 16:28:39 UTC，晚于 PER-52 交付评论（16:16 UTC）——与 PER-54 描述中「交付负责人交付 review 重冻确定性复算」相符；本审计独立复算的全部哈希与声明一致，内容不受该次重写影响。
- 本审计不生成排行榜、CSR、pass^3 或演示；n=1/模型/case 的统计限制在新重跑后仍适用（与 v3.8 交付审计同口径）。
- 字节级取证依赖本机 Multica 会话记录（PER-51/PER-52 运行 transcript）；哈希闭环（旧脚本重建 == PER-51 公布哈希；逆/正向 Edit 双吻合）使该证据可被任何持有相同记录者复核。

## 九、审计哈希

- 独立复审脚本：`audit/stage3_v3_9_refreeze_independent_audit.py`，SHA-256 `ae8c21142ed029173722f155409e7f1eba313528201af309273886b0e4376d94`（56 项检查全部通过）
- 本报告文件 SHA-256 由交付评论随附件公布（避免自引用改变文件哈希）。
