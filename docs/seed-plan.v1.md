# 公开 benchmark seed 冻结方案 v1

状态：Frozen before Stage 2；版本：`1.0.0`；冻结议题：PER-26；核验日：2026-08-11（Asia/Shanghai）。机器可读的唯一清单为 `catalog/spec.seed-catalog.v1.json`，文件哈希和 bundle hash 见 `catalog/spec.seed-catalog.frozen.v1.json`。

本方案冻结的是来源池、30 个案例族的名额、去重键和晋级门，不是 90 个已完成题目。Stage 2 只能在这些名额内策展；不得根据候选模型输出、运行表现或正式排名删题、换题、改权重。公开原题、公开答案、公开程序和候选模型输出一律不得成为生产 oracle。

## 冻结目录与规模

- `docs/seed-plan.v1.md`：人工审阅方案与边界。
- `catalog/spec.seed-catalog.v1.json`：来源、许可、版本、配额、30 个案例族和晋级门。
- `catalog/spec.seed-catalog.frozen.v1.json`：文件 SHA-256 和 bundle hash。
- 30 个案例族：Financial Knowledge Work（FKW）15，Financial Tool Workflow（FTW）15。
- 每族固定三个 `case_card` 变体：`normal`、`single_factor_perturbation`、`missing_or_anomalous`，合计 90 个案例卡。
- 24 个 Gold 候选族的正常/单因素变体共 48 个 Gold 候选案例；所有缺证/异常变体及 6 个诊断族共 42 个 Silver 诊断案例。Gold 是待晋级状态，不代表本阶段已生成 Gold 标准答案。

## 来源与许可核验结论

| 来源 | 冻结版本 | 许可结论 | 原始结构与评分器 | 正式主集边界 |
|---|---|---|---|---|
| FinanceBench | GitHub `cc39aeb4…`; HF `e04404e3…` | 官方 HF 卡片为 CC-BY-NC-4.0；官方 GitHub 无 LICENSE，且不能推定其收录 PDF 的再分发权 | 150 个公开问答，含 answer、evidence、justification、文档与页码；无可直接采用的冻结确定性评分器 | 公开行只作开发/诊断。正式题必须从新的主披露重新取证、记录 as-of/许可并独立复算；不得仅复制公开答案/PDF |
| FinQA | GitHub `0f16e286…` | 官方站称数据 CC-BY-4.0；代码仓库 LICENSE 为 MIT；保留上游报告血缘 | 文本、表格、问题、支持事实、可执行 program、执行答案；`code/evaluate/evaluate.py` 给出 execution/program accuracy | 公开 train/dev/test 标签与程序只作开发；评分器只作交叉诊断，Gold 使用新的披露和独立 oracle |
| TAT-QA | GitHub `870accc4…` | README 称数据 CC-BY-4.0；代码 LICENSE 为 MIT；底层报告另存来源 | 16,552 问题、2,757 混合上下文；span/multi-span/count/arithmetic；EM/F1/scale/operator 评分器 | 2024 年已公开 test gold，污染风险高；原题只作开发，新的表文证据与数值 oracle 才能晋级 |
| BizBench | HF `0a793f2f…` | 数据卡为 Apache-2.0；作为复合基准仍须逐行满足上游许可，不能用汇总标签覆盖上游义务 | 8 个任务、14,377 train + 4,673 test；question/answer/task/context/options/program；数据仓库无冻结本地 scorer | 公开行只作开发；CodeFinQA、CodeTATQA、ConvFinQA(E)、TAT-QA(E) 必须按上游记录去重和核验许可 |
| FinMCP-Bench | HF `fa3ffa69…` | CC-BY-NC-SA-4.0；Qieman MCP 服务条款不在数据许可内 | 613 个唯一样本：145 single-tool、249 multi-tool、219 multi-turn；公开参考消息/工具调用，无自包含可执行 oracle | v1 不直接占正式名额，只给 FTW-13～15 提供结构参考；不复制含用户标识、时变回包或专有工具依赖的样本 |
| Longbridge 公开只读池 | `case-data` contract v1（PER-23） | 场景设计为项目原创；每份快照仍须逐条记录上游许可；不推定可再分发 | 仅公开只读查询；状态/交易语义用确定性模拟账本；Stage 2 为每族实现 oracle | 12 个 Gold 候选族 + 3 个 Silver 诊断族；严禁账户、资产、持仓、订单、成交或真实下单 |

核验依据均保存在 catalog 的 artifact URI、commit、commit time、许可证据路径与检索日期中。特别处理如下：

1. FinanceBench 的 GitHub 与 HF 许可信息不对称，因此按较严格的 CC-BY-NC-4.0 处理注释数据，同时把仓库代码和第三方 PDF 权利标为未覆盖。
2. FinQA、TAT-QA 区分“数据许可”与“代码许可”，不能只引用仓库 LICENSE 后将其套到全部数据。
3. BizBench 是复合数据集。其 CodeFinQA、CodeTATQA、ConvFinQA(E)、TAT-QA(E) 与上游基准重叠，必须先通过上游记录键排除重复。
4. FinMCP-Bench 的 `benchmark_all.json` 是另外三个文件的并集；四个文件不可直接拼接，否则 613 条会被重复计数。数据含公开参考工具调用和用户标识样式，主集不复制。

## 30 个案例族配额

### 总配额

| 维度 | 冻结配额 |
|---|---|
| 轨道 | FKW 15；FTW 15 |
| 主来源 | 公开 benchmark 15；Longbridge 公开只读 15 |
| 公开 benchmark | FinanceBench 3；FinQA 4；TAT-QA 4；BizBench 4；FinMCP-Bench 直接题 0 |
| 任务域 | research、valuation、risk、portfolio、wealth_compliance、operations 各 5 |
| 风险层 | critical 5；high 14；medium 9；low 2 |
| 家族质量目标 | Gold candidate 24；Silver diagnostic only 6 |
| 变体 | 每族正常/单因素/缺证异常各 1，共 90 |

FinMCP-Bench 不直接计入 30 个主来源名额；它只作为 FTW-13～15 的结构参考，这三个家族的主来源仍是重新设计的 Longbridge/模拟环境。这样既使用了公开工具基准的复杂度结构，也不把其许可、外部服务和公开答案风险带入正式题。

### 家族冻结表

| 家族 | 来源 | 域 / 风险 | 质量目标 | 单因素轴 |
|---|---|---|---|---|
| FKW-01 | FinanceBench | research / medium | Gold candidate | as_of_time |
| FKW-02 | FinanceBench | research / high | Gold candidate | evidence_completeness |
| FKW-03 | FinanceBench | valuation / high | Gold candidate | currency_unit |
| FKW-04 | FinQA | valuation / high | Gold candidate | accounting_basis |
| FKW-05 | FinQA | valuation / medium | Gold candidate | fiscal_period |
| FKW-06 | FinQA | risk / high | Gold candidate | consolidation_scope |
| FKW-07 | FinQA | risk / critical | Gold candidate | method_applicability |
| FKW-08 | TAT-QA | risk / high | Gold candidate | event_regime |
| FKW-09 | TAT-QA | research / high | Gold candidate | source_revision |
| FKW-10 | TAT-QA | research / low | Gold candidate | language |
| FKW-11 | TAT-QA | operations / medium | Gold candidate | document_modality |
| FKW-12 | BizBench | portfolio / high | Gold candidate | claim_materiality |
| FKW-13 | BizBench | wealth_compliance / high | Silver only | source_ambiguity |
| FKW-14 | BizBench | operations / medium | Silver only | ocr_quality |
| FKW-15 | BizBench | wealth_compliance / medium | Silver only | forecast_horizon |
| FTW-01 | Longbridge | valuation / high | Gold candidate | tool_parameter_semantics |
| FTW-02 | Longbridge | wealth_compliance / critical | Gold candidate | authorization |
| FTW-03 | Longbridge + simulator | operations / critical | Gold candidate | timeout_state |
| FTW-04 | Longbridge + simulator | operations / critical | Gold candidate | idempotency_key |
| FTW-05 | Longbridge | portfolio / high | Gold candidate | partial_success |
| FTW-06 | Longbridge + simulator | portfolio / critical | Gold candidate | account_identity |
| FTW-07 | Longbridge | research / high | Gold candidate | instruction_injection |
| FTW-08 | Longbridge | valuation / medium | Gold candidate | stale_cache |
| FTW-09 | Longbridge | portfolio / low | Gold candidate | pagination_order |
| FTW-10 | Longbridge | risk / high | Gold candidate | retryable_error |
| FTW-11 | Longbridge | wealth_compliance / high | Gold candidate | required_abstention |
| FTW-12 | Longbridge + simulator | operations / high | Gold candidate | final_state |
| FTW-13 | Longbridge；FinMCP 结构参考 | risk / medium | Silver only | rate_limit |
| FTW-14 | Longbridge；FinMCP 结构参考 | portfolio / medium | Silver only | provider_field_alias |
| FTW-15 | Longbridge；FinMCP 结构参考 | wealth_compliance / medium | Silver only | recovery_message_order |

## 三变体契约

每个家族只能生成以下三张卡，变体之间共享 `family_key`：

1. `normal`：完整证据、明确权限和可用工具；Gold 候选族必须可独立复算。
2. `single_factor_perturbation`：只改变冻结表中的一个 `variant_axis`；其他语义字段保持不变。Gold 候选族在确定性 oracle 完成后可晋级 Gold。
3. `missing_or_anomalous`：移除必要证据或注入声明异常；固定为 Silver、`ranking_eligible=false`，期望 `abstain`、`escalate` 或 `reject_action`，不得伪装为唯一答案题。

目前 `preregistration/benchmark_preregistration.v1.json` 使用 `baseline / single_factor_stress / single_factor_control`，而 `case_card` 冻结契约和本议题使用 `normal / single_factor_perturbation / missing_or_anomalous`。正式运行前必须发布有版本的 crosswalk 或新版 preregistration；不得悄悄把 `missing_or_anomalous` 映射成语义不同的 `single_factor_control`。

## 去重键

所有键均按 `financial-agent-c14n-json-v1` 规范化后取 SHA-256：

- `upstream_record_key = sha256(source_id, source_revision, upstream_record_id)`：阻止同一公开行重复进入。
- `primary_evidence_key = sha256(primary_source_stable_id, document_revision, source_locator, as_of)`：把同一原始披露/行情记录对齐。
- `cross_source_task_key = sha256(primary_evidence_key, normalized_question_intent, operator_graph, answer_target, variant_axis)`：排除 BizBench 与 FinQA/TAT-QA 等跨源重叠。
- `family_key = sha256(primary_evidence_key, task_domain, operator_graph, answer_target, variant_axis)`：名额和统计聚类使用；变体类型、扰动值不进入 family key。

稳定标识优先使用 SEC accession、交易所公告 ID、发行人文件 revision、MIC+证券 ID+数据时点、Longbridge 完整查询参数与响应 hash；禁止只用文件名、公司简称或问题文本作为证据键。

## Stage 2 晋级门

公开原题永远只作开发/诊断 seed。一个 Gold 候选家族的正常/单因素案例只有同时满足以下条件才能晋级：

- 来源 revision 与适用许可证重新核验，复合数据逐条完成上游许可链；许可不明立即排除。
- 用新的主披露或冻结公开行情构造事实，记录 event/as-of/available/retrieved 时间、定位符、查询、原始响应 hash 和证据 hash。
- 独立实现确定性 oracle，并由第二实现或人工复算一致；公开 benchmark 答案和候选模型输出不得参与定标。
- 单因素差分验证器确认只有注册轴发生语义变化；缺证/异常固定为 Silver。
- 四层去重键全部唯一；发现共享根源只保留一个家族名额，不能靠改写措辞规避去重。
- Longbridge 只读范围通过校验；涉及超时、幂等、身份、最终状态的任务只运行在确定性模拟账本。
- 两名审阅者在揭盲候选表现前签署来源、许可、时点、oracle 可判定性和无未来信息确认。

FKW-13～15 与 FTW-13～15 在 v1 固定为 Silver 诊断族，不得在本版本就地升 Gold。若未来补足唯一 oracle 和确定性环境，须新建 catalog 版本、保留变更理由，并在候选运行前重新预注册。

## 适用边界与未决风险

- 这些公开 benchmark 主要覆盖美国公开披露，不能代表所有市场、会计准则、语言或合规辖区；30 族的域配额不等于地域代表性。
- 公开答案、程序和 test gold 已广泛暴露，不能用公开集成绩证明抗污染能力。
- FinanceBench 的非商业条款、GitHub 无 LICENSE 与第三方 PDF 权利边界使其不适合直接分发为正式主集。
- BizBench 的聚合许可证不足以替代上游逐项审计；未完成 lineage audit 的行不得进入任何可发布主集。
- FinMCP-Bench 的外部 Qieman 服务、时变响应、用户标识和无自包含 scorer 阻止其直接晋级 Gold。
- Longbridge 快照许可必须逐源记录；即使 API 可读取，也不等于允许再分发原始响应。
- preregistration 变体命名不一致是正式运行前的硬门；本阶段不修改他人所有的 preregistration 文件。

## 一手来源

- [FinanceBench paper](https://arxiv.org/abs/2311.11944), [official GitHub](https://github.com/patronus-ai/financebench), [official dataset card](https://huggingface.co/datasets/PatronusAI/financebench)
- [FinQA paper](https://aclanthology.org/2021.emnlp-main.300/), [official GitHub](https://github.com/czyssrs/FinQA), [official project site](https://finqasite.github.io/)
- [TAT-QA paper](https://aclanthology.org/2021.acl-long.254/), [official GitHub](https://github.com/NExTplusplus/TAT-QA)
- [BizBench paper](https://aclanthology.org/2024.acl-long.452/), [official dataset](https://huggingface.co/datasets/kensho/bizbench)
- [FinMCP-Bench paper](https://arxiv.org/abs/2603.24943), [official dataset](https://huggingface.co/datasets/DianJin/FinMCP-Bench), [project index](https://github.com/aliyun/qwen-dianjin)


---

**PER-323 历史说明(2026-08-17,Stage 2 追加)**:本文引用的冻结目录路径(`contracts/`、`cases/`、`catalog/`、`snapshots/`、`preregistration/`、`evidence/`、`audit/`、`reports/` 及 gitignore 的 `runs/` 等基线 v1 目录)已按 PER-323 冻结清理清单 v1 删除;原文内容可按 `docs/per323-stage2-deletion-record.md` 所载各目录回滚索引 SHA 从 git 历史找回(`runs/` 的删除前归档见该记录 §2)。本文原文与结论作为历史记录保留,未改写。