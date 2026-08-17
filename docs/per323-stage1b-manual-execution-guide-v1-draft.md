# 手动执行指南(草案 v1)

- 议题:PER-325(PER-323 Stage 1b);产出日期:2026-08-17
- 状态:**草案 v1**。Stage 2(PER-327)正式落地到 README/docs;落地前以本文为手动执行的唯一经过实测的参考。
- 结论血缘:预设依赖 C-323-2(已有三个控制台入口,项目并非只能由 Agent 驱动)、C-323-4 / C-323-7(执行方案 v2 获项目所有者批准)。
- 实测基线:HEAD `c19a66f`(main,与 origin/main 一致),全新克隆 + 原工作区两处实测;环境为 uv 0.11.21、node v26.3.0、npm 11.16.0、Python 3.11.14(uv 按 `.python-version`=3.11 提供),macOS aarch64。全部命令实测留痕见文末附录。
- 纪律边界:本草案不执行付费模型调用与真实交易;不含任何密钥值,密钥一律只经环境变量注入;不改动冻结目录内容。

## 0. 必读前提:两类工作环境(实测发现,最重要的一条)

仓库的测试与命令分两档,**干净 git 检出无法跑全**:

| 档位 | 环境 | 能力 |
| --- | --- | --- |
| A. 裸检出 | 仅 git 克隆 | 安装、运行时边界测试、309 个 Python 用例、报告/契约离线校验、harness 清单构建 |
| B. 完整工作区 | 裸检出 + 本地冻结运行输出 `runs/`(gitignore,约 28M,仅本地保存) | 全量 328 个 Python 用例、复盘全链路(`fareli-retro` 全部子命令)、`build-smoke-plan` / `smoke` |

原因:`runs/` 在 `.gitignore` 中(口径 P1:完整性由 bundle manifest 逐件 sha256 自证 + 独立重算),14 个 unittest 用例与多个 CLI 子命令直接读取 `runs/stage3/...`。**`runs/` 的冻结子集如何分发给新操作者目前没有任何文档或机制——这是最大的"从零"缺口,已列入 F1,由 Stage 2 裁决。**

## 1. 前置环境

| 依赖 | 版本实测 | 说明 |
| --- | --- | --- |
| git | 任意现代版本 | 克隆仓库 |
| uv | 0.11.21(实测) | 唯一的 Python 环境管理器;按 `.python-version`(3.11)自动解析解释器 |
| Node.js | v26.3.0(实测) | 运行时边界测试与 `.mjs` 集成测试 |
| npm | 11.16.0(实测) | 随 Node 提供 |

```bash
git clone https://github.com/wendaoheri/financial-agent-reliability
cd financial-agent-reliability
```

## 2. 路径 A:离线验证(裸检出即可)

### 2.1 安装

```bash
uv sync     # 安装 jsonschema 等 7 个包,editable 安装本项目,注册三个控制台入口
npm ci      # 安装 @mariozechner/pi-agent-core@0.73.1(精确锁定)
```

实测:`uv sync` 后 `.venv/bin/` 出现 `fareli-harness` / `fareli-report` / `fareli-retro`;后续一律用 `uv run <入口>` 调用,无需手动激活环境。`npm ci` 输出中可能出现 `allow-scripts` 警告(针对传递依赖的 install 脚本),为信息级,不影响安装与测试。

### 2.2 Python 全量测试

```bash
uv run python -m unittest discover -s tests -v
```

| 环境 | 实测结果 |
| --- | --- |
| 裸检出 | 323 用例:**309 通过、1 失败 + 13 错误、13 跳过**——失败/错误全部因缺 `runs/`(见 F1/F4) |
| 完整工作区 | **328 用例全部通过(OK)** |

### 2.3 运行时边界测试(node)

```bash
npm run test:runtime        # node --test tests/integration/pi_runtime.test.mjs,实测 6/6 通过
```

注意:该脚本只覆盖 `pi_runtime.test.mjs`。`tests/integration/` 下其余 `.test.mjs`(验收契约的 synthetic-transport 端到端件)**当前未接入任何 npm 脚本**,且以 glob 直接运行会在当前 HEAD 失败 7 例,见 F5/F8。

### 2.4 契约与冻结件离线校验

```bash
uv run python contracts/run_trace_validator.py verify-freeze
# 实测 exit 0:{"contract_bundle_sha256": "5ab5b2a4...", "files": 13}
uv run python contracts/run_trace_validator.py validate-fixtures
# 实测 exit 0:{"accepted": 5, "expected_rejections": 1}
uv run fareli-report verify-freeze        # 实测 exit 0,报告契约冻结指针自检
uv run fareli-report validate reports/stage5/financial_agent_report_bundle.v1.json
# 实测 exit 0:810 runs、coverage complete、ranking_published=true
uv run fareli-report render reports/stage5/financial_agent_report_bundle.v1.json \
    --markdown out.md --html out.html     # 实测 exit 0,确定性渲染
```

### 2.5 三个控制台入口的手动调用

**fareli-harness(评测 harness)**

```bash
uv run fareli-harness --help
uv run fareli-harness build-manifest --output scratch/manifest.rebuilt.json
# 实测 exit 0。⚠️ 只可输出到临时路径,严禁写回 src/.../run_manifest.v3.json,见 F3
```

`build-smoke-plan` / `smoke` / `preflight` / `freeze-preflight` 子命令见 §3 与 F4。

**fareli-report(报告契约)**:`validate` / `render` / `verify-freeze`,见 §2.4。

**fareli-retro(历史轨迹复盘,全部只读离线)**

| 子命令 | 裸检出实测 | 完整工作区实测 |
| --- | --- | --- |
| `list` | exit 0(列出 20 个批次) | exit 0 |
| `run --all` | **exit 2**,untraceable=14(缺 `runs/` 的必然结果) | **exit 0**,traceable=19、partially_traceable=1 |
| `lineage` / `invalidation` | exit 0 | exit 0 |
| `archive-map` | exit 2(缺 `runs/` 归档) | exit 0 |
| `ranking` / `report-level` | exit 1(未捕获 AssertionError:sealed rows 为 0,见 F4) | exit 0 |
| `evidence [--out DIR]` | exit 1(同上;且 `--out` 必须在仓库内,见 F6) | exit 0 |

判读:完整工作区下 `run --all` 的 exit 0 是正常基线;裸检出的 exit 2 不代表检出损坏,仅代表本地冻结运行输出缺失。

## 3. 路径 B:线上预检(需环境变量;本次未实测真实请求)

### 3.1 凭据纪律

密钥**只允许**通过环境变量注入,严禁写入任何文件、日志、提示词或本文档。以下示例全部使用占位符。

### 3.2 环境变量设置

```bash
export BENCH_BAILIAN_API_KEY='<你的百炼 API 密钥,勿写入任何文件>'
export BENCH_BAILIAN_BASE_URL='https://<百炼 OpenAI 兼容接入点>/compatible-mode/v1'
export BENCH_BAILIAN_MODEL_IDS='["qwen3.8-max","glm-5.2","deepseek-v4-pro"]'
```

⚠️ **模型 ID 必须逐字符等于冻结身份集**:`qwen3.8-max`(无连字符)、`glm-5.2`、`deepseek-v4-pro`(以 `contracts/model_manifest.frozen.v2.json` 与 `src/financial_agent_reliability/providers/bailian.py` 的 `EXPECTED_MODELS` 为准)。README 目前写作 `qwen-3.8-max`,照抄会被配置门拒绝——见 F2。支持 JSON 数组或逗号分隔两种写法;URL 必须是绝对 HTTP(S) 地址。

缺失或取值错误时,配置门在任何网络请求发生之前即拒绝(已离线实测,使用占位值):

```text
BailianConfigError: missing required environment: BENCH_BAILIAN_API_KEY, ...
BailianConfigError: BENCH_BAILIAN_MODEL_IDS must contain exactly the three frozen model IDs
```

### 3.3 预检调用

```bash
uv run fareli-harness preflight --output runs/preflight.<日期>.json
```

- 逐模型执行模型身份预检(请求模板取自冻结配置 `contracts/run_trace_harness_config.v2.json`,seed 固定 20260811),重试受冻结资源预算约束。
- 退出码:0 = 三模型全部通过;2 = 存在 blocked/invalidated;1 = 配置错误(当前为原始 traceback,见 F7)。
- 判定纪律:响应模型 ID 不完全相等、检测到回退、参数未被接受或工具能力不可验证时,该模型如实记为 blocked,**不得换模型补跑、不得回退、不得冒名**。
- 预检通过后可冻结证据:`uv run fareli-harness freeze-preflight --preflight <输出文件> --destination <bundle 目录>`。
- `uv run fareli-harness build-smoke-plan --output <path>` 与 `smoke` 子命令需要完整工作区(`runs/stage3/session-20260811/preflight.v4.json`)与显式授权;当前冻结配置 `full_paid_matrix_runs_allowed=false`,只允许本地 fixture transport 的 dry-run,不得启动 810 行付费矩阵。

### 3.4 推理配置(占位,Stage 2 更新)

> **占位说明**:provider/模型可配置化改造(独立配置文件声明 provider↔模型关联,密钥仍只走环境变量)由 PER-326 产出契约草案、PER-327(Stage 2)实现。届时本节替换为配置文件的格式、路径与 `fareli-harness` 按配置运行的说明。**在 Stage 2 落地前,唯一 provider 为百炼,唯一配置途径是 §3.2 的三个 `BENCH_BAILIAN_*` 环境变量,候选模型 ID 为 §3.2 的冻结身份集。**

## 4. 实测发现的文档缺口与命令偏差(一并交由 Stage 2 处理)

| # | 发现 | 证据 | 影响与建议 |
| --- | --- | --- | --- |
| F1 | README 宣称"全量测试(328 个用例)",裸检出只能跑到 309 通过(323 收集,14 例依赖 gitignore 的本地 `runs/`);`runs/` 冻结子集的分发途径无任何文档 | 裸检出实测 1 失败 + 13 错误 + 13 跳过;失败件全部指向 `runs/stage3/...` | 最大的"从零"缺口。Stage 2 需裁决:随证据 bundle 分发 / 工作区交接流程 / 将该 14 例标注为"仅完整工作区",并在 README 注明 |
| F2 | README/部分文档写候选模型 `qwen-3.8-max`,代码与冻结契约钉住 `qwen3.8-max`(预注册 v1.1 已记录"corrected qwen id (qwen3.8-max, not qwen-3.8-max)") | 离线实测:按 README 拼写设置 `BENCH_BAILIAN_MODEL_IDS` 被配置门拒绝;按契约拼写通过 | 按 README 设置环境变量必然预检失败。Stage 2 落地指南时统一为契约拼写并修订 README |
| F3 | `docs/harness-operations.md` 的本地复现步骤将 `build-manifest` 输出写回 `src/.../run_manifest.v3.json`;当前 builder 产出 contract_version **4.0.0**(15 件 bundle,sha256 `80bee92a...`),与已提交冻结件(3.0.0,11 件,sha256 `20a546d3...`)不同世代 | 裸检出重建后逐字段 diff | 照做会用 v4 世代产物覆盖冻结 v3 清单。落地前应在该文档加警示:重建只可输出到临时路径 |
| F4 | `runs/` 依赖面未在任何文档列明:`build-smoke-plan`、`smoke`、`fareli-retro ranking/report-level/evidence/archive-map`、`run --all` 的 14 个批次、14 个 unittest 用例、`test_harness_runtime` 中 2 例 | 裸检出逐一实测(FileNotFoundError / AssertionError / exit 2) | 指南 §0 已列档;建议 Stage 2 在代码层给出更友好的"缺 runs/"错误信息 |
| F5 | `node --test tests/integration/*.test.mjs`(冻结 v3 契约所载的规范命令)在当前 HEAD 失败 7/79:7 个 synthetic-transport 端到端用例的内联校验器以 `uv run python -c` 直接 `import harness`(旧顶层包名),而 PER-86 兼容别名层要求先导入 `financial_agent_reliability` | 裸检出与完整工作区均失败,报 `ModuleNotFoundError: No module named 'harness'`;已验证别名层仅在先导入主包后生效 | 属 PER-86 迁移后的遗留漂移,在 PER-327"迁移适配受影响的测试与脚本"范围内修复;修复前该 glob 不可作为手动验收命令 |
| F6 | `fareli-retro evidence --out` 被 F7 路径策略限制在仓库内;默认输出目录 `docs/retrospectives/` 是 tracked 证据件,直接重生成会覆盖(同 HEAD 下逐字节稳定,口径 P4) | 仓外 `--out` 实测被拒并给出明确错误 | 手动操作者应先输出到仓内独立目录并 diff 后再决定是否替换 |
| F7 | `fareli-harness preflight` 缺环境变量时输出原始 Python traceback(exit 1),对手动操作者不友好 | 裸检出实测 | 建议 Stage 2 改为结构化错误提示 |
| F8 | `npm run test:runtime` 只覆盖 `pi_runtime.test.mjs`(6 例),与冻结契约所载 glob 不一致;`npm ci` 出现 allow-scripts 信息级警告 | package.json 与冻结契约 `stage3_acceptance_contracts.frozen.v3.json` 对照 | 与 F5 一并收口:明确 npm 脚本与 `.test.mjs` 集合的对应关系 |

## 5. 附录:实测记录(留痕)

实测日期 2026-08-17;裸检出位于 `../per325-manual-checkout`(由本仓库 main `c19a66f` 全新克隆,实测后工作区零改动)。

| 命令 | 裸检出 | 完整工作区 |
| --- | --- | --- |
| `git clone` + `git status --porcelain` | 干净,clean tree | — |
| `uv sync` | 7 包安装,三入口注册 | 已存在 |
| `npm ci` | pi-agent-core 0.73.1 | 已存在 |
| `uv run python -m unittest discover -s tests -v` | 323 收集:309 通过、1 失败 + 13 错误、13 跳过 | **328 全部通过** |
| `npm run test:runtime` | **6/6 通过** | 6/6 通过 |
| `node --test tests/integration/*.test.mjs` | 72 通过 / 7 失败(F5) | 72 通过 / 7 失败(F5) |
| `uv run python -m unittest tests.integration.test_harness_runtime` | 25 用例,2 错误(缺 runs/) | **25 全部通过** |
| `contracts/run_trace_validator.py verify-freeze` | exit 0,13 files,sha256 `5ab5b2a4...` | exit 0,同 |
| `contracts/run_trace_validator.py validate-fixtures` | exit 0,5 accepted / 1 expected rejection | exit 0,同 |
| `fareli-harness build-manifest --output <临时>` | exit 0,产出 4.0.0 清单(F3) | exit 0,同 |
| `fareli-harness build-smoke-plan --output <临时>` | FileNotFoundError(F4) | exit 0,36 runs / 12 tasks,plan_sha256 `c81f2fd4...` |
| `fareli-harness preflight`(无环境变量) | exit 1,BailianConfigError(F7) | 同 |
| 预检配置门(占位值,离线) | 缺变量/错拼写拒绝、正确拼写通过、密钥不出现在 repr | — |
| `fareli-report verify-freeze` | exit 0 | exit 0 |
| `fareli-report validate <stage5 bundle>` | exit 0,810 runs / coverage complete | exit 0 |
| `fareli-report render <stage5 bundle>` | exit 0 | — |
| `fareli-retro list` | exit 0,20 批次 | exit 0 |
| `fareli-retro run --all` | exit 2,untraceable=14 | **exit 0**,19 traceable + 1 partial |
| `fareli-retro lineage` / `invalidation` | exit 0 | exit 0 |
| `fareli-retro archive-map` | exit 2 | exit 0 |
| `fareli-retro ranking` / `report-level` | exit 1(F4) | exit 0 |
| `fareli-retro evidence --out <仓内目录>` | exit 1(F4) | exit 0(`--out` 仓外被拒,F6) |

未实测项(按纪律不执行):真实 `BENCH_BAILIAN_*` 密钥下的线上预检请求、`smoke` 付费矩阵(冻结配置禁止)。
