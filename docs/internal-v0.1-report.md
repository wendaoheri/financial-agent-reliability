# 金融 Agent 差异化评测实验室 v0.1 内部报告

报告日期：2026-08-19（Asia/Shanghai）  
范围：PER-360 / PER-367，离线、mock、只读、零付费内部交付  
结论：**v0.1 轻量链路达到内部收口门槛；0 个 release blocker。暂不启动付费 pilot。**

本结论证明任务、Runner、真实 mock 工具调用、独立评分、trace、比较和失败诊断可以
闭环复现；它不证明任何真实模型优劣，也不授权生产工具、真实交易、外部账号、付费调用
或对外发布。

## 1. 直接产物与版本证据

| 交付 | 版本/位置 | 状态 |
| --- | --- | --- |
| Runner MVP、任务 schema 与 4-slice smoke | PR #3，merge `ae6b928` | 已合并 |
| 8 slice × 2 variants 任务集 | PR #4，merge `fd9c8c4` | 已合并 |
| model/agent 双轴矩阵与 compare | PR #5，merge `045b943` | 已合并 |
| Gold 隔离、真实 mock 工具、独立 grader、配对统计与负控 | PR #6，merge `62bb1a2d134dbb0e1aeab4fbb1ae07eeeb805d81` | 已合并 |
| 独立定向红队复核 | Multica PER-388 报告及复算脚本 | 通过，0 blocker |
| 轻量入口 | `README.md`、`docs/runner-mvp.md`、`docs/` 的 v0.1 任务契约说明 | 当前主路径 |
| legacy 回退 | Git tag `legacy-heavy-governance-v6` → `7d36f9e` | 保留可定位 |

一次运行由 Git commit、`uv.lock`、`package-lock.json`、候选配置、任务 ID/seed 和
append-only JSONL trace 共同定义。PER-388 复核所用输入哈希如下：

| 输入 | SHA-256 |
| --- | --- |
| `examples/bench/mock-tasks.jsonl` | `e224c6828785b123d920674293a3596c91b51aaa159038e69ed1215d3476bf5a` |
| `examples/bench/mock-candidates.json` | `4ece73628d76585cd2dc35a1783b01a761384254eda10a16ca85386f87108462` |
| `examples/bench/negative-control-candidates.json` | `7cdbe319db21fd8ca7a7906a1ab3e42f11125d50dbb13288abf6de94977144a8` |
| `uv.lock` | `8305c4f1516c5e08200953506289385914f35c618f4f49b8e53939b073c39729` |
| `package-lock.json` | `44476fc4a13962e5545653251c0fa2422e8ae4d66b3b3845d6e4fd90d4a28242` |

PER-387 附件是正式运行证据入口：`matrix-traces.jsonl`、`matrix-aggregate.json`、
`negative-control-traces.jsonl`、`negative-control-aggregate.json`、
`failure-signatures.json` 和 `reproduction.json`。四项核心产物的 SHA-256 分别为：

- normal trace：`76c987a1da2ecf572e491fe4b167114d0f0e4454ec22ca1b6167142b15fda22a`
- normal aggregate：`0e2124154ae0b7e387d617903ce890f29a8adc0ce7c5398a1d750d5e2a9d1bd7`
- negative-control trace：`8a2d7752f197871a4d0ab76f4d8f3cb18ba2bb2aa576bb9f974bb2fca9458abf`
- negative-control aggregate：`3908932ada87686681253d4fd29b0808ed2a0379602087fed75d86ad50f38f4e`

## 2. 实验结果与归因

正常矩阵为 64 条 trace，覆盖 8 个 slice、16 个成对 variants、2 个 mock model 和
2 个 Agent 配置。correctness 均为 4，safety 均为 1。32 个 plain-agent cell 均为
0 次工具调用；32 个 tool-agent cell 均产生 1 次 `read`、`status=ok` 的
Runner-owned 合成只读工具调用。

同 model 下的成对 Agent 对照可识别：`tool-agent - plain-agent` 的 evidence delta
为 `+2.0`、quality delta 为 `+2.0`、tool-call delta 为 `+1.0`，对应 95% 区间均
退化为同一点。mock model 之间没有执行或结果变化，因此 model 轴明确输出
`non_identifiable`，不得包装成“模型相同”或模型排名。整体 safety=100%，cell-level
Wilson 95% 区间为 `[0.943, 1.000]`。

这组差异能归因于 harness 内真实发生的 mock 工具调用和独立证据评分，不再只是候选
标签差异。候选请求 DTO 不含 `expected_output`、Gold/Oracle、required evidence 或
safety policy；evidence/safety 由候选之外的 grader 从工具审计和 evaluator policy
计算，候选伪造自报字段不会改变最终评分。

## 3. 负控与失败签名

四类负控共 64 条 trace，均产生预期差异：

| 负控 | 结果 | 失败签名 |
| --- | --- | --- |
| wrong-answer | 16/16 correctness=0 | `WRONG_ANSWER=15` |
| missing-evidence | 16/16 evidence=0 | `MISSING_EVIDENCE=16` |
| forbidden-action | 16/16 触发 safety hard gate | `SAFETY_HARD_GATE=17` |
| tool-error | 16/16 记录工具错误 | `TOOL_ERROR=16` |

计数交叉来自一个“错误答案 + 应拒绝真实交易”的 cell，按安全优先归入 safety 签名；
该 cell 的 correctness 失败仍保留，没有被硬门掩盖。正常矩阵中的 32 个
`MISSING_EVIDENCE` 是预设 plain baseline 的对照信号，不是 Runner 执行错误。

## 4. 独立复核与测试

PER-388 在 `main@62bb1a2` 上独立复算正常矩阵 64 条和负控 64 条。128/128 条 trace
的 correctness、evidence、safety、证据引用和安全违规逐条一致；两份 aggregate
重新生成后与附件逐字节一致。产物生成提交 `dea4955` 与合并提交的代码树无差异。

最终收口应复现以下命令：

```bash
uv run python -m unittest tests.test_bench_mvp -v
uv run python -m unittest discover -s tests -v
npm run test:runtime
uv run bench validate --tasks examples/bench/mock-tasks.jsonl --candidates examples/bench/mock-candidates.json
uv run bench validate --tasks examples/bench/mock-tasks.jsonl --candidates examples/bench/negative-control-candidates.json
uv run python attachments/per388/independent_recompute.py
```

PER-388 记录结果为 focused Python 17/17、全量 Python 134/134、Node runtime 6/6、
两套 validate 及独立复算全部通过。两次诊断 `bench run` 因预设失败签名返回 1，均完整
写出 64 条 trace；后续 `bench compare` 返回 0。

## 5. 已知限制与适用边界

- 8 张任务卡全部仍为 `dev`；没有 pilot/eval 证据，不得用于正式模型排名。
- Gold 隔离是受支持 adapter 的 DTO/API 边界，不是任意不可信本地代码的 OS 沙箱。
- mock 工具只证明合成只读路径、审计和 evidence 归因，不等同于生产数据工具。
- 区间按 cell 描述；确定性 mock cell 不是来自真实总体的独立随机样本。
- model 轴当前为 `non_identifiable`；只有真实候选 pilot 才可能检验模型差异。
- 旧 harness、baseline 与 validation 材料继续保留作历史证据和兼容路径，不扩建新重型
  冻结世代；回退依赖 Git tag，而不是改写当前轻量主路径。

## 6. 14 天团队观察指标

观察期从本报告进入主分支后的首个工作日开始；每个指标只基于实际 issue/PR/trace，
不新增日常审计工单。

| 指标 | 采集方式 | 14 天通过线 | 触发动作 |
| --- | --- | --- | --- |
| 轻量路径采用率 | 新实验中直接使用 `bench` 的数量 / 新实验总数 | ≥80% | 低于阈值时修正文档/CLI，不扩编 |
| 首次可运行时间 | issue 开始到首个有效 trace | 中位数 ≤1 工作日 | 超线时优先削减任务/适配复杂度 |
| 证据完整率 | 含版本、候选配置、原始 trace、aggregate、失败签名的实验占比 | 100% | 缺件不得进入 pilot 决策 |
| 归因覆盖率 | 关键差异有 paired contrast 或 `non_identifiable` 的占比 | 100% | 禁止无证据归因 |
| 安全回归 | 安全硬门、secret/no-real-transaction 测试失败数 | 0 | 任一失败立即停止 pilot |
| 返工率 | 因 schema/trace/grader 契约缺陷而重跑的实验占比 | ≤20% | 超线时先修契约，不增样本 |
| 策展负荷 | 每周新增/维护高信息量任务的人时 | ≤8 人时 | 连续两周超线才评估策展资源 |
| 平台负荷 | 每周 Runner/adapter 维护人时 | ≤8 人时 | 连续两周超线才评估平台资源 |

团队继续维持 4 人核心编制。只有策展或平台负荷连续两周超过阈值，并且积压确实阻断
pilot，而非文档或接口问题，才提交量化扩编方案。

## 7. Pilot 决策输入与当前建议

当前建议是**方案 A：先完成 14 天观察，不启动付费 pilot**。原因是所有任务仍为 dev，
model 轴尚不可识别；先确认轻量流程稳定，可避免把预算用于修复基础流程。

- 方案 A（推荐）：零费用、零外部账号；观察期后按上述指标复核，再决定是否申请 pilot。
- 方案 B（暂不执行）：在观察期通过后，申请 3 models × 2 agents × 16 variants ×
  3 repeats = 288 次调用。按 576k input + 144k output tokens 的保守估算，硬金额上限
  `$5.00`；价格和模型可用性必须在授权当天从 provider 官方来源复核。

方案 B 的启动硬门：项目所有者书面确认候选、288 次调用和 `$5.00` 上限；三个模型逐一
通过 exact-response identity preflight；任务、候选、Git/锁文件和价格快照落盘；密钥
扫描通过；只读 adapter 不注册任何真实交易或生产写入能力。

运行中达到任一条件立即停止：预计或实际费用达到 `$5.00`；任何安全硬门失败、密钥疑似
落盘、真实写入企图或模型身份不一致；provider/工具错误率超过 10%；实际 token 超过
预算的 120%；同一候选连续 3 次超时。只有三次重复方向一致、至少一个 slice/variant
出现可复现 model 或 agent 质量差异且无安全硬门失败，才考虑下一轮；否则退回 dev。

本报告不请求也不构成方案 B 的授权。观察期结束前没有待项目所有者决定的阻塞项。
