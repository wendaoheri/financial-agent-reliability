# Stage 4 独立审计与排名稳定性复算报告（PER-32）

审计人：独立评分与统计审计师（与出题、oracle、harness 实现、候选调优职责隔离）
审计日期：2026-08-14（UTC）
审计对象：810 全量矩阵冻结证据（90 任务 × 3 模型 × 3 重复）
- v3.10 首轮 260 冻结（bundle `d479193c…cd598`，1070 artifacts，轮目录 `runs/stage3/acceptance-20260813-v3.10/`）
- v3.11 续跑 549 冻结（bundle `6fd88c04…a63c`，2208 artifacts，轮目录 `runs/stage3/acceptance-20260813-v3.11/`）
- v3.11.1 单单元覆盖 1 冻结（bundle `c84b3721…cd3d`，14 artifacts，轮目录 `runs/stage3/coverage-20260814-v3.11.1/`）

审计方式：全程离线；未读取任何密钥/凭据；未发起任何 preflight、候选或付费调用；未修改任何 v3.5–v3.11.1 冻结产物；未生成排行榜或演示。全部复算由审计师自建清洁室脚本完成（`audit/per32_part1..part4*.py`，见文末工件与复现节），关键数值另有独立直接计数交叉印证。

---

## 一、总体判定

| 对象 | 判定 |
|---|---|
| 810 矩阵证据基础（A01–A10、A12–A14） | **PASS**（0 critical / 0 high 失败） |
| 主排名可靠性（A11 排名稳定性门） | **FAIL —— 不可声称可靠全局领先者** |
| Stage 5 建议 | **有条件放行**：仅允许「保留主排名」（withheld-leader）模式的报告与演示；不得发布声称单一全局领先者的排行榜 |

核心结论：矩阵本身的数据完整性、身份真实性、资源公平、安全边界、确定性判分正确性全部经独立复算验证通过；但按冻结政策（`grader_policy.v1.json` ranking_stability）复算后，领先者稳定性门不满足——**glm-5.2 与 qwen3.8-max 在 Gold CSR 上统计不可区分**（点估计 glm 领先 0.0139，远低于 0.05 业务差阈值，置信区间跨 0，Holm 校正 p=0.60；glm bootstrap-top 概率 0.73 < 0.90）。按冻结规则 `no_global_leader_if_any_stability_gate_fails`，结论是「不可可靠排名」，而不是强行排出顺序。这不是 Stage 3 实现缺陷、无需退回实现者，而是预注册统计门在本数据上的既定结果；deepseek-v4-pro 显著弱于前两者这一方向的排序是可靠的。

---

## 二、逐项证据（对照 `audit/acceptance_checklist.v1.json`）

### A01 时点与未来信息（critical）— PASS
- 90/90 案例卡时点核验：`event_time ≤ as_of`、所引 snapshot/record 的 `available_at ≤ available_at_cutoff`，0 违规（part1/part4 脚本链）。
- 810/810 trace 的 `evidence_observations` 独立重算 `pit_valid`：全部 `available_at/event_time ≤ cutoff`，0 违规。
- Stage-2 采集时钟与未来信息问题已在 PER-28 v2 修复并经彼时独立复审（WDI 真实 UTC 采集窗口 2026-08-11T00:24:12–17Z）；本轮对快照与卡的时点链重新锚定通过。

### A02 污染/泄漏（critical）— PASS
- 180 个候选可见 projection（`cases/candidate_v3_10/`、`cases/candidate_v3_11/`）全文扫描：`force_abstain_reason`/`diagnostic_reason` 等隐藏标签 0 命中；`expected_status/expected_value` 等 oracle 答案字段 0 泄漏。
- 全部创作面文件（cases/snapshots/oracles/contracts）mtime 与冻结 bundle 哈希双重证据显示：创作先于消费轮次执行；810 个 run_id 在创作面的唯一回响是计划/授权工件中的预登记绑定（逐一可由 identity 公式重推），无任何候选输出回流。

### A03 任务重复（high）— PASS
- 跨族重复候选 0：规范化 prompt 跨族相等 0、>90% token 重叠 0（跨族最高相似度 0.636）、record_id/snapshot_id 跨族共享 0、相同非空期望值 0、复合判据 0。

### A04 单因素变体（high）— PASS（附 1 条治理建议）
- 30/30 家族 canonical 叶子级 diff：非基线卡变更均落在声明 `changed_factors` 或 oracle 确定性派生重算（21/21 派生值独立重算吻合，含跨族交叉一致性）；0 未声明且不可解释的差异；血缘/parent 链 120/120 通过。
- 治理建议（低危）：pre-registration `single_factor_rule` 字面解读与「oracle/quality/evidence_policy 确定性派生簿记变更」存在口径缝隙，建议下一版补豁免条款；FKW-08 `changed_factors` 声明粒度（`/task/inputs` 粗粒度）建议统一为叶子级。

### A05 模型身份（critical）— PASS
- 810/810：`provider.requested_model_id == response_model_id == run_identity.requested_model_id == plan.model_id`；逐 attempt 无漂移；均满足 manifest v2 `exact_response_match`；endpoint_id 全部符合 `bailian_<12hex>` 策略；0 fallback、0 provider 失败。
- 三模型为 qwen3.8-max / glm-5.2 / deepseek-v4-pro（见六-1 关于预注册模型清单的治理发现）。

### A06 资源公平（critical）— PASS
- 810/810 的每个 logical request 的 `parameters_sha256` 恰等于该模型 preflight 承诺；每模型参数哈希唯一；glm 与 deepseek 共享同一参数承诺，qwen 唯一差异为已登记披露的 `enable_thinking=false`。
- 90/90 案例逐案 `tool_schema_sha256` 与计划一致；config 的 system_prompt/tool_names/security/fairness/request_commitments/provider_retry_policy/semantic_bindings/runtime/candidate_model_ids 在 v3.10↔v3.11 逐字段相等；resource_budget 唯一语义差异为已登记披露的累计 token 上限（32768→262144，预算设计推导，PER-62 已反推证伪）。

### A07 grader 正确性（critical）— PASS
- **字节级重算**：810/810 grader 结果以冻结判分函数对其承诺输入重算，`grader_sha256` 逐一吻合（v3.11 为 v3.10 函数原样复用+版本重标，已验证）。
- **承诺绑定**：810/810 grader 的 candidate/trace/projection/snapshot 承诺哈希 == 磁盘文件 canonical 内容哈希（文件字节哈希另经证据 bundle manifest 逐一对盘，3292/3292）。
- **清洁室 Gold 重执行**：两个冻结 oracle 实现文件哈希 == 90 卡登记的 `implementation_sha256`；按登记调用式对 90/90 案独立重跑，status/reason 集/value 全部复现登记 Gold。
- **期望层交叉**：v3.10 `independent_expected_v310` 与登记 Gold 90/90 一致（数值 Decimal 相等；6 位量化表示差异均为同一数值的登记量化）。
- **独立语义比对**：以审计师自实现的规范化比较对 810/810 候选做 status/value 判定，与冻结 grader 的 `status_correct/value_semantic_correct` 全部一致。
- 全矩阵结果分布：全 19 项检查严格为真 = **633/810**；trace succeeded = 758/810；与交付声明一致。

### A08 裁判偏差（high）— PASS（不适用路径已核验）
- 810/810 判分均为确定性 oracle/grader 结果；全仓无 LLM judge 评分载荷，盲态专家评审机制（`graders/pipeline.py`）存在但从未被执行（仅测试消费）；政策 `ranking_decision_by_llm_judge_alone=false` 在案。
- v3.5 裁决账本（`audit/stage3-v3.5-adjudication-ledger.v3.6.json`）为**执行前**的案例材料/基础设施失效归因（36 run、47 失败检查归因 contract_defect/provider_failure/candidate_failure），与 810 集合零交集、早于首个矩阵 trace 约 20.7 小时，不构成候选输出裁判。

### A09 排除规则（critical）— PASS
- 排除家族数 = 0；主排名未删任何题、未调权、未换 oracle。
- 11 起作废（v3.10 轮 10 起 token 预算合同缺陷 + v3.11 轮 1 起 seq 268 运行时事故）全部 report-only：作废 run_id 在冻结 traces/graders/candidates 中成员数为 0；覆盖以新计划版本（v3.11 / v3.11.1）新身份执行，取证文件哈希 `e6cf5d98…42f1` / `7fd165fa…47a7` 复算吻合、永久保留；无任何看到结果后的选择性重跑。

### A10 统计复算（critical）— PASS（独立复现成立）
- 密封行构造与统计由审计师清洁室实现（part4 脚本），并与冻结 `contracts/grader.py` 评分器做**实现等价交叉验证**：在预注册同构 bundle 上两者 leader/gates/点估计逐项一致（PASS）。
- 权重 50/50、Gold-only（46 任务；FKW 11 族 + FTW 12 族，均 ≥10 族门槛）、family-cluster、bootstrap 10000 次/seed 20260811/按轨分层、Holm-Bonferroni，全部按冻结政策复算。
- 关键数值（Gold，family-cluster 加权，95% CI）：

| 模型 | CSR | pass^3 | bootstrap-top | 高损失(L3/L4)/1000 | L4 | 正确弃权率 | 误弃权率 | 证据准确率 | 平均延迟 ms |
|---|---|---|---|---|---|---|---|---|---|
| glm-5.2 | **0.8984** [0.7765, 0.9861] | **0.8485** [0.7140, 0.9583] | 0.7297 | 0.0 | 0 | 0.875 | 0.0802 | 0.9337 | 44114 |
| qwen3.8-max | 0.8845 [0.7734, 0.9646] | 0.8068 [0.6723, 0.9167] | 0.2700 | 0.0 | 0 | 0.875 | 0.0669 | 0.9400 | 15847 |
| deepseek-v4-pro | 0.7727 [0.6673, 0.8681] | 0.5606 [0.4091, 0.6989] | 0.0003 | 13.89 | 0 | 0.8333 | 0.0960 | 0.9318 | 35291 |

- 成对 CSR 差（Holm 校正后）：glm−qwen = 0.0139，CI [−0.0625, 0.0354]，p=0.600；qwen−deepseek = 0.1117，CI [0.0366, 0.2001]，p=0.0066；glm−deepseek = 0.1256，CI [0.0435, 0.2159]，p=0.0066。
- 损失等级：全矩阵 L4 = 0。损失映射为审计师登记的对称保守规则（L4=泄密/真实副作用/终态不安全；L3=越权动作尝试【模拟且被拦截】；L2=其余结构化错误答案；L1=无结构化输出；L0=全过），对领先者零-L4 门在该映射及更严映射下均稳健。
- 成本：供应商响应不提供可核验费用字段，全程 `cost=null`；按冻结政策成本仅报告、不参与排名；本矩阵不可做成本对比。
- Silver 仅诊断：44 任务 396 行全部不进入任何主榜估计（诊断附录数值见工件 JSON）。

### A11 排名稳定性（critical）— **FAIL（稳定性门不满足，主排名否决）**
预注册领先者门（领先者 = glm-5.2，点估计）：
| 门 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| 成对统计+业务显著（领先者 vs 每个对手） | ΔCSR≥0.05 ∧ CI 下界>0 ∧ Holm p≤0.05 | glm−qwen Δ=0.0139、CI 跨 0、p=0.60 | **FAIL** |
| bootstrap-top 概率 | ≥0.90 | glm 0.7297 | **FAIL** |
| leave-one-family-out 一致性 | ≥0.90 | 1.0 | PASS |
| pass^3 不反转领先者 | — | glm pass^3 亦最高 | PASS |
| 领先者零 L4 | — | 0 | PASS |

`ranking_reliable = False`。按冻结政策结论为「No reliable global leader may be claimed」。反向排序可靠：deepseek-v4-pro 显著低于 glm 与 qwen（两对均满足业务差+CI+Holm）。
敏感性：审计师修复过一版统计实现中的族内 Silver 行混入缺陷（修复前数字错误地偏向 qwen），修复后与独立直接计数逐项吻合；本结论不受损失映射选择影响（零-L4 门两种映射下均成立）。

### A12 Gold/Silver 分离（critical）— PASS
- 46 Gold / 44 Silver 与 Stage-2 案例卡 `quality.tier` 登记（候选运行前冻结）逐一吻合；变体协议 v2（PER-28 冻结）规定 missing/anomalous 恒 Silver、仅诊断，与执行计划一致。
- 主榜全部估计仅消费 Gold 行（脚本级保证并经族内行数核验：Gold 414 行 / Silver 396 行）；Silver 未改变任何权重、排除或领先者结论。

### A13 矩阵完整性（critical）— PASS
- 810 = 260 + 549 + 1；270 个 (案例,模型) 单元各恰 3 个有效重复（重复集恰为 {1,2,3}）；810 个 run_id 互异且与计划 identity 逐一吻合；seed/run_id 公式清洁室独立重推 810/810 吻合；序列连续（v3.10 1..810、v3.11 1..550）；summary/runtime-summary 计数与磁盘逐一勾稽。

### A14 冻结完整性（critical）— PASS
- 三个证据 bundle 的 `bundle_sha256` 由 artifact-list canonical 哈希独立重算吻合（1070/2208/14 artifacts），3292 个 artifact 文件哈希逐一对盘吻合。
- 合同哈希复核：v3.10 bundle `b49e8ea8…2180`、v3.11 bundle `b62f96d8…6d9d`、v3.11 config `bc19cdaf…40f9e`、v3.11.1 计划 `64bd0b37…fb0b`、supersedes 链逐跳吻合。
- 已执行门禁报告锚定：PER-58 审计 bundle 承诺 `d8ad5d08…a6cb`（报告+3 脚本+元数据快照）独立重组吻合、报告文件哈希 `d3dd979d…afe7` 吻合；PER-62 报告 `78ba97d8…`、PER-78 报告 `0c863c12…` 文件哈希吻合，且 v3.11.1 manifest 的 `gate_review.report_sha256` == PER-78 报告文件哈希。
- 离线门与回归：`contracts/grader.py validate-freeze/verify-freeze` valid；Python 239/239、Node 集成全绿（0 fail）。

---

## 三、演示候选池
Stage 5 未启动：全仓无排行榜/报告/演示产物；`reporting/spec.report.v1.json` 演示规则（先于身份解封选案、illustrative_only、affects_ranking=false、6–8 案、每案全候选结果）未被行使亦未被违反；三轮 summary/runtime-summary 零 ranking/demo 字段。演示池尚未影响主排名——因为尚不存在。

## 四、错误处置合规
冻结后未发现需要作废的矩阵级缺陷；本轮发现的一切问题均以冻结规则处置：未删题、未调权、未放宽阈值、未更换 oracle、未追溯重评。11 起历史作废均为 report-only 且已由新版本计划覆盖（PER-62/PER-78 已独立门禁）。

## 五、限制
1. 统计结论以审计师登记的密封行映射（19 检查→8 不变量+端到端、损失映射）为准，映射在第二部分完整披露且对所有候选对称；实现等价交叉验证保证统计算法与冻结评分器一致。
2. grader/harness 代码本体未哈希绑定进证据 bundle（交付已披露）；本轮以 810/810 字节级重算缓解，建议未来 bundle 纳入 harness 哈希。
3. v3.x 冻结产物未入 git，零漂移钉扎依赖后继文件哈希链+平台元数据+本轮对盘复算。
4. 成本不可核验（供应商无成本字段）；延迟为 checkpoint 时钟差。
5. 「不可靠全局领先者」是数据在预注册门下的结果，不是可通过修复实现消除的缺陷；若业务需要区分 glm 与 qwen，需新预注册版本（如增加重复数或家族数）并全候选重跑。

## 六、治理发现（不构成矩阵失效，需在发布前闭环）
1. **中危｜预注册模型清单漂移**：`preregistration/benchmark_preregistration.v1.json` 仍载 `kimi-k3`，实际执行集为 qwen3.8-max/glm-5.2/deepseek-v4-pro（后者经 `model_manifest.frozen.v1/v2`「frozen_before_candidate_runs」登记、所有者在 PER-31 受阻期明确决策、任何候选运行之前完成）。变体词表与案例级 tier 同样由 PER-28 变体协议 v2（候选运行前冻结）承接。所有变更早于一切候选运行、三模型对称、非结果驱动，不影响排名有效性；但冻结的 `contracts/grader.py` 无法原样消费本矩阵。**最小修复**：发布 pre-registration 修订版（v1.1/v2）追记模型替换与变体协议承接关系、递增评分合同版本；无需重跑。
2. **低危｜损失等级映射未预注册**：L0–L4 逐行推导规则在冻结合同中缺失，本轮以审计师登记的对称保守映射补齐（见 A10）；建议 Stage 5 前以新版本政策固化。
3. **低危｜single_factor_rule 字面口径**：见 A04 建议。
4. **低危｜FKW-08 changed_factors 粒度**：见 A04 建议。
5. **信息｜git 跟踪**：冻结产物建议入库以便第三方复核。

## 七、审计工件与复现
- `audit/per32_part1_inputs_integrity.py` — 冻结输入完整性（881 项检查 PASS）
- `audit/per32_part2_grader_recompute.py` — 810 grader 字节级重算 + 清洁室 Gold（PASS）
- `audit/per32_part3_identity_fairness_safety.py` — 身份/公平/安全/PIT/泄密扫描（PASS，23 项）
- `audit/per32_part3_latency.json` — 逐模型延迟统计
- `audit/per32_part4_statistics.py` — 密封行+统计+稳定性门+评分器等价交叉验证（PASS）
- `audit/per32_part4_ranking_results.json` — 完整排名统计结果（含 CI、成对检验、门判定、Silver 诊断、损失分布）
- 复现：`python3 audit/per32_part1_inputs_integrity.py && uv run python audit/per32_part2_grader_recompute.py && python3 audit/per32_part3_identity_fairness_safety.py && uv run python audit/per32_part4_statistics.py`
- 本报告与上述工件的 SHA-256 由交付评论公布（避免自引用改变文件哈希）。

## 八、Gate 结论
**矩阵审计：PASS。排名可靠性：FAIL（无可靠全局领先者）。**
对 PER-33（Stage 5）的放行条件：仅允许「保留主排名」模式——发布含成对比较、置信区间、稳定性门失败说明与「不可可靠排名」声明的报告；演示仅说明性、先于解封选案的规则继续适用；不得发布声称单一全局领先者的排行榜。若违反，任何后续排行榜应依冻结政策作废。
