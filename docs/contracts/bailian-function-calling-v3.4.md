## 百炼 Function Calling 适配规则 v3.4

状态：冻结。访问日期：2026-08-12。适用于本项目通过百炼 OpenAI-compatible Chat Completions 接口调用 `qwen3.8-max`、`glm-5.2`、`deepseek-v4-pro` 的 Stage 3 协议预检；不能外推到其他模型、其他端点或未来接口版本。

## 直接依据

- 百炼的 Qwen OpenAI-compatible Chat API 文档说明，`qwen3.8-max` 默认开启思考；关闭思考需要显式使用 `enable_thinking=false`，也可用等价的 `reasoning_effort=none`。本项目采用前者，避免只在本地 SDK 对象中标记 `reasoning=false`、却没有控制供应商实际行为。
- 同一文档说明，思考模式的多轮请求需要保留历史 `reasoning_content`。v3.4 显式关闭 Qwen 思考，因此预期不会产生需要回传的思考历史；如果供应商仍返回该字段，运行不得静默丢弃后继续冒充受控非思考模式。
- 百炼 Function Calling 文档说明，思考模式下不支持强制指定函数。因此 v3.4 只允许 `tool_choice=auto`，删除 v3.3 的 forced-tool 诊断。
- 百炼文档说明，复杂数组或对象工具参数使用 `tool_stream=false` 时完整输出参数，准确性更高。v3.4 对三个候选模型都显式固定为 `false`，不依赖默认值。

来源：

- [Qwen OpenAI-compatible Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [Qwen Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)

## 冻结请求规则

- 模型 ID 必须精确为 `qwen3.8-max`、`glm-5.2`、`deepseek-v4-pro`，响应身份也必须精确匹配；禁止回退或别名冒充。
- 三模型共享同一 prompt、候选可见工具、资源预算、重试和修复策略。
- 三模型共同固定 `tool_choice=auto`、`tool_stream=false`、`parallel_tool_calls=false`。
- 只对 `qwen3.8-max` 发送百炼 Qwen 扩展参数 `enable_thinking=false`。GLM、DeepSeek 不发送 Qwen 专属参数；这是 provider adapter 的协议差异，不是候选可见特调。
- 工具定义使用 OpenAI function 形式和有效 JSON Schema。项目不把 HTTP 200 或供应商接受 schema 等同于参数已经满足本地业务合同。
- 不发送 `strict`，因为当前固定 runtime 没有证明百炼对三模型提供一致的服务端 strict 行为。参数解析后由 harness 做确定性校验。

## 提交协议修订

v3.3 的单工具参数把 `value` 暴露为 `anyOf(逐题答案对象, null)`。v3.4 改为两个模型中立函数：

- `submit_candidate_answer`：状态隐含为 `answer`，`value` 必须匹配逐题公开的对象 schema。
- `submit_candidate_non_answer`：只允许 `abstain`、`escalate`、`reject_action`，没有 `value` 字段；harness 在工具解析后确定性补为 `value=null`。

这一变化只简化传输层，不改变候选输出的语义合同、grader 或 oracle。旧 v3.3 合同与结果保持冻结，不后验改判。

## 证据边界

上述接口行为属于官方文档直接依据；“联合类型会降低 Qwen 参数遵循稳定性”仍只是基于 v3.3 轨迹的推论。v3.4 的三模型协议预检用于区分适配问题与模型结构化参数能力问题，不评价金融推理能力，也不授权 36 单元正式验收。
