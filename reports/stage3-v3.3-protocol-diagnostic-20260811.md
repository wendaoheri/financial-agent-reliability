## 结论

v3.3 诊断证明：`qwen3.8-max` 并非没有调用 `submit_candidate_result`。在 `auto_strict` 预检中，它先成功读取协议题，随后实际发出 5 次提交工具调用；5 次都在工具实现之前因 `/value` 字段类型/形状不符合严格动态 schema 而被拒绝。

因此，旧结论“Qwen 没有提交”被本版本纠正。当前直接失败点是 Qwen 的严格工具参数生成兼容性，不是金融语义判断，也不是没有自主选择提交工具。

## 冻结与验证

- v3.3 合同 bundle：`c0030bfafca48bac9790f73deea5c856ce3e152e13a0a9a0c2d4fac7da00b949`
- v3.3 合同 manifest 文件：`6464b4737de3e15a743760c48d86ec2b5ca19b6811e4156ec261a3bf93d11e09`
- Harness config：`20103db6b4d534b19f19b94f098c75336cbe9e8fcc8199aa29bbc86a0dbccd46`
- Run-trace schema：`66f32f4b65abf99d249eceb3aabff4693c56a0034ca98d483c86b4359b44cace`
- Python 全量测试：124/124 通过
- Node 集成测试：20/20 通过
- 合同复核：有效，0 hash drift

合同在付费预检前冻结。v3.2 失败产物和旧 36-run 结果均未改写、未后验重判。

## 执行规模

按冻结的顺序必要性策略执行：

1. A：`auto_strict`，三模型共用纯协议题、两项工具、严格动态 schema、相同预算与修复策略。
2. A 仅 2/3，因此执行 B：`forced_strict`，除按阶段强制工具选择外，其余合同不变。

实际执行 6 个模型单元、16 个 provider requests；没有启动新的 36 单元验收。供应商响应没有可核验成本字段，成本继续记录为 `null`。

## 直接证据

| 变体 | 模型 | 结果 | 关键轨迹 |
|---|---|---:|---|
| auto_strict | qwen3.8-max | blocked | 读取 1 次成功；观察到提交 5 次；5 次均在执行前因 `/value` `field_type` 被拒；固定修复轮已真实使用 2 个保留请求 |
| auto_strict | glm-5.2 | passed | 读取 1 次、提交 1 次，均通过 schema 并执行 |
| auto_strict | deepseek-v4-pro | passed | 读取 1 次、提交 1 次，均通过 schema 并执行 |
| forced_strict | qwen3.8-max | blocked | 未取得有效工具事件或用量；本产物没有可安全确认的响应状态 |
| forced_strict | glm-5.2 | passed | 强制读取和强制提交均成功 |
| forced_strict | deepseek-v4-pro | blocked | 未取得有效工具事件或用量；本产物没有可安全确认的响应状态 |

A 的 Qwen 轨迹中，5 次提交参数形成两个脱敏 hash，其中一个重复 4 次，说明不是偶然漏调，而是稳定地产生了无法满足 `/value` union 的参数形状。原始参数和原始校验错误按冻结隐私合同不落盘，因此不能进一步声称具体生成了哪一种错误值。

B 对 Qwen/DeepSeek 的现象与此前“指定函数 tool-choice 被供应商拒绝”的诊断一致，但由于 v3.3 没有持久化可确认的 HTTP 状态，这一点只保留为推论，不作为新的直接证据。

## 原因判断

- **直接证据：** Qwen 会自主选择并调用提交工具；失败发生在 `/value` 的 schema 校验阶段。
- **基于证据的推论：** Qwen 在当前百炼 OpenAI-compatible 工具通道下，对 `anyOf(逐题对象, null)` 这种严格嵌套参数的生成兼容性弱于 GLM/DeepSeek。
- **不能推出：** Qwen 金融推理能力失败。该预检没有金融题，也没有进入正式 12 case 验收。

## 安全与下一门

产物扫描为 0 secret value、0 credential pattern、0 原始参数、0 原始校验错误、0 原始供应商响应；没有真实交易或其他副作用。

v3.3 的一次中立修订及 6 单元上限已用完，当前应停止继续付费调试。下一步需要负责人选择：

1. 将 Qwen 记为“严格结构化工具协议能力失败”，本轮三模型验收继续 blocked；或
2. 若业务必须支持 Qwen，另行批准新的全模型统一 wire contract，把复杂 `value` 对象改为更简单的模型中立传输形式，再由 harness 在工具执行后做确定性结构校验。该方案必须发布新版本，不能改写 v3.3，也不能直接启动 36 单元。
