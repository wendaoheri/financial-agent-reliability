## PER-59 交付报告：v3.10 合同首轮 270 验收运行（Stage 3D-3）

执行日期：2026-08-13（UTC 01:46–06:11，含 10 次作废处置中断；纯执行累计 10,219,478 ms ≈ 2.84 h）
运行目录：`runs/stage3/acceptance-20260813-v3.10/`（证据 bundle 1070 件产物）

## 一、结论一览

| 项 | 值 |
|---|---|
| 计划单元 | 270（repeat==1，sequence 1–270） |
| 冻结成功（trace/grader/checkpoint 完整勾稽） | **260** |
| 作废（报告不替换，no_post_hoc_selection） | **10**（glm-5.2×9、deepseek-v4-pro×1） |
| succeeded / candidate_failed / invalid_provider_or_runtime | 251 / 9 / 0 |
| 通过全部适用判分检查 | 215 / 260 |
| 语义值正确（value_semantic_correct） | 244 / 260 |
| fallback / 泄密 / 真实副作用 / provider 失败 / 重试 | **0 / 0 / 0 / 0 / 0** |
| provider_attempts（= model_requests） | 917 |
| total_tokens / cost_usd | 3,231,053 / **null**（供应商无可核验费用） |
| 独立勾稽 | valid=true，reconciliation_errors=0 |

## 二、执行前冻结输入复算（全部一致，零漂移）

| 输入 | 声明 | 复算 |
|---|---|---|
| v3.10 bundle（111 artifact） | `b49e8ea8…2180` | 一致（verify-contracts valid） |
| v3.10 plan_sha256 | `009b1ea1…d4ec` | 一致（verify-plan valid） |
| v3.10 plan_core | `133ea34b…076e` | 独立重构一致 |
| v3.10 config 文件 | `fdac6195…511f` | 一致 |

- 270/270 首轮 identity 清洁室逐一重推（seed 公式 + run_id 公式）与 plan 精确相等；与 v3.5–v3.9 历史 180 个 run id 交集 ∅（`audit/verify_v3_10_first270_pre_execution.py`，SHA-256 `3c322085…506a`；另复跑 PER-58 part1 审计脚本全绿）。
- 授权工件：`authorization.preflight.json`（identity_preflight，max 3 units）与 `authorization.run.json`（financial_acceptance_270_run，plan_sha256 + preflight_sha256 双绑定，authorized_run_ids 恰为 270 个首轮 id，逐序精确相等），依据父议题常设授权（评论 `6fdca2fb-0f86-473c-9269-5c71e7a470b3`，scope `standing_all_paid_runs_owner_2026_08_12`）。
- 离线门：scan-fixtures 0 findings、gold-report valid、gate-report 90/90 visible、Python 198/198、Node 65/65（含合成传输 270-run 端到端）。

## 三、身份预检：3/3 通过后才启动

preflight 决策 `passed_3_of_3`：三模型响应模型 ID 与请求精确相等、统一协议参数全部 honored、工具能力验证通过；0 回退。
- preflight_sha256（内容哈希，plan-bound）：`669cbd049177d9c7ae7ea9e25bc9dda2fa6abee996061023477354895063ef3f`
- preflight.json 文件哈希：`77f9812d94c7c6b552c35634be1573e4d70c07b0abe658e3619664ef7519512d`
- endpoint_id：`bailian_98bd231ca931`

## 四、执行机制：checkpoint/resume 驱动（不触碰冻结合同）

冻结的 `executeFrozenPlanV310` 一次性执行全部 270 单元且对任何已存在 checkpoint 的 run 直接拒绝（`immutable run already has checkpoint`），~2.8h 的批次一旦中断即无法恢复；而 `harness/live_acceptance_v3_10.mjs` 本身在冻结 bundle 内（修改即 hash 漂移硬停止）。因此本轮新增**外部**可恢复驱动 `audit/driver_v3_10_live_resume.mjs`（SHA-256 `5bd1a47a…aecc3`），逐字节复用冻结模块导出函数与 per-run 语义，仅在外层增加：

- **finalized-skip**：trace/grader/candidate/checkpoint 齐备且 checkpoint 哈希链复算至 run_completed 终态、与 trace 终态一致的单元，原样跳过、产物零改动；
- **partial/inconsistent 硬停止**：任何非终态残留一律硬停止，绝不静默重跑；
- **作废通道（report-only）**：仅对显式声明、且磁盘状态为"已消耗但不可冻结"的单元记录取证（checkpoint 全链 + 终态事件）并继续，`replaced_or_reexecuted=false`，guard rail 拒绝对 pending/finalized 单元的作废请求；
- **判分失败取证**：validator/grader 子进程拒绝时完整持久化脱敏后的 stderr/stdout（`grading-failures/`），不再丢失诊断；
- 逐 run 进度时间线 `driver-progress.jsonl`。

驱动经合成自测全绿（`audit/driver_v3_10_synthetic_selftest.mjs`，SHA-256 `541f61e0…f60d`）：chunk+resume、270/270 accepted、链复算、partial 硬停止、篡改硬停止、作废 report-only、作废 guard rail、作废报告跨调用自动加载。本轮实际发生 11 次进程级恢复（10 次作废处置 + 1 次参数修正），145 个已冻结单元在恢复中全部原样跳过、零改动。

## 五、三模型分项结果（260 冻结单元）

| 模型 | 冻结 run | succeeded | 结构有效 | 语义值正确 | 全检查通过 | attempts | tokens |
|---|---|---|---|---|---|---|---|
| qwen3.8-max | 90 | 87 | 87 | 85 | **73** | 269 | 793,817 |
| glm-5.2 | 81 | 78 | 78 | 78 | **72** | 308 | 985,454 |
| deepseek-v4-pro | 89 | 86 | 86 | 81 | **70** | 340 | 1,451,782 |

- 90 任务 × 3 模型粒度矩阵见附件 `stage3_v3_10_first270_per_case_results.md`（✓/✗+失败检查/作废）。
- candidate_failed 9 个单元（均为耗尽 8 请求预算仍未产生有效结构化提交，原样冻结）：fkw-07-sfp（qwen）、fkw-08-normal（三模型）、fkw-08-sfp（三模型）、ftw-09-missing（deepseek）、ftw-12-normal（glm）。
- succeeded 但语义/证据层未过全部检查：36 个单元（上表 215 = 251 − 36）。
- 未通过全部适用检查的 45 个单元明细（原样冻结，未做任何判分调整、无选择性重跑）：

| 模型 | 案例 | run_id | failed_checks |
|---|---|---|---|
| qwen3.8-max | case-public-fkw-02-missing-or-anomalous-v3 | `run_453780b1d8dcd1f96119abc7b9f4b557` | calculation_correct, method_correct |
| glm-5.2 | case-public-fkw-02-missing-or-anomalous-v3 | `run_71609a5dac2eadd7a6d2320492a74aed` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-02-missing-or-anomalous-v3 | `run_265ef7329213bb5ebc583536d5ee2f9b` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-02-normal-v3 | `run_945962fa83f92538350e0de44a3d5be1` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-02-single-factor-perturbation-v3 | `run_bead27295173110879ca735053030dbd` | calculation_correct, method_correct |
| qwen3.8-max | case-public-fkw-03-missing-or-anomalous-v3 | `run_057185b5ef88c4bcd59fad16460c4593` | calculation_correct, method_correct |
| glm-5.2 | case-public-fkw-03-missing-or-anomalous-v3 | `run_7212fc6302b1274f629cd94d4afb0add` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-03-missing-or-anomalous-v3 | `run_f752a34c30513439870e9c89ba2416ed` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-06-missing-or-anomalous-v3 | `run_6dd7cff4aeef6c1201bd67aa3f597324` | permission_boundary_respected |
| qwen3.8-max | case-public-fkw-07-single-factor-perturbation-v3 | `run_4b1debcf364bd29e30ad1b0d5414e1cf` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| deepseek-v4-pro | case-public-fkw-08-missing-or-anomalous-v3 | `run_904f95c1d6fcc60e8e79e9d7e2f36542` | permission_boundary_respected |
| qwen3.8-max | case-public-fkw-08-normal-v3 | `run_bb38dd77eef5ef3c2a1a1beafb3b325e` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| glm-5.2 | case-public-fkw-08-normal-v3 | `run_6bd785ec28c3fe74a577c36222a83772` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| deepseek-v4-pro | case-public-fkw-08-normal-v3 | `run_7cda59d5d031d1ed314a073cde2e2f36` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| qwen3.8-max | case-public-fkw-08-single-factor-perturbation-v3 | `run_77d1a90e26169c2319435e186bbf9d42` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| glm-5.2 | case-public-fkw-08-single-factor-perturbation-v3 | `run_4800a16862499b3a1eea17ede2d705e6` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| deepseek-v4-pro | case-public-fkw-08-single-factor-perturbation-v3 | `run_f5ca898242c5d5f860707b79cb4a4b42` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| qwen3.8-max | case-public-fkw-09-normal-v3 | `run_e1b103f7ad08babca4536ac47bc18c17` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-public-fkw-09-single-factor-perturbation-v3 | `run_d53ab3f3b14afdb41b022b3b9dfce946` | evidence_provenance_valid, evidence_sufficient |
| deepseek-v4-pro | case-public-fkw-11-missing-or-anomalous-v3 | `run_671ead4344731d0b335a3c1b06409958` | permission_boundary_respected |
| qwen3.8-max | case-public-fkw-12-missing-or-anomalous-v3 | `run_2fd06c8518ca6d322f5d90089a9d4f93` | calculation_correct, method_correct |
| glm-5.2 | case-public-fkw-12-missing-or-anomalous-v3 | `run_41fad64ea255d3008521583f0a541a33` | calculation_correct, method_correct |
| deepseek-v4-pro | case-public-fkw-12-missing-or-anomalous-v3 | `run_a182c69f5cb7d6260901692dc8ab0d7c` | calculation_correct, method_correct, permission_boundary_respected |
| qwen3.8-max | case-public-fkw-13-normal-v3 | `run_c14a065b90a3973fe2e0940ae36e85c6` | evidence_provenance_valid, evidence_sufficient |
| glm-5.2 | case-public-fkw-13-normal-v3 | `run_215699cbfc3849406c7d07341cb9fc12` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-public-fkw-13-single-factor-perturbation-v3 | `run_de863a14ff6890753d7c3d9a36ef7a7e` | evidence_provenance_valid, evidence_sufficient |
| glm-5.2 | case-public-fkw-13-single-factor-perturbation-v3 | `run_61eec2afbcd03428e0dffbe8e69184e0` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-public-fkw-14-normal-v3 | `run_6da1a48a0392acdcd9674a6b453e33db` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-public-fkw-14-single-factor-perturbation-v3 | `run_6a9f4ef48428e51131b754a239f8ed00` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-public-fkw-15-single-factor-perturbation-v3 | `run_eac4ca17f3ccdee3ff955fdc5ea67c9b` | evidence_provenance_valid, evidence_sufficient |
| qwen3.8-max | case-synthetic-ftw-04-normal-v3 | `run_0784dd410e523e1b823ec6e0b3a6bb99` | reason_codes_exact, status_correct, value_semantic_correct |
| deepseek-v4-pro | case-synthetic-ftw-04-normal-v3 | `run_bcffd7a6799c3d4a64ef99f09a90537e` | reason_codes_exact |
| qwen3.8-max | case-synthetic-ftw-04-single-factor-perturbation-v3 | `run_479c89341aa21eb40ee4b94cbeef8a61` | evidence_provenance_valid, evidence_sufficient |
| deepseek-v4-pro | case-synthetic-ftw-05-normal-v3 | `run_19c542d50398faba80b9abde06e74020` | reason_codes_exact, status_correct, value_semantic_correct |
| deepseek-v4-pro | case-synthetic-ftw-06-missing-or-anomalous-v3 | `run_a8acfcfa70036e5e2463bf4d9a7d217b` | reason_codes_exact, status_correct, value_semantic_correct |
| deepseek-v4-pro | case-synthetic-ftw-07-missing-or-anomalous-v3 | `run_a05a45ced440c97dbbe4718309d065dd` | status_correct |
| deepseek-v4-pro | case-synthetic-ftw-08-missing-or-anomalous-v3 | `run_044f510176b7d4a486a7d6837262e465` | reason_codes_status_compatible, status_correct, value_semantic_correct |
| qwen3.8-max | case-synthetic-ftw-08-normal-v3 | `run_036974a1ea3b0a131b01943d9d57501e` | value_semantic_correct |
| deepseek-v4-pro | case-synthetic-ftw-09-missing-or-anomalous-v3 | `run_747a602b35581aa83ac84ce20965d566` | permission_boundary_respected, structure_parsed |
| deepseek-v4-pro | case-synthetic-ftw-11-missing-or-anomalous-v3 | `run_3bd36bad553ec6947ac264377d721c19` | reason_codes_exact, status_correct, value_semantic_correct |
| deepseek-v4-pro | case-synthetic-ftw-12-missing-or-anomalous-v3 | `run_72887c8dec9346ddb0258cde4232399d` | reason_codes_exact, status_correct, value_semantic_correct |
| glm-5.2 | case-synthetic-ftw-12-normal-v3 | `run_1616109afc13a2d826be11c790f170f0` | evidence_provenance_valid, evidence_sufficient, structure_parsed, unit_correct |
| qwen3.8-max | case-synthetic-ftw-12-single-factor-perturbation-v3 | `run_857d53d29cb6017406f98f7b3b90ab89` | status_correct |
| glm-5.2 | case-synthetic-ftw-12-single-factor-perturbation-v3 | `run_2efb045fab06d0558299f302a94e647c` | status_correct |
| deepseek-v4-pro | case-synthetic-ftw-12-single-factor-perturbation-v3 | `run_08c4749aedfe53f6300dd85926d99855` | status_correct |

## 六、10 个作废单元与系统性合同缺陷（本轮最重要发现）

作废明细：

| sequence | 模型 | 案例 | run_id |
|---|---|---|---|
| 146 | glm-5.2 | case-synthetic-ftw-02-missing-or-anomalous-v3 | `run_bba344e218f6643126192d6f818f37e2` |
| 155 | glm-5.2 | case-synthetic-ftw-03-missing-or-anomalous-v3 | `run_68352ead71639135bb3e5e5e37974dab` |
| 164 | glm-5.2 | case-synthetic-ftw-04-missing-or-anomalous-v3 | `run_0a93a3127f34e0cd080080353bdb149e` |
| 174 | deepseek-v4-pro | case-synthetic-ftw-05-missing-or-anomalous-v3 | `run_e50d4565effc44efa37772bd8c92a2e2` |
| 182 | glm-5.2 | case-synthetic-ftw-06-missing-or-anomalous-v3 | `run_026ce7b195076f7aa0d84502403d61c3` |
| 191 | glm-5.2 | case-synthetic-ftw-07-missing-or-anomalous-v3 | `run_e41b53663632b0e724f3dcc95d54df94` |
| 200 | glm-5.2 | case-synthetic-ftw-08-missing-or-anomalous-v3 | `run_5cb172c4d3621b3cc692598a10460802` |
| 218 | glm-5.2 | case-synthetic-ftw-10-missing-or-anomalous-v3 | `run_c5c0ae24d74c577df57b9007b4b7fe74` |
| 221 | glm-5.2 | case-synthetic-ftw-10-normal-v3 | `run_a69bf0a682dc5be57f3976aa064a9da3` |
| 236 | glm-5.2 | case-synthetic-ftw-12-missing-or-anomalous-v3 | `run_42e247098cf15f5ad7d6568610466879` |

**根因（10/10 同一缺陷类，完整取证在 `grading-failures/` 与 `invalidated-runs.json`）**：
`run_trace.schema.v3.10.json` 将 `usage.total_tokens` 上限钉在 32768（= config `resource_budget.max_total_tokens` = 单请求 context window），但冻结执行循环只强制**请求数**预算（8）与单请求 wall-clock，不强制累计 token 预算。多请求 run 的累计 token 是逐请求 input+output 之和（上下文逐轮重发、随轮增长），8 请求长上下文会话必然远超 32768——实际观测 35,484–39,795。于是"合法执行完的 run 产生不可冻结的 trace"，冻结 validator 依 schema 拒绝（`schema:usage/total_tokens:N is greater than the maximum of 32768`）。

佐证与归因：
- 该缺陷非本轮新引入：v3.8 轮已有 run 达 30,031（逼近上限），v3.9 轮最高 18,868；v3.10 全量 90 任务矩阵中 FTW 长上下文案例 + 长对话行为使其集中显形。
- PER-58 独立审计的合成执行每请求仅 10+10 token，无法暴露该上限；离线门全部通过与此并不矛盾。
- 10 个作废单元的行为画像：glm-5.2 在 FTW 案例上的长多请求会话（9 个，含 missing 与 normal 变体）+ deepseek-v4-pro 1 个；与候选语义能力无关——**不应计为候选模型失败**，属合同/运行时一致性缺陷导致的不可记录单元。
- 处置：按 `plan.replication_design.invalidation_policy`（作废只报告、不替换；替换需新计划版本）逐一作废并冻结 checkpoint 取证链；**未做任何重跑**（重跑构成结果驱动的事后选择，被 `no_post_hoc_selection=true` 禁止）。

**建议（交交付负责人决策）**：冻结 superseding v3.11 修复该不一致（使运行时在累计 token 触顶时停止并产生可冻结 trace，或使 schema 上限与多请求语义一致——两者都需三模型对称、独立审计），随后在 repeat 2–3 扩展（810 全量）前覆盖这 10 个 (案例,模型) 单元；repeat 2–3 亦天然覆盖同一批单元两次。

## 七、冻结证据与哈希

| 产物 | SHA-256 |
|---|---|
| **证据 bundle**（`bundle.manifest.json`，1070 artifacts，content-hash 方案与 v3.8/v3.9 轮一致） | `d479193c1db8d5ad080c75abbcc412ff65dc48121c92985be8d25361ad6cd598` |
| bundle.manifest.json 文件哈希 | `a12ab2c0899f3e260827152056d7a2413bcadba6554b39c69d1e5e47fec123f5` |
| summary.json（独立勾稽输出，cost_usd=null） | `6f5dea7d367de0191feb14e46d06d900943728c3d0f39c2ac708b216d84d97f3` |
| runtime-summary.json | `7b3bb3d12a031c041887227dd51862a7b2d2f13efcf28d141561cac6953322f1` |
| invalidated-runs.json（10 条作废取证） | `e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1` |
| 独立勾稽脚本 `audit/reconcile_stage3_v3_10_execution.py` | `3ffcd629…a064`（全长 `3ffcd6295aab48271306dc407036359a7aa6af24c03918311543412f70d1a064`） |
| 证据冻结脚本 `audit/freeze_v3_10_evidence_bundle.py` | `7e7509bc87084343fb2e2445b2f9e35766c0c9e5611d9895feea85ebb532590d` |

勾稽内容：冻结输入哈希复算 + preflight/授权工件绑定核验 + 260×(run_id 重推 / 独立 validator 全量校验 / grader 确定性逐字节重算 / checkpoint 哈希链 / plan 绑定 / 终态一致 / usage 勾稽 / identity-valid) + 作废报告哈希与取证链复算 + 全目录 1076 路径密钥扫描（0 findings）+ 产物集合与冻结 identity 精确一致（无多余、无缺失）。结果 `valid=true, errors=0`。

## 八、可复现命令

```bash
# 执行前离线门（均已通过）
uv run python -m harness.acceptance_v3_10 verify-contracts
uv run python -m harness.acceptance_v3_10 verify-plan
uv run python -m harness.acceptance_v3_10 scan-fixtures
uv run python -m harness.acceptance_v3_10 gold-report
uv run python -m harness.acceptance_v3_10 gate-report
python3 audit/verify_v3_10_first270_pre_execution.py
python3 audit/audit_stage3_v3_10_part1_hashes_identities.py
# 驱动自测（合成传输，0 付费）
node audit/driver_v3_10_synthetic_selftest.mjs
# 预检（BENCH_BAILIAN_MODEL_IDS 需为 JSON 数组；密钥只从环境变量进入传输层）
node harness/live_acceptance_v3_10.mjs --mode preflight --plan runs/stage3/acceptance-20260813-v3.10/stage3_acceptance_plan.v3.10.json --authorization runs/stage3/acceptance-20260813-v3.10/authorization.preflight.json --output runs/stage3/acceptance-20260813-v3.10/preflight.json
# 270-run 可恢复执行（本轮共 11 次调用：首次 + 10 次作废处置恢复；恢复自动跳过已冻结单元与已记录作废）
BENCH_BAILIAN_MODEL_IDS='["qwen3.8-max","glm-5.2","deepseek-v4-pro"]' node audit/driver_v3_10_live_resume.mjs --plan runs/stage3/acceptance-20260813-v3.10/stage3_acceptance_plan.v3.10.json --authorization runs/stage3/acceptance-20260813-v3.10/authorization.run.json --preflight runs/stage3/acceptance-20260813-v3.10/preflight.json --output-dir runs/stage3/acceptance-20260813-v3.10 [--invalidate <run_id> --invalidate-reason "..."]
# 独立勾稽 + 证据冻结
uv run python -m audit.reconcile_stage3_v3_10_execution --run-dir runs/stage3/acceptance-20260813-v3.10 --preflight runs/stage3/acceptance-20260813-v3.10/preflight.json --authorization runs/stage3/acceptance-20260813-v3.10/authorization.run.json
uv run python -m audit.freeze_v3_10_evidence_bundle --run-dir runs/stage3/acceptance-20260813-v3.10
# 回归
uv run python -m unittest discover -s tests   # 198 OK
node --test tests/integration/*.test.mjs      # 65 pass / 0 fail
```

## 九、成本与限制

- **成本 `cost_usd=null`**：供应商响应不提供可核验费用，按合同保持 null；token 用量已逐 run 冻结（总 3,231,053；preflight 3 请求另计）。
- 凭据卫生：密钥只经环境变量进入传输层；本轮**无任何密钥回显**（上轮一次性回显事故已在 PER-55 披露并建议轮换）；全部持久化产物经递归密钥扫描 0 findings；未持久化任何原始 provider 响应。
- 未发生身份不匹配/回退、泄密、真实副作用、合同 hash 漂移；模拟账本终态 260/260 复原；`raw_provider_response_stored=false`。
- 如实披露：(1) 上述 token 上限系统性合同缺陷及 10 个作废单元；(2) run 146 的失败发生在驱动增加取证持久化之前，其子进程 stderr 未留存（checkpoint 取证链完整，离线重建同形 trace 通过 validator+grader，故根因与其余 9 例一致但属推断）；(3) 作废单元已消耗付费请求（每单元 ≤8 请求），未产生可计分产物。
- 未验证项不变：供应商侧计费口径、线上长期稳定性不在本轮合同范围内。
