# PER-420 八维评测资产

这组资产用于固化评测设计与零网络验收，不是第二套运行框架，也不产出模型排名。
唯一用户入口仍是 `bench`。

## 固化内容

`tasks/per420/` 包含：

- `task-contract.v2.json`：D1–D8 八个家族、16 张 normal/challenge 任务卡及 Gold；
- `fixtures.v2.json`：16 份合成只读 fixture，每对任务只改变一个登记因素；
- `scoring-contract.v1.json`：评分、三分类、聚合分母与无效输出脱敏规则；
- `pilot-candidates.v2.json`：PER-420 当时登记的三模型候选坐标；
- `harness-contract.v2.json`：当时登记的 48 单元 pilot 约束。

后两项只保留为评测资产的来源证明，不是当前可执行配置。当前树中不存在专用 live
Runner；任何付费调用都必须重新设计、重新授权，并接入现有 `bench` live 边界。

候选输出统一经过 `financial_agent_reliability.contracts.validate_candidate_output`。Gold
同时由两个独立 Oracle 重算。任务结构、八维覆盖、单因素配对、引用完整性、候选协议和
密钥扫描任一失败，资产校验即失败。

## 零网络验证与回放

```bash
uv run bench eval-validate --pack tasks/per420
uv run bench eval-run --pack tasks/per420 \
  --output-dir runs/per420-offline
uv run bench eval-replay --pack tasks/per420 \
  --bundle runs/per420-offline
```

运行固定生成三类控制：`candidate_success`、`candidate_failure`、`invalid_run`。协议无效
输出只保存分类、长度和 SHA-256，不保存原始内容；`invalid_run` 明确从 CSR 分母中排除。
重评分命令先核验 manifest 中的资产哈希，再用同一 Eval Pack 重新执行中央协议、评分和
三分类判定。框架源码、Git 状态、依赖锁和工程环境既不写入 trace，也不进入
`eval_pack_id`；`runner_protocol_version` 只表示实验协议语义兼容性。
产物为：

- `validation.json`：任务、fixture、双 Oracle、协议、引用与密钥门；
- `trace.jsonl`：48 条零网络合成控制 trace；
- `aggregate.json`：总体、维度和变体聚合；
- `failure_signatures.json`：仅候选失败的签名；
- `manifest.json`：资产坐标及全部产物哈希。

这些产物只证明评测链路能够识别并重评分三类结果，不能解释为真实模型或 Agent 的能力
结论。
