## Harness 运行说明

状态：工程实现；不是候选模型已通过的研究证据。

### 固定边界

- `package.json` / `package-lock.json` 精确锁定 `@mariozechner/pi-agent-core@0.73.1`；Python 调度与验证仍统一通过 `uv run` 执行。
- 三个可执行身份仅为 `qwen-3.8-max`、`glm-5.2`、`deepseek-v4-pro`。PER-24 预注册中的早期抽象槽位名称仅决定三个候选槽位的矩阵基数，不可作为供应商请求 ID。
- provider adapter 只从 `BENCH_BAILIAN_API_KEY`、`BENCH_BAILIAN_BASE_URL`、`BENCH_BAILIAN_MODEL_IDS` 读取配置。配置对象隐藏密钥，持久化数据统一递归脱敏。
- matrix builder 强制读取 `catalog/public/preregistration_variant_protocol.v2.json`，校验其冻结状态、`2.0.0` 版本、三个 canonical execution id、Silver/主榜边界及 retired legacy crosswalk。协议缺失、旧版或任何可执行 `single_factor_control` 映射都会在生成清单前失败。
- Stage 3 输入只允许 public v2 contract bundle `e3067d7a7cdb66694052e1a959a80120f7ccfbfa43b0525192b40acee942d62c` 与 clean-room synthetic v2 Stage 3 bundle `62511d582702c8019201c16f18e22a36bb0b8632d8c2ac39b3c9b8a8e49118e8`。builder 会复算两个 manifest 的全部文件承诺、synthetic Stage 3 collection，并锁定 public collection session、variant protocol、两个 catalog、synthetic policy/source spec 的文件 hash。
- revoked public v1、隔离的 Longbridge v1、非 v2 路径、文件缺失或任一输入 hash 漂移都会在生成清单前失败。所有选择与文件 SHA-256 均写入 manifest 并进入 `immutable_bundle_sha256`；任何变化都会重建全部 run ID。
- 本阶段仅允许注入本地 fixture transport 的 dry-run。`full_paid_matrix_runs_allowed=false`，不得启动 810 行付费矩阵。

### 本地复现

```bash
uv run python -m unittest tests.integration.test_harness_runtime -v
npm run test:runtime
uv run python -m financial_agent_reliability.harness.cli build-manifest --output src/financial_agent_reliability/harness/run_manifest.v3.json
uv run python -m unittest discover -s tests -v
uv run python contracts/run_trace_validator.py verify-freeze
uv run python contracts/run_trace_validator.py validate-fixtures
```

`src/financial_agent_reliability/harness/run_manifest.v1.json` 因 legacy `single_factor_control` 消费路径作废；`src/financial_agent_reliability/harness/run_manifest.v2.json` 因早于 public v2 与 synthetic workflow v2 作废。两者仅保留为审计证据，不得进入 Stage 3。`run_manifest.v3.json` 固定为 30 案例族、90 任务（46 Gold / 44 Silver）、两轨 50/50、3 canonical execution variants、3 模型、3 重复，共 810 行；三个变体各 270 行，第三类只能是 `missing_or_anomalous_diagnostic`。随机区组种子为 `20260811`；每个 run ID 由完整 run identity、Harness 配置哈希与包含两个 v2 输入 bundle 的 immutable bundle 哈希确定。

### 线上预检门

后续获明确授权并配置 secret 后，应逐模型调用 `BailianAdapter.preflight`。响应模型 ID 不完全相等、检测到回退、请求参数未被接受或工具调用能力不可验证时，该模型块必须标记 invalidated/blocked；不得换模型补跑。超时、限流和暂时不可用仅可使用冻结的统一重试预算。

### 适用范围与限制

直接证据：本地 fixture 测试覆盖身份不匹配、脱敏、恢复、grader 优先级、Gold/Silver 隔离、盲态 payload、模拟账本权限/幂等/超时/重复回包。

工程推论：相同配置与 bundle 可稳定生成相同矩阵和 run ID；这不证明供应商线上会接受 seed、参数或工具调用，也不证明任何候选模型可靠。

未验证：真实百炼 endpoint、候选身份、线上参数语义、流式协议兼容、token 成本和供应商故障行为。本阶段按验收要求不执行这些付费检查。
补充:文中涉及的 `fareli-harness build-manifest` / `build-smoke-plan` / `smoke` 子命令与 `fareli-report verify-freeze` 已随基线 v1 退役(PER-323 清理清单 M2),文中相应本地复现步骤不再适用;现行手动执行路径以 `docs/manual-execution-guide.md` 为准。


---

**PER-323 历史说明(2026-08-17,Stage 2 追加)**:本文引用的冻结目录路径(`contracts/`、`cases/`、`catalog/`、`snapshots/`、`preregistration/`、`evidence/`、`audit/`、`reports/` 及 gitignore 的 `runs/` 等基线 v1 目录)已按 PER-323 冻结清理清单 v1 删除;原文内容可按 `docs/per323-stage2-deletion-record.md` 所载各目录回滚索引 SHA 从 git 历史找回(`runs/` 的删除前归档见该记录 §2)。本文原文与结论作为历史记录保留,未改写。