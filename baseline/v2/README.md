# 基线 v2(最小可用版本)

PER-323 Stage 3(PER-328)重建的最小可用评测基线。历史基线 v1(30 族 × 3 变体、
810 运行矩阵)已按项目所有者批准的方案 B 删除(C-323-5/6,回滚索引见
`docs/per323-stage2-deletion-record.md`);本基线按 C-323-7 **不恢复历史完整规模**。

## 内容

- `cases/` — 12 张冻结案例卡,4 个家族 × 3 变体(normal /
  single_factor_perturbation / missing_or_anomalous):
  - FKW2-PUB-01 估值:Apple 营收同比增速(SEC EDGAR 公有领域披露,确定性十进制重算);
  - FKW2-PUB-02 研究:决策时点可得性(同一快照、不同时点 cutoff 得出不同答案);
  - FTW2-LBQ-01 估值:Longbridge 公开只读行情字段选取;
  - FTW2-LBQ-02 合规:public_read_only 授权边界(critical 风险,越权须拒绝)。
- `snapshots/` — 4 个主快照(2 × SEC EDGAR XBRL 事实,2 × Longbridge 行情)+
  4 个缺证派生快照(records 置空,链接 parent,供弃权评测)。
- `contracts/` — case_card/data_snapshot schema v2、run_trace schema v4
  (承接 v3.11,run_identity 改绑 inference_config_sha256 +
  harness_contract_sha256 + immutable_bundle_sha256)、理由码词表 v2、
  验证配置 v2、grader 捆扎清单。
- `grader/grader_policy.v2.json` — critical_success 公式与不变量词表(时点与口径、
  证据血缘、结论验证、弃权与升级等八维)、Gold-only 排名纪律、三层证据标注规则。
- `build/` — 确定性构建器与采集血缘:`capture_manifest.v2.json` 登记原始公开
  响应的 sha256、查询参数、采集时间与许可;`captures/` 保存原始响应。
- `validate_baseline_v2.py` — 无第三方依赖校验器(validate-bundle /
  verify-manifest / verify-trace)。
- `baseline_manifest.frozen.v2.json` — 全基线逐件 sha256 与 bundle hash,
  是基线 v2 的单一入口哈希。

## 冻结纪律

- 冻结后不改不删;修订只增版本并保留变更理由(口径 v2 §6)。
- 不得把演示案例反向用于调权;权重与排除规则在候选运行前冻结。
- 密钥零落盘:本目录全部文件通过 `harness/secret_scan.py` 扫描门。
- 数据源纪律:公开 seed 优先(SEC EDGAR 公有领域);Longbridge 仅公开只读查询,
  account/assets/cash/holdings/orders/positions/portfolio/trades 禁入;
  无付费模型调用、无真实交易。
- oracle 纪律:Gold 期望由生产实现与独立参考实现双算一致后注册;公开 benchmark
  答案与候选模型输出不得参与定标。

## 复现命令

```bash
uv run python -m unittest discover -s tests -v      # 含 tests/test_baseline_v2.py
python3 baseline/v2/validate_baseline_v2.py validate-bundle baseline/v2
python3 baseline/v2/validate_baseline_v2.py verify-manifest baseline/v2
```

重建(仅在冻结裁决前允许;冻结后以 manifest 为准):

```bash
uv run python baseline/v2/build/build_baseline_v2.py
```

验收判读标准:`docs/contracts/acceptance-criteria-v2.md`(口径 v2)。
