## Stage 3 离线诊断

本诊断只读取已冻结的 36-run 证据，没有发起 provider 请求。来源为 plan hash `570bf615d8d96ffdcf6067a292ea906fd98620934c7f42654b39c355aa0c4a12`、bundle hash `f35874cee212c191c9c2f48b9bd470e8c296bd70c2bcc03328a1e92df4e7331f`。36 份 trace、36 份 grader、36 份 checkpoint 和 bundle 的 121 个 artifact 均复算一致。

### 结论

`0/36 oracle match` 是冻结 exact-output 合同的真实结果，但不能等价解释为“36 次金融语义全部错误”。主要原因是模型输出遵循问题与测量合同缺陷同时存在：

- `qwen3.8-max` 12/12 可解析，状态精确匹配 11/12，但 value 精确匹配仅 4/12、reason codes 精确匹配 0/12。它常返回语义相关的标量和解释性原因，而隐藏 oracle 要求未向模型声明的对象形状及精确原因码集合。
- `glm-5.2` 0/12、`deepseek-v4-pro` 1/12 通过严格结构解析，说明两者确有输出契约遵循问题；但无效最终文本按安全策略被丢弃，只保存哈希，因此无法离线断言究竟是混入说明文字、额外字段、类型错误还是其他语法问题。
- 三模型的 provider/tool 循环本身工作正常。执行 trace 中只有 2 次可恢复工具错误，模拟账本 6 次调用全部为 `preview`，没有 `buy`/`sell`，没有真实副作用。

### 测量合同缺陷

1. Prompt 只公开六个顶层字段，没有公开每案例 `value` schema，也没有 reason-code 词表；grader 却对隐藏 oracle 的 value 和 reason-code 集合做 canonical exact match。该条件会把语义相近但序列化不同的结果确定性判错。
2. `evidence_supports_material_claims` 和 `calculation_reproducible_and_units_correct` 直接复用 `oracle_match`，`method_applicable_to_scenario` 直接复用 `status_match`。这些不是独立 grader，因而 0/36 和不变量失败数存在结构化相关放大。
3. Evidence grader 要求输出全部注册 record IDs，但相关案例只声明 `minimum_evidence_count=1`。例如目标年份任务即使读取三年记录并引用关键年份，也可能被判 evidence invalid。
4. 权限不变量把模型输出中的自声明布尔值与真实执行安全混为一体。23 个“权限失败”主要来自结构化输出无效，不能解释成 23 次越权；实际工具轨迹为 0 次禁止写入。
5. 无效输出在 trace 中被默认写成 `action="abstain"`，会把 parse failure 与主动弃权混淆；应以 grader 的 `actual_status=null` 为准。
6. `calculate` 的 JSON Schema 允许任意 `inputs` 对象，运行时却要求 `inputs.values` 为 decimal-string 数组。GLM 使用 schema 合法的 `inputs.value` 后发生工具错误，说明 schema 与运行实现不一致。
7. 部分可见输入含 `force_abstain_reason`，实质泄露诊断 reason code，与“oracle removed”的表述不完全一致。

### 仍可采信与不可采信

可采信的直接证据是：三模型身份/API/tool-choice 兼容；冻结严格输出合同 0/36；Qwen 的顶层格式遵循明显优于另外两模型；没有模型回退、真实交易或禁止账本写入。

不可采信的扩展结论是：36 次都在金融语义上错误、23 次发生越权、L2/L3 等同真实损失，或 GLM/DeepSeek 的具体 parse 根因已经确定。L2/L3 当前只是“任一门失败后按案例风险级别映射”的派生标签。

### 下一步

暂不启动 270/810。应发布新版本并在看到新候选结果前冻结：每案例 candidate-output JSON Schema、reason-code 词表与空值规则；相互独立的证据/计算/方法/权限 grader；与实现一致的工具 schema；不保存原始响应但能区分 JSON 语法、额外字段、类型和截断的脱敏 parse diagnostics；消除 `force_abstain_reason` 等标签泄漏。先用合成正反 fixture 验证测量合同，再单独申请小规模付费重跑。

旧结果不得按后验宽松规则改判通过，只能作为 v1.1 exact-contract 结果和新版本设计证据保留。
