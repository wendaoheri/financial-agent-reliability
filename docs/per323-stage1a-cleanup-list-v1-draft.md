# 清理清单 v1 草案（PER-323 Stage 1a，只读盘点产物）

- 任务：PER-324（PER-323 Stage 1a）。本草案为只读盘点产物，**未删除、未修改任何受控内容**；须经评测交付负责人裁决冻结后，Stage 2（PER-327）才据此执行删除。
- 结论血缘（预设依赖）：
  - C-323-4：执行方案获批准（用户已确认，PER-323 D1）
  - C-323-5：采用方案 B，推翻 PER-85-D6，删除 ❄️ 历史基线（用户已确认，PER-323 D2）
  - C-323-6：删除后重新建立基线（用户已确认，PER-323 D2）
  - C-323-7：执行方案 v2 获批准（用户已确认，PER-323 D3）
- 盘点基线：仓库 `financial-agent-reliability`，main 与 origin/main 一致、工作区干净；`git rev-parse HEAD` = `f08430227612df32a23e988157322f2b933c813a`（盘点时点）。
- 引用影响明细：见附录 A（逐文件引用计数，盘点命令见附录 B）。

---

## 1. 删除候选清单（逐项）

### 1A. ❄️ 历史基线目录（9 项）

依据：C-323-5（方案 B，推翻 PER-85-D6）。逐项留痕如下（大小为 `du -sh` 工作区占用；tracked 数为 `git ls-files` 计数）。

| # | 路径 | tracked 文件数 | 大小 | 最后内容 commit | 理由 | 风险 | 删除方式 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `contracts/` | 110 | 2.7M | `077fcb5`（2026-08-14） | v3.x 契约世代（candidate_output_contracts、wire contract、run_trace_validator_*、grader、harness config 等），随基线 v1 废弃 | **高**：被 21 个 Python 测试文件与 21 个 src 模块以包形式 import（`from contracts...`）；`fareli-harness`、`npm run test:runtime` 运行时读取其配置 | Stage 2 先完成 §3 迁移项 M1–M4，再 `git rm -r contracts/` + commit |
| A2 | `cases/` | 390 | 3.9M | `077fcb5`（2026-08-14） | v3.x 用例（candidate_v3*、public、longbridge），基线 v1 用例集 | 中：`cases.public.oracle/oracle_reference` 被 2 个测试 import；多个 harness/测试引用用例路径 | 同上，`git rm -r cases/` |
| A3 | `catalog/` | 23 | 380K | `c68e051`（2026-08-11） | seed catalog 与 frozen_manifest（longbridge/public） | 中：`harness/matrix.py`、`run_manifest.v2/v3/v4.json`、`test_harness_runtime.py` 引用 | `git rm -r catalog/` |
| A4 | `snapshots/` | 121 | 608K | `c68e051`（2026-08-11） | 冻结数据快照（longbridge/public） | 中：`acceptance_v3_9/v3_10`、`matrix.py`、`build_synthetic_v2.py`、`freeze.py` 及多个 tests/fixtures 引用 | `git rm -r snapshots/` |
| A5 | `preregistration/` | 2 | 44K | `077fcb5`（2026-08-14） | benchmark 预注册 v1/v1.1 | 低：`matrix.py`、run_manifest、`test_grader_contract_v2.py`、口径 v1 文档各 1 处引用 | `git rm -r preregistration/` |
| A6 | `evidence/` | 266 | 1.5M | `077fcb5`（2026-08-14） | stage3 证据 bundle 正本（bundle.manifest 等） | 中：复盘工具链（`retrospective/registry.py` 等）与 docs/retrospectives 血缘索引指向此处；是 runs/frozen-runtime-archive 的正本 | `git rm -r evidence/` |
| A7 | `audit/` | 67 | 2.2M | `83876cd`（2026-08-14） | 旧审计/构建脚本（stage3、per32 系列） | 中：`tests/test_stage3_v3_6_adjudication.py` import `audit.*`；复盘 registry 引用 | `git rm -r audit/` |
| A8 | `reports/` | 30 | 1.7M | `f2b377b`（2026-08-14） | stage3/stage5 交付报告与证据 zip | 低：`retrospective/labels.py`、`report_level.py` 与 3 篇 docs 引用 | `git rm -r reports/` |
| A9 | `runs/` | **0（gitignored，从未入库）** | 28M | 无 | 本地冻结运行输出（`runs/stage3` 27M + `runs/frozen-runtime-archive` 1.2M） | **高且不可按原设缓解**：见 §2 风险 R1——删除后无法从 git 历史找回 | **待裁决**：建议删除前先打包归档（见 §2 R1 处置选项）；归档后再 `rm -rf runs/`（无需 git 操作，目录已在 .gitignore） |

### 1B. 已合并 git 分支（7 项）

核实方法：`git branch --merged main` / `git rev-list --count main..<branch>` 全部为 0（已逐一确认并入 main，无未合并提交）。

| # | 分支 | 位置 | tip SHA | 删除方式 |
| --- | --- | --- | --- | --- |
| B1 | `per317-scenario-conclusion-criteria` | 本地+远端 | `59a3ac6121eb9d03336237ef3327c29321084430` | `git branch -d` + `git push origin --delete` |
| B2 | `per320-stage3-independent-audit` | 本地+远端 | `f835b07368a6dbf0aa2e004e2cd7df3baa78a2c2` | 同上 |
| B3 | `per321-criteria-codification` | 本地+远端 | `f08430227612df32a23e988157322f2b933c813a` | 同上 |
| B4 | `refactor/python-project-layout` | 仅本地 | `9af307b85ce40a84110b8770384bf54bc5dd2999` | `git branch -d`（无远端对应） |

注：B1–B3 的 tip 均已是 main 历史中的提交，删除分支不丢失任何提交。

### 1C. gitignore 的缓存与临时文件

| # | 路径 | 大小 | 理由 | 重建方式 |
| --- | --- | --- | --- | --- |
| C1 | 各 `__pycache__/`（含 src/、tests/、以及冻结目录内的 `contracts/__pycache__`、`audit/__pycache__`、`cases/public/__pycache__`、`cases/public/v2/__pycache__`） | 小 | Python 字节码缓存 | 解释器自动重建；冻结目录内者随 A1/A2/A7 一并删除 |
| C2 | `node_modules/` | 132M | npm 依赖本地副本 | `npm ci`（按 `package-lock.json` 精确重建） |
| C3 | `.venv/` | 3.1M | uv 虚拟环境 | `uv sync`（按 `uv.lock` 重建） |
| C4 | `attachments/` | 248K（7 个文件） | Multica issue 附件下载的工作副本（历史审计/验收材料） | 可经 `multica attachment` CLI 按需重新下载；非源产物 |

注：`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、`dist/`、`build/` 盘点时点不存在，无需处理。

### 1D. 明确排除项（不列入删除）

- Multica 平台本地运行文件：`CLAUDE.md`、`description.md`、`.multica/`、`.agent_context/`、`.claude/` —— 当前 Agent 运行所需平台文件，非项目产物。
- `vendor/`（离线 pi-agent-core 归档 tgz）、`package-lock.json`、`uv.lock`、`docs/research/`（研究起点材料）—— 活的依赖与研究基线，不属于历史基线废弃内容。
- `src/`、`tests/`、`docs/`、`package.json`、`pyproject.toml` 本体不删；其中受影响的引用按 §3 在 Stage 2 迁移适配。

## 2. 回滚索引（git SHA）

盘点时点：`HEAD = f08430227612df32a23e988157322f2b933c813a`（= origin/main）。

| 目录 | 最后内容 commit（完整 SHA） | 找回方式 |
| --- | --- | --- |
| `contracts/` | `077fcb560f02997343a1cb2bd19b5895e759e224` | `git checkout <SHA> -- contracts/` 或 `git show <SHA>:contracts/<path>` |
| `cases/` | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| `catalog/` | `c68e05160ee27a88649b9440009021d90e1a9860` | 同上 |
| `snapshots/` | `c68e05160ee27a88649b9440009021d90e1a9860` | 同上 |
| `preregistration/` | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| `evidence/` | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| `audit/` | `83876cddaf8f73de9a2febbea603b64a7fe58a03` | 同上 |
| `reports/` | `f2b377b2ec3cd25945c128101ff108c7b308c8fd` | 同上 |
| `runs/` | **无（从未被 git 跟踪，.gitignore 排除）** | 见风险 R1 |

分支回滚：§1B 表中 tip SHA 均可通过 `git branch <name> <tip-sha>` 重建。

**风险 R1（须在冻结裁决时处置）：`runs/` 不可从 git 历史找回。**
父议题结论作废声明中的缓解表述（"全部历史内容仍可从 git 历史按 commit SHA 找回"）对 `runs/` 不成立——`git log --all -- runs` 为空。实际构成：
- `runs/frozen-runtime-archive/`（1.2M，220 文件）：为 `evidence/stage3/` 正本的逐字节一致子集（PER-318 差距报告已抽查验证，见 `docs/stage1-historical-trace-inventory-gap-report.v1.md` 第 15、102 行）——在 `evidence/` 被删除**之前**可经其正本恢复；`evidence/` 删除后此兜底也随之消失。
- `runs/stage3/`（27M，约 3750 文件）：本地运行输出（含 smoke/acceptance/preflight/coverage 运行目录；其中 `acceptance-20260812-v3.5`、`-v3.8` 为指向 `evidence/stage3/` 的 symlink，其余为未入库实体文件）——**删除即永久丢失**。
处置选项（请交付负责人裁决）：
  - 选项 1（建议）：Stage 2 删除前将 `runs/` 打包为 tar.gz 移交仓库外存储（如 Multica 附件/本地资源目录），清单中记录归档位置与哈希后再删；
  - 选项 2：确认 `runs/stage3` 的运行输出已被 `evidence/` bundle 充分覆盖、可接受永久丢失，直接删除（需明确书面确认）。
  注：此前只读盘点（C-323-1）曾建议保留 `runs/`；D2 方案 B 决定删除，本项按删除候选列入，但以上不可逆性必须先裁决。

## 3. 引用影响分析与 Stage 2 迁移适配建议

盘点范围内（`tests/`、`src/`、`docs/`、`package.json`、`pyproject.toml`、`AGENTS.md`、`README.md`；仓库无 `scripts/` 目录）共 **115 个文件、约 640 处引用**指向删除目标：tests 56 个文件、src 28 个、docs 29 个、根级 2 个（AGENTS.md、README.md）；另有 `pyproject.toml` 5 处裸名引用。逐文件明细见附录 A。

关键影响面（删除后若不适配将直接失败）：

| 影响类 | 具体位置 | 失败方式 |
| --- | --- | --- |
| Python 包导入断裂 | 21 个测试文件 `from contracts.* / cases.* / audit.* import ...`（清单见附录 A）；src 侧 21 个模块同样 import（`harness/acceptance_v3*.py`、`matrix.py`、`runner.py`、`smoke.py`、`stage3.py`、`pipelines/longbridge/build_synthetic_v2.py`、`freeze.py`、`retrospective/hashing.py`、`scenario_check.py`） | `unittest discover` 收集期 ImportError |
| 运行时配置钉住 | `providers/bailian.py:14 CONFIG_PATH = contracts/run_trace_harness_config.v2.json`；`harness/runner.py`、`matrix.py` 同；`harness/live_*.mjs`、`pi_runtime_v3*.mjs`、`diagnose_preflight_v3.mjs` 钉住 v3.x 配置 | `fareli-harness preflight/smoke` 及全部 live 脚本 FileNotFoundError |
| npm 运行时测试 | `tests/integration/pi_runtime.test.mjs` 读 `contracts/run_trace_harness_config.v2.json` | `npm run test:runtime` 失败 |
| 复盘工具链钉住 | `retrospective/registry.py`：`ARCHIVE_ROOT = runs/frozen-runtime-archive`、`EVIDENCE/REPORTS/AUDIT` 根、各批次 `config_file=contracts/run_trace_harness_config.v3.*.json`；`labels.py`、`lineage.py`、`report.py`、`report_level.py`、`archive_map.py` 引用 `evidence/ audit/ reports/ runs/` | `fareli-retro` 全部子命令失败 |
| 打包声明 | `pyproject.toml` `[tool.hatch.build.targets.sdist].include` 含 `contracts cases catalog snapshots preregistration` | sdist 构建告警/缺失 |
| 文档指针 | AGENTS.md（❄️ 纪律整节、PER-85-D6、口径 v1 段）、README.md、`docs/retrospectives/*`（lineage-index 27 处 runs/、retrospective-index 等）、`docs/stage1-...gap-report`、`docs/stage3-independent-audit-per320-report`、`docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`、`docs/harness-operations.md`、`docs/stage3-sequential-smoke.md` | 指针悬空（不阻断运行，但口径与血缘文档失真） |
| 测试 fixture 内嵌路径 | `tests/fixtures/acceptance_v3_*`、`tests/fixtures/harness/run_trace.*.json`、`tests/expected/reporting/*` 中内嵌 `snapshots/ cases/ contracts/ evidence/` 路径串 | 相应测试断言/加载失败 |

Stage 2 迁移适配建议（逐项，供 PER-327 执行）：

- **M1 测试迁移/退役**：与基线 v1 绑定的测试（21 个 import 冻结包的 py 测试 + 13 个引用冻结目录的 `*.test.mjs` + 依赖 fixture 的用例）随旧基线整体退役；其中验证「活能力」的用例（run_trace 校验、grader 逻辑、oracle 重算）改写为基于基线 v2 种子数据的新测试，而非原样保留。全量 `unittest discover` 与 `npm run test:runtime` 必须在 Stage 2 收尾重新全绿。
- **M2 src 迁移**：`harness/` 下 v3.x 验收链（acceptance_v3*.py、live_*.mjs、pi_runtime_v3*.mjs、diagnose_preflight_v3.mjs、run_manifest.v2–v4.json）与 `pipelines/longbridge/` 的 build/freeze 属旧基线管线，建议整体退役；`runner.py/matrix.py/smoke.py/stage3.py/cli.py` 中对 `contracts/run_trace_harness_config.*.json` 的钉住改接 Stage 2c 新配置文件（PER-326 契约）；`retrospective/` 工具链随 Stage 3 基线 v2 重建（registry/labels/lineage/archive_map 的根路径与批次表全部重写），重建前 `fareli-retro` 应显式报"基线空窗"而非静默失败。
- **M3 配置与打包**：`pyproject.toml` sdist include 移除 5 个冻结目录名；`providers/bailian.py` CONFIG_PATH 改读新配置文件（密钥仍只走环境变量）。
- **M4 文档同步**：AGENTS.md/README.md 的 ❄️ 纪律、PER-85-D6、口径 v1 段随 Stage 3 口径 v2 一并改写；`docs/retrospectives/*`、PER-318/320 报告等历史留痕文档**保留原文**，仅追加「路径已随基线 v1 删除，内容可按 §2 回滚索引 SHA 从 git 历史找回」的说明，不改写历史结论。

## 4. 口径空窗期影响清单

口径 v1（`docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`，PER-317 冻结）依赖冻结产物做证据血缘；删除后至基线 v2/口径 v2 冻结（Stage 3）前为空窗期。受影响清单：

| # | 受影响项 | 状态 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| G1 | PER-316（调整评测可复现要求， umbrella） | in_review | 其验收依据即口径 v1 与复盘证据链；删除后引用的证据路径失效，口径 v1 作废 | 在 Stage 2 执行前收口（完成或明示转入以口径 v2 验收），避免悬置；请交付负责人裁决 |
| G2 | PER-325（Stage 1b 手动执行指南草案，进行中） | todo/进行中 | 指南实测依赖现状命令（`fareli-harness` 预检读冻结配置、全量测试含冻结依赖用例）；Stage 2 后命令面变化 | 草案按现状实测 + 占位标注 Stage 2 变更点，Stage 2 收尾时同步更新（其任务描述已预设） |
| G3 | PER-326（Stage 1c 推理配置契约草案，进行中） | todo/进行中 | 新配置须承接被删的 `contracts/run_trace_harness_config.v2.json`；草案文件不得放入删除清单目录 | 与 M3 对齐；新配置文件落在 `src/` 或仓库根部新路径 |
| G4 | PER-327–331（Stage 2–6） | backlog | 本身按清单执行，不受空窗影响，但以本清单冻结为前置 | 本草案冻结后再提升 |
| G5 | `docs/retrospectives/*`（PER-318/319 复盘证据）与 PER-320 审计报告 | 已完成、留痕在库 | 指针悬空（指向被删目录）；`fareli-retro` 不可复跑 | 按 M4 追加历史说明；复跑能力待基线 v2 |
| G6 | AGENTS.md / README.md 中口径 v1 固化段（PER-321 产物） | 已完成、留痕在库 | 口径失效但文档仍指向 v1 | Stage 3 口径 v2 冻结时同步改写 |

空窗期约束（建议随清单冻结一并生效）：空窗期内不启动任何以口径 v1 为依据的新验收；新运行产物一律暂存待基线 v2 收编；并行任务（G2/G3）继续执行但不得新建对冻结目录的依赖。

## 5. 冻结裁决待决项汇总

1. **R1：`runs/` 不可逆删除的处置**（选项 1 先归档后删 / 选项 2 书面确认直接删）。
2. **G1：PER-316 在空窗期前是否收口**。
3. M1 中「退役 vs 改写」的具体测试边界由 Stage 2 执行者按基线 v2 种子确定，如与验收口径 v2 冲突以交付负责人裁决为准。

---

## 附录 A：逐文件引用明细（按删除目标分组，计数为单文件内匹配行数）

```text
===== contracts =====
AGENTS.md:3
README.md:1
docs/harness-operations.md:2
docs/retrospectives/lineage-index.v1.json:6
docs/retrospectives/retrospective-index.v1.json:2
docs/retrospectives/retrospective-report.v1.md:2
docs/stage3-independent-audit-per320-report.v1.md:3
docs/stage3-sequential-smoke.md:2
src/financial_agent_reliability/__init__.py:1
src/financial_agent_reliability/harness/acceptance_v3.py:1
src/financial_agent_reliability/harness/acceptance_v3_10.py:25
src/financial_agent_reliability/harness/acceptance_v3_11.py:23
src/financial_agent_reliability/harness/acceptance_v3_11_1.py:5
src/financial_agent_reliability/harness/acceptance_v3_6.py:10
src/financial_agent_reliability/harness/acceptance_v3_7.py:6
src/financial_agent_reliability/harness/acceptance_v3_8.py:20
src/financial_agent_reliability/harness/acceptance_v3_9.py:20
src/financial_agent_reliability/harness/diagnose_preflight_v3.mjs:2
src/financial_agent_reliability/harness/live_acceptance_v3_6.mjs:1
src/financial_agent_reliability/harness/run_manifest.v2.json:2
src/financial_agent_reliability/harness/run_manifest.v3.json:2
src/financial_agent_reliability/harness/run_manifest.v4.json:6
src/financial_agent_reliability/pipelines/longbridge/build_synthetic_v2.py:1
src/financial_agent_reliability/pipelines/longbridge/freeze.py:1
src/financial_agent_reliability/retrospective/__init__.py:1
src/financial_agent_reliability/retrospective/lineage.py:1
src/financial_agent_reliability/retrospective/report.py:3
src/financial_agent_reliability/retrospective/report_level.py:2
src/financial_agent_reliability/retrospective/scenario_check.py:3
tests/fixtures/harness/run_trace.identity_mismatch.json:1
tests/fixtures/harness/run_trace.normal.json:1
tests/fixtures/harness/run_trace.rate_limit_retry.json:1
tests/fixtures/harness/run_trace.recovery.json:1
tests/fixtures/harness/run_trace.secret_leak.json:1
tests/fixtures/harness/run_trace.timeout.json:1
tests/integration/acceptance_v3.test.mjs:1
tests/integration/acceptance_v3_1.test.mjs:1
tests/integration/acceptance_v3_2.test.mjs:1
tests/integration/acceptance_v3_3.test.mjs:1
tests/integration/acceptance_v3_4.test.mjs:2
tests/integration/financial_acceptance_v3_10.test.mjs:2
tests/integration/financial_acceptance_v3_11.test.mjs:2
tests/integration/financial_acceptance_v3_11_1_coverage.test.mjs:4
tests/integration/financial_acceptance_v3_5.test.mjs:1
tests/integration/financial_acceptance_v3_6.test.mjs:1
tests/integration/financial_acceptance_v3_7.test.mjs:2
tests/integration/financial_acceptance_v3_8.test.mjs:2
tests/integration/financial_acceptance_v3_9.test.mjs:2
tests/integration/pi_runtime.test.mjs:1
tests/test_financial_acceptance_v3_11_1.py:3
tests/test_grader_contract_v2.py:5
tests/test_retrospective_offline.py:1
===== cases =====
AGENTS.md:1
src/financial_agent_reliability/harness/acceptance_v3_10.py:7
src/financial_agent_reliability/harness/acceptance_v3_11.py:3
src/financial_agent_reliability/harness/acceptance_v3_11_1.py:1
src/financial_agent_reliability/harness/acceptance_v3_6.py:2
src/financial_agent_reliability/harness/acceptance_v3_9.py:7
src/financial_agent_reliability/harness/matrix.py:3
src/financial_agent_reliability/pipelines/longbridge/build_synthetic_v2.py:2
src/financial_agent_reliability/reporting/report.py:7
src/financial_agent_reliability/retrospective/report.py:1
tests/fixtures/acceptance_v3_10/grader.average_contract.json:1
tests/fixtures/acceptance_v3_10/grader.baseline.json:1
tests/fixtures/acceptance_v3_10/grader.bounded_retry.json:1
tests/fixtures/acceptance_v3_10/grader.ftw_workflow.json:1
tests/fixtures/acceptance_v3_11/grader.average_contract.json:1
tests/fixtures/acceptance_v3_11/grader.baseline.json:1
tests/fixtures/acceptance_v3_11/grader.bounded_retry.json:1
tests/fixtures/acceptance_v3_11/grader.ftw_workflow.json:1
tests/fixtures/acceptance_v3_6/grader.baseline.json:1
tests/fixtures/acceptance_v3_7/grader.baseline.json:1
tests/fixtures/acceptance_v3_8/grader.baseline.json:1
tests/fixtures/acceptance_v3_9/grader.baseline.json:1
tests/fixtures/acceptance_v3_9/grader.fkw03.decimal_contract.json:1
tests/fixtures/harness/run_trace.identity_mismatch.json:1
tests/fixtures/harness/run_trace.normal.json:1
tests/fixtures/harness/run_trace.rate_limit_retry.json:1
tests/fixtures/harness/run_trace.recovery.json:1
tests/fixtures/harness/run_trace.secret_leak.json:1
tests/fixtures/harness/run_trace.timeout.json:1
tests/integration/acceptance_v3.test.mjs:1
tests/integration/acceptance_v3_1.test.mjs:1
tests/integration/financial_acceptance_v3_5.test.mjs:1
tests/integration/financial_acceptance_v3_6.test.mjs:1
tests/integration/test_harness_runtime.py:3
tests/test_financial_acceptance_v3_9.py:2
tests/test_longbridge_synthetic_v2.py:1
===== catalog =====
AGENTS.md:1
src/financial_agent_reliability/harness/matrix.py:8
src/financial_agent_reliability/harness/run_manifest.v2.json:2
src/financial_agent_reliability/harness/run_manifest.v3.json:15
src/financial_agent_reliability/harness/run_manifest.v4.json:15
src/financial_agent_reliability/pipelines/longbridge/build_synthetic_v2.py:4
src/financial_agent_reliability/pipelines/longbridge/freeze.py:1
tests/integration/test_harness_runtime.py:8
tests/test_longbridge_synthetic_v2.py:1
===== snapshots =====
AGENTS.md:1
docs/stage1-historical-trace-inventory-gap-report.v1.md:1
src/financial_agent_reliability/harness/acceptance_v3_10.py:10
src/financial_agent_reliability/harness/acceptance_v3_9.py:5
src/financial_agent_reliability/harness/matrix.py:2
src/financial_agent_reliability/harness/run_manifest.v3.json:2
src/financial_agent_reliability/harness/run_manifest.v4.json:2
src/financial_agent_reliability/pipelines/longbridge/build_synthetic_v2.py:3
src/financial_agent_reliability/pipelines/longbridge/freeze.py:1
tests/fixtures/acceptance_v3_10/grader.average_contract.json:3
tests/fixtures/acceptance_v3_10/grader.baseline.json:2
tests/fixtures/acceptance_v3_10/grader.bounded_retry.json:2
tests/fixtures/acceptance_v3_10/grader.ftw_workflow.json:2
tests/fixtures/acceptance_v3_10/oracle_visibility.negative.json:8
tests/fixtures/acceptance_v3_10/trace.ledger_restored.json:1
tests/fixtures/acceptance_v3_10/trace.multi_request_retry.json:1
tests/fixtures/acceptance_v3_11/grader.average_contract.json:3
tests/fixtures/acceptance_v3_11/grader.baseline.json:2
tests/fixtures/acceptance_v3_11/grader.bounded_retry.json:2
tests/fixtures/acceptance_v3_11/grader.ftw_workflow.json:2
tests/fixtures/acceptance_v3_11/oracle_visibility.negative.json:8
tests/fixtures/acceptance_v3_11/trace.ledger_restored.json:1
tests/fixtures/acceptance_v3_7/grader.baseline.json:2
tests/fixtures/acceptance_v3_7/trace.multi_request_retry.json:1
tests/fixtures/acceptance_v3_8/grader.baseline.json:2
tests/fixtures/acceptance_v3_8/trace.ledger_restored.json:1
tests/fixtures/acceptance_v3_8/trace.multi_request_retry.json:1
tests/fixtures/acceptance_v3_9/grader.baseline.json:2
tests/fixtures/acceptance_v3_9/grader.fkw03.decimal_contract.json:2
tests/fixtures/acceptance_v3_9/oracle_visibility.negative.json:5
tests/fixtures/acceptance_v3_9/trace.ledger_restored.json:1
tests/fixtures/acceptance_v3_9/trace.multi_request_retry.json:1
tests/fixtures/harness/run_trace.identity_mismatch.json:1
tests/fixtures/harness/run_trace.normal.json:1
tests/fixtures/harness/run_trace.rate_limit_retry.json:1
tests/fixtures/harness/run_trace.recovery.json:1
tests/fixtures/harness/run_trace.secret_leak.json:1
tests/fixtures/harness/run_trace.timeout.json:1
tests/integration/test_harness_runtime.py:2
tests/test_financial_acceptance_v3_9.py:2
tests/test_longbridge_synthetic_v2.py:3
===== preregistration =====
docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md:1
src/financial_agent_reliability/harness/matrix.py:1
src/financial_agent_reliability/harness/run_manifest.v2.json:1
src/financial_agent_reliability/harness/run_manifest.v3.json:1
src/financial_agent_reliability/harness/run_manifest.v4.json:1
tests/test_grader_contract_v2.py:1
===== evidence =====
AGENTS.md:1
docs/retrospectives/archive-map.v1.json:2
docs/retrospectives/batches/acceptance-v3.5.v1.json:1
docs/retrospectives/batches/acceptance-v3.8.v1.json:1
docs/retrospectives/lineage-index.v1.json:7
docs/retrospectives/retrospective-index.v1.json:4
docs/retrospectives/retrospective-report.v1.md:1
docs/stage1-historical-trace-inventory-gap-report.v1.md:2
src/financial_agent_reliability/retrospective/labels.py:2
src/financial_agent_reliability/retrospective/lineage.py:1
src/financial_agent_reliability/retrospective/registry.py:4
tests/expected/reporting/report.partial.valid.md:18
tests/fixtures/reporting/report.partial.valid.json:22
tests/test_retrospective.py:2
tests/test_retrospective_integration.py:4
tests/test_retrospective_offline.py:1
===== audit =====
AGENTS.md:1
docs/retrospectives/batches/acceptance-v3.10.v1.json:2
docs/retrospectives/batches/acceptance-v3.11.v1.json:2
docs/retrospectives/batches/acceptance-v3.8.v1.json:2
docs/retrospectives/batches/acceptance-v3.9.v1.json:2
docs/retrospectives/batches/coverage-v3.11.1.v1.json:2
docs/retrospectives/retrospective-index.v1.json:10
docs/stage1-historical-trace-inventory-gap-report.v1.md:1
src/financial_agent_reliability/__init__.py:1
src/financial_agent_reliability/harness/live_acceptance_v3_11.mjs:1
src/financial_agent_reliability/reporting/report.py:1
src/financial_agent_reliability/retrospective/registry.py:5
src/financial_agent_reliability/retrospective/report.py:1
tests/integration/financial_acceptance_v3_11_1_coverage.test.mjs:1
tests/test_stage3_v3_6_adjudication.py:1
===== reports =====
AGENTS.md:1
docs/retrospectives/retrospective-index.v1.json:1
docs/stage1-historical-trace-inventory-gap-report.v1.md:2
src/financial_agent_reliability/retrospective/labels.py:1
src/financial_agent_reliability/retrospective/report_level.py:1
===== runs =====
docs/retrospectives/archive-map.v1.json:2
docs/retrospectives/batches/acceptance-v3.1.v1.json:1
docs/retrospectives/batches/acceptance-v3.10.v1.json:1
docs/retrospectives/batches/acceptance-v3.11.v1.json:1
docs/retrospectives/batches/acceptance-v3.2.v1.json:1
docs/retrospectives/batches/acceptance-v3.3.v1.json:1
docs/retrospectives/batches/acceptance-v3.4.v1.json:1
docs/retrospectives/batches/acceptance-v3.9.v1.json:1
docs/retrospectives/batches/acceptance-v3.v1.json:1
docs/retrospectives/batches/coverage-v3.11.1.v1.json:1
docs/retrospectives/batches/frozen-preflight-evidence-v1.v1.json:1
docs/retrospectives/batches/frozen-preflight-evidence-v2.v1.json:1
docs/retrospectives/batches/frozen-preflight-evidence-v3.v1.json:1
docs/retrospectives/batches/frozen-preflight-evidence-v4.v1.json:1
docs/retrospectives/batches/frozen-smoke-evidence-v1.v1.json:1
docs/retrospectives/batches/frozen-smoke-evidence-v2.v1.json:1
docs/retrospectives/batches/session-20260811.v1.json:1
docs/retrospectives/batches/smoke-v1.v1.json:1
docs/retrospectives/batches/smoke-v2.v1.json:1
docs/retrospectives/lineage-index.v1.json:27
docs/retrospectives/retrospective-index.v1.json:20
docs/retrospectives/retrospective-report.v1.md:1
docs/stage1-historical-trace-inventory-gap-report.v1.md:2
docs/stage3-independent-audit-per320-report.v1.md:3
docs/stage3-sequential-smoke.md:1
src/financial_agent_reliability/harness/acceptance_v3_1.py:1
src/financial_agent_reliability/harness/acceptance_v3_11.py:3
src/financial_agent_reliability/harness/acceptance_v3_11_1.py:9
src/financial_agent_reliability/harness/acceptance_v3_2.py:1
src/financial_agent_reliability/harness/diagnose_preflight_v3.mjs:2
src/financial_agent_reliability/retrospective/labels.py:1
src/financial_agent_reliability/retrospective/lineage.py:1
src/financial_agent_reliability/retrospective/registry.py:5
src/financial_agent_reliability/retrospective/report.py:3
tests/integration/financial_acceptance_v3_11_1_coverage.test.mjs:3
tests/test_financial_acceptance_v3_11.py:1
tests/test_financial_acceptance_v3_11_1.py:1
tests/test_retrospective_integration.py:4
tests/test_retrospective_offline.py:4
```

## 附录 B：盘点命令（可复现）

```bash
git rev-parse HEAD                          # 盘点基线 SHA
git ls-files <dir> | wc -l                  # 各目录 tracked 文件数
git log -1 --format='%H %ad %s' -- <dir>    # 各目录最后内容 commit
git branch --merged main                    # 分支合并核实
git rev-list --count main..<branch>         # 未合并提交数（全部为 0）
git log --all -- runs                       # 核实 runs/ 从未入库（空输出）
grep -RI --exclude-dir={node_modules,.venv,.git,__pycache__,<dir>} \
     -cE "(^|[\"' /(])<dir>/" tests src docs AGENTS.md README.md package.json pyproject.toml
grep -RIl -E '^(from|import) (contracts|cases|audit)( |\.|$)' src tests --include='*.py'
```
