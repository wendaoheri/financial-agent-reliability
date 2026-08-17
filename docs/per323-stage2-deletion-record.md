# PER-323 Stage 2 删除留痕记录(清理清单 v1 执行档案)

- 执行议题:PER-327;执行分支:`agent/harness/4c8db3ea`;执行日期:2026-08-17。
- 依据:冻结清理清单 v1(`docs/per323-stage1a-cleanup-list-v1-draft.md`,Stage 1a
  PER-324 产出,交付负责人于 PER-323 评论区冻结)+ 门禁裁决 C-323-8(runs/ 先归档
  后删)/ C-323-9(PER-316 空窗处置)/ C-323-10(设计契约 Q1–Q5)。
- 纪律核对:**仅删除清单内项目**;清单外内容一律未动。清单 §1D 排除项
  (CLAUDE.md、description.md、.multica/、.agent_context/、.claude/、vendor/、
  package-lock.json、uv.lock、docs/research/、src/、tests/、docs/ 本体等)全部保留。

## 1. A1–A8:❄️ 历史基线目录(git tracked,已 git rm)

执行提交:`10a9068`(分支 `agent/harness/4c8db3ea`,PR 合并后进入 main)。执行前
全量测试 40 用例与运行时测试 6/6 通过;删除后复跑同样全绿(见 §6)。

| # | 路径 | tracked 文件数 | 最后内容 commit(回滚索引)| 核实 |
| --- | --- | --- | --- | --- |
| A1 | `contracts/` | 110 | `077fcb560f02997343a1cb2bd19b5895e759e224` | 删除前逐目录 `git log -1`/`git ls-files` 复核,与冻结清单一致 |
| A2 | `cases/` | 390 | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| A3 | `catalog/` | 23 | `c68e05160ee27a88649b9440009021d90e1a9860` | 同上 |
| A4 | `snapshots/` | 121 | `c68e05160ee27a88649b9440009021d90e1a9860` | 同上 |
| A5 | `preregistration/` | 2 | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| A6 | `evidence/` | 266 | `077fcb560f02997343a1cb2bd19b5895e759e224` | 同上 |
| A7 | `audit/` | 67 | `83876cddaf8f73de9a2febbea603b64a7fe58a03` | 同上 |
| A8 | `reports/` | 30 | `f2b377b2ec3cd25945c128101ff108c7b308c8fd` | 同上 |

找回方式:`git checkout <SHA> -- <目录>` 或 `git show <SHA>:<目录>/<路径>`。
A1 按清单要求先完成 §3 迁移项 M1–M4(commit `47ae1f2`)再删除。

## 2. A9:`runs/`(gitignored,先归档后删,C-323-8)

- 归档位置(仓库外):`/Users/liuxiang/workspace/financial-agent-reliability-archive/runs-stage3-baseline-v1-20260817.tar.gz`
- 归档 sha256:`a06c95d6229572fe44dd8174d19ba288d30c476725c1da3253190976a25898ca`
- 归档内容:3972 个文件 + 2 个 symlink(tar 条目共 4053,含目录);`gzip -t` 校验通过。
- 删除:`rm -rf runs/`(原工作区克隆,2026-08-17);删除后目录不存在。
- 说明:归档为运行时本机产物,不随仓库分发;如需找回按上述路径与哈希核验。

## 3. B1–B4:已合并分支(逐一核实后删除)

核实方法:各分支 tip 均为 origin/main 历史中的提交(`git merge-base --is-ancestor`
逐一验证;`git branch -d` 安全删除模式亦要求已合并才执行)。

| # | 分支 | tip SHA | 本地删除 | 远端删除 |
| --- | --- | --- | --- | --- |
| B1 | `per317-scenario-conclusion-criteria` | `59a3ac6121eb9d03336237ef3327c29321084430` | 两个本地克隆均 `git branch -d` 成功 | `git push origin --delete` 成功 |
| B2 | `per320-stage3-independent-audit` | `f835b07368a6dbf0aa2e004e2cd7df3baa78a2c2` | 原工作区克隆 `git branch -d` 成功 | 同上 |
| B3 | `per321-criteria-codification` | `f08430227612df32a23e988157322f2b933c813a` | 原工作区克隆 `git branch -d` 成功 | 同上 |
| B4 | `refactor/python-project-layout` | `9af307b85ce40a84110b8770384bf54bc5dd2999` | 原工作区克隆 `git branch -d` 成功 | 无远端对应(清单已注明) |

重建方式:`git branch <名称> <tip-sha>`。
**不在清单内、未删除的分支(留档说明)**:`per324-cleanup-list-draft`(Stage 1
冻结产物分支,随 Stage 2 PR 内容进入 main 后由交付负责人处置)、`agent/*`
(Multica 检出工作分支)、Stage 2 本分支(合并且验收后处置)。清单冻结时点之后
新产生的分支不属于清单范围,按纪律不删。

## 4. C1–C4:gitignore 缓存与临时文件

| # | 路径 | 处置 | 重建方式 |
| --- | --- | --- | --- |
| C1 | 各 `__pycache__/` | 两个工作区均已删除 | 解释器自动重建 |
| C2 | `node_modules/` | 两个工作区均已删除 | `npm ci`(实测重建成功) |
| C3 | `.venv/` | 两个工作区均已删除 | `uv sync`(实测重建成功) |
| C4 | `attachments/`(248K) | 原工作区已删除 | `multica attachment` CLI 按需重新下载 |

删除 C2/C3 后按《手动执行指南》§2 重建并复跑全量测试通过(§6),重建路径得验证。

## 5. 迁移适配与退役清单(M1–M4 执行记录,commit `47ae1f2`)

### 5.1 src 退役(清单 M2)

`harness/acceptance_v3*.py`(13)、`harness/matrix.py`、`harness/smoke.py`、
`harness/live_acceptance_v3*.mjs`(13)、`harness/live_smoke.mjs`、
`harness/pi_runtime_v3*.mjs`(4)、`harness/diagnose_preflight_v3.mjs`、
`harness/run_manifest.v1–v4.json`(4)、`pipelines/longbridge/build_synthetic_v2.py`、
`pipelines/longbridge/freeze.py`、`relocation.py`(PER-86 冻结钉住解析层,职能随
冻结目录删除)。其中 `run_manifest.v1.json` 为 M2 所列 v2–v4 的同族前代,一并退役。
`live_smoke.mjs` 的四个纯函数能力(normalizePayload / resolveResponseModelIdentity /
buildRunPrompt / gradeStructuredCandidate)逐字迁入新文件
`harness/candidate_checks.mjs`(模型集改读 `configs/inference.json`),断言语义不变。

### 5.2 src 改接(清单 M2/M3、契约 §5)

新增 `configs/inference.json`、`configs/inference.schema.v1.json`、
`configs/harness_contract.v1.json`(supersedes 旧 v2 配置,SHA
`38c1930735e83c509bd80948a5304c83efec4f4347b3639ab5c51e63c9e5697c`)与
`inference_config.py`、`harness/secret_scan.py`(C4,模式集逐字继承 F8)、
`harness/hashing.py`。`providers/bailian.py`(含 `BailianSettings`/`BailianAdapter`/
`build_all_adapters` 公开符号)、`harness/stage3.py`、`harness/runner.py`、
`harness/cli.py`、`harness/pi_runtime.mjs` 全部改接新配置;预检输出与冻结 bundle
血缘字段改为 `inference_config_sha256` + `harness_contract_sha256`。
`pyproject.toml` sdist include 移除 5 个冻结目录名、新增 `configs`。
`redaction.py` 按契约 §5.6 扩展(只增不删)。`fareli-retro` 全部子命令显式报
「基线空窗」(exit 2);`fareli-report verify-freeze` 随基线 v1 报告契约退役。

### 5.3 测试退役与迁移(清单 M1)

- **退役**(与基线 v1 绑定):24 个 Python 测试(test_acceptance_v3*、
  test_financial_acceptance_v3_*、test_grader_contract(s)、test_harness_contracts*、
  test_case_data_contracts、test_public_cases*、test_longbridge_*、
  test_stage3_v3_6_adjudication、test_retrospective* 3 个)+ 13 个
  `tests/integration/*.test.mjs` + fixtures(acceptance_v3_* 6 目录、case_data、
  grader、harness)。
- **迁移不放松**:`tests/integration/test_harness_runtime.py`(run_trace 改为结构化
  断言替代被删校验器;血缘字段断言升级)、`tests/integration/pi_runtime.test.mjs`
  (改读 configs/ 与 candidate_checks.mjs)、`tests/test_reporting_contracts.py`
  (verify_freeze 用例改为在线 spec 自检)。
- **新增**:`tests/test_inference_config.py`(契约 §7 全部离线测试点)。
- **Stage 3 重写递延项(留档)**:oracle 重算与用例数据校验类用例
  (原 test_public_cases*/test_longbridge_*)需基线 v2 种子数据,按 M1 由 Stage 3
  (PER-328)随基线 v2 重写;递延决定与理由见交付评论。

### 5.4 文档同步(清单 M4)

- 新增:`docs/manual-execution-guide.md`(Stage 1b 草案落地)、本记录。
- README.md / AGENTS.md:修正候选模型拼写为契约权威拼写 `qwen3.8-max`(F2/F11),
  追加 PER-323 过渡状态说明;❄️ 纪律与口径 v1 段落的整体改写随 Stage 3 口径 v2
  进行(清单 G6)。
- 历史留痕文档(retrospective-report、stage1 gap report、per320 审计报告、
  stage3-sequential-smoke、harness-operations、口径 v1、run-trace/case-data/
  full-matrix 契约说明、seed-plan、reporting-contract)逐篇追加「路径已随基线 v1
  删除、可按本记录回滚索引找回」说明,原文与结论不改写。
- `docs/retrospectives/*.json` 与 `batches/*.json` 为机器可读索引,不改写 JSON
  结构,其悬空指针由本记录统一说明(与 M4「追加说明」等效,实现方式按文件格式
  调整,留档备查)。

## 6. 验证快照

| 检查点 | 结果 |
| --- | --- |
| 迁移后、删除前:`unittest discover` | 40/40 OK |
| 删除后:`unittest discover` | 40/40 OK |
| 删除后:`npm run test:runtime` / `.test.mjs` glob | 各 6/6 通过 |
| 缓存删除后按指南重建(uv sync + npm ci)+ 复跑 | 40/40 OK + 6/6 通过 |
| `fareli-harness preflight` 无凭据 | exit 1,结构化 config_error |
| `fareli-retro list` | exit 2,baseline_gap |

## 7. 密钥纪律核对

- 全程未落盘任何密钥:配置文件只含凭证环境变量名;`configs/` 两文件经
  `secret_scan.scan_persisted_file` 扫描零命中;新增配置层内置 R1/R2 硬校验。
- `BENCH_BAILIAN_BASE_URL` 覆盖值与配置文件 base_url 均为公开接入点地址(非密钥)。
