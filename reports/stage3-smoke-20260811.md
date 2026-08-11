## Stage 3 顺序必要性 smoke 结果

访问日期：2026-08-11；市场/接口：阿里云百炼 OpenAI Chat Completions 兼容接口；适用范围：冻结的 12 个合成/公开数据任务、三个模型各一次，不代表完整 810-run 排名或总体失败率。

### 直接证据

- 精确模型 ID `qwen3.8-max`、`glm-5.2`、`deepseek-v4-pro` 各完成 12 个 run；36/36 provider 执行成功，0 failed、0 invalidated、0 L4。
- 三模型共使用冻结的四工具 OpenAI function schema 与 `tool_choice=auto`，累计 103 次 provider 请求、95 次工具调用，全部未触发 API/tool schema hard stop。未发生回退、敏感信息落盘、真实交易或生产写入。
- 严格 grader 结果为 0/36 oracle match、0/36 end-to-end complete。`qwen3.8-max` 的结构化输出有效 12/12，`deepseek-v4-pro` 为 1/12，`glm-5.2` 为 0/12。
- 六个需要非空 evidence record 的任务中，证据集合完整数分别为：`qwen3.8-max` 4/6、`deepseek-v4-pro` 1/6、`glm-5.2` 0/6。`qwen3.8-max` 的期望状态匹配 11/12，但精确 value/reason code 仍未命中 oracle。
- 失败不变量计数：计算/单位可复现 36、实质主张证据支持 36、方法适用 24、权限边界输出 23、时点/证据完整 13、必要弃权或升级 15。权限边界输出失败主要来自结构化输出无效；工具 trace 未显示真实副作用。
- provider 不返回可核验价格，成本为 `null`；观测 usage 为 input 129,071、output 59,643、provider total 282,538 tokens。

### 版本化更正

首版在三个 run 后产生假 identity hard stop。原因是 `@mariozechner/pi-ai` 0.73.1 仅在响应模型与请求模型不同时写入 `AssistantMessage.responseModel`，字段缺省实际表示身份未变化。v1 bundle 保留不变；v1.1 更正三份身份字段与派生状态，保留候选输出哈希且新增 provider 请求为 0，然后只运行剩余 33 项。候选 run 总数仍为 36。

### 基于证据的工程判断

当前没有证据支持按百炼专有格式重写 tool schema 或 `tool_choice`；兼容链路已经跨三模型和多轮工具调用工作。主要失效点是模型最终输出契约、证据引用、精确值/原因码对齐，而不是 API 接口拒绝。

冻结计划机械地指出：若要估计 repeat stability，需要 270-run 重复试验；这不是自动授权。鉴于本轮严格质量门为 0/36，建议先离线诊断结构化输出和 oracle 对齐，修订时另起版本并重新预注册，再决定是否值得授权 270-run。禁止直接启动 810-run。

### 不确定性与限制

每个 cell 只有一次运行，不能估计随机稳定性；12 个任务不是总体随机样本；严格的 exact-match grader 可能同时捕获真实语义错误和序列化/原因码格式差异。由于原始 provider 响应按安全策略不落盘，结构化输出无效项只能从生命周期、工具 trace、哈希和 grader 结果定位，不能事后恢复原始文本。
