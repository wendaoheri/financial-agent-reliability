## Stage 3 v3.5 金融场景验收报告

日期：2026-08-12

### 结论

三个模型已在同一候选可见合同下完成基础预检，且实际模型身份 3/3 通过；这里的“同一水平线”只表示测试条件一致，不表示模型能力相同。基于用户对 36 个付费验收单元的授权，本轮已执行全部 12 case × 3 模型金融场景测试，没有扩展到 270/810，也没有选择性重跑失败单元。

新合同的结构化工具链已解决 Qwen 未提交最终答案的问题：`qwen3.8-max` 12/12 调用了结构化最终提交工具，`deepseek-v4-pro` 12/12，`glm-5.2` 6/12。36 个模型身份全部匹配，无回退、无真实副作用、无密钥泄漏。

验收门未通过。独立语义全项通过 15/36：Qwen 7/12、DeepSeek 6/12、GLM 2/12。该数字仍混合了候选能力、provider 可用性和剩余题目合同缺陷，不能直接解释为模型金融准确率。

### 直接证据

| 指标 | 总计 | Qwen | DeepSeek | GLM |
| --- | ---: | ---: | ---: | ---: |
| 预注册单元 | 36 | 12 | 12 | 12 |
| 结构化最终提交 | 30 | 12 | 12 | 6 |
| 独立语义全项通过 | 15 | 7 | 6 | 2 |
| provider/空输出失败 | 6 | 0 | 0 | 6 |

- 36 trace、36 grader、36 checkpoint 完整勾稽；身份有效 36/36；fallback 0；invalidated 0。
- 安全结果：0 secret leakage、0 unsafe/real side effect；环境终态与权限轨迹均为 36/36。
- 共发出 96 次 provider request；百炼响应不提供可核验成本，因此成本按合同记录为 `null`。
- 结构化结果中的独立检查：状态 27/36、reason code 20/36、证据充分性 32/36、计算可复现 30/36；时点、方法、权限、环境终态、敏感信息均为 36/36。

### 诊断

1. Qwen 的旧问题不是模型“不会调用工具”，而是旧版工具 schema / tool-choice / thinking 模式组合不适配。v3.5 使用百炼 OpenAI-compatible 调用、`tool_choice=auto`、非并行工具调用、模型中立的 answer/non-answer 提交工具，并对 Qwen 使用 provider adapter 的 `enable_thinking=false` 后，Qwen 12/12 完成最终工具提交。这是直接证据。
2. GLM 的 6 个失败均为 `provider_unavailable` + `empty_output`，不是结构化 schema 校验拒绝。其中 3 个首请求即无 HTTP 响应，另外 3 个在 1–2 次成功工具轮后失去 provider 响应；有 1 个还消耗约 4104 输出 token 后未提交。由于冻结合同禁止后验重跑，本轮保留原结果。现有脱敏轨迹未保存 provider 原始错误正文，因此“限流、服务波动或模型端生成耗尽”的精确占比不能从当前证据唯一确定。
3. 题目合同仍有至少一处确定缺陷：`case-public-fkw-12-normal-v3` 的候选 schema 允许任意合法小数且未声明舍入规则，三个模型都提交源数据全精度 `36.1479343675069`，但 oracle 要求六位小数 `36.147934`，导致三者同时被判“计算不可复现”。这是考试合同问题，不应计作模型能力失败。
4. 多个异常题在三模型间共同出现 reason-code 精确集合失败。虽然 v3.5 公布了词表，但没有为每个 code 发布充分的触发语义和最小/可选集合规则；因此这些失败仍需合同复核，不能全部归因于模型。
5. 排除上述明确或高概率合同/基础设施因素后，仍存在真实的候选差异，例如状态选择错误和个别证据不足；这些应由金融评测负责人按冻结轨迹复核，不能为追求 36/36 而修改 oracle。

### 合同与证据

- 执行合同版本：3.5.0
- 合同 bundle SHA-256：`d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8`
- 计划 SHA-256：`acf720b9267b2b27e2c6b082dab47150baed929093985e59d79ac0ec60e10057`
- harness config SHA-256：`845f0f935882b8359ff5a0ab8c4181dd9090c484272937588ec6894ba15716e4`
- 冻结证据 bundle SHA-256：`9f0123159f3e7018bfee423dd11d5bd902649ee0c0cfe01f3b921980acfa5532`
- 旧 v1.1 `0/36 oracle match` 与 v3.3 协议失败均保持原样，未后验重判。

### 验证命令

```text
node --test tests/integration/financial_acceptance_v3_5.test.mjs
uv run python -m unittest tests.test_financial_acceptance_v3_5 -v
uv run python -m unittest discover -s tests -v
node --test tests/integration/*.test.mjs
uv run python -m harness.acceptance_v3_5 verify-contracts
uv run python -m harness.acceptance_v3_5 grade --plan contracts/stage3_acceptance_plan.v3.5.json --output-dir runs/stage3/acceptance-20260812-v3.5
uv run python -m harness.acceptance_v3_5 freeze-evidence --plan contracts/stage3_acceptance_plan.v3.5.json --output-dir runs/stage3/acceptance-20260812-v3.5 --destination evidence/stage3/acceptance-20260812-v3.5
```

测试结果：focused Node 4/4、focused Python 3/3、全量 Python 130/130、全量 Node 31/31；合同与冻结证据逐文件哈希复算通过。
