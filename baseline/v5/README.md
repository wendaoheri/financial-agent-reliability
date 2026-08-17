# 基线 v5（第三轮审计 frozen-input 绑定版）

基线 v5 是 PER-328 的追加式冻结世代。它保留 v4 的 provider/alias、配置
path/SHA、preflight freeze、claim-label、许可、双 oracle、Gold/Silver 与密钥扫描
硬门，并以 trace v7 新增 `frozen_input_path` 和显式 frozen-input registry：
`(case_id, variant_id) → bundle-relative path → sha256 → immutable bundle artifact`。
v2/v3/v4 与既有 Stage 4 证据不改不删，只作为历史失败证据。

- `build/`：可再分发捕获、许可清单与确定性生成器。
- `cases/`、`snapshots/`：4 家族 × 3 变体及 8 个冻结快照。
- `contracts/frozen_input_registry.frozen.v5.json`：12 个 case/variant 的唯一输入注册。
- `contracts/run_trace.schema.v7.json`：完整 trace v7 schema。
- `validate_baseline_v5.py`：bundle、registry、manifest 与 trace v7 校验入口。

```bash
uv run python baseline/v5/validate_baseline_v5.py validate-bundle baseline/v5
uv run python baseline/v5/validate_baseline_v5.py verify-manifest baseline/v5
uv run python -m unittest tests.test_baseline_v5 tests.test_per327_third_audit_regressions -v
```

本基线不运行付费模型、不访问账户、不下单。SEC EDGAR 捕获为公开领域材料；行情
fixture 为项目自制合成数据，只能作为说明性案例。
