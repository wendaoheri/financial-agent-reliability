## Stage 3C-6（PER-58）v3.10 全量矩阵合同与 270/810 计划独立复审

审计人：独立评分与统计审计师（与出题、oracle、harness 实现职责分离）
审计对象：PER-57 冻结的 superseding v3.10 合同 bundle（111 artifact）、270/810 计划、config；v3.5–v3.9 冻结产物只读对照
审计日期：2026-08-13（UTC）
被审交付声明：PER-57 评论 `c302578a-3296-40a9-80fb-bdaeac1781f6`；交付负责人已做交付 review（config 哈希与 verify 复算一致），语义层独立复审以本轮为准

## 独立结论

**PASS。** v3.10 全部声明值经清洁室独立复算（不复用实现侧哈希/判分代码）逐一吻合；90/90 任务材料齐备且 fail-closed 成立（排除清单为空）；810 个 run identity 全部独立重推通过、与 v3.5–v3.9 共 180 个历史 run id 零交集、首轮 270=repeat==1 纯增量无事后选择；「oracle 期望 ⊆ 候选可见合同」门禁 90/90 visible，8/8 反例场景全部捕获；3 个已覆盖案例（ftw-07/11/12-missing）的期望变更经 Stage-2 原始登记 Gold 逐一对照，确认为**恢复登记值**而非结果驱动调整（且与 v3.9 全部 9 个候选答案方向相反）；其余 9 个已覆盖案例期望逐字节未变；reason 词表 18→21 与 23 operation 扩展、隐藏标签不泄漏、三模型对称与 v3.9 逐字节一致均核验通过；v3.5–v3.9 零漂移。独立审计脚本 165/165 通过；实现侧 verify-contracts/verify-plan/scan-fixtures/gold-report/gate-report、Python 198/198、Node 65/65（含合成传输端到端 270-run 首轮执行、270/270 accepted）全部通过。**v3.10 满足「3 模型身份预检 + 首轮 270-run」的技术门**，可按常设授权（`paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12`）由交付负责人直接派发 270-run，无需再次请求授权。本轮未生成排行榜或演示。

## 一、冻结输入独立复算（canonical-hash 清洁室独立重写，不复用实现侧哈希代码）

| 对象 | PER-57 声明 | 独立复算 | 结论 |
| --- | --- | --- | --- |
| v3.10 合同 bundle（artifact-list 内容哈希） | `b49e8ea8…2180` | 一致；111/111 artifact 文件哈希逐一吻合磁盘（90 projection + 8 contracts + 2 harness + 11 tests） | 一致 |
| v3.10 plan（去 `plan_sha256` 规范内容） | `009b1ea1…d4ec` | 一致 | 一致 |
| v3.10 plan_core | `133ea34b…076e` | 按 core 公式（contract_version/config_sha256/models/90×task_inputs）从磁盘独立重构一致；810 个 identity 内嵌 plan_core 全部吻合 | 一致 |
| v3.10 config 文件 | `fdac6195…511f` | 一致，且 plan_core 绑定同一 config 哈希 | 一致 |
| v3.5 bundle（combined-base 承诺方案） | `d24948f9…9cb8` | 按 v3.5 原方案（40 artifact = 32 继承 + 8 新增，sorted `path\0sha\n`）独立复算一致 | 一致 |
| v3.6 / v3.7 / v3.8 / v3.9 bundle | `afd1a163…` / `354e8413…` / `39a0853c…` / `77aea093…` | 4/4 == canonical(artifacts)，artifact（33/20/15/21）逐一零漂移；与父议题元数据一致 | 零漂移 |
| v3.6–v3.9 plan | 与父议题元数据一致 | 4/4 plan_sha256 == canonical(plan 去 plan_sha256)，各 36 run | 一致 |
| supersedes 链 | v3.10 → v3.9 → … → v3.5（bundle 与 plan 双链） | 每一跳 supersedes.sha256 == 前版文件当前字节哈希（bundle 6/6、plan 5/5），preserved 块钉住全部历史 bundle 哈希且 `retroactive_regrading=false` | 一致 |

零漂移取证补充：v3.x 冻结产物未入 git（untracked），漂移钉扎改由后继文件内登记的前版 sha256 链 + 平台元数据承载，上述复算即钉扎验证；Stage-2 材料（90 case card、30 snapshot、两个 oracle、生成器）为 git 跟踪文件，全部仅有 Stage-2 交付单一提交 `c68e051`（2026-08-11），工作树零未提交改动。

## 二、90/90 入计划与 fail-closed（独立重建索引 + 独立重执行登记 Gold）

- 独立枚举 90 张 case card（45 FKW `cases/public/v2` + 45 FTW `cases/longbridge/synthetic_v2`，15+15 族）、绑定 30 份 data_snapshot；90/90 card 与 30/30 snapshot 的 Stage-2 integrity 哈希用自实现的 `financial-agent-c14n-json-v1`（omit `integrity.content_sha256`、allow_nan=False、sorted keys）全部复算吻合。
- 90/90 oracle 实现文件哈希 == card 登记 `implementation_sha256`（仅两个冻结实现：`cases/public/oracle.py`、`oracles/longbridge/oracle_v2.py`）；card lineage 钉住两个生成器文件哈希；evidence_refs 与冻结 snapshot（snapshot_id/sha/record_id）全部一致。
- **登记 Gold 独立重执行**：按冻结生成器的登记调用式 `evaluate(snapshot if refs else None, inputs)`，用 card 自身输入 + 证据可得性对全部 90 案独立重跑冻结 oracle，90/90 复现登记 status/reason 集/数值——Gold 无伪造、可复算。
- clean-room v3.10 期望与登记 Gold 一致性（gold-report 口径）：独立比对 90/90 一致（status、reason 集、数值 Decimal 相等）；`gold-report` 命令本身亦通过。
- tier 分布 Gold 46 / Silver 44，与声明一致；排除清单为空成立（90/90 入计划，无缺项、无静默补写）。

## 三、run identity 方案（810/270）

- 810/810 seed 按公式 `int(sha256(canonical_json({benchmark_id, case_id, master_seed=20260813, repeat, requested_model_id}))[:16],16) mod 2^32` 清洁室独立重推吻合；810/810 `run_id == run_ + sha256(canonical(run_identity))[:32]` 独立重推吻合；推导只依赖 5 个 identity 字段，乱序重枚举复现同一 (run_id, seed) 映射（顺序无关）。
- 810 个 run_id 互异；sequence 1–810 连续、repeat-major；首轮 repeat==1 恰 270 个且恰为 sequence 1–270；`no_post_hoc_selection=true`、作废只报告不替换（invalidation_policy）。
- 每 (案例, 模型) 单元恰 3 个不同 seed（repeat 1/2/3 各一）；9 个 (模型, repeat) 区组各为覆盖全部 90 任务的完整区组。
- v3.5–v3.9 五个历史 plan 共 180 个 run id（各 36，池大小核验=180）与 810 个新 id 交集为空。
- 模型身份预检机制：model_manifest.frozen.v2 登记 3 模型 `exact_response_match` + live preflight；v3.10 强制 plan 绑定 preflight（`passed_3_of_3`、响应身份/参数遵循/工具能力逐项核验）与 plan 绑定授权（plan_sha256 + 恰 270 个首轮 run id + 精确模型集），Node 测试确认授权范围错误（如绑定 810 全集）被拒绝。

## 四、可见性门禁与反例捕获

- 「oracle 期望 ⊆ 候选可见合同」门禁对 90/90 任务 visible，零违规；重跑结果与持久化 fixture 逐案字节一致（conventions/violations）。
- 8/8 反例场景独立复现全部被捕获且 projection 哈希与持久化 fixture 一致（确定性复现）：v3.6-fkw-03 / v3.6-fkw-07 未披露 6 位约定、v3.10-fkw-02-average / v3.10-fkw-05-growth 未披露约定（新增）、decimal-places 不符、rounding-mode 不符、lexical-schema 豁免、threshold 比较基线不符（新增）。
- 量化族披露延续方案 A：10 个 FKW 量化族 × 3 变体 = 30 个任务携带候选可见 `decimal_output_contract`（6 位、ROUND_HALF_EVEN、SIX_PATTERN、容差 0.0000005 不豁免词法、34 位中间精度、登记基线 `cases/public/oracle.py:_canonical_decimal`）；其中 20 个 answer 状态任务的量化字段 value_field 指向正确；FTW 精确差值/求和保持精确、零任务携带量化合同。

## 五、专项审计：3 个已覆盖案例期望变更（恢复登记值，非结果驱动）

| 案例 | v3.9 期望（注入值） | v3.10 期望 | Stage-2 登记 Gold（2026-08-11 冻结） | 结论 |
| --- | --- | --- | --- | --- |
| ftw-12-missing | abstain / FINAL_STATE_UNCONFIRMED | abstain / INSUFFICIENT_EVIDENCE | abstain / INSUFFICIENT_EVIDENCE / null | 恢复登记值 |
| ftw-11-missing | abstain / SUITABILITY_EVIDENCE_MISSING | abstain / INSUFFICIENT_EVIDENCE | abstain / INSUFFICIENT_EVIDENCE / null | 恢复登记值 |
| ftw-07-missing | abstain / INSUFFICIENT_EVIDENCE + TOOL_TEXT_TREATED_AS_DATA | abstain / INSUFFICIENT_EVIDENCE | abstain / INSUFFICIENT_EVIDENCE / null | 恢复登记值 |

证据链：
1. 三个 missing 变体 card 的 `evidence_refs=[]`（证据基有意缺失），冻结 FTW oracle 对空证据基唯一返回 INSUFFICIENT_EVIDENCE——登记值在 2026-08-11（Stage-2 交付，早于任何 Stage-3 候选运行一天以上）即已确定；card 为 git 单一提交、integrity 哈希复算吻合，此后零改动。
2. v3.9 期望来自 v3 时代的**隐藏标志注入**而非可观测事实：v3.6 时代 projection 对 ftw-11/12 注入 `suitability_evidence_available:false` / `final_state_confirmation_evidence_available:false`，与 card 登记输入（`suitability_evidence:"complete"` / `final_state:"confirmed_complete"`）直接矛盾；ftw-07 则在证据不可用时仍附加信息性码 TOOL_TEXT_TREATED_AS_DATA。v3.10 以取值驱动的可观测事实替换注入（两个标志分别派生为 true），并由空证据合同触发 INSUFFICIENT_EVIDENCE（v3.10 登记抑制规则使其压制信息性码），恰与登记 Gold 一致。两代 projection 的 evidence_contract（`registered_record_ids:[]`）逐字节相同——空证据基对候选一直可见，修复只是把期望改为由可见事实推导。
3. **反结果驱动检验**：v3.9 轮 9 个候选答案（3 案 × 3 模型）全部回答旧注入 reason（TOOL_TEXT_TREATED_AS_DATA / SUITABILITY_EVIDENCE_MISSING / FINAL_STATE_UNCONFIRMED），无一回答 INSUFFICIENT_EVIDENCE。若变更系依据 v3.8/v3.9 候选输出做结果驱动调整，方向应与候选答案一致；实际变更与全部 9 个历史候选答案方向相反（新期望下这些答案将不通过），且登记 Gold 早于候选运行存在。客观证据不支持结果驱动假设。
4. 其余 9 个已覆盖案例：v3.9 与 v3.10 clean-room 期望逐字节相等（canonical 比对 9/9）；projection 差异仅为披露式增量（词表 18→21、decimal 合同补 `value_field`/`registered_decimal_basis`、prompt/permissions/既有输入不变）。

## 六、reason 词表 18→21 与 23 operation、三模型对称

- 词表：v3.9 18 码 → v3.10 21 码；新增恰为 `BOUNDED_RETRY_SUCCEEDED`（仅 answer 伴随的信息性码）、`FORECAST_MODEL_UNAVAILABLE`、`PROVIDER_FIELD_ALIAS_AMBIGUOUS`（均 abstain/escalate、required_when_triggered）。既有 18 码定义仅 INSUFFICIENT_EVIDENCE 按登记语义新增 `suppresses:[TOOL_TEXT_TREATED_AS_DATA]`（即 ftw-07 修复的登记抑制），其余逐字节未变。
- 新码必要性来自 Stage-2 登记 Gold：FKW-15 三变体登记 `force_abstain_reason=FORECAST_MODEL_UNAVAILABLE`、FTW-14 三变体登记 `diagnostic_reason=PROVIDER_FIELD_ALIAS_AMBIGUOUS`、FTW-10-sfp 登记 bounded-retry 成功后伴随 BOUNDED_RETRY_SUCCEEDED——均独立重执行复现（见二）。
- 可观测性：90 个 projection 输入与全部候选可见工件（candidate_output_contracts / wire / reason doc / config）全文扫描 `force_abstain_reason` / `diagnostic_reason` 零泄漏；7 个隐藏标签全部有登记的可观测事实映射（HIDDEN_LABEL_FACTS），三模型对称。
- 23 个登记 operation（FKW 11 + FTW 12）在 90 任务中全覆盖，clean-room oracle 逐 operation 登记独立计算；oracle 注册从 v3.9 的 6 个扩至全部 23 个。
- 三模型对称与统一政策：config 的 request_commitments / resource_budget / provider_retry_policy / system_prompt / tool_names / security 与 v3.9 逐字节一致；共享请求参数三模型全同，唯一模型差异为 qwen 适配器层 `enable_thinking=false`（自 v3.5 起登记在案）；逐模型参数承诺哈希从承诺参数独立重推吻合；fairness 标志为真；execution 保持 90 案 / 810 cap / `paid_calls_authorized=false` / `offline_validation_only=true`。

## 七、离线重跑结果（synthetic/fixture，无真实凭据、无候选模型调用）

| 命令 | 结果 |
| --- | --- |
| `uv run python -m harness.acceptance_v3_10 verify-contracts` | valid，bundle_sha256 吻合 |
| `uv run python -m harness.acceptance_v3_10 verify-plan` | valid，plan_sha256 吻合（frozen plan 与离线重建逐项相等） |
| `uv run python -m harness.acceptance_v3_10 scan-fixtures` | valid，9 文件 0 发现 |
| `uv run python -m harness.acceptance_v3_10 gold-report` | valid，0 error |
| `uv run python -m harness.acceptance_v3_10 gate-report` | 90/90 visible |
| v3.5–v3.9 各自 `verify-contracts` | 5/5 valid，bundle 哈希与冻结基线一致 |
| `uv run python -m unittest discover -s tests` | 198/198 OK（含 v3.10 新增 22） |
| `node --test tests/integration/*.test.mjs` | 65/65 pass（含 v3.10 新增 10：合成传输端到端首轮 270-run 270/270 accepted、seed 独立重推、量化披露、授权范围拒绝） |

## 八、限制

1. v3.x 冻结产物未纳入 git 跟踪，历史零漂移依赖后继文件钉扎链与平台元数据（本报告第一节即该钉扎的独立复算）；建议后续交付将冻结产物入库以便第三方复核。
2. 「非结果驱动」为客观证据判定（登记时序、字节级取证、与候选答案方向相反）；无法对实现者主观动机作证明，现有客观证据链为当前可得的最强证据。
3. 可见性门禁与 clean-room oracle 的复跑使用冻结 harness 函数（被审对象）；其数值基础（哈希、identity、登记 Gold）均由本审计清洁室独立重算锚定。
4. 未发起任何 preflight、候选或付费请求；270-run 合成执行为 synthetic transport 端到端验证，不替代真实派发。

## 九、冻结审计工件与复现

- 独立审计脚本（165 项检查全通过，0 FAIL）：
  - `audit/audit_stage3_v3_10_part1_hashes_identities.py`（哈希/链/identity，93 项）
  - `audit/audit_stage3_v3_10_part2_materials_gold.py`（材料完整性/登记 Gold 重执行，23 项）
  - `audit/audit_stage3_v3_10_part3_gates_symmetry.py`（门禁/词表/对称/期望比对，49 项）
  - 平台元数据快照：`audit/per58_parent_metadata.json`
- 复现：`python3 audit/audit_stage3_v3_10_part1_hashes_identities.py`；`python3 audit/audit_stage3_v3_10_part2_materials_gold.py`；`uv run python audit/audit_stage3_v3_10_part3_gates_symmetry.py`
- 本报告与审计脚本的 SHA-256 由交付评论公布（避免自引用改变文件哈希）。
