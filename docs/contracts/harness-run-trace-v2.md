## Harness 与 run_trace v2 身份及百炼工具协议修订

状态：在候选 smoke 前冻结。v1 保留为历史失败证据，不得作为新的执行配置。

### 直接证据

- 百炼模型目录列出 `qwen3.8-max`、`glm-5.2`、`deepseek-v4-pro`，不列出旧 ID `qwen-3.8-max`。
- 三个正确 ID 的最小聊天、完整冻结参数（无工具）和最小单工具 `auto` 请求均返回逐字一致的响应 model ID。
- 四个原始工具 JSON Schema、完整冻结参数及 `tool_choice: auto` 组合在三个模型上均被接受且产生工具调用。
- 同一组工具使用字符串 `tool_choice: required` 时，qwen/deepseek 返回 HTTP 400，glm 接受请求但未产生工具调用；对 qwen/deepseek 使用指定函数对象也返回 HTTP 400。

### 修订结论

工具 JSON Schema 本身兼容百炼的 OpenAI-compatible function wire format，不需要改写。v2 只做两项可审计修订：候选 ID 改为 `qwen3.8-max`；预检工具选择固定为 `auto`，并通过明确的 `read_frozen_case/PREFLIGHT` 指令及实际 tool-call 观测验证能力。不得把 HTTP 接受等同于语义执行；预检仍要求响应身份精确匹配并真实出现工具调用。

### 适用限制

这是百炼当前 endpoint 和三个候选 ID 的兼容证据，不推断其他 provider、模型版本或未来接口行为。旧 v1 run ID、manifest 和失败 bundle 保持不变；v2 配置进入新的 v4 run manifest，全部 run ID 必须重算。
