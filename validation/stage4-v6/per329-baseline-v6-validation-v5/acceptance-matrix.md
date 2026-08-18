# PER-329 Stage 4 baseline v6 验证冻结报告

- issue：PER-329（PER-323 Stage 4 第四次返工）
- status：PASS
- 验证日期：2026-08-18（Asia/Shanghai）
- baseline v6 冻结提交：`7d36f9e0f3b08195141ead3316f6f1ba5aa83288`
- baseline v6 manifest 文件 SHA-256：`8f37947aaa053cf9d610e0150bb85fd89683a19037990895cf536c6b0d69f966`
- baseline v6 bundle SHA-256：`25ea0bd32df5071de72096f55b5fa22af2eb78b114c8a966c0b9670596bab63a`
- 口径 v6 SHA-256：`78ef6fd31fa809a4886ded36c831a948bd09072bf95d50185677e30c94a682a3`
- grader bundle SHA-256：`f28d66b343e68f423c4feb13c8900c0be45e92fc66e82063df22a7792686996e`
- 手动指南对齐提交：`4e745b1`

## 结论与追加路径

baseline v6 的冻结内容、累计硬门、全量测试和从零复现全部通过，可交付 Stage 5 独立
审计复算。C-323-27 已作废 v5 的新验收结论；本报告不沿用 v5 PASS，也不改写旧世代。

v6 自检钉住既有 `validation/stage4/` 与 `validation/stage4-v5/` 历史证据，因此本轮采用
追加式相邻世代 `validation/stage4-v6/`，避免修改已冻结证据。

本阶段只验证离线基线、trace、grader 与报告机制；依照轻量差异实验边界，不执行候选
模型付费矩阵，不生成模型排名、成本或延迟结论，也不声称 provider 端点可用或线上模型
身份已确认。

## 全量与从零复现

| 项目 | 当前工作区 | 全新检出 `4e745b1` | 判定 |
| --- | --- | --- | --- |
| v6/runtime 聚焦回归 | 35/35 | 被全量覆盖 | PASS |
| Python 全量 | 117/117 | 117/117 | PASS |
| Node runtime | 6/6 | 6/6 | PASS |
| Node integration | 6/6 | 6/6 | PASS |
| v6 `validate-bundle` | ok | ok | PASS |
| v6 `verify-manifest` | ok | ok | PASS |
| `uv sync --frozen` / `npm ci` | 已有环境 | 成功 | PASS |
| 工作树漂移 | 用户原有改动未纳入 | clean | PASS |

## v6 累积硬门

| 硬门 | 判定 | 证据 |
| --- | --- | --- |
| provider / model identity | PASS | provider 分组、requested/response identity 与登记 alias 按配置严格对账。 |
| config 与跨块锚 | PASS | 实际配置 path/SHA、harness SHA、run identity、request、provider、bundle 与 frozen input 逐项重算。 |
| preflight freeze | PASS | blocked 行不能靠伪造汇总跨过状态对账和冻结门。 |
| claim-label | PASS | claims 非空，labels 与 claims 严格等集且层级合法。 |
| trace v8 schema | PASS | 完整 Draft 2020-12 schema 与新增冻结输入绑定约束生效。 |
| frozen-input registry | PASS | 12 个 `(case_id, variant_id)` 唯一注册；trace、实际文件、bundle artifact 三方 path/SHA 一致。 |
| 内部重锚攻击 | PASS | 同一 case/variant 即使同步改写 trace、registry 和 bundle 内 path/SHA，仍因外部冻结期望锚点不一致而硬失败。 |
| 跨 case 改指 | PASS | case A 改指同 bundle 内 case B 的真实 path/SHA 仍硬失败。 |

## 其余专项门

- v6 manifest 38 件和 grader 37 件逐项 SHA 及聚合 hash 精确复算；12 个注册期望经双 oracle 逐对象一致。
- policy 声明与实现 invariant 严格相等；submission 原对象的 secret-shaped key 会触发泄露门。
- v6/config 42 个文件对象级密钥扫描零发现；实现/config/test 范围 127 个文本文件仅 3 个登记负例测试命中，意外命中 0。
- capture 可再分发，仅含 SEC EDGAR 美国公有领域材料与项目自编 CC0 合成 fixture；无授权市场数据。
- baseline v2/v3/v4/v5、`validation/stage4/` 与 `validation/stage4-v5/` 树哈希均等于冻结期望，零漂移。

## 线上与复盘边界

- 无凭据 preflight 在网络请求前返回结构化 `config_error`（预期 exit 1），不产生输出文件。
- `fareli-retro list` 返回 `baseline_gap`（预期 exit 2）：v6 重建评测基线，不重建已删除的 v1 历史运行证据。
- 未执行真实凭据请求、付费模型调用、账户访问、真实交易或候选排名。

原始命令输出与结构化结果均在本目录。`SHA256SUMS` 将对除自身外的证据文件逐件登记；
清单自身 hash 在 PER-329 完成评论中登记。主线祖先证明与分支清理结果在收敛后追加。

## main 收敛

`main` 已 fast-forward 并推送至 `243bb54dd4c341ff0d12fbaa386107fc928e237e`；
`main-ancestry.log` 证明上一轮 main、trace v8 修复、baseline v6 冻结、手动指南及本轮
首批证据均为其祖先。确认祖先关系后，已删除本轮范围内本地
`per328-baseline-v6`、`per329-baseline-v6-validation` 与远端
`agent/harness/per-327-trace-v8`、`per328-baseline-v6`。

PER-361/PER-366 是本 issue 之后的独立工作，未并入本次收敛，故其本地/远端分支明确
保留。最终清单和清理证据追加提交后再 fast-forward 到同一主线。
