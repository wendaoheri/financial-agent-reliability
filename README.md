# Financial Agent Reliability(金融 Agent 可靠性研究)

围绕金融 Agent 从"会生成、能执行"到"能判断、能负责"之间的系统性断层开展研究,
以《金融Agent系统性失效问题研究报告.html》(现位于 `docs/research/`)为研究起点,
建设一套可验证的评测 harness、契约体系与证据库,用于控制投研、估值、
量化、风险管理等场景中的高损失错误、结构化可信错误、越权执行与责任真空。

> **PER-323 状态(2026-08-17,Stage 3)**:基线 v1 的 ❄️ 旧血缘历史基线
> (contracts/、cases/、catalog/、snapshots/、preregistration/、evidence/、
> audit/、reports/、runs/)已按项目所有者批准的方案 B 与冻结清理清单 v1 删除,
> 逐项留痕与回滚索引见 `docs/per323-stage2-deletion-record.md`。推理层已改造为
> provider/模型可配置(`configs/inference.json`)。基线 v2(最小可用:4 族 ×
> 3 变体,见 `baseline/v2/`)与口径 v2(`docs/contracts/acceptance-criteria-v2.md`)
> 已由 Stage 3(PER-328)重建,待交付负责人裁决冻结。手动执行见
> `docs/manual-execution-guide.md`。

## 快速开始

环境基线:Python 3.11(见 `.python-version`),一律使用 `uv` 管理;node/npm 用于
运行时边界测试。项目为标准 src 布局的可安装包,`uv sync` 会以 editable 方式安装
`financial-agent-reliability` 并注册 `fareli-harness` / `fareli-report` /
`fareli-retro` 三个控制台入口。

```bash
uv sync                                            # 安装依赖并安装本项目(editable)
npm ci                                             # 安装 pi-agent-core 0.73.1(运行时边界)
uv run python -m unittest discover -s tests -v     # 全量测试(62 个用例)
npm run test:runtime                               # pi-agent-core 运行时边界测试(node --test)
uv run fareli-harness --help                       # 评测 harness CLI(preflight / freeze-preflight)
uv run fareli-report --help                        # 报告契约 CLI(validate / render)
uv run fareli-retro --help                         # 历史轨迹复盘 CLI(当前为基线空窗期,见上文)
```

完整手动执行路径(离线验证 + 线上预检两条)见 `docs/manual-execution-guide.md`。
付费模型评测仅在显式授权下进行,凭据只通过环境变量注入(见下文),禁止真实交易。

## 目录结构

PER-323 Stage 2 后,仓库由**活的代码包**、**推理配置**与常规目录构成;基线 v1
的 ❄️ 旧血缘历史基线已整体删除(留痕与回滚索引见
`docs/per323-stage2-deletion-record.md`)。改动任何目录前,先读 `AGENTS.md`。

### 📦 代码包(src 布局,唯一可编辑代码区)

```
src/financial_agent_reliability/
├── inference_config.py  provider/模型配置加载与校验(PER-323 契约 §5.1)
├── harness/      评测 harness:bundle、checkpoint、预检编排、脱敏、密钥扫描门、CLI 与 node 运行时(.mjs)
├── graders/      确定性评分管线
├── oracles/      Longbridge 案例 oracle(生产实现 + 独立参照实现)
├── pipelines/    案例/快照管线(基线 v1 管线已退役,随基线 v2 重建)
├── providers/    provider adapter 与 HTTP transport(模型中立、脱敏;当前实现 bailian)
├── reporting/    报告契约校验与确定性渲染
├── retrospective/ 历史轨迹复盘工具链(基线空窗期显式报 baseline_gap,随基线 v2 重建)
└── simulators/   确定性模拟账本
```

顶层导入名为 `financial_agent_reliability`。

### 🧊 基线 v2(`baseline/v2/`,最小可用重建,Stage 3 PER-328)

| 路径 | 内容 |
| --- | --- |
| `baseline/v2/cases/` | 12 张案例卡(4 族 × normal/single_factor_perturbation/missing_or_anomalous),公开 seed 优先(SEC EDGAR 公有领域披露)+ Longbridge 公开只读行情 |
| `baseline/v2/snapshots/` | 4 个主数据快照 + 4 个缺证派生快照(弃权评测专用,Silver) |
| `baseline/v2/contracts/` | case_card/data_snapshot schema v2、run_trace schema v4、理由码词表 v2、验证配置、grader 捆扎清单 |
| `baseline/v2/grader/grader_policy.v2.json` | grader 政策:critical_success 公式、不变量词表、Gold-only 排名纪律、三层证据标注规则 |
| `baseline/v2/build/` | 确定性构建器、采集清单与原始公开响应(sha256 血缘) |
| `baseline/v2/validate_baseline_v2.py` | 无第三方依赖校验器:validate-bundle / verify-manifest / verify-trace |
| `baseline/v2/baseline_manifest.frozen.v2.json` | 全基线逐件 sha256 与 bundle hash(单一入口) |

### ⚙️ 推理与运行时契约(`configs/`,随仓库提交、不含密钥)

| 文件 | 内容 |
| --- | --- |
| `configs/inference.json` | provider 与候选模型声明(凭证只存环境变量**名称**) |
| `configs/inference.schema.v1.json` | 配置文件 JSON Schema |
| `configs/harness_contract.v1.json` | 运行时不变量:pi-agent-core 钉住、系统提示词、工具 schema、seed 策略、资源预算、失败与检查点策略、安全块 |

### 📝 常规目录

| 目录 | 内容 |
| --- | --- |
| `docs/` | 手动执行指南、契约说明、运营文档;`docs/research/` 为研究起点文档 |
| `tests/` | 测试套件(unittest + node --test;fixture 与期望输出在其下) |
| `vendor/` | 离线 vendored 运行时归档(pi-agent-core 0.73.1) |

## 可复现性与可追溯性验收口径

**口径 v2(基线 v2 世代)**:`docs/contracts/acceptance-criteria-v2.md`(PER-328
重建,随基线 v2 冻结)。核心判定维度为时点与口径、证据血缘、结论验证、弃权与
升级,均锚定为机器可执行的 critical invariants;研究结论须按三层标注
(研究直接证据/金融推论/说明性案例)。基线 v2 校验入口:

```bash
python3 baseline/v2/validate_baseline_v2.py validate-bundle baseline/v2
python3 baseline/v2/validate_baseline_v2.py verify-manifest baseline/v2
```

口径 v1(`docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`,
PER-317 冻结)所依赖的冻结产物已随基线 v1 删除,口径 v1 自删除起失效,作为历史
记录保留原文,不追溯推翻其有效期内的历史验收(PER-323 C-323-9)。历史留痕:
Stage 1 差距报告(PER-318)、复盘证据(PER-319,`docs/retrospectives/`)、
独立审计报告(PER-320)均保留原文并追加了 PER-323 历史说明;复盘命令
`fareli-retro` 面向基线 v1 历史运行的复盘仍显式返回 `baseline_gap`(exit 2)
——基线 v2 为最小可用版本,不恢复历史运行证据。

## 环境变量(凭据纪律)

密钥**只允许**通过环境变量注入,严禁写入任何文件、日志或提示词:

- `BENCH_BAILIAN_API_KEY` — 百炼 API 密钥(必填,配置文件以名称引用它)
- `BENCH_BAILIAN_BASE_URL` / `FARELI_BAILIAN_BASE_URL` — 可选,覆盖配置文件
  `base_url`(必须是绝对 HTTP(S) URL;通用名优先)
- `FARELI_INFERENCE_CONFIG` — 可选,指向私有配置文件副本
- `BENCH_BAILIAN_MODEL_IDS` — **已退役**(模型清单回归 `configs/inference.json`);
  过渡期若仍设置,必须与配置文件模型集逐项一致,否则在任何网络请求前报错

候选模型 ID 以 `configs/inference.json` 为权威:`qwen3.8-max`(**无连字符**)、
`glm-5.2`、`deepseek-v4-pro`;模型身份预检失败时如实报告 blocked,不回退、不冒名。
持久化内容的密钥扫描门为 `financial_agent_reliability.harness.secret_scan`
(模式集只增不减)。

## 许可与来源

研究结论区分"研究直接证据 / 基于证据的金融推论 / 说明性案例",保留来源、时间、
适用范围、反例与不确定性。详见 `AGENTS.md`。
