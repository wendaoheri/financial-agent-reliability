# 基线 v4（第二轮审计硬门版）

基线 v4 是 PER-328 的追加式冻结世代。它以 v3 的 4 个家族、12 张 case card、
8 个 snapshot 和可再分发数据为基础，仅把 PER-330 第二轮审计确认的四类缺口
升级为硬门：provider/模型别名、完整 trace schema 与跨块锚点、preflight 后冻结、
以及 claim-label 键集合完全一致。v2、v3 和 Stage 4 v3 证据不改不删。

- `build/`：冻结捕获、许可清单与确定性生成器。
- `cases/`、`snapshots/`：4 家族 × 3 变体及其 8 个冻结快照。
- `contracts/`：case/snapshot v4、run_trace v6、理由码与 grader bundle。
- `grader/`：冻结评分政策 v4。
- `validate_baseline_v4.py`：bundle/manifest 校验，并直接执行生产 v6 trace validator。

验证入口：

```bash
uv run python baseline/v4/validate_baseline_v4.py validate-bundle baseline/v4
uv run python baseline/v4/validate_baseline_v4.py verify-manifest baseline/v4
uv run python -m unittest tests.test_baseline_v4 -v
```

本基线不运行付费模型、不访问账户、不下单。SEC EDGAR 捕获为公开领域材料；行情
fixture 是项目自制合成数据，只能作为说明性案例。
