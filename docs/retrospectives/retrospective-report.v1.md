# 历史运行复盘记录(Stage 2,PER-319)

- 依据口径:`docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`(v1,PER-317 冻结)
- 差距报告:`docs/stage1-historical-trace-inventory-gap-report.v1.md`(PER-318)
- git 锚点:`f835b07368a6dbf0aa2e004e2cd7df3baa78a2c2`
- 复盘方式:完全离线;只读冻结/本地产物;无模型调用、无网络、无交易
- runs/ 完整性依据:runs/ 为 .gitignore 排除对象,git 不覆盖该目录:其完整性由 bundle manifest 逐件 sha256 自证(A1_manifest_integrity)+ 独立重算承担;git 零改动验证仅对 tracked 目录主张(contracts/、evidence/、audit/、reports/、snapshots/、cases/、catalog/、preregistration/)(PER-320 审计 P1 纠正)
- 判定汇总:partially_traceable × 1;traceable × 19

## 逐批次判定

| 批次 | 类型 | 契约版本 | 判定 | 降级标注 | 依据 |
| --- | --- | --- | --- | --- | --- |
| `acceptance-v3` | protocol_gate | 3.0.0 | **traceable** | H1,L1,L2,L6 | 适用判定项全部通过(协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)) |
| `acceptance-v3.1` | protocol_gate | 3.1.0 | **traceable** | H1,L1,L2,L6 | 适用判定项全部通过(协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)) |
| `acceptance-v3.2` | protocol_gate | 3.2.0 | **traceable** | H1,L1,L2,L6 | 适用判定项全部通过(协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)) |
| `acceptance-v3.3` | protocol_gate | 3.3.0 | **traceable** | H1,L1,L2,L6 | 适用判定项全部通过(协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)) |
| `acceptance-v3.4` | protocol_gate | 3.4.0 | **traceable** | H1,L1,L2,L6 | 适用判定项全部通过(协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)) |
| `frozen-preflight-evidence-v1` | frozen_preflight_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(预检证据 bundle:结论限于模型身份预检判定,非验收评分证据) |
| `frozen-preflight-evidence-v2` | frozen_preflight_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(预检证据 bundle:结论限于模型身份预检判定,非验收评分证据) |
| `frozen-preflight-evidence-v3` | frozen_preflight_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(预检证据 bundle:结论限于模型身份预检判定,非验收评分证据) |
| `frozen-preflight-evidence-v4` | frozen_preflight_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(预检证据 bundle:结论限于模型身份预检判定,非验收评分证据) |
| `smoke-v1` | smoke | 2.0.0 | **traceable** | L1,L6 | 适用判定项全部通过(冒烟线批次:结论限于冒烟通过/硬停判定,非验收评分证据) |
| `smoke-v2` | smoke | 2.0.0 | **traceable** | L1,L6 | 适用判定项全部通过(冒烟线批次:结论限于冒烟通过/硬停判定,非验收评分证据) |
| `frozen-smoke-evidence-v1` | frozen_smoke_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(冒烟线批次:结论限于冒烟通过/硬停判定,非验收评分证据) |
| `frozen-smoke-evidence-v2` | frozen_smoke_evidence | — | **traceable** | L1,L6 | 适用判定项全部通过(冒烟线批次:结论限于冒烟通过/硬停判定,非验收评分证据) |
| `session-20260811` | diagnostic_session | — | **traceable** | L1,L6 | 适用判定项全部通过(诊断会话留存:仅过程排障证据,不构成任何评分结论) |
| `acceptance-v3.5` | acceptance | 3.5.0 | **partially_traceable** | M1,L1,L3,L6,L7,L10 | 完整性通过但存在影响结论的降级/缺失节点:A5_governance_freeze(验收评分批次:结论链 N0–N5 全量复盘) |
| `acceptance-v3.8` | acceptance | 3.8.0 | **traceable** | L1,L3,L6,L7,L10,L11 | 适用判定项全部通过;降级标注不留结论影响:A2_scenario_inputs(验收评分批次:结论链 N0–N5 全量复盘) |
| `acceptance-v3.9` | acceptance | 3.9.0 | **traceable** | L1,L3,L4,L6,L7,L11,L14 | 适用判定项全部通过;降级标注不留结论影响:A2_scenario_inputs(验收评分批次:结论链 N0–N5 全量复盘) |
| `acceptance-v3.10` | acceptance | 3.10.0 | **traceable** | M3,L1,L3,L5,L6,L7,L11,L14 | 适用判定项全部通过;降级标注不留结论影响:A2_scenario_inputs(验收评分批次:结论链 N0–N5 全量复盘) |
| `acceptance-v3.11` | acceptance | 3.11.0 | **traceable** | L1,L3,L6,L7,L8,L11,L12,L14 | 适用判定项全部通过;降级标注不留结论影响:A2_scenario_inputs(验收评分批次:结论链 N0–N5 全量复盘) |
| `coverage-v3.11.1` | coverage | 3.11.1 | **traceable** | L1,L3,L6,L7,L11,L12,L14 | 适用判定项全部通过(验收评分批次:结论链 N0–N5 全量复盘) |

## 报告层(stage5 合并口径)

- `grader_bundle_freeze`: 通过
- `report_bundle_freeze`: 通过
- `report_consistency`: 通过
- 密封行重建: 810 行;provisional_leader=glm-5.2;ranking_reliable=False

## 推导件

- 血缘索引:`lineage-index.v1.json`(20 批次)
- archive↔evidence 映射:`archive-map.v1.json`(一致:True)
- 作废对账:`invalidation-recon.v1.json`(acceptance-v3.10=ok;acceptance-v3.11=ok)
- 排名导出:`ranking.v1.json`(ranking_reliable=False)

## 降级标注登记

- **H1**(high):v3–v3.4 无任何验收运行轨迹/grader/评分;按设计即无运行(v3.4 契约 acceptance_runs_authorized=false),属定性问题而非数据丢失。 影响:这些批次只构成'模型身份与协议门'证据,不是'场景答题→评分'证据;任何验收评分结论不得引用这些批次。
- **M1**(medium):v3.5 付费调用授权记录缺失(authorization.run/preflight 均无);v3.8 的 authorization_basis 未追认 v3.5。 影响:v3.5 评分链本身完整(36/36 grader↔trace 对账一致),但治理层授权节点缺失:该批次结论按'部分可追溯'标注,授权缺失不影响评分重算本身,影响的是执行合规性声明。
- **M3**(medium):v3.10 run_bba344e2 被验证器在持久化前拒绝,无 grading-failures 转录;该次拒绝本身不可从取证复现,仅存 checkpoint 与作废记录。 影响:孤立事件(1/270);作废记录本身即证据,该 run 不入结论。复盘按'孤立取证不可复现事件'显式标注,不影响其余 260 run。
- **L1**(low):cost_usd 全为 null(provider 响应不含成本);token 用量与请求次数完整。 影响:金额口径不可复盘;以 token/请求次数为替代口径。
- **L2**(low):早期 preflight 不记录消费的 case_id(脱敏代价)。 影响:早期 preflight 的用例级消费不可复盘;批次级结论不受影响。
- **L3**(low):summary 无显式 ranking 字段。 影响:无;可由 by_model/by_repeat 聚合推导导出(本工具 ranking 命令)。
- **L4**(low):v3.9 无 driver-console/driver-progress 日志(机制 v3.10 才引入)。 影响:过程复盘以 checkpoints 哈希链 + trace usage/attempts 承载,无缺口。
- **L5**(low):v3.10 driver-progress.jsonl 中 run_invalidated 事件存在断点续跑重复落盘;复盘须按 run_id 去重。 影响:去重后与 invalidated-runs.json 完全吻合(本工具 invalidation 命令复核)。
- **L6**(low):双哈希口径:规范化 c14n 哈希与整文件 sha256 并存;裸文件哈希复核会误判失配。 影响:无;复盘工具内建口径区分(hashing.detect_bundle_aggregate 等)。
- **L7**(low):FTW 合成案例卡 evidence_refs=[]:卡级快照指针缺失,快照绑定仅在运行时投影哈希(trace/checkpoint/grader commitments)。 影响:运行内链条完整(复盘按运行时锚点校验);卡级指针缺失按缺口记录,不影响本口径下的可追溯判定。
- **L8**(low):v3.11 无独立 authorization.preflight.json(carry-over 取代:源哈希 + 9 项等价校验 + PER-62/63 独立审计)。 影响:链条闭合,不构成缺口;复盘按 carry-over 记录核对。
- **L9**(low):reports/stage5 无独立 artifact manifest,provenance 内嵌于report bundle/machine_readable_results。 影响:外部可复核性弱于 runs bundle;REPRODUCE.md + build_stage5.py 重推路径存在。
- **L10**(low):runs/stage3 的 v3.5/v3.8 目录是 symlink → evidence/stage3(无 drift 风险但无冗余)。 影响:无;复盘工具 symlink 感知,以 evidence/stage3 为正本。
- **L11**(low):v3.8+ graders 不含 model_id(v3.5 含),模型归属须经 run_id 联结。 影响:无;已验全部可联结(本工具经 plan.runs 联结并复核)。
- **L12**(low):批内部分文件权限 600(owner-only),他人复盘需注意读权限。 影响:提示性;不影响本次复盘(同机同用户)。
- **L14**(low):契约文件 paid_calls_authorized=false 与 authorization 文书的 true 并存(语义分层:契约不授权,授权来自 authorization_basis)。 影响:表面不一致、语义正确;复盘按语义分层判读。

## 复现命令

```bash
uv run fareli-retro run --all
uv run fareli-retro evidence   # 重生成本目录全部证据
```
