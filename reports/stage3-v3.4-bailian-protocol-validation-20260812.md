## 结论

v3.4 改造与最小付费预检均已完成，三模型协议预检 **3/3 通过**。`qwen3.8-max` 在 2 个 HTTP 200 请求内完成“读取冻结协议题 → 调用 `submit_candidate_answer`”，参数一次通过本地严格校验，没有修复轮、没有 schema 拒绝。

这直接推翻了“Qwen 不会调用提交最终答案工具”的解释。更准确的结论是：v3.3 的失败来自接入配置与工具传输合同的交互；它不是 Qwen Function Calling 不可用，也不是金融推理失败。

## v3.4 改造

- 对 `qwen3.8-max` 按百炼 Qwen API 显式发送 `enable_thinking=false`，不再误把本地 `reasoning=false` 当成供应商思考模式已经关闭。
- 三模型共同固定 `tool_choice=auto`、`tool_stream=false`、`parallel_tool_calls=false`；删除思考模式下无效的 forced-function 诊断。
- 将单一 `submit_candidate_result` 拆为 `submit_candidate_answer` 和 `submit_candidate_non_answer`。answer 工具只接收逐题公开的答案对象；non-answer 工具没有 `value` 字段。模型侧不再面对 `anyOf(answer object, null)`。
- 工具解析后由 harness 重建原有候选结果对象并执行相同确定性校验。没有改 grader、oracle 或候选语义合同，也没有后验改判 v3.3。
- 百炼规则已固化在 `docs/contracts/bailian-function-calling-v3.4.md`，包含来源、访问日期与适用边界。

## 预检结果

| 模型 | 身份 | 请求数 | 读取 | 答案提交 | schema 拒绝 | 修复轮 | 结果 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen3.8-max` | 精确匹配 | 2 | 1/1 | 1/1 | 0 | 0 | passed |
| `glm-5.2` | 精确匹配 | 2 | 1/1 | 1/1 | 0 | 0 | passed |
| `deepseek-v4-pro` | 精确匹配 | 2 | 1/1 | 1/1 | 0 | 0 | passed |

三个模型的最终提交参数哈希完全一致：`7df25a2e776a445c34a5411f555a60ce6c91f86858eeab676f5b7629907bea33`。观测形状均为 `value=object`、`value.protocol_ok=boolean`、两个证据/原因字段为数组、权限声明为布尔，未知字段数均为 0。

Qwen 与 v3.3 的对比很明显：模型请求从 6 降为 2，输出 token 从 1786 降为 120，提交由 5 次观察/0 次通过/5 次拒绝，变为 1 次观察/1 次通过/0 次拒绝。这个对比支持“旧失败是接入合同问题”的判断。

## 因果边界

本轮遵循最小必要调用，只给每个模型一个协议单元。由于同时修正了 Qwen 思考控制和提交 schema，**不能进一步声称究竟是哪一个单独因素导致恢复**，也不能给两者分配因果比例。若只为定位单因素而追加 A/B，会增加付费调用但不改变当前工程决策，因此本轮没有继续。

本预检只证明统一 Agent 工具协议已经可用，不评价金融判断质量。新的 36 单元正式验收仍为 0/36，未获本合同授权，也未启动。

## 验证与安全

- 定向测试：Node 7/7、Python 3/3。
- 全量测试：`uv run python -m unittest discover -s tests -v` 为 127/127；Node 集成测试为 27/27。
- 合同 manifest 可复算；预检确定性不变量全部通过。
- 3 个 unit ID 唯一，6/6 HTTP 200，3/3 身份精确匹配，3/3 结构化提交有效。
- 0 credential pattern、0 原始参数、0 原始校验错误、0 原始供应商响应、0 真实副作用。
- 百炼响应未提供可核验成本字段，成本继续记录为 `null`。

## 哈希

- v3.4 累积合同 bundle：`720b95a1d1897bb0b77ebcc756fd7e30efc20e28cfd0ecbc83def2942e7a2edb`
- 合同 manifest 文件：`6c148ad01986f749d14683ac2d5f8b56e7ae710a68dbbcb8421f37abe65b427f`
- Harness config：`40d050e2f942234dc69318f6c5f28dfcaf6ae7fbc845f8a2872915cc2500f5ce`
- Split submission wire contract：`8e9e933f7b037a13f7331453da17a968fba60099ef7611f4e62892d251c857f1`
- 预检结果：`e45685c9e1f1c255706ccabb5efa1a10058876d00035ff5f161c530c8b46aad4`
