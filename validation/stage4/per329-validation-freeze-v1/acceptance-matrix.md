# PER-329 Stage 4 验证冻结报告 v1

- issue: PER-329（PER-323 Stage 4）
- status: PASS
- 验证日期: 2026-08-17（Asia/Shanghai）
- 冻结提交: `00afd959d674bb22155617559c37b9ac87d95caa`
- 基线 v2 bundle SHA-256: `e401ccce3496ace2a9da7ab6c063cbc28ff17bfa4496e655c674cbf10f49e34d`
- 判读口径: `docs/contracts/acceptance-criteria-v2.md`，SHA-256 `5dd9529df4f11411b6b6717335ca65b323212eacc90f5c8382143898a73997f2`

## 结论

基线 v2 的验证矩阵全绿，可移交 Stage 5 独立审计。验证覆盖当前工作区与基于冻结提交的
全新本地克隆；没有执行付费模型请求或真实交易，也没有落盘任何凭据。

这次验证冻结验证的是**基线、契约、离线运行边界与确定性评分机制**，不是候选模型评测。
因此没有候选结果、模型间排名或报告结论可供声称；口径 v2 的 B1–B5 在“候选运行交付”
语境下记为 N/A，在“基线冻结”语境下由双 oracle、grader 与 Gold/Silver 隔离测试覆盖。

## 全量与从零复现

| 项目 | 当前工作区 | 全新克隆 | 判定 |
| --- | --- | --- | --- |
| Python 全量 | 62/62 OK | 62/62 OK | PASS |
| Node runtime | 6/6 pass | 6/6 pass | PASS |
| Node integration 全集 | 6/6 pass | 与 runtime 同一集合 | PASS |
| `validate-bundle` | ok | ok | PASS |
| `verify-manifest` | ok | ok | PASS |
| `uv sync` | 已存在环境 | Python 3.11.14、7 包安装成功 | PASS |
| `npm ci` | 已存在环境 | 106 包安装成功、0 vulnerabilities | PASS |

全新克隆 HEAD 为冻结提交，安装/测试后 `git status --short` 为空。npm 输出中的 deprecated
与 allow-scripts 均为信息级提示；锁定的 `@mariozechner/pi-agent-core@0.73.1` 运行时测试通过。

## 口径 v2 A/B/G 门逐条判读

| 门 | 判定 | 证据与边界 |
| --- | --- | --- |
| A1 manifest 完整 | PASS | 两个环境 `verify-manifest: ok`；36 件登记工件及 bundle hash 重算一致，无未登记基线文件。 |
| A2 跨对象语义 | PASS | 两个环境 `validate-bundle: ok`；12 case、8 snapshot、四族三变体、时点/引用/权限约束由测试覆盖。 |
| A3 v4 trace | PASS | `test_runner_emits_schema_v4_traces_that_verify` 生成离线 trace 并通过 `verify-trace`；篡改 run_id 与密钥形态负例均被拒绝。 |
| A4 链锚 | PASS | runner 由实算 `inference_config_sha256`、`harness_contract_sha256`、immutable bundle hash 构造 identity；commitment 四哈希的结构门由 grader 测试覆盖。当前没有候选运行，不伪造 N3–N5 证据。 |
| A5 grader 捆扎 | PASS | 15 件逐件 SHA 与登记一致；contract bundle 重算为 `deeed28a…ce44`。 |
| B1 单运行重评分 | N/A（候选运行）/ PASS（机制） | 无候选运行；12 个冻结期望均经生产与独立参考 oracle 逐位重算，grader 正/负例确定。 |
| B2 批级统计 | N/A（候选运行）/ PASS（机制） | 无候选批；pipeline 测试确定性隔离 Gold ranking rows 与 Silver diagnostic rows。 |
| B3 对外报告 | N/A | 本阶段不发布模型结果或排名。报告契约的确定性与拒绝不完整排名由全量测试覆盖。 |
| B4 排除规则 | PASS（机制） | 失败/blocked/missing 不得静默记零的报告契约负例全通过。 |
| B5 Gold-only | PASS（机制） | Gold/Silver 隔离测试通过；Silver 不进入主排名。 |
| G1 六节点与版本 | PASS | N0/N1/契约和 grader 齐备；N2–N5 的运行期形态由离线生成测试覆盖。无候选运行时不声称存在候选证据。 |
| G2 A 组 | PASS | A1–A5 全部通过。 |
| G3 B1–B3 重算 | PASS（基线范围） | 双 oracle、grader、pipeline 与报告契约测试通过；候选交付范围 N/A。 |
| G4 排除与 Gold-only | PASS | 机制测试通过。 |
| G5 降级留痕 | PASS | 唯一预期降级是已文档化的 baseline v1 `baseline_gap`；不影响基线 v2 冻结判定。 |
| G6 种子与安全纪律 | PASS | 公开 SEC seed、Longbridge public_read_only、双 oracle、密钥扫描零命中；无网络付费调用、无真实交易。 |

## 密钥扫描门

机器扫描了 `configs/inference.json`、`configs/harness_contract.v1.json` 与基线 v2 的全部
JSON，共 36 文件：持久化密钥命中 0，credential 环境变量命名命中 0。全仓文本模式扫描
仅命中 3 个专门验证扫描器拒绝能力的负例测试源文件；未命中任何配置、基线、日志或本次
验证产物。预检命令通过 `env -u` 显式清除四个相关变量，返回结构化 `config_error`
（exit 1），且没有生成输出文件，证明在网络请求前失败。

## 删除后血缘与死引用

九个已删除旧根目录均不存在。扫描发现的旧路径文字均属于以下可保留类别：删除/回滚
历史说明、被 `baseline_gap` 门隔离的 v1 复盘注册表、合成报告 fixture 的逻辑引用、迁移
supersedes 元数据。全新克隆的 62 项 Python 与 6 项 runtime 测试全绿，三个控制台入口
按手动指南表现一致，未发现会在当前基线 v2 路径上解引用已删除目录的活引用。

## 手动指南核对

- 离线路径：安装、全量测试、Node 边界、bundle 两门、三控制台入口均按指南实测。
- 线上预检路径：配置解析、模型 ID、payload、身份不匹配、fallback 禁止、重试与工具能力
  由离线注入 transport 的测试覆盖；无凭据实测在网络前结构化失败。
- 真实凭据线上请求：按本议题“不得执行付费模型调用”纪律未执行，不能声称 provider
  端点当时可用或三个模型身份已获线上确认；这不构成基线冻结失败。
- `fareli-retro list`：按指南返回 `baseline_gap`、exit 2；这是基线 v1 删除后的预期状态。

## 产物索引

原始命令输出、结构化命令结果、grader 捆扎核对、密钥扫描和死引用分类均在本目录。
`SHA256SUMS` 对除自身以外的每个产物记录逐件 SHA-256；清单自身哈希在
PER-329 完成评论和 Git 提交中登记。
