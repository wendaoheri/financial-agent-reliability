# Stage 3 独立审计报告：历史轨迹复盘证据与可追溯性复算（PER-320）

- report_type: `stage3_independent_audit`
- report_version: `1.0.0`
- auditor: 独立评分与统计审计师（与出题、oracle、harness、Stage 2 复盘实现职责隔离）
- audit_date: 2026-08-17
- 审计依据: `docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`（口径 v1，冻结锚点 `59a3ac6`，文件 sha256 `077f38eaf7756e60b0cb23ef8c816ae0033b57d4cfce0db4ee0d0be4477b3384` —— 本次审计实盘复核一致）
- 被审计对象: PER-319（Stage 2）复盘工具链 `src/financial_agent_reliability/retrospective/` 与复盘证据 `docs/retrospectives/`（git `2eee889`、`099255f`）
- 审计环境: 项目资源 local_directory 工作副本（`git status` 干净、HEAD=`099255f`、与 origin/main 一致）。按口径 §6.3，复盘/审计先复验捆扎哈希再重算（见 §4.4）；该副本非全新克隆，作为残余风险留痕。

## 0. 审计结论（先给结论）

**审计通过。** Stage 2 交付的 20 个批次判定（traceable ×19 + partially_traceable ×1，唯一降级批为 acceptance-v3.5/M1）经本次独立复算全部复现，逐位一致；未发现篡改、静默放行或结论反向修饰。发现 4 项问题（P1–P4，见 §5），均不动摇复盘结论与已发布排名结论，其中 P1、P2 需 Stage 2 原实现者按最小修复建议纠正/加固（不构成本证据链返工）。

## 1. 抽样方案（自定，含理由）

分层全覆盖设计，不设批次抽样率上限：

| 层 | 对象 | 方法 | 理由 |
| --- | --- | --- | --- |
| A 全链重算 | acceptance-v3.5 / v3.8 / v3.9 / v3.10 / v3.11 / coverage-v3.11.1（全部 6 个评分批次，36+36+36+260+549+1=918 run） | 冻结 reconcile 脚本原样整批执行 + v3.5 自研重放 + B2 逐字段 diff + R4/R2 抽样 | 评分结论是排名结论的唯一输入，抽样风险不可接受；冻结脚本整批重算成本低，故选全覆盖而非抽样 |
| B 结构审计 | v3–v3.4（协议门）、frozen-preflight v1–v4、smoke v1/v2、frozen-smoke v1/v2、session-20260811 | 目录结构核验 + manifest 逐件重哈希 + 契约条款核验 | 这些批次不产生评分结论，审计目标是"按设计无运行"与"结论边界声明"是否如实 |
| C 横切锚点 | grader 捆扎、报告捆扎、预注册绑定、810 密封行、排名/发布一致性、archive↔evidence、作废对账 | 冻结 grader_v2/bridge 原样重算 + 自研字节比对 | 报告层是结论对外发布点，必须独立复核到发布文本 |

独立性声明：全部重算证据由审计方自有脚本（仓库外 `/Users/liuxiang/per320-audit/`）或对**冻结产物**（audit/reconcile_stage3_v3_*、contracts/grader_v2.py、contracts/sealed_row_bridge_v2.py、contracts/validate_case_data.py）的直接执行产生；未采用 Stage 2 工具链的任何中间结论作为输入。对 Stage 2 工具链另做了独立代码审查（见 §4.5）。

## 2. 独立复盘结果（A 组/B 组逐条）

### 2.1 A1 manifest 完整性（自研脚本，12/12 批次）

逐件重算 sha256 + 缺件 + 未登记污染检测：**12/12 PASS**，共 3,866 件（v3.5=112、v3.8=152、v3.9=152、v3.10=1,070、v3.11=2,208、coverage=14、frozen-smoke v1=16、v2=121、frozen-preflight v1–v4=6/7/8/5），零失配、零缺件、零污染。

### 2.2 R3/R4/B1/B2：冻结 reconcile 脚本原样整批重算（v3.8–v3.11.1）

以审计方驱动原样执行五个冻结 reconcile 脚本（其 main() 会重写 summary.json，审计前先备份，重算后逐字段 diff 再恢复原件；v3.8 正本 summary 为 444 只读冻结件，改在字节级副本上执行）：

| 批次 | 重算记录 vs 落盘 summary | 差异字段 |
| --- | --- | --- |
| acceptance-v3.8 | 36/36 记录逐字段相等 | 仅 `status`/`reconciliation_errors`（见下） |
| acceptance-v3.9 | 36/36 | 同上 |
| acceptance-v3.10 | 260 冻结 + 10 作废留痕 | 同上 |
| acceptance-v3.11 | 549 冻结 + 1 作废留痕 | 同上 |
| coverage-v3.11.1 | 1/1 | 同上 |

唯一差异：现时点重算各产生 4 条 `artifact drift:<旧路径>` 错误（harness/acceptance_v3_X.py、live_acceptance_v3_X.mjs、tests/×2——PER-86 src 重构的路径钉住失配），其余**全部**逐运行校验（trace 校验器、账本哈希链重放、grader 确定性重算、checkpoint 事件数、preflight/授权校验、作废取证）零错误。交付时点（重构前）这些钉住在原位成立，落盘 summary `status=completed/errors=0` 为交付时点事实；重构后按 PER-85-D6 放行清单解析，与 Stage 2 的 `frozen_pins_relocated=4` 留痕一致。checkpoint 事件独立复核：v3.8=182、v3.9=186、v3.10=1,407、v3.11=2,972、coverage=5，与落盘一致。

### 2.3 路径钉住放行的独立实证（不放行清单之谈）

对 v3.5–coverage 六个冻结契约 bundle 的全部 266 个唯一 artifact 钉住逐一：① 与 git 历史（`cbfe2f7^` 迁移前旧路径内容）重算 sha256 比对——**21/21 非一致钉住的 pinned hash 全部等于迁移前历史内容**（钉住忠实）；② 245/266 现位或迁移位**逐字节一致**；③ 21 个内容变更件（acceptance_v3_5/8/9/10/11.py、对应 mjs 与 tests）逐一全文 diff：**仅 import 改写、ROOT 深度、自校验路径三类机械变更**；五个评分模块的 `grade_candidate_*`/`canonical` 评分逻辑零改动（代码审查路另对 v3/v3_5 至 v3_11_1 七个模块做了同法 diff，结论相同）。评分语义保持另由 §2.2/§2.4 的逐行重算相等实证背书。

### 2.4 v3.5 独立重放（无冻结 reconcile 脚本，审计自研）

按冻结 `acceptance_v3_5.grade_output` 语义、用冻结 validator/grader 自研重放 36 run：**36/36 重评分与落盘 grader 行逐位相等**；36/36 trace 过配套校验器；checkpoint 哈希链 36/36 完整（162 事件）；identity 36/36；重算 summary 的 counts/by_model/independent_checks 与落盘逐字段相等（含 all_critical_invariants=15、exact_semantic_match=15、structured=30、failed=6）；`acceptance_gate_passed=false` 与落盘一致。评分链完整性成立 → v3.5 判 partially_traceable 的依据**仅在治理层**：批内确无 `preflight.json`/`authorization.run.json`（目录实证），M1 降级标注如实。

### 2.5 R2 场景重建（v3.11 全量 90 任务，自研 + 冻结 c14n）

plan 逐任务 270 个整文件钉住（projection/snapshot/source_case）**270/270 一致**；90 张源案例卡 + 90 份快照的 `integrity.content_sha256`（`financial-agent-c14n-json-v1`）**180/180 重算一致**；`evidence_refs` 交叉校验 60/60 通过，30 张合成卡 evidence_refs 为空 = 已登记的 L7 缺口（运行内投影哈希链完整，卡级指针缺失如实标注）。

### 2.6 B3/报告层（冻结 bridge + grader_v2 原样重算）

- 810 密封行重建与落盘 `reports/stage5/work/sealed_rows.v2.json` **深度相等**（810 = 90 用例格 × 3 模型 × 3 重复；构成 260 v3.10 + 549 v3.11 + 1 coverage 合并口径）；
- `grader_v2.score_results` 重评分与落盘 score_results 深度相等，与 PER-32 签署统计 `audit/per32_part4_ranking_results.json` 在 models/pairwise_csr/leader_gates/ranking_reliable/provisional_leader 上**零差异**；
- 发布件 `machine_readable_results.v1.json` 与重算逐字段一致（ranking_reliable=false、leader_gates、pairwise、各模型统计）；`official_statistics_sha256` 登记值 = 实盘 sha256（16df9fd9…）；密封行捆扎预注册绑定 = `benchmark_preregistration.v1.1.json` 实盘哈希（786c0260…）；
- grader 捆扎 `verify-freeze` 通过（contract_bundle_sha256=511da190…，15 件）；
- 作废 run 从未进入密封行/records：11 起作废（v3.10 ×10 + v3.11 ×1）全部 report-only，见 §3.3。

## 3. 证据链审计（降级如实性 / 静默放行 / 结论修饰）

### 3.1 降级标注与实际缺口相符

- **H1**（v3–v3.4）：结构实证五批目录仅含 preflight 件，无任何 traces/graders/candidates/summary；v3.4 契约明文 `acceptance_runs_authorized=false`。"按设计无验收运行"如实；scope_note 将结论限定于协议/身份门并禁止引用为评分证据，排名/报告层实查未引用这些批次。
- **M1**（v3.5）：授权/预检文书缺失经目录实证（非硬编码断言可替代的事实）；评分链完整（§2.4），降级影响面限定为"执行合规性声称"，未波及评分重算。如实。
- **M3**（v3.10 run_bba344e2…）：作废清单中该 run `replaced_or_reexecuted=false`，checkpoint 取证链在盘且可重放，grading-failures 转录确不存在——与 M3"孤立取证不可复现事件"标注逐条相符；该 run 不在 records。
- **L5**：v3.10 driver-progress `run_invalidated` 事件实盘 55 条 → 按 run_id 去重 10 个，与 invalidated-runs.json、summary.invalidated_runs、manifest.invalidated_run_ids 三处登记完全吻合；v3.11 为 1/1。
- **L7/L8/L10/L11/L12/L14 等**：与差距报告语义一致，均为标注留痕、不构成链断裂。

### 3.2 无静默放行 / 无结论反向修饰

- 判定聚合规则（任一 FAIL → untraceable；影响结论的降级 → partially_traceable）经代码审查确认为无 except-pass、无"缺失即通过"路径（残留的 skip-on-missing 路径见 §5-P2，均对应假设性输入或已登记缺口，未在实盘数据上造成放行）。
- 发布层未修饰：stage5 报告（FAI-2026-08-14-retained-no-global-leader）在点估计存在第一名（glm-5.2 CSR 0.89835859）的情况下，仍按冻结政策公布 `NO_RELIABLE_GLOBAL_LEADER`，并如实给出判负依据（CSR 差 0.0139 < 0.05 业务差、CI [-0.0625, 0.0354] 跨 0、Holm p=0.60、bootstrap-top 0.73 < 0.90）；`ranking_reliable=false` 三处（重算/签署统计/发布）一致。未发现任何因结论不合预期而调权、放宽门槛或改阈值的痕迹（grader 捆扎冻结 + 预注册未改动 + 门槛数值未变）。

### 3.3 作废治理

10+1 个作废 run 全部 report-only、不复用不删除；对应 traces/graders/candidates 冻结件不存在、checkpoint 取证在盘；records 与密封行中缺席核验通过。

## 4. 纪律审计

1. **旧冻结产物零改动**：`git diff --name-status 7df8895..HEAD`（Stage 1 基线→现 HEAD）仅新增 `src/financial_agent_reliability/retrospective/`、`tests/test_retrospective*.py`、`docs/retrospectives/` 与 `pyproject.toml` 一行入口；contracts/、preregistration/、snapshots/、evidence/、audit/、reports/、catalog/、cases/ 零改动、零新增文件；工作树无未登记新文件。evidence/stage3 v3.8 正本 summary 为 444 只读（物理冻结）。**注意**：runs/ 自 `cf35261` 起被 .gitignore 排除，git 无法验证其改动——其完整性由 §2.1 manifest 逐件重算承担（全部通过）；Stage 2 评论将 runs/ 列入"git 可验证"表述不准确，见 P1。
2. **无旧版本号复用**：新增证据均为 `docs/retrospectives/*.v1.json` 新目录新命名；未在冻结目录新增任何文件，未复用任何契约版本号。
3. **无替代模型冒名**：identity_valid 全量通过（36+36+36+260+549+1 逐运行 requested==response + preflight 3/3 passed_3_of_3，由冻结 reconcile/校验器在 §2.2/§2.4 中强制）。
4. **无结果反向调权**：见 §3.2；grader 捆扎与预注册哈希绑定实盘复核一致。
5. **测试与稳定性**：`uv run python -m unittest discover -s tests` → **295 OK**（与 261→295 声称一致）；`fareli-retro evidence` 连续两次执行逐文件字节一致（实测）；现 HEAD 再生成与落盘证据仅 git 锚点字段不同（证据生成于 `2eee889`，现 HEAD `099255f`），其余逐字节一致——"可重复且稳定"成立，需附"固定 HEAD"限定（P4）。
6. **复盘纪律**：本次审计对 runs/ 下 summary 的任何重写均在备份-恢复协议下执行并逐件 sha256 复核恢复（恢复后与 manifest 登记一致）；审计未向任何冻结目录写入。

## 5. 问题清单（逐条：现象 / 影响面 / 严重度 / 复现 / 最小修复）

**P1（中，表述准确性）** Stage 2 交付评论称旧冻结产物"git 可验证零改动"并列出 runs/；runs/ 实为 gitignore 对象（`git ls-files runs/` 为空），git 不覆盖该目录。影响面：表述问题，不构成数据问题——runs/ 内容完整性已由 manifest 自证（§2.1 全部 PASS）承担。复现：`git check-ignore runs/stage3/acceptance-20260813-v3.11`。最小修复：Stage 2/Stage 4 文档将 runs/ 的完整性依据改写为"bundle manifest 逐件 sha256 自证 + 独立重算"，git 验证仅对 tracked 目录主张。

**P2（中，工具链加固）** 对 `src/financial_agent_reliability/retrospective/` 的独立代码审查（全量 2,770 行 + 冻结依赖 diff）确认重算真实（无自比、无 except-pass、无 mismatch-skip），但存在以下需修复项：
- F2：v3.5 的 M1 标注与治理检查按 `batch_id` 硬编码，v3.5 契约 bundle 钉住校验空转（`frozen_input_errors` 恒空元组）。本次审计已独立补验（§2.3/§2.4），结论不受影响；修复：M1 改为由 governance 文书缺失检测导出，v3.5 增补 bundle 钉住校验。
- F3：`invalidation_check.py` 重复 run_id 检出被后续赋值覆盖丢弃（潜在 bug；现盘无重复，§3.1 实证）。修复：一行合并 problems 列表。
- F4：v3.5 证据文本 "anchors hold"（anchor_problems:0）为空转结果——v3.5 契约世代本无 commitments/链锚字段，属 N/A 而非 pass。修复：改为显式 N/A 注记。
- F7/健壮性：`fareli-retro evidence --out` 对仓库外路径或相对路径崩溃（审计实测，`relative_to` ValueError）。修复：路径策略校验 + resolve。
- F9：核心复盘逻辑（run_checks/summary_check/report_level 等）仅由依赖历史产物的集成测试覆盖，干净检出下测试面坍缩；write_evidence 无测试。修复：补合成 bundle 单元测试。
其余低危项（F5/F6/F8/F10/F11/F12）见审计工作底稿，均不影响本次实盘判定。

**P3（低，口径判读）** 协议门批次（v3–v3.4 等）判"traceable + scope_note + H1 标注"而非 partially_traceable。按口径 §3.4，受影响结论已退出其声称用途且边界逐批留痕，该判读可辩护、与差距报告处方一致；要求 Stage 4 固化时明文禁止将这些批次引用为评分证据（当前排名/报告层实查无引用）。

**P4（信息）** 复盘证据内嵌 `git_commit` 锚点，"两次运行逐字节一致"需附"同一 HEAD"限定（证据生成时 HEAD=2eee889，审计时 HEAD=099255f，再生成仅该字段不同）。Stage 4 固化时写入可复现章节。

## 6. 审计意见

Stage 2 复盘证据与结论**独立复现、逐位一致**：6 个评分批次 918 run 全量重算、14 个非评分批次结构与边界核验、报告层 810 密封行重建与发布一致性、作废治理与降级标注，均未发现篡改、静默放行或结论修饰。审计通过；P1/P2 按 §5 最小修复建议退回 Stage 2 原实现者纠正（不构成证据返工），P3/P4 移交 Stage 4 规范固化。

## 附录：复现命令（审计证据产生方式）

```bash
# 基线与改动面
git diff --name-status 7df8895..HEAD
shasum -a 256 docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md   # 077f38ea…

# A1 manifest 逐件重算（审计自研脚本，12 批次）
python3 /Users/liuxiang/per320-audit/r1_manifest_check.py <12 个 bundle 目录>

# R3/R4/B1/B2 冻结 reconcile 原样执行 + 备份-恢复-逐字段 diff
python3 /Users/liuxiang/per320-audit/run_frozen_reconcile2.py
python3 /Users/liuxiang/per320-audit/b2_summary_diff.py        # 仅 status/reconciliation_errors 差异

# 钉住放行实证（git 历史内容哈希 + 迁移 diff）
python3 /Users/liuxiang/per320-audit/relocation_pin_check.py

# v3.5 独立重放（36/36 逐位相等）
uv run python /Users/liuxiang/per320-audit/v35_independent_replay.py

# 报告层重算（810 密封行 + 重评分 + 发布一致）
uv run python /Users/liuxiang/per320-audit/report_level_check.py
uv run python contracts/grader_v2.py verify-freeze

# 作废对账（55→10 / 1→1、M3 取证）
python3 /Users/liuxiang/per320-audit/invalidation_recon.py

# R2 场景重建抽样（270 钉住 / 180 c14n / 60 refs）与 archive 字节比对：见审计工作底稿脚本

# 测试与稳定性
uv run python -m unittest discover -s tests                    # 295 OK
uv run fareli-retro evidence --out <仓内绝对路径>（两次，逐字节一致）
```

审计工作底稿（脚本 + JSON 结果）留存于审计执行机 `/Users/liuxiang/per320-audit/`，随议题评论附送摘要包。
