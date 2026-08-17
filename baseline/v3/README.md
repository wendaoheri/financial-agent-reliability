# 基线 v3（最小可用审计整改版）

PER-328 按 C-323-16 发布的新冻结世代。基线 v2 因 PER-330 独立审计失败而仅作
历史失败证据，v3 不回写 v2，也不复用 v2 中 `redistributable=false` 的原始行情。

## 工件

- `cases/`：4 族 × 3 变体共 12 张案例卡；2 族使用 SEC EDGAR 公有领域事实，
  2 族使用项目自编 CC0 合成 fixture。
- `snapshots/`：4 个主快照和 4 个缺证 Silver 派生快照。
- `contracts/`：case/snapshot schema v3、run_trace schema v5、理由码 v3、
  grader 冻结捆扎 v3。
- `grader/grader_policy.v3.json`：八项 critical invariant 与 grader 的
  `SUPPORTED_INVARIANTS` 完全一致。
- `build/capture_manifest.v3.json`：逐源许可、sha256 与再分发门；所有条目
  `redistributable=true`。
- `baseline_manifest.frozen.v3.json`：逐件 sha256 与单一 bundle hash 入口。

## 审计整改

- mapping 按严格键集合递归相等，附加金融字段必定失败；
- submission 对象直接进入密钥扫描，secret-shaped key 不会因 JSON 序列化丢失；
- policy 声明的八项 invariant 均有执行分支，并由回归测试逐项覆盖；
- Longbridge 原始响应不进入 v3；合成 fixture 明示为说明性案例，不是真实市场事实。

## 复现

```bash
uv run python baseline/v3/build/build_baseline_v3.py
uv run python baseline/v3/validate_baseline_v3.py validate-bundle baseline/v3
uv run python baseline/v3/validate_baseline_v3.py verify-manifest baseline/v3
uv run python -m unittest tests.test_baseline_v3 tests.test_baseline_v3_grader_regressions -v
```

冻结后不改不删；修订只增版本。不得用候选输出或演示结果反向调权。
