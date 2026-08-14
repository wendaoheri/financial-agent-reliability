# Stage 3C-7 独立门禁复审报告：v3.11 token 预算修复与 550 续跑计划（PER-62）

日期：2026-08-13 · 审计方：独立评分与统计审计师（与出题、oracle、harness 实现职责隔离）
审计方式：全程离线；未读取任何密钥/凭据，未发起 preflight、候选或任何付费模型调用；未修改任何 v3.5–v3.11 冻结产物；未生成排行榜或演示。

## 一、结论

**判定：PASS。**

v3.11 满足「3 模型身份预检 + 550 单元续跑（10 覆盖 + repeat 2–3）」技术门：

1. **token 预算一致性修复成立**（方向 a）：累计上限 262144 = max_model_requests(8) × single_request_context_window(32768)，为 budget-design 推导而非观测反推；三模型对称；运行时请求数强制语义逐字未变。
2. **550 续跑计划成立**：550/550 identity 清洁室独立重推一致；coverage_map 与 v3.10 作废取证 10/10 精确对应；与 v3.5–v3.10 全部 990 个历史 plan run id 交集为 ∅；作废取证永久保留、覆盖不替换。
3. **身份预检子门以 carry-over 成立**：v3.10 preflight（3/3 passed，`preflight_sha256=669cbd04…`）所绑定的身份要素在 v3.11 下逐字节未变（见第六节），预检证据在 v3.11 下继续有效；本轮按禁止条款未重跑 preflight。
4. 260 个 v3.10 冻结单元在 v3.11 下有效可比，无不可比项、无混版；v3.5–v3.10 冻结产物零漂移；可恢复执行内建于冻结 harness 且无外部驱动旁路；离线门与全量测试全绿（Python 222/222、Node 78/78）。

父议题常设付费授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`）下，pass 后由交付负责人直接派发 550 单元续跑，无需再次请求授权。

## 二、审计方法

6 条独立核验轨并行执行（哈希/supersedes、token 预算语义、变更最小化、可比性、续跑计划、可恢复执行与测试），每轨独立复算、不采信实现侧脚本为黑盒；协调员另对关键锚点（取证文件哈希、种子/run_id 公式、262144 推导）亲自独立复算交叉印证。独立复推脚本固化于 `audit/per62_550_rederivation.py`、`audit/per62_plan_audit.py`（RESULT: PASS）。

## 三、冻结哈希与零漂移（独立复算）

**v3.11 声明哈希 13/13 复算一致**（口径均独立确定：bundle_sha256 = canonical-json(artifacts[{path,sha256}]) 的 SHA-256，111 个 artifact 逐一与磁盘字节比对；plan_sha256 = 去除自引用字段后全文 canonical 哈希；plan_core = {contract_version, config_sha256, models, task_inputs[5 键/任务]} canonical 哈希）：

| 产物 | SHA-256 | 复算 |
|---|---|---|
| bundle_sha256 | `b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d` | ✓ |
| bundle 文件哈希 | `760a32cccedfdcc5126dd6f78d8ad024e00216e24e0b0b23c69689a174a171c1` | ✓ |
| plan_sha256 | `c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c` | ✓ |
| plan_core_sha256 | `559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604` | ✓（独立重建） |
| config 文件 | `bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e` | ✓ |
| run_trace.schema.v3.11.json | `fb14da23222b19f82b7157fa551ebacf0b0697e8ffbd4d118b4b6f7e90d02027` | ✓ |
| reason_codes.v3.11.json | `f16f47059c95b6d083afef57ece3979519abdd8d25c989d4d8e8185f0ced31ee` | ✓ |
| candidate_output_contracts.v3.11.json | `817db749da451fb8dcccc427f0ef7271d623fa5951f124c99434cb739563deb0` | ✓ |
| candidate_submission_wire_contract.v3.11.json | `0596d6b08593fd5e33f7e6fcd49da7197f30f04974f8c9f862aaf8682d2808d4` | ✓ |
| grader_result.schema.v3.11.json | `7f7cdd9fa47420d014da8e7f8fbe4214f5111b7a76dcbe8cd9ac1aa1c3654383` | ✓ |
| run_trace_validator_v3_11.py | `4bda365768e6044da24a23de93e284e9fd52e3c2dee66c2fc3a2bf2c5568b0bd` | ✓ |
| harness/acceptance_v3_11.py | `ecf1af3ac1ab779042986fd527a5cda3c5c0e12948f9f482732104c52eaa651b` | ✓ |
| harness/live_acceptance_v3_11.mjs | `5f8c99520f0ff7203be1a73b1b646b46395fe35bd292c8500243f0178a296fec` | ✓ |
| invalidated-runs.json（v3.10 取证） | `e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1` | ✓ |

**v3.5–v3.10 零漂移**：各版合同 bundle/plan/evidence bundle 哈希相对父议题基线全部复算一致（v3.6–v3.10 bundle+plan、v3.5/v3.8/v3.9/v3.10 evidence bundle），累计 1500+ artifact 文件逐一字节复算，0 漂移。

**supersedes 链**：合同 bundle 链与 plan 链 v3.11→v3.10→…→v3.5 连续、无跳版、无环，每跳 sha256 与被指向文件实测哈希一致；v3.5 为根。

口径疑点（低危，不构成风险）：① v3.5 合同 bundle 采用历史口径（继承 artifacts ∪ 自身 artifacts 的行承诺方案），与 v3.6+ 口径不同但按冻结时口径复算一致；② run_trace.schema / grader_result.schema 各版不含机器可验 supersedes 字段，版本连续性靠 bundle 链锚定——建议未来版本在 schema 内加 `{path, sha256}` supersedes。

## 四、token 预算修复核验

1. **推导**：config `resource_budget.max_total_tokens=262144`、`single_request_context_window=32768`、`max_model_requests=8`；schema `usage.total_tokens.maximum=262144`；推导块 `max_total_tokens_derivation` 与 `token_budget_repair` 写入 config/plan/bundle 三处且数值一致；8×32768=262144 独立复算成立。v3.10 缺陷属实（schema :304 钉 32768 + 实际拒绝取证 `usage/total_tokens:39795 > maximum 32768`）。
2. **非反推（对抗性证伪尝试全部失败）**：字面观测值 35484/39795 在仓库中仅出现于取证散文与注释，无任何代码解析；262144 在 runs/ 观测数据中零出现；因子结构互素（262144=2¹⁸，39795=3×5×7×379，gcd=1）；对 k=1…10 的 floor/ceil/round(obs×k) 均 ≠262144；唯一写入 max_total_tokens 的代码为字面常数乘积（`acceptance_v3_11.py:191`）；`back_derived_from_observed_usage=false` 声明与实际一致。对观测峰值裕量 6.59×（>6× 声明属实）。32768 为冻结传输层既有常数（v1 config 至 v3.10 传输层出处链完整），非本轮新造。
3. **三模型对称**：上限位于模型无关的 `resource_budget` 与模型无关 schema `usage`；无任何按模型 ID 的预算/判分特判；唯一按模型分支为 qwen `enable_thinking=false`（自 v3.4 既有的协议参数，双版 fairness 块均有披露），不构成预算/判分不对称。
4. **运行时请求数强制未变**：v3.10/v3.11 执行循环条件逐字相同（均以 `max_model_requests=8` 强制）；v3.11 执行循环中 total_tokens 仅作记账，无任何累计 token 中止/截断逻辑；validator v3_11 新增的显式上限比对属冻结时检查（与 schema maximum 冗余同值），运行时行为零改动。

## 五、变更最小化核验（独立叶子级 diff）

程序化 diff 逐字节复现（`audit/build_stage3_v3_11_diff.py` 重跑输出与冻结产物字节一致，脚本无白名单/隐藏逻辑）。协调员轨另以逐元素递归 diff 独立复核并补做实现侧脚本未覆盖的 frozen bundle 对：

- config：18 条叶差异 = token 预算块（3）+ planned_run_cap（1）+ 版本/扩展元数据（14）；`system_prompt`、`tool_names`、`security`、`fairness`、`request_commitments`、`provider_retry_policy`、`semantic_bindings`、`runtime`、`candidate_model_ids` 深比较全等。
- schema：恰 6 条（`$id`、`contract_version` const、`benchmark_id` const、`repeat` const 1→enum[1,2,3]、`usage.total_tokens.maximum`）；其余 token 约束（input/output_tokens、model_requests、attempts、tool_calls、maxItems）全部未动。
- reason_codes / output_contracts / wire_contract / grader_result.schema：仅版本标签与 supersedes；reason 定义、case_sets、算法与规则逐字节相等。
- frozen bundle：231 条叶差异全部归类；唯一非版本内容变化为测试夹具替换（`trace.multi_request_retry.json`→`trace.long_context_cumulative_tokens.json`，retry 策略本体未变，v3.10 套件原夹具保留）；`candidate_answers.synthetic.json` 两版哈希相同。
- 90 个 projection：非版本字段差异总数 = 0（叶子级与块级双重验证）；`source_case_sha256/snapshot_sha256/tool_schema_sha256` 跨版本 0 差异，且全部对盘复算一致。
- prompt、oracle 期望、判分阈值、reason 语义、案例材料逐字节未变（哈希 + 深比较 + mtime 时点三重证据；v3.11 判分/oracle 接口为 v3.10 纯函数原样 import 复用，仅重打版本标签）。

## 六、可比性核验（260 个 v3.10 冻结单元）

1. 计数与隔离：traces/graders/candidates 各 260，checkpoints 270（差集恰为 10 个作废 run）；10 个作废 run_id 在冻结产物中成员关系为 0。
2. total_tokens：260 trace 全部 ≤32768（min 4211，max 32432），天然落在新上限 262144 内。
3. oracle：clean-room oracle 对全部 90 案例在 v3.10/v3.11 projection 下输出 0 不一致（另 13 案例独立手工 Decimal 重算吻合）。
4. grader：判分函数全函数体无 token 读取；12 组样例（4 pass fixture + 4 自构造 fail + 4 世系）在 v3.10/v3.11 下 checks/failed_checks/derived_reason_codes 逐项相同；探针：仅改 usage.total_tokens 判分结果不变。
5. tool schema/snapshot/案例哈希：90 案例三类绑定哈希跨版本逐一相等；30 个去重 snapshot + 90 个源案例卡全量复算吻合。
6. 无混版：v3.10 冻结运行目录全目录无 v3.11/262144 命中；260 grader 结果自哈希与 candidate 绑定全部复核吻合；`retroactive_regrading=false`。

**结论：无不可比项，无混版。** 260 个 v3.10 单元与后续 550 个 v3.11 单元可在同一判分口径下合并分析（合并报告阶段须声明合同版本）。

## 七、550 续跑计划核验（清洁室独立重推）

- **公式锚定**：以 invalidated-runs.json 10 条作废记录为真值，seed/run_id 公式（canonical-json sha256，master_seed=20260813）独立复现 10/10（协调员亲自复算亦 10/10）。
- **550 重推**：全部 550 单元 seed+run_id+identity 与 plan 声明逐一相等，mismatches=0；sequence 恰为 1..550；plan_core_sha256 与 plan_sha256 独立重构一致。
- **coverage_map**：10 项与作废取证 10 条逐一精确对应（case/model/repeat/作废 run_id/v3.10 sequence），按 v3.10 sequence 升序 [146,155,164,174,182,191,200,218,221,236] 排为 coverage sequence 1–10；覆盖 run_id ≠ 作废 run_id（benchmark_id 升版 + seed 全部不同）。
- **零交集**：v3.5–v3.10 六份 plan 去重历史 run_id = 990（核实属实）；550 内部互异；交集 ∅。
- **取证保留**：`coverage_replaces_or_reexecutes_invalidation=false`；forensics 块绑定文件哈希/entry_count 与实物一致；`invalidated-runs.json` 与 `grading-failures/`（9 件，对应 9 条判分拒绝路径作废；另 1 条 seq 146 为不可复现环境拒绝、仅 forensics，自洽）在盘。
- **cap 自洽**：550 = 10 + 540，540 = 90×3×2（repeat 2/3 各 270）；`registered_total_run_cap=550` 为 per-version 口径（v3.10 同口径=810，证伪跨版本累计口径），自洽。

## 八、可恢复执行与离线门

- `harness/live_acceptance_v3_11.mjs` 内建四种 resume 语义并经独立探针实证：finalized-skip（产物哈希 resume 前后逐一相等）、partial/inconsistent 硬停止（含故障注入探针）、report-only 作废 + guard rail（pending/finalized 作废被拒）、判分失败取证持久化（注入 Bearer token 被 `[REDACTED]` 脱敏）。
- 无外部驱动旁路：v3.11 路径零引用 `audit/driver_*`，无 env 后门（SKIP/FORCE/BYPASS/OVERRIDE 零命中）；`driver_v3_10_live_resume.mjs` 仅历史保留。
- 离线门复跑 5/5 绿：verify-contracts（valid=true，bundle 哈希吻合）、verify-plan（valid=true）、scan-fixtures（0 findings）、gold-report（valid）、gate-report（90/90 visible）。
- 回归：Python 222/222（198 既有 + 24 新增，逐文件计数核实）、Node 78/78（65 既有 + 13 新增）；550-run 合成端到端与 resume 语义测试存在且断言真实；全程 synthetic-only（live transport 在 tests/ 中零引用，endpoint 均 example.invalid）。

## 九、身份预检子门（协调员直接核验）

v3.11 未重跑 preflight（本轮禁止付费调用，正确）。carry-over 有效性证据：preflight（3/3 passed）绑定的 `parameters_sha256_by_model`（3 个哈希）与 90 案例 per-case `tool_schema_sha256` 向量在 v3.10/v3.11 plan/config 间逐字节相等（协调员独立比对 90/90）；三候选模型 ID、endpoint、请求承诺均未变。**预检证据在 v3.11 下继续有效。** 建议：续跑派发时按 config `requires_passing_identity_preflight=true` 在首个付费请求前做一次声明核对（若 endpoint/参数配置自 2026-08-13 以来未变则直接沿用）。

## 十、限制、疑点与建议（全部低危，不影响判定）

1. schema 文件内 total_tokens 无 description 字段，累计语义的合同可见载体为 config 推导块/修复块（满足门要求，建议未来在 schema 自述）。
2. run_trace.schema / grader_result.schema 各版无机器可验 supersedes 字段（由 bundle 链锚定；建议未来补充）。
3. v3.11 validator 新增冻结时显式上限检查：与 schema maximum 冗余同值、不改变判分，属已披露的非实质强化。
4. 仓库测试未断言的 4 项 resume 语义（invalidation guard rail、inconsistent 硬停止、report-only 作废流水、判分失败取证脱敏）本轮由审计探针实证通过；建议固化为冻结测试。
5. 取证脱敏为「先脱敏后截尾」，跨截断边界理论上可残留无前缀碎片；现实注入通道（子进程 stderr）已被覆盖，候选 schema 结构上阻断合法提交注入。
6. `bundle_sha256` 自哈希字段的精确规范化定义建议在文档中补充（版本链内自洽，文件级哈希链已全部实测通过）。
7. pyproject.toml/uv.lock 的工作树改动早于本轮（8/12 19:30），与 v3.11 冻结产物无关。

## 十一、复现命令

```bash
# 协调员锚点复算与六轨复核入口
uv run python audit/per62_550_rederivation.py      # 10/10 真值锚定 + 550/550 清洁室重推
uv run python audit/per62_plan_audit.py            # coverage_map/零交集/cap 自洽
shasum -a 256 runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json
# 离线门与回归
uv run python -m harness.acceptance_v3_11 verify-contracts|verify-plan|scan-fixtures|gold-report|gate-report
uv run python audit/build_stage3_v3_11_diff.py
uv run python audit/verify_v3_11_continuation_pre_execution.py
uv run python -m unittest discover -s tests
node --test tests/integration/*.test.mjs
```

## 十二、判定与授权

**PASS**——v3.11 满足「3 模型身份预检 + 550 单元续跑（10 覆盖 + repeat 2–3）」技术门。按父议题常设授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`），由交付负责人直接派发 550 单元续跑。本轮未生成排行榜或演示；v3.5–v3.10 冻结产物未覆盖、未重评。
