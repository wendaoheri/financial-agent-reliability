# 轻量 Runner MVP（v0.1）

本路径用于区分基础模型差异和 Agent 工程差异，不延续重型基线的逐文件冻结治理作为
日常主执行路径。仓库只保留现行冻结的 `baseline/v2`；失败的 v3–v6 世代及其验证、
测试和迁移代码已从工作树清理，仍可通过 Git tag `legacy-heavy-governance-v6`
（提交 `7d36f9e`）回溯。

## 版本和双轴

一次候选由 `model` 与 `agent` 两个独立字段定义，`candidate.id` 只负责稳定引用。
实验版本由以下证据共同确定：

- Git commit（自动写入每条 trace）；
- Python/Node 锁文件；
- 候选 `config` 的规范化 SHA-256；
- 任务集与候选清单文件 SHA-256；
- trace schema 版本（当前 `0.2.0`；读取器继续兼容 `0.1.0`）。

任务集遵循 dev → pilot → eval 生命周期；任务字段、评分硬门、Oracle 和首批 4-slice
合成 smoke 见 `docs/task-contract-v0.1.md`。v0.1 未引入真实金融数据、外部账户或
网络调用。

PER-390 在 v0.1 离线基线上追加了受控的 `bailian-live` plain-agent 路径和 trace
v0.3；旧 trace v0.1/v0.2 继续可读。它只用于项目所有者已授权的四模型 token-plan
MVP，不把 dev 任务提升为 pilot/eval，也不开放真实工具或交易能力。

## 单命令工作流

```bash
uv sync
uv run bench validate \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json
uv run bench run \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json \
  --output runs/bench/mock-smoke.jsonl \
  --run-id mock-smoke
uv run bench compare runs/bench/mock-smoke.jsonl \
  --output runs/bench/mock-smoke-report.json
```

默认示例清单提供 2 个 mock model × 2 个 mock agent 的完整笛卡尔矩阵。候选行只声明
`model`、`agent`、`adapter` 和 adapter 自有 `config`；Runner 不读取任务语义来选择
候选，任务卡也不引用候选配置。可重复传入 `--slice`、`--variant`、`--candidate` 只跑
目标单元，例如：

```bash
uv run bench run --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json \
  --output runs/bench/portfolio-refusal.jsonl --run-id portfolio-refusal \
  --slice portfolio --variant execute_trade --candidate mock-small__plain-agent
```

`run` 以追加方式写 JSONL，每条记录包含输入、工具调用、输出、错误、延迟、token/
成本估计、Git commit/dirty 状态、任务集/候选/锁文件哈希和完整候选配置。`compare`
只读原始 trace；报告写入独立文件，并输出 overall、slice、variant 三层结果及 model、
agent、candidate 三种轴向视图；成本与延迟位于 `operational_metrics`，不进入质量分。
总体、slice、variant 同时报告同任务成对 delta、95% 小样本区间与
`non_identifiable` 状态。测试会在 compare 前后重算原始 trace SHA-256。

候选只接收不含 Gold、Oracle、证据答案和安全判定的 `CandidateRequest`；Gold 与策略
留在独立 grader。plain-agent 不调用工具，tool-agent 通过 Runner 持有的离线只读工具
边界执行，工具响应和审计记录不能由候选伪造。evidence 只由成功只读调用的 fixture
响应推导，safety 只由策略与工具审计记录推导，不接受 adapter 自报。

mock adapter 支持 `wrong_answer`、`failure`、`timeout`、`tool_error`、
`missing_evidence`、`forbidden_action` 故障注入。四类发布门诊断配置见
`examples/bench/negative-control-candidates.json`。失败 trace 照常落盘并带失败签名；存在任一失败签名时
`bench run` 返回 1，输入/契约错误返回 2。缺证会保留结构化低分，但不伪装
成执行异常。此适配器不模拟 provider 协议、真实 token 计费或网络尾延迟。

`validate` 对正式任务卡执行 JSON Schema、fixture 元数据与引用闭包、成对变体及
确定性 Gold/Oracle 重算校验。为方便从 Runner MVP 迁移，加载器暂时仍接受旧的
`task_id` / `input` 简版行；新任务不得再使用该兼容格式。

## 百炼 Token Plan 四模型 MVP（PER-390）

密钥只通过环境变量注入，不得写入候选文件、命令参数、trace 或评论：

```bash
export BENCH_BAILIAN_API_KEY='<安全注入，勿落盘>'
uv run bench validate \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/bailian-token-plan-candidates.v0.1.json
uv run bench preflight \
  --candidates examples/bench/bailian-token-plan-candidates.v0.1.json \
  --output runs/bench/per390-preflight.json
uv run bench run \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/bailian-token-plan-candidates.v0.1.json \
  --preflight runs/bench/per390-preflight.json \
  --output runs/bench/per390-traces.jsonl \
  --run-id per390-bailian-token-plan
uv run bench compare runs/bench/per390-traces.jsonl \
  --output runs/bench/per390-aggregate.json
```

本配置使用 Token Plan 华北 2（北京）OpenAI 兼容端点
`https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。来源：阿里云百炼
《Token Plan 快速开始》（发布日期 2026，访问日期 2026-08-19，适用范围为 Token Plan
个人版/团队版的中国区 OpenAI 兼容接入）：
`https://help.aliyun.com/zh/model-studio/token-plan-quickstart`。Token Plan、Coding Plan 与
按量付费的 Key/端点彼此隔离，不可混用。

预检最多 4 次请求，并要求响应模型 ID 与请求 ID 逐字一致；矩阵最多 64 次请求，按
4 models × 16 variants × 1 plain-agent × 1 repeat 顺序执行。没有金额上限，但不重试，
provider 错误率超过 10% 即停止。trace 将 token-plan 的金额估算记为 `0.000000`，同时
用 `cost_basis=token_plan_unpriced` 明确表示这不是“已核验为零成本”的价格结论。
预检报告必须与候选清单哈希绑定，否则矩阵在网络请求前拒绝。

live 模型只看到任务指令、合成 variant 输入和严格 JSON 输出契约；看不到 Gold、Oracle、
评分策略或期望 reason code。当前不注册工具，故 evidence quality 按 plain-agent 基线为
0；本次只能识别 model 轴，不可用于 Agent 工程差异结论。任务仍为 dev，结果是一次
内部 MVP 诊断，不是正式排名。

## 安全门

默认路径仍只接受 `adapter: "mock"`，不读取 API key，不产生付费请求，仅执行项目
内存中的合成只读 mock 工具，不执行交易或生产写入。`bailian-live` 只允许
`plain-agent`，必须有哈希绑定且全部通过的 exact-identity preflight；密钥缺失、身份不符、
配置漂移或请求预算超限均在矩阵前拒绝。PER-390 的授权不覆盖其他 live adapter、工具
Agent、真实数据/账号、生产写入、真实交易或对外发布。
