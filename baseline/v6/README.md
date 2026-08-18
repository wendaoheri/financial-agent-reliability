# 基线 v6（第四轮审计外部 registry commitment 版）

基线 v6 是 PER-328 的追加式冻结世代。它保留 v5 的 provider/alias、配置
path/SHA、preflight freeze、claim-label、许可、双 oracle、Gold/Silver 与密钥扫描
硬门，并以 trace v8 保留 registry 的 `(path, sha256)` 强类型 commitment，硬校验
`registry SHA == actual file SHA == bundle artifact SHA == trace context SHA`。
v2-v5、trace v7 与既有 Stage 4/Stage 4-v5 证据不改不删，只作为历史失败证据。

- `build/`：可再分发捕获、许可清单与确定性生成器。
- `cases/`、`snapshots/`：4 家族 × 3 变体及 8 个冻结快照。
- `contracts/frozen_input_registry.frozen.v6.json`：12 个 case/variant 的唯一输入注册。
- `contracts/run_trace.schema.v8.json`：完整 trace v8 schema。
- `validate_baseline_v6.py`：bundle、registry、manifest 与 trace v8 校验入口。

```bash
uv run python baseline/v6/validate_baseline_v6.py validate-bundle baseline/v6
uv run python baseline/v6/validate_baseline_v6.py verify-manifest baseline/v6
uv run python -m unittest tests.test_baseline_v6 tests.test_per327_fourth_audit_regressions -v
```

本基线不运行付费模型、不访问账户、不下单。SEC EDGAR 捕获为公开领域材料；行情
fixture 为项目自制合成数据，只能作为说明性案例。
