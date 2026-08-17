# PER-329 Stage 4 baseline v4 验证冻结报告

- issue：PER-329（PER-323 Stage 4 二次返工）
- status：PASS
- 验证日期：2026-08-17（Asia/Shanghai）
- baseline v4 冻结提交：`3fda6c99292d7d5a5d6bbe14037df50a117f5d10`
- baseline v4 bundle SHA-256：`d9c8a169bb9e121ba33c5688f2c7cad8b165c1e21a44df437a620f305d512d6d`
- 口径 v4 SHA-256：`baee53916aa82ffe229d2f76738c56ee8268a9d98ce60f92dfc5216cb82922e5`
- grader bundle SHA-256：`236db290f480fca7eb5648b1125cfcb4b8b591746bee99e572bed4f57b5b5a19`
- 手动指南对齐提交：`7d9c216`

## 结论与边界

baseline v4 的冻结内容、第二轮审计四项硬门、全量测试与从零复现全部通过，可交付
Stage 5 独立审计复算。C-323-19 已作废 v3 的新验收结论；本报告不沿用 v3 PASS，亦未
改写或删除 v2、v3 及既有 Stage 4 证据。v2/v3/旧 Stage 4 固定树哈希由 v4 测试复核。

本阶段验证基线、离线运行机制、确定性 grader 与报告约束，不执行候选模型付费矩阵，
因此不生成模型排名，也不声称 provider 端点可用或线上模型身份已确认。

## 全量与从零复现

| 项目 | 当前工作区 | 全新检出 `7d9c216` | 判定 |
| --- | --- | --- | --- |
| v4/runtime 聚焦回归 | 31/31 | 被全量覆盖 | PASS |
| Python 全量 | 96/96 | 96/96 | PASS |
| Node runtime | 6/6 | 6/6 | PASS |
| Node integration | 6/6 | 6/6 | PASS |
| v4 `validate-bundle` | ok | ok | PASS |
| v4 `verify-manifest` | ok | ok | PASS |
| `uv sync --frozen` / `npm ci` | 已有环境 | 成功 | PASS |
| 工作树漂移 | 原工作区用户改动未纳入 | clean | PASS |

## 口径 v4 硬门

| 硬门 | 判定 | 证据 |
| --- | --- | --- |
| provider / model identity | PASS | 第二 provider 实际分组；requested model 只在其自身 `ModelConfig.allowed_response_model_ids` 中判定；合法 alias 通过，跨模型/未登记 alias 拒绝。 |
| trace v6 | PASS | 执行完整 Draft 2020-12 schema；缺顶层块、缺嵌套必填字段均拒绝；run ID、配置路径/SHA、provider/model、harness、bundle、frozen input 跨块锚逐项重算，篡改负例全部失败。 |
| preflight freeze | PASS | blocked 模型行即使伪造总状态 `passed`，冻结入口仍以状态对账硬失败，不能生成可冒充通过的 bundle。 |
| claim-label | PASS | answer 必须提供非空 claims；缺失、额外、无关 label key 均失败，只有 claims/labels 严格等集且值在注册层级内才通过。 |

## 其余专项门

- `live_preflight_required=false` 的模型不解析未使用 provider 凭据、不发起调用。
- 自定义 inference 配置的解析后绝对路径与实际 SHA 进入 preflight、冻结 decision 和 v6 trace；错误路径或 SHA 被拒绝。
- grader 29 件逐件 SHA 与聚合 hash 精确复算；双 oracle 对 12 个注册期望逐对象一致。
- policy 声明与实现的八项 invariant 严格相等；submission 原对象上的 secret-shaped key 触发泄露门。
- 36 件 v4 manifest 工件逐件 hash、bundle 聚合、schema 与语义门通过；40 个 v4/config 文件对象级密钥扫描零发现。
- 5/5 capture 均可再分发；来源仅 SEC EDGAR 美国公有领域材料与项目自编 CC0 合成 fixture，无授权市场数据。

## 线上与复盘边界

- 无凭据 preflight 在网络请求前返回结构化 `config_error`（预期 exit 1），未产生输出文件。
- `fareli-retro list` 返回 `baseline_gap`（预期 exit 2）：v4 重建评测基线，不重建已删除的 v1 历史运行证据。
- 未执行真实凭据请求、付费候选运行、账户访问或真实交易；未发布或暗示模型排名。

原始命令输出与结构化核对结果均在本目录。`SHA256SUMS` 对除自身外的证据文件逐件登记；
清单自身 hash 在 PER-329 完成评论中登记。主线祖先证明与分支清理结果在收敛后追加。

## main 收敛

`main` 已 fast-forward 并推送至 `863fab3b207b38947a7414fc319e4612cdc20d8b`；
`main-ancestry.log` 证明上一轮 main、PER-327 二次整改、baseline v4 冻结、手动指南
以及本轮首批验证证据均为其祖先。确认祖先关系后，已删除合并完成的本地
`per327-second-audit-fixes`、`per328-baseline-v4`、`per329-baseline-v4-validation`
及远端前两条分支；当前本地仅 `main`，远端仅 `origin/main`（另有 `origin/HEAD`
符号引用）。最终清单与清理证据追加提交后再 fast-forward 到同一主线。
