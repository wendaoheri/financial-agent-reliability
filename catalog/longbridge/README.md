# Longbridge 冻结数据与 Oracle v1

本目录对应 PER-29，只消费 PER-26 冻结的 FTW-01～FTW-15 配额。15 个家族各有 `normal`、`single_factor_perturbation`、`missing_or_anomalous` 三个变体；FTW-01～12 的前两种变体可由两份独立代码重算，FTW-13～15 以及所有缺证变体固定为 Silver。

采集只允许 `longbridge quote <symbol> --format json`。禁止调用账户、资产、现金、持仓、订单、组合或成交接口；涉及超时、幂等、身份和最终状态的内容全部是明确标记的确定性模拟状态。

```bash
uv run python pipelines/longbridge/freeze.py fetch
uv run python pipelines/longbridge/freeze.py build
uv run python pipelines/longbridge/freeze.py check
uv run python -m unittest tests.test_longbridge_cases -v
```

`build` 与 `check` 只读取已冻结的 `snapshots/longbridge/raw/`，不会访问网络。行情条款不授予再分发权，因此所有快照均标记 `redistributable: false`，候选运行与发布保持关闭；公开发布前必须由两名审阅者分别确认来源、许可、时点、可判定性和无未来信息。
