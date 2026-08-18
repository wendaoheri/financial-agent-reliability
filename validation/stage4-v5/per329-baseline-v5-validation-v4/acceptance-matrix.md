# PER-329 Stage 4 baseline v5 验证冻结报告

- issue：PER-329（PER-323 Stage 4 第三次返工）
- status：PASS
- 验证日期：2026-08-18（Asia/Shanghai）
- baseline v5 冻结提交：`cb1e5f90eac0b6a3154fa7a375e2fe371f892c22`
- baseline v5 bundle SHA-256：`7a6cd3544e4f7e4b09debd2b0fa73ecfdef3efb3324254ecea4327b4a4bafbb9`
- 口径 v5 SHA-256：`ae2e49b593a05ad9ae7b53c3984d80ffd950501b2cc3d39f4c4e39b3095bead2`
- grader bundle SHA-256：`80af0ce3a01df05bb23134510b0d523023a8a4c2ad1a17135a9e85fe9145cbc3`
- 手动指南对齐提交：`91dc304`

## 结论与追加路径

baseline v5 的冻结内容、累计硬门、全量测试和从零复现全部通过，可交付 Stage 5 独立
审计复算。C-323-23 已作废 v4 的新验收结论；本报告不沿用 v4 PASS，也不改写 v2/v3/v4。

v5 自检将既有 `validation/stage4/` 整棵树作为历史证据钉住，向该目录新增 v5 证据会
正确触发漂移。因此本轮采用追加式相邻世代 `validation/stage4-v5/`，确保旧 Stage 4
树哈希 `990c6339…a27c` 不变。首次试写在未跟踪状态即发现并移走，没有提交、覆盖或删除
任何旧证据。

本阶段只验证离线基线、trace、grader 与报告机制，不执行候选模型付费矩阵，不生成
模型排名，也不声称 provider 端点可用或线上模型身份已确认。

## 全量与从零复现

| 项目 | 当前工作区 | 全新检出 `91dc304` | 判定 |
| --- | --- | --- | --- |
| v5/runtime 聚焦回归 | 32/32 | 被全量覆盖 | PASS |
| Python 全量 | 106/106 | 106/106 | PASS |
| Node runtime | 6/6 | 6/6 | PASS |
| Node integration | 6/6 | 6/6 | PASS |
| v5 `validate-bundle` | ok | ok | PASS |
| v5 `verify-manifest` | ok | ok | PASS |
| `uv sync --frozen` / `npm ci` | 已有环境 | 成功 | PASS |
| 工作树漂移 | 原工作区用户改动未纳入 | clean | PASS |

## v5 累积硬门

| 硬门 | 判定 | 证据 |
| --- | --- | --- |
| provider / model identity | PASS | 第二 provider 分组；requested/response alias 仅按同一 ModelConfig 白名单判定；未登记 alias 拒绝。 |
| config 与跨块锚 | PASS | 实际配置 path/SHA、harness SHA、run identity、request、provider、bundle 与 frozen input 逐项重算。 |
| preflight freeze | PASS | blocked 行不能靠伪造汇总 `passed` 跨过状态对账和冻结门。 |
| claim-label | PASS | answer 的 claims 非空，labels 与 claims 严格等集且层级合法；缺失、额外、无关键均失败。 |
| trace v7 schema | PASS | 完整 Draft 2020-12 schema 生效，`context.frozen_input_path` 为必填。 |
| frozen-input registry | PASS | 12 个 `(case_id, variant_id)` 唯一注册；path/SHA 同时与 trace、实际文件及 bundle artifact 一致。case A 即使改指同 bundle 内 case B 的真实 path 与真实 SHA仍硬失败；未注册 case、错误 SHA、篡改 registry 均失败。 |

## 其余专项门

- `live_preflight_required=false` 不解析未使用 provider 凭据、不调用；自定义配置真实路径/SHA 全链留痕。
- v5 manifest 38 件和 grader 33 件逐项 SHA 及聚合 hash 精确复算；12 个注册期望经双 oracle 逐对象一致。
- policy 声明与实现的八项 invariant 严格相等；submission 原对象的 secret-shaped key 会触发泄露门。
- v5/config 42 个文件对象级密钥扫描零发现；实现/config/test 范围 121 个文本文件只有 3 个注册负例测试源命中，意外命中 0。
- 5/5 capture 可再分发，仅含 SEC EDGAR 美国公有领域材料与项目自编 CC0 合成 fixture；无授权市场数据。
- v2/v3/v4 与既有 Stage 4 树哈希全部等于冻结期望，零漂移。

## 线上与复盘边界

- 无凭据 preflight 在网络请求前返回结构化 `config_error`（预期 exit 1），不产生输出文件。
- `fareli-retro list` 返回 `baseline_gap`（预期 exit 2）：v5 重建评测基线，不重建已删除的 v1 历史运行证据。
- 未执行真实凭据请求、付费模型调用、账户访问、真实交易或候选排名。

原始命令输出与结构化结果均在本目录。`SHA256SUMS` 对除自身外的证据文件逐件登记；
清单自身 hash 在 PER-329 完成评论中登记。主线祖先证明与分支清理结果在收敛后追加。

## main 收敛

`main` 已 fast-forward 并推送至 `ddf5c573abd8b8773a15cc0c0ff7b8cc48fb8321`；
`main-ancestry.log` 证明上一轮 main、PER-327 第三轮 frozen-input 修复、baseline v5
冻结、手动指南及本轮首批证据均为其祖先。确认祖先关系后，已删除本地
`per327-third-audit-input-binding`、`per328-baseline-v5`、
`per329-baseline-v5-validation` 及远端前两条分支。当前本地仅 `main`，远端仅
`origin/main`（另有 `origin/HEAD` 符号引用）。最终清单和清理证据追加提交后再
fast-forward 到同一主线。
