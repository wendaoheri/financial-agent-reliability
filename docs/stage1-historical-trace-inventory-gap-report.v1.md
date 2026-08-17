# Stage 1 历史轨迹日志盘点与复盘能力差距报告(v1)

- 议题:PER-318(父议题 PER-316 Stage 1 双轨之一)
- 盘点日期:2026-08-17;盘点方式:**只读**(未修改/移动/删除任何冻结产物)
- 验收口径(PER-316-D1,用户已确认):场景与结论可复现可追溯(历史轨迹日志复盘);**不要求代码级可复现重放**
- 基线纪律(PER-316-D2 推断,与 PER-257-D6 一致):不重跑;旧冻结产物内容不改不删、原位保留
- 审计方法:5 路并行只读审计(早期 preflight 批次 / v3.5·v3.8 副本拓扑 / v3.9–v3.11 / coverage·smoke·session / 横切锚点),全部关键引用经 `shasum -a 256` 或规范化哈希交叉复核

## 1. 总判断

1. **v3.8 起的验收批次(v3.8 / v3.9 / v3.10 / v3.11 / coverage v3.11.1)证据链完整闭环**,满足降级后的复盘口径:场景输入(case_card + data_snapshot,哈希锚定)→ 模型身份预检(3/3 通过、requested==response)→ 运行轨迹(traces + checkpoints 哈希链事件账本)→ grader 输入输出(commitments 哈希互绑)→ 评分与排名结论(summary.records + by_model 聚合)。作废 run 全部 report-only 留痕、不入结论。
2. **v3.5 是第一个有真实验收运行的批次**,主链闭合(36/36 grader↔trace 对账一致),但治理层有缺口:无授权记录、无批次级 preflight 文书、候选答案未外置;验收门本身未通过(glm-5.2 六次 provider_unavailable)。
3. **v3–v3.4 与 frozen-preflight-evidence v1–v4 共 9 个批次止步于 preflight**,从未发生验收运行(v3.4 契约明文 `acceptance_runs_authorized=false`)。它们是"模型身份与协议门"证据(协议演进复盘链完整自洽、哈希闭环),**不是**"场景答题→评分"证据;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)。
4. **smoke v1/v2 与 session-20260811 构成冒烟线完整叙事**:v1 hard stop(harness 身份判定缺陷)→ frozen-v1 取证冻结 → v2 纠正性续跑 36/36 成功 → frozen-v2 收官冻结(含 harness 代码与 validator);tar.gz 与目录逐文件一致(抽样 7/7 sha256 匹配)。session-20260811 是当日 preflight 排障会话留存,经哈希绑定全部 36 个冒烟 run。
5. **未发现任何篡改或字节级 drift**:evidence/stage3(正本)↔ frozen-runtime-archive(子集)抽查全部逐字节一致;v3.5 bundle 112/112、v3.8 bundle 152/152、v3.10 1070 件、v3.11 2208 件 artifact 存在性与哈希抽检全部通过;catalog frozen manifest 抽检 5/5 一致(1 条经 PER-86 迁移路径可解析)。
6. **复盘不可行的区域仅一处**:v3–v3.4 的"场景评分结论"复盘(运行不存在);其余所有批次的既定结论均可由现存轨迹日志复盘。

## 2. 批次覆盖矩阵(批次 × 证据链节点)

图例:✅ 齐备 ◐ 部分/降级 ❌ 缺失 ➖ 不适用(按设计无此节点)

| 批次 | 场景输入 | preflight/授权 | 运行轨迹 | grader I/O | 评分结论 | 自证 manifest |
|---|---|---|---|---|---|---|
| acceptance v3 | ◐ 契约间接锚定(12 用例) | ✅ preflight + 诊断 | ❌ 无运行 | ❌ | ❌(仅协议门结论) | ❌ |
| acceptance v3.1 | ◐ 同上 | ✅ | ❌ | ❌ | ❌ | ❌ |
| acceptance v3.2 | ◐ 同上 | ✅ | ❌ | ❌ | ❌ | ❌ |
| acceptance v3.3 | ◐ 同上 | ✅ 三件套(auto/forced/sequence) | ❌ | ❌ | ❌(协议门 decision) | ❌ |
| acceptance v3.4 | ◐ 同上 | ✅(契约禁止验收运行) | ❌ | ❌ | ❌ | ❌ |
| frozen-preflight-evidence v1 | ◐ run_manifest 清单级 | ✅ 2 会话,0/3 通过 | ❌ | ➖ | ➖ execution_decision=blocked | ✅ |
| frozen-preflight-evidence v2 | ◐ 同上 | ✅ 3 会话,0/3 | ❌ | ➖ | ➖ blocked | ✅ |
| frozen-preflight-evidence v3 | ◐ 同上 | ✅ + 目录探测根因证据 | ❌ | ➖ | ➖ blocked | ✅ |
| frozen-preflight-evidence v4 | ◐ 同上 | ✅ 修正 ID 后 3/3 通过 | ❌ | ➖ | ➖ preflight_passed | ✅ |
| smoke v1 | ✅ plan 锚定 | ✅(权威件在 frozen-v1) | ◐ 3 run,全部作废(hard stop) | ◐ 冒烟级 grader 3 份 | ✅ hard_stop 结论 | ❌(在 frozen-v1) |
| smoke v2 | ✅ | ✅ | ✅ 36/36(含 3 条纠正版) | ✅ 36 份 | ✅ expand_to_270=true | ❌(在 frozen-v2) |
| frozen-smoke-evidence v1/v2 | ✅ 自包含 | ✅ | ✅ | ✅ | ✅ | ✅(16/121 artifacts) |
| session-20260811 | ➖ | ✅ 6 份诊断/预检会话 | ➖ | ➖ | ➖ | ❌ |
| acceptance v3.5 | ✅ 12/12 用例哈希锚定 | ◐ 无批次级文书(trace 内嵌;6 条 valid=false);❌ 无授权 | ✅ 36 traces + 162 事件 checkpoint 链 | ✅ 36/36 对账一致 | ✅ gate=false(qwen 7 > ds 6 > glm 2) | ✅ 112/112 |
| acceptance v3.8 | ✅ | ✅ preflight + 双授权 | ✅ 36 traces + 182 事件 | ✅ 36/36,19 项检查 | ✅ accepted 31/36 | ✅ 152/152 |
| acceptance v3.9 | ✅ | ✅ 双授权 + 3/3 | ✅ 36/36(无 driver 日志,机制未引入) | ✅ 36/36 | ✅ accepted 30/36 | ✅ 152 件 |
| acceptance v3.10 | ✅ 90 用例 | ✅ 双授权(270 run)+ 3/3 | ✅ 260 traces + 270 checkpoints(多出的 10 = 作废取证链)+ driver 日志 | ✅ 260/260 + 9 份 gate 拒绝转录 | ✅ accepted 215/270,10 作废留痕 | ✅ 1070 件 |
| acceptance v3.11 | ✅ 90 用例 × repeat 1–3 | ◐ preflight 自 v3.10 carry-over(9 项等价校验,无独立授权.preflight) | ✅ 549 traces + 550 checkpoints + driver 日志 | ✅ 549/549 | ✅ accepted 417/550,1 作废留痕 | ✅ 2208 件 |
| coverage v3.11.1 | ✅(批内无副本,plan 哈希锚定仓库,逐一核验一致) | ✅ carry-over + 0 付费预检 + PER-78 门审 | ✅ 1 run(5 事件链) | ✅ 19/19 checks | ✅ 独立轮次;stage5 报告层合并 | ✅ 14/14 |

跨批次规模一致性:traces = candidates = graders 逐批相等;checkpoints 多出数恒等于作废 run 数(取证链保留)。stage5 报告口径 810 = 260(v3.10)+ 549(v3.11)+ 1(v3.11.1),与盘上 traces 实数逐批吻合。

## 3. 差距清单(按严重度)

### High

| # | 缺口 | 影响批次 | 可否从现有产物推导 |
|---|---|---|---|
| H1 | v3–v3.4 无任何验收运行轨迹/grader/评分;若误作"验收结论"证据则链断裂。按设计即无运行(v3.4 契约 `acceptance_runs_authorized=false`),属定性问题而非数据丢失 | v3, v3.1, v3.2, v3.3, v3.4 | ❌ 不可推导(运行从未发生);只能重新运行或按"协议门证据"降级标注 |

### Medium

| # | 缺口 | 影响批次 | 可否推导 |
|---|---|---|---|
| M1 | 付费调用授权记录缺失(authorization.run/preflight 均无);v3.8 的 authorization_basis 未追认 v3.5 | v3.5 | ❌ 只能降级标注(v3.8 起机制已建立) |
| M2 | frozen-runtime-archive 副本不自证:缺 bundle.manifest/plan/contracts(v3.8 副本还缺 preflight/authorization/candidates/config) | v3.5, v3.8 归档副本 | ✅ 可从 evidence/stage3 正本推导(已验哈希一致);需建立映射索引 |
| M3 | v3.10 run_bba344e2 被验证器在持久化前拒绝,无 grading-failures 转录、离线重建同构 trace 却能通过——该次拒绝本身不可从取证复现,仅存 checkpoint 与作废记录 | v3.10(1/270) | ❌ 孤立事件;作废记录本身即证据,建议显式标注 |

### Low

| # | 缺口 | 影响批次 | 可否推导 |
|---|---|---|---|
| L1 | cost_usd 全为 null(provider 响应不含成本);token 用量与请求次数完整 | 全部批次 | ❌ 金额不可推导;token 口径可作替代,金额需价目表事后折算 |
| L2 | 早期 preflight 不记录消费的 case_id(v3–v3.2 无字段,v3.3 仅 arguments_sha256,v3.4 仅 argument_shape;脱敏代价) | v3–v3.4 | ❌ 未来运行须新增 case_id 明文记录(非敏感字段) |
| L3 | summary 无显式 ranking 字段 | v3.5–v3.11.1 | ✅ 可由 by_model/by_repeat 聚合导出 |
| L4 | v3.9 无 driver-console/driver-progress 日志(机制 v3.10 才引入) | v3.9 | ✅ checkpoints 哈希链 + trace usage/attempts 已可承载过程复盘 |
| L5 | v3.10 driver-progress.jsonl 中 55 条 run_invalidated 事件仅 10 个唯一 run_id(断点续跑重复落盘);复盘须按 run_id 去重 | v3.10 | ✅ 去重后与 invalidated-runs.json 完全吻合 |
| L6 | 双哈希口径:引用值多为规范化 c14n 哈希(plan_sha256、snapshot content_sha256),与整文件 sha256 不同;裸文件哈希复核会误判失配 | 全部批次 | ✅ 需在复盘工具中区分口径(catalog manifest 钉整文件哈希,case_card 钉 content 哈希,两者各自一致) |
| L7 | FTW 合成案例卡 `evidence_refs=[]`:卡级快照指针缺失,快照绑定仅在运行时投影哈希(trace/checkpoint/grader commitments);快照实体在 snapshots/longbridge/synthetic_v2/ 存在 | v3.5–v3.11 的合成案例 | ◐ 运行内链条完整,卡级指针需新增记录(或文档说明) |
| L8 | v3.11 无独立 authorization.preflight.json(carry-over 取代,源哈希 + 9 项等价校验 + PER-62/63 独立审计,链条闭合) | v3.11 | ✅ |
| L9 | reports/stage5 无独立 artifact manifest,provenance 内嵌于 report bundle/machine_readable_results;外部可复核性弱于 runs bundle | stage5 | ✅ REPRODUCE.md + build_stage5.py 重推路径存在 |
| L10 | runs/stage3 的 v3.5/v3.8 目录是 symlink → evidence/stage3(无 drift 风险但无冗余;不解引用符号链接的归档/打包会丢失) | v3.5, v3.8 | ✅ 提示性 |
| L11 | v3.8 graders 不含 model_id(v3.5 含),模型归属须经 run_id 联结(已验 36/36 可联结) | v3.8+ | ✅ |
| L12 | coverage 与 v3.11 批内部分文件权限 600(owner-only),他人复盘需注意读权限 | v3.11, v3.11.1 | ✅ 提示性 |
| L13 | v3.6/v3.7 无执行批次目录——属"契约修订版"(有全套契约文件 + 独立门审计 + 复现脚本 audit/reproduce_stage3_v3_7_gate_gaps.py),非缺口,但盘点时易误读为丢失 | — | ✅ 已有审计文档闭环 |
| L14 | 契约文件 `paid_calls_authorized=false` 与 authorization.run/runtime-summary 的 true 并存(语义分层:契约不授权,授权来自 authorization_basis)——表面不一致,建议文档注明以免审计误读 | v3.9–v3.11 | ✅ |

## 4. 最小补齐方案(只提方案,本 Stage 不执行)

### A. 可从现有产物推导(建议 Stage 2 复盘工具实现)

1. **批次血缘索引**:batch → 契约(base_bundle/supersedes 链)→ plan → preflight → bundle manifest 的机器可读索引;含 v3–v3.4 无 plan 的说明(契约包 `supersedes.plan` 指向 stage3_smoke_plan.v2)。
2. **排名导出器**:由 summary.by_model / by_repeat / by_model_and_repeat 生成显式 ranking(补 L3)。
3. **作废对账器**:driver-progress 按 run_id 去重后与 invalidated-runs.json、summary.invalidated_runs、bundle.invalidated_run_ids 三处对账(补 L5,已在本次盘点人工验证 v3.10/v3.11 吻合)。
4. **archive ↔ evidence 映射**:为 frozen-runtime-archive 子集副本生成"对应正本 + manifest 条目"索引(补 M2)。
5. **哈希口径校验器**:区分规范化 c14n 哈希与整文件 sha256 两种口径,避免误判 drift(补 L6)。
6. **降级标注**:在复盘输出中为 v3–v3.4、frozen-preflight v1–v4 标注"协议门证据(非验收评分证据)";为 v3.5 标注"授权记录缺失(历史批次)";为 run_bba344e2 标注"孤立取证不可复现事件"(对应 H1/M1/M3)。

### B. 必须新增记录(适用于未来运行,不回补历史)

1. **preflight/工具调用记录 case_id 明文**(非敏感字段,与脱敏策略不冲突;补 L2)。
2. **成本口径**:价目表映射或供应商账单归档;当前以 token/请求次数为替代口径(补 L1)。
3. **授权文书强制前置**:authorization.preflight/run 作为批次冻结的必要 artifact(v3.8 起已成事实标准,固化进新契约版本即可)。
4. **合成案例卡级快照指针**(evidence_refs 补齐 snapshot_sha256;补 L7)——或在新契约版本中书面确认"运行时投影哈希即为卡级锚点"的口径。
5. **归档打包规范**:解引用 symlink、保留文件权限说明(补 L10/L12)。

## 5. 副本拓扑与完整性备注

- `runs/stage3/acceptance-20260812-v3.5`、`-v3.8` 为 **symlink** → `evidence/stage3/` 同名目录;物理上只有两份数据:evidence/stage3(正本,含 manifest)与 runs/frozen-runtime-archive(子集)。名义三副本实为两副本,无独立漂移面。
- evidence vs archive:summary/runtime-summary(4 对)+ 抽查 traces/graders/checkpoints(12 对)shasum-256 全部一致,**零 drift**。
- frozen-smoke-evidence-20260811-v2.tar.gz 与目录:122 条目路径+大小全一致,抽样 7/7 sha256 一致(只读流式解出,未落盘解压)。
- 全量密钥模式扫描(api_key/secret/token/bearer/sk-*)命中仅为字段名;所有批次声明 `credentials_persisted=false`、`raw_provider_responses_persisted=false`;authorization 文件仅含 owner comment/issue UUID 与授权范围。
- 作废治理纪律全程有效:作废 run 永不复用/删除、report-only、不入 summary.records(v3.10 十个、v3.11 一个 run_id 逐一核验缺席于 records);coverage v3.11.1 的补跑单元经 plan.coverage_map 显式映射被替换的 v3.10 单元,非静默重选。

## 6. 对 Stage 2(复盘工具建设)的输入要点

1. 复盘单元 = run_id;最小证据包 = trace + checkpoint 链 + grader + summary.records 行 + plan.tasks 对应条目(snapshot/case 哈希锚)。
2. 复盘工具必须内建:run_id 去重(L5)、双哈希口径(L6)、symlink 感知(L10)、批次类型标签(协议门批次 vs 验收批次 vs 冒烟 vs coverage)。
3. 跨批次可比性已由契约 comparability 条款保障(v3.10→v3.11 仅 token 上限变化,prompt/oracle/评分阈值/用例材料不变);工具应保留该声明的引用。
4. 结论合并点在 reports/stage5 报告层(v3.11.1 并入 v3.10 r1 + v3.11 r3 构成该单元 3 个有效重复);复盘工具应复刻该合并规则而不是改写任何批次 summary。


---

**PER-323 历史说明(2026-08-17,Stage 2 追加)**:本文引用的冻结目录路径(`contracts/`、`cases/`、`catalog/`、`snapshots/`、`preregistration/`、`evidence/`、`audit/`、`reports/` 及 gitignore 的 `runs/` 等基线 v1 目录)已按 PER-323 冻结清理清单 v1 删除;原文内容可按 `docs/per323-stage2-deletion-record.md` 所载各目录回滚索引 SHA 从 git 历史找回(`runs/` 的删除前归档见该记录 §2)。本文原文与结论作为历史记录保留,未改写。