## Phase 1 真实 pilot（PER-420）

本轮按已确认的诊断性发现设计运行 3 个模型 × A0/A1 × 8 张卡，共 48 个单元。结果仅用于验证任务和对照设计，不用于模型排名、统计显著性或跨运行稳定性声明。

### 执行结果

- 48/48 单元完成，基础设施有效；74 次模型请求。
- 输入 34,424 Token，输出 38,281 Token；按预注册单价估算 ¥1.499624。
- 引用覆盖 Gold：45/48；安全门：48/48；严格 JSON 解析：46/48。
- 动作精确命中 10/48，value 精确命中 23/48，理由码精确命中 1/48。

### 结论

本轮不能形成模型质量或 A0/A1 差异结论。任务卡的 grader 要求 `action`、`value`、`reason_codes` 精确匹配，但候选可见接口只声明了 JSON 字段类型，没有声明受控动作词表、理由码词表和 family-specific value schema。高引用/安全通过率与正确性地板效应并存，表明主要失败签名是 `GRADER_OUTPUT_CONTRACT_UNDERSPECIFIED`。

当前 trace、Gold 和聚合保留为失败 pilot 证据，不进行事后改分。生命周期退回 dev；新版本必须补全候选可见输出契约，重新通过泄漏、单因素、双 Oracle 和合成负对照门，再以新版本运行 pilot。

### 复现

```bash
uv run python -m financial_agent_reliability.experiments.phase1 --validate-only
uv run python -m financial_agent_reliability.experiments.phase1 --output runs/phase1/differential-pilot-v1
uv run python -m financial_agent_reliability.experiments.phase1_diagnosis --output runs/phase1/differential-pilot-v1
```

主要产物位于 `runs/phase1/differential-pilot-v1/`：`trace.jsonl`、`aggregate.json`、`failure_signatures.json`、`manifest.json`、`diagnosis.json`。
