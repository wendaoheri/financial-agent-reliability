## Stage 3 顺序必要性验证

本轮仅执行经 issue 评论授权的 36-run smoke，不执行 810-run 全量矩阵。运行单元从冻结的 `src/financial_agent_reliability/harness/run_manifest.v4.json` 中确定性选择，覆盖 12 个任务、两个 track、Gold/Silver 两个质量层级和三类变体；每个任务仅运行三个候选模型各一次。

候选模型 ID 固定为 `qwen3.8-max`、`glm-5.2`、`deepseek-v4-pro`。运行使用锁定的 `@mariozechner/pi-agent-core` 0.73.1、冻结 system prompt、四个 OpenAI function 工具 schema 和 `tool_choice=auto`。工具只读取冻结案例与证据、执行确定性计算或访问 run-local 模拟账本；不允许真实交易或生产系统写入。

每个 run 最多发起 8 次 provider 请求、24 次工具调用，墙钟上限 120 秒；SDK 重试关闭，以便精确核对付费请求数。每次请求固定 `temperature=0`、`top_p=1`、`max_tokens=4096`、冻结 seed 和流式输出。原始 provider 响应、密钥及原始 endpoint 均不落盘，provider 未返回可核验价格时成本保持 `null`。

遇到模型身份不一致、敏感信息泄漏、真实副作用、沙箱逃逸或系统性工具/API 不兼容时，在完成当前三模型 block 后停止。普通候选失败不触发提前终止。36 次全部完成且未触发 hard stop，只能说明可以申请 270-run 重复稳定性试验；不能据此形成完整排名、总体失败率或已完成 810-run 的结论。任何扩量都需要新的明确授权。

首版 smoke 暴露了 harness 自身的身份解释错误：`pi-ai` 0.73.1 仅在流式响应模型与 `model.id` 不同时设置 `AssistantMessage.responseModel`，因此字段缺省代表模型身份未变化。v1 错把缺省解释成身份未知，在首个三模型组后触发了假 hard stop。v1 输出与 bundle 保留不变；v1.1 用版本化计划更正这三个结果的身份字段，保留候选输出哈希且不新增 provider 请求，然后仅执行剩余 33 个 run。任务选择、grader 阈值与 36-run 总上限均不改变。

可复现命令：

```bash
uv run python -m financial_agent_reliability.harness.cli build-smoke-plan --output contracts/stage3_smoke_plan.v2.json
uv run python -m financial_agent_reliability.harness.cli smoke --plan contracts/stage3_smoke_plan.v2.json --correct-from-v1 runs/stage3/smoke-20260811-v1 --output-dir runs/stage3/smoke-20260811-v2 --freeze-destination runs/stage3/frozen-smoke-evidence-20260811-v2
```
