# PER-329 Stage 4 baseline v3 验证冻结报告

- issue: PER-329（PER-323 Stage 4 返工）
- status: PASS
- 验证日期: 2026-08-17（Asia/Shanghai）
- baseline v3 冻结提交: `6bfd9e65218bd9b56a6fe9d5e7d1266d0d553fc8`
- baseline v3 bundle SHA-256: `4001148c8c2cd4f972c1375a11a8b95eadd033033ff2b7c6a65f65f80a7e236d`
- 口径 v3 SHA-256: `c3fcde8227e8934c76161a50756c4569f2ccf19f00d541a74699a9a5b8452eda`
- Stage 4 可执行代码提交: `209bd87afc50387233555161ec8681d4d9a5908f`

## 结论与边界

baseline v3 的验证矩阵全绿，可供 Stage 5 独立审计复算。v2 的旧 PASS 结论已由
C-323-15 作废；本报告只增发布，不修改 baseline v2、口径 v2 或旧验证目录。固定 v2
manifest/口径文件 SHA 复核零漂移。

本阶段验证 baseline、运行时、离线 trace 和确定性评分机制，不执行候选模型付费矩阵。
因此不生成或暗示任何模型排名，也不伪造真实线上 N3–N5；provider 端点可用性与线上
模型身份明确标注为未验证。

## 本轮发现并修复的执行缺口

Stage 3 已冻结 `run_trace.schema.v5.json`，但 live runner 原先只会生成 v4/v2 identity。
Stage 4 为 `OfflineHarness` 增加显式 `baseline_generation="v3"` 执行桥，生成
`contract_version=5.0.0` 与 `financial-agent-reliability-v3`，并保留 v2 默认行为以避免
回写或破坏历史测试。新增测试实际生成 v5 trace，校验 run_id 与三项真实 hash 锚点，
再由 v3 `verify-trace` 验收；未知 generation 会被拒绝。

同时把手动指南从已作废 v2 更新到 v3/82 测试，并修正 `fareli-retro` 的空窗说明：
baseline v3 重建的是评测输入与契约，不是已删除的历史运行证据。

## 全量与从零复现

| 项目 | 当前工作区 | 全新检出 `209bd87` | 判定 |
| --- | --- | --- | --- |
| v3/runtime 聚焦回归 | 29/29 | 被全量覆盖 | PASS |
| Python 全量 | 82/82 | 82/82 | PASS |
| Node runtime | 6/6 | 6/6 | PASS |
| Node integration | 6/6 | 6/6 | PASS |
| v3 `validate-bundle` | ok | ok | PASS |
| v3 `verify-manifest` | ok | ok | PASS |
| `uv sync --frozen` / `npm ci` | 已有环境 | 成功；0 npm vulnerabilities | PASS |
| 工作树漂移 | 仅原工作区用户改动不纳入 | clean | PASS |

## 口径 v3 A/B/G 门

| 门 | 判定 | 证据与边界 |
| --- | --- | --- |
| A1 manifest | PASS | 36 件逐件 hash、无缺件/未登记件，bundle hash 重算一致。 |
| A2 语义 | PASS | 12 case、8 snapshot、四族三变体、schema/时点/许可/引用门全过。 |
| A3 trace v5 | PASS | 新增实际 v5 trace 生成与 `verify-trace` 测试；身份、权限、状态、redaction 均通过。 |
| A4 链锚 | PASS | trace 对实际 inference config、harness contract、immutable bundle 三项 SHA 精确断言；自定义配置实际路径/SHA 进入 report 和 frozen bundle 的集成回归通过。 |
| A5 grader | PASS | 17 件逐件 SHA 与聚合 hash `def93ba4…55f7` 重算一致。 |
| B1 | PASS（机制）/ N/A（真实候选） | 12 个注册期望经双 oracle 严格对象重算；真实候选运行未授权、无落盘评分行。 |
| B2/B3 | PASS（机制）/ N/A（真实候选） | Gold-only/Silver diagnostic 与报告拒绝不完整排名测试通过；本阶段无候选汇总/报告。 |
| G1–G5 | PASS | A 组全过，边界和 v2 作废状态显式留痕，未把历史失败结论用于 v3。 |
| G6-v3 | PASS | 双 oracle、八 invariant、三组审计负例、v2 零漂移、许可门与零密钥门全部通过。 |

## 专项复验

- 多 provider：第二 provider 分组调用通过；只含 `live_preflight_required=false` 模型的
  provider 不解析凭据、不调用。
- alias：只有模型配置中显式列入 `allowed_response_model_ids` 的响应 ID 才通过；未登记
  alias 与 fallback 均拒绝。
- 自定义配置血缘：显式配置文件的真实路径/SHA 进入 preflight report、冻结 bundle 和
  decision；错误 hash 的 report 被拒绝。
- grader：mapping 严格键集合和递归对象等值；附加金融字段失败；submission 原对象的
  secret-shaped key 触发泄露 invariant；policy 八项 invariant 与实现集合完全相等。
- 数据许可：5/5 capture 均 `redistributable=true`；来源仅 SEC EDGAR 公有领域与项目
  自编 CC0 fixture；无 Longbridge raw payload。

## 线上与复盘边界

- 无凭据 preflight 在任何网络请求前返回结构化 `config_error`（预期 exit 1），无输出文件。
- 真实凭据线上预检按纪律未执行，不声称端点可用或模型身份在线确认。
- `fareli-retro list` 返回 `baseline_gap`（预期 exit 2）：v1 历史运行根已删除，v3 未重建
  历史运行证据。这是明确边界，不是 v3 bundle 损坏。
- 无付费调用、真实交易、真实密钥或不可再分发行情落盘。

## main 收敛

`main` 已 fast-forward 并推送；`main-ancestry.log` 证明 PER-327 runtime 修复、PER-328
baseline v3 冻结提交和 PER-329 可执行 v5 bridge 均为 `main` 祖先。分支只在确认最终
证据提交成为 `origin/main` 祖先后清理，结果另见 `branch-cleanup.log`。

本目录的 `SHA256SUMS` 对除自身外的每个证据文件逐件登记 SHA-256；清单自身 hash 在
PER-329 完成评论中登记。
