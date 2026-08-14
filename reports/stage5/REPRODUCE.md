# Stage 5（PER-33）交付物复现说明

前置：本仓库工作副本（含 `runs/stage3/` 三轮冻结证据、`contracts/`、`preregistration/`、`audit/`）。
全程离线、零付费调用、零候选模型请求。

## 一键复现

```bash
cd financial-agent-reliability

# 1) Stage 4 审计复现（签署统计的直接来源）
python3 audit/per32_part1_inputs_integrity.py \
  && uv run python audit/per32_part2_grader_recompute.py \
  && python3 audit/per32_part3_identity_fairness_safety.py \
  && uv run python audit/per32_part4_statistics.py
# part4 输出 audit/per32_part4_ranking_results.json（SHA-256 16df9fd9…710b）

# 2) 冻结合同校验
uv run python contracts/grader_v2.py verify-freeze    # grader contract v2，bundle 511da190…
uv run python reporting/report.py verify-freeze       # reporting contract v1，bundle a0a10533…

# 3) Stage 5 消费链重建（密封行 → 冻结 v2 评分器）
uv run python contracts/sealed_row_bridge_v2.py --output reports/stage5/work/sealed_rows.v2.json
uv run python contracts/grader_v2.py score reports/stage5/work/sealed_rows.v2.json \
  --output reports/stage5/work/score_results.v2.json

# 4) Stage 5 报告重建（脚本内断言：score_results 与 PER-32 签署统计逐字段相等，
#    分赛道诊断按同一口径重算并与总口径勾稽；演示选案对模型标签置换不变）
uv run python reports/stage5/build_stage5.py

# 5) 契约校验与契约标准渲染
uv run python reporting/report.py validate reports/stage5/financial_agent_report_bundle.v1.json
uv run python reporting/report.py render reports/stage5/financial_agent_report_bundle.v1.json \
  --markdown reports/stage5/financial_agent_index_report.v1.md \
  --html reports/stage5/financial_agent_index_report.v1.html

# 6) 完整报告 HTML 渲染（Markdown → 无障碍 HTML）
uv run python reports/stage5/render_full_html.py

# 7) 回归测试（2026-08-14 本机复跑：261 tests OK；node --test 6/6 pass）
uv run python -m unittest discover -s tests -q
npm run test:runtime
```

## 数字勾稽关系

- `reports/stage5/work/score_results.v2.json` == `audit/per32_part4_ranking_results.json`
  （models、pairwise_csr、leader_gates、ranking_reliable 逐字段相等；`build_stage5.py` 强制断言）。
- 主榜 FAI = Gold CSR（族聚类、50/50 赛道权重）；全部 CI/p/bootstrap-top 引自 PER-32 签署统计，
  本阶段**未引入任何新的统计实现**，仅以冻结 v2 消费链（bridge + grader_v2）复算并交叉校验。
- 分赛道诊断为同一已验证聚合口径的赛道内分解；正确弃权率总口径为合并原始率（24 行均在 FTW），
  已在报告 §4 注明。
- 演示案例选取仅依赖单元级属性与跨候选结果模式（见 `demo_selection_commitment.v1.json`），
  不读取 CSR/名次/领先者信息。

## 交付物清单（reports/stage5/）

| 文件 | 角色 |
|---|---|
| `financial_agent_report_bundle.v1.json` | 契约 v1 报告 bundle（810 run_records、主榜、7 演示案例、限制、复现），`reporting/report.py validate` 通过 |
| `financial_agent_index_report.v1.md` / `.v1.html` | 冻结渲染器的契约标准输出 |
| `stage5_full_report.md` / `.html` | 完整排行榜报告（含成对比较、CI、Holm p、稳定性门、哈希台账、扩展路线） |
| `machine_readable_results.v1.json` | 机器可读全量结果（签署统计 + 分赛道诊断 + Silver 诊断 + 损失分布 + 延迟 + 演示案例明细 + 选案承诺） |
| `demo_selection_commitment.v1.json` | 演示选案规则承诺与时序披露 |
| `build_stage5.py` / `render_full_html.py` | 确定性构建/渲染脚本 |
| `work/sealed_rows.v2.json` / `work/score_results.v2.json` | 冻结消费链中间产物（可重建） |

## 关键哈希（SHA-256）

- Stage 4 冻结审计 bundle：`5c9a260f0e788c510b3157987ad0deb863dd10b38dd4d1ec600a4798cac76866`
- PER-32 签署排名统计：`16df9fd98be08a7f9e6c9a4aabe3bdf8f6bf7ad8f07598e280743619ec80710b`
- 预注册 v1.1 追记：`786c02609e3526becf0c3916c217a5ecc4c06a3fd627c678c8a9ea000d9f06e3`
- grader contract v2 bundle：`511da1901afccd1581782496d8488d47300ba40adb80f64590da635be0ae2eb7`
- 三轮证据 bundle：`d479193c1db8…cd598` / `6fd88c045b8a…a63c` / `c84b3721894c…cd3d`

完整台账见 `stage5_full_report.md` §9.2。
