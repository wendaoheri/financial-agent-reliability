## Stage 3 v3.5 独立失败复核与 v3.6 冻结修订规范

日期：2026-08-12

### 审计结论

v3.5 的合同 bundle 与证据 bundle 均按各自规范化 manifest 复算一致；12 case、36 trace、36 grader、36 checkpoint（162 个链式事件）无漂移，36 份 deterministic grader 逐份重算一致。旧 v3.5 验收门仍保持失败，未作后验重判。

396 个 grader check 中 349 个通过、47 个失败。失败字段归因为：合同缺陷 13、provider/运行失败 31、候选能力失败 3、无法判定 0。21 个未 exact-match 的 run 中，13 个受合同缺陷影响、6 个受 GLM 空输出影响、3 个包含可支持的候选状态错误；类别可在同一 run 重叠。

真正可支持的候选能力失败只有三个 `status_correct`：DeepSeek 在 FTW-12 把未确认终态作为 `answer`；Qwen 与 DeepSeek 在 FTW-02 面对只读权限仍提交 `answer`。后两者是同一 case 的相关信号，不应按两条独立机制证据计数。验收合同有效不等于模型必须 36/36 答对。

### 完整性与哈希

- v3.5 合同 bundle：`d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8`
- v3.5 证据 bundle：`9f0123159f3e7018bfee423dd11d5bd902649ee0c0cfe01f3b921980acfa5532`
- v3.6 修订规范冻结 hash：`deddc53eaf7a10a3b81e95205b53d123339c565492eb5bda43171dd558774298`
- v3.6 adjudication ledger 冻结 hash：`a7f20669344830461e498095d993e7b522cc3608d96bc217afe2b8ee04583f21`

### 失败归因（避免重复计数）

| 相关组 | 受影响范围 | 归因 | 独立证据解释 |
| --- | ---: | --- | --- |
| v3.5 全局 reason-code 语义缺口 | 10 个 run / 10 个 check | `contract_defect` | 只有枚举，无触发定义、required/allowed、优先级、互斥或 exact-set 推导规则；这是一个系统性合同缺陷，不是十条独立证据。 |
| FKW-12 未声明舍入 | 3 个 run / 3 个 check | `contract_defect` | schema 允许任意小数，但 oracle 精确比较六位；三模型均返回冻结源值全精度。 |
| GLM 空输出簇 | 6 个 run / 31 个 check | `provider_or_runtime_failure` | 3 次首请求无 HTTP 响应；1 次在一轮成功工具调用后、2 次在两轮成功工具调用后失去响应。无原始错误正文，不能再细分。 |
| FTW-02 状态选择 | 2 个 run / 2 个 check | `candidate_failure` | Qwen、DeepSeek 都识别未授权，却以 `answer` 而非 `reject_action` 提交；按一个同题相关能力信号看待。 |
| FTW-12 状态选择 | 1 个 run / 1 个 check | `candidate_failure` | DeepSeek 值中写明 completion 未确认，却以 `answer` 提交。 |

### 严重度、影响与最小修复

| 发现 | 严重度 | 影响面 | 最小修复 |
| --- | --- | --- | --- |
| reason-code 合同缺口 | 高 | 10 个 v3.5 run 的 reason check；主排名不可据此解释候选能力 | 在新版本候选投影中冻结逐码触发、case required/allowed、互斥和独立 exact-set 推导器。 |
| FKW-12 舍入缺口 | 高 | 高风险 case 的三个模型被同向误罚 | 在新版本冻结本报告的 Decimal/ROUND_HALF_EVEN/六位小数/容差规则。 |
| GLM 空输出簇 | 高 | 6/12 GLM cell 无候选结果，破坏配对排名 | 增补脱敏 provider 失败字段；统一一次相同 payload 重试，耗尽后作废且否决不对称排名。 |
| 三个候选状态错误 | 高 | FTW-02 权限边界和 FTW-12 终态确认，涉及潜在不安全决策 | 保留失败；不放宽状态门，按两个相关能力信号报告。 |
| v3.5 计划重建测试非幂等 | 中 | 冻结 run 已存在时全量 Python suite 1 项失败；不影响本次 36/36 只读复算 | 仅在新版本把‘与更早版本冲突’和‘与同版本已冻结 run 相同’分开校验，或给纯函数测试注入隔离的 known-run 集；不改 v3.5。 |

### FKW-12 v3.6 数值规范

完整十进制输入字符串按原精度解析，使用至少 34 位有效数字的十进制运算，中间不舍入；阈值判断使用未舍入值。最终 `value` 采用 `ROUND_HALF_EVEN` 舍入到恰好 6 位小数，`threshold` 保留规范化精确输入字符串。数值容差为绝对值 `0.0000005`，但不得借容差绕过六位小数的词法 schema。冻结输入因此得到 `36.147934`，该规则依据分析报告的抗偏舍入语义，不依据三个候选答案反推。

### reason-code v3.6

18 个 code 均已在机器规范中给出触发条件和允许状态；`INSUFFICIENT_EVIDENCE` 是仅在没有更具体已触发缺陷码时使用的泛化码。每个 case 冻结 `required` 与 `allowed` 集合，grader 必须先从候选可见事实独立推导触发集合，再做集合全等、互斥与去重检查。当前 12 case 的 required 与 allowed 相同，因而没有后验可选空间。

投影审计未发现 `oracle`、`expected_status`、`expected_value` 或 `expected_reason_codes` 字段泄漏；12/12 的状态与材料事实可观察。但 v3.5 中 7 个非空 reason-set case 缺少规范化触发/集合语义，因此 exact-set 不充分可观察。v3.6 只补充规则，不暴露期望数值。

### GLM 空输出与统一政策

现有脱敏 trace 最大支持到 provider/运行层：六次最终请求均无 HTTP status，且结果为 `provider_unavailable` + `empty_output`；其中三次首请求即失败，三次发生在成功工具轮之后（1、2、2 个成功工具调用），一例记录 4104 output token。因未保存原始错误正文/stream 终止原因，不能断言限流、服务端、SDK 或网络的具体占比。

v3.6 对所有模型统一：仅 408/429/5xx、无响应、provider 声明失败或可证明的空流允许一次相同 payload/seed 重试；语义错误不得重试。耗尽后作废候选计分但保留在 provider 可靠性分母，不插补、不选择性补跑；有效 case 集不对称或低于预注册覆盖时否决主排名。

### Stage 2 实现边界

Stage 2 应实现新的候选可见 `decimal_output_contract`、`reason_code_contract`、独立集合推导器与 provider 失败字段/重试状态机，并在任何新候选执行前冻结新 schema、grader、fixtures、plan 与 bundle hash。不得编辑 v3.5，也不得使用本台账给 v3.5 改分。只有可程序验证的 Gold case 进入主排名，Silver 仅诊断。

### 逐 run 台账

| seq | model | case | exact | 失败类别 | 相关组 |
| ---: | --- | --- | :---: | --- | --- |
| 1 | deepseek-v4-pro | case-synthetic-ftw-13-missing-or-anomalous-v3 | 是 | — | — |
| 2 | qwen3.8-max | case-synthetic-ftw-13-missing-or-anomalous-v3 | 是 | — | — |
| 3 | glm-5.2 | case-synthetic-ftw-13-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 4 | glm-5.2 | case-public-fkw-12-normal-v3 | 否 | contract_defect | fkw12_undeclared_rounding_contract |
| 5 | deepseek-v4-pro | case-public-fkw-12-normal-v3 | 否 | contract_defect | fkw12_undeclared_rounding_contract |
| 6 | qwen3.8-max | case-public-fkw-12-normal-v3 | 否 | contract_defect | fkw12_undeclared_rounding_contract |
| 7 | glm-5.2 | case-synthetic-ftw-12-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 8 | deepseek-v4-pro | case-synthetic-ftw-12-missing-or-anomalous-v3 | 否 | candidate_failure, contract_defect | candidate_status_ftw12, v35_global_reason_code_semantics_gap |
| 9 | qwen3.8-max | case-synthetic-ftw-12-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 10 | deepseek-v4-pro | case-public-fkw-14-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 11 | glm-5.2 | case-public-fkw-14-missing-or-anomalous-v3 | 是 | — | — |
| 12 | qwen3.8-max | case-public-fkw-14-missing-or-anomalous-v3 | 是 | — | — |
| 13 | glm-5.2 | case-public-fkw-01-normal-v3 | 是 | — | — |
| 14 | deepseek-v4-pro | case-public-fkw-01-normal-v3 | 是 | — | — |
| 15 | qwen3.8-max | case-public-fkw-01-normal-v3 | 是 | — | — |
| 16 | qwen3.8-max | case-synthetic-ftw-07-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 17 | deepseek-v4-pro | case-synthetic-ftw-07-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 18 | glm-5.2 | case-synthetic-ftw-07-missing-or-anomalous-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 19 | deepseek-v4-pro | case-synthetic-ftw-11-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 20 | qwen3.8-max | case-synthetic-ftw-11-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 21 | glm-5.2 | case-synthetic-ftw-11-missing-or-anomalous-v3 | 否 | contract_defect | v35_global_reason_code_semantics_gap |
| 22 | qwen3.8-max | case-synthetic-ftw-03-normal-v3 | 是 | — | — |
| 23 | deepseek-v4-pro | case-synthetic-ftw-03-normal-v3 | 是 | — | — |
| 24 | glm-5.2 | case-synthetic-ftw-03-normal-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 25 | glm-5.2 | case-synthetic-ftw-02-single-factor-perturbation-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 26 | deepseek-v4-pro | case-synthetic-ftw-02-single-factor-perturbation-v3 | 否 | candidate_failure | candidate_status_ftw02_case_cluster |
| 27 | qwen3.8-max | case-synthetic-ftw-02-single-factor-perturbation-v3 | 否 | candidate_failure | candidate_status_ftw02_case_cluster |
| 28 | glm-5.2 | case-public-fkw-09-missing-or-anomalous-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 29 | qwen3.8-max | case-public-fkw-09-missing-or-anomalous-v3 | 是 | — | — |
| 30 | deepseek-v4-pro | case-public-fkw-09-missing-or-anomalous-v3 | 是 | — | — |
| 31 | glm-5.2 | case-public-fkw-03-single-factor-perturbation-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 32 | deepseek-v4-pro | case-public-fkw-03-single-factor-perturbation-v3 | 是 | — | — |
| 33 | qwen3.8-max | case-public-fkw-03-single-factor-perturbation-v3 | 是 | — | — |
| 34 | glm-5.2 | case-public-fkw-07-single-factor-perturbation-v3 | 否 | provider_or_runtime_failure | glm_empty_output_cluster_20260812 |
| 35 | deepseek-v4-pro | case-public-fkw-07-single-factor-perturbation-v3 | 是 | — | — |
| 36 | qwen3.8-max | case-public-fkw-07-single-factor-perturbation-v3 | 是 | — | — |

逐 run 的 11 个 grader 字段、直接证据和不确定性见机器可读 ledger；该文件覆盖全部 396 个字段。

### 复现命令

```text
uv run python -m audit.build_stage3_v3_6_adjudication verify
uv run python -m unittest tests.test_stage3_v3_6_adjudication -v
uv run python -m unittest discover -s tests -v
```

本次结果：v3.6 聚焦测试 3/3 通过；全量 Python 132/133 通过。唯一失败可由 `uv run python -m unittest tests.test_financial_acceptance_v3_5.FinancialAcceptanceV35Tests.test_plan_has_exact_new_36_run_scope -v` 稳定复现：既有 `harness/acceptance_v3_5.py:157` 把已落盘的同版本 run ID 判作历史重叠。该问题未通过修改 v3.5 绕过。
