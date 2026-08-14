## 结论

Stage 3 新合同已实现、测试并按 v3 / v3.1 / v3.2 逐版冻结；旧 v1.1 的 `0/36 oracle match`、旧 bundle 与旧哈希均未改写或后验重判。由于最终 v3.2 预检仍只有 2/3 通过，严格门槛未满足，因此没有生成新 36-run plan，也没有启动任何 12 case × 3 模型验收单元。

这是 blocked 结果，不应解释为模型身份或 provider 不可用：三模型响应身份都与请求 ID 完全一致；断点仅发生在 `qwen3.8-max` 的最终结构化提交行为。

## 已完成的合同修复

- 新增 candidate-output v3 合同、全局 reason-code 词表和 12 个 candidate projection；公开 status/value 条件、answer value 字段/类型/单位、material records 与最低数量，不公开 expected status/value。
- 从候选视图移除 `force_abstain_reason`、`diagnostic_reason`，替换为可观察事实。
- 新增三模型共用的 OpenAI-compatible `submit_candidate_result`；`tool_choice=auto`，无模型专属 prompt/schema。
- `calculate` wire schema 与运行时同时要求 `inputs.values` decimal-string 数组；二元运算恰好两个值、direct 恰好一个值。
- grader 拆为 11 个独立布尔检查：结构、状态、可执行 value/单位、reason、证据、时点、方法、计算、权限轨迹、环境终态、敏感信息。权限自声明仅保留为诊断字段。
- parse failure 与主动 abstain 分离；只持久化 category、field path、SHA-256，不保存原始候选文本。
- v3.1 把 tool wire 上过宽的 `value:{}` 改成每 case 已公开 answer schema 或 null；v3.2 增加一次固定、模型中立、未提交时才触发的修复轮。每次失败版本均保留，没有覆盖。

## 测试

- `uv run python -m unittest tests.test_acceptance_v3 -v`：8/8 通过。
- `node --test tests/integration/acceptance_v3.test.mjs`：5/5 通过。
- `node --test tests/integration/acceptance_v3_1.test.mjs`：2/2 通过。
- `node --test tests/integration/acceptance_v3_2.test.mjs`：1/1 通过。
- `uv run python -m unittest discover -s tests -v`：121/121 通过。
- `node --test tests/integration/*.test.mjs`：14/14 通过。
- 脱敏扫描：0 个 key/Bearer/Authorization 命中。
- v1.1 plan 中登记的 8 个旧合同/实现文件 SHA-256 全部仍匹配。

## 付费预检证据

| 版本 | 结果 | 直接证据 | 决策 |
|---|---:|---|---|
| v3 | 1/3 | 三模型身份 3/3；qwen/glm 的 generic `value` 未满足 per-case object schema | 冻结失败证据，不运行 36 |
| v3 脱敏诊断 | 0/2（诊断） | qwen/glm 均调用 submit；最后错误 `/value`，只留类别/路径/hash | 发布 v3.1 |
| v3.1 | 2/3 | glm/deepseek 一次有效提交；qwen 读取 case 后 submit 0 次 | 冻结失败证据，不运行 36 |
| v3.2 | 2/3 | glm/deepseek 一次有效提交；qwen 在 `read_frozen_case → calculate` 后耗尽 8 次模型请求，submit 0、repair 0 | 最终 blocked，停止付费尝试 |

预检/诊断合计 11 个模型单元、54 个 provider requests；正式验收单元为 0/36。provider 未返回可核验费用，成本继续记 `null`。

## 哈希

- v3 合同 bundle：`60fd6b391c5d7c65a824cfcf22f13eaee034e60966ef6bf434063972da90cf0a`
- v3.1 合同 bundle：`7ba47cd90526bcc13cf4ee9382e795d5cb5aba08719725f8c93b9cfee298dd44`
- v3.2 合同 bundle：`8a269e939917bc9476319a14f191104c89291eaff2a9afd5692d652f77bf35c9`
- v3.2 manifest 文件：`78543d54a8f8322e47903bc5720803601d5555330722dff767199155f568cf5d`
- v3.2 preflight 文件：`ffc31be2c77063a1d9e5bcec0c4809d230486c7c780254dbd03056de4754c87e`
- 保留的 v1.1 smoke evidence bundle：`f35874cee12ab31e10aee21a8614c67414a70f60e8604f373fb6a41f646df2ef`

## 未满足项

- 3/3 预检：实际 2/3。
- 新 36 run IDs、36 trace / grader / checkpoint：因门槛未满足，均未生成/执行。
- 36/36 结构化结果与独立不变量：未进入验收，不能宣称通过。

后续若继续，必须先由评测负责人决定是否把“预检专用 case 的非必要 calculate 循环”视为候选能力失败，或另行批准一个新版本的模型中立 preflight task 设计；不能覆盖 v3.2、放宽 oracle 或加入模型特调。
