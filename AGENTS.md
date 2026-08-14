
# Project Working Agreement(项目工作规范)

These rules apply to every agent working in this directory. The auto-managed
Multica runtime block above remains authoritative for platform operations.

本文件是盘点现行目录、命名、测试、产物冻结与密钥纪律后固化的可执行规范。
与冻结产物冲突时,以证据血缘完整性为准。

## Project Purpose

- Treat `docs/research/金融Agent系统性失效问题研究报告.html` as the research
  starting point, not as a frozen standard or implementation template.
- Optimize for detecting and controlling high-loss failures, correlated errors,
  unsafe execution, and responsibility gaps in financial-agent systems.
- Keep research evidence, evidence-based financial inference, and illustrative
  examples explicitly separated.

## Repository Layout(目录语义)

顶层目录按证据血缘约束强度分为三类,全部保留在仓库根的第一层
(原因见下节"路径约定"):

| 分类 | 目录 |
| --- | --- |
| ❄️ 冻结评测产物 | `contracts/`、`preregistration/`、`snapshots/`、`runs/`、`evidence/`、`audit/`、`reports/` |
| 🔒 血缘钉住 | `harness/`、`cases/`、`catalog/`、`oracles/`、`reporting/`、`docs/`(部分)、`tests/`(被记录的文件) |
| 📝 常规 | `docs/research/`(研究文档)、`tests/`(其余)、`vendor/`(离线归档)、`attachments/`(gitignore,Multica 临时文件) |

辅助文件:`pyproject.toml`、`uv.lock`、`.python-version`(Python);
`package.json`、`package-lock.json`、`node_modules/`(gitignore)与
`vendor/mariozechner-pi-agent-core-0.73.1.tgz`(Node 运行时边界)。

## Frozen Artifacts and Evidence Lineage(冻结产物与证据血缘纪律)

1. **冻结产物内容不可修改、不可删除。** 冻结目录(❄️ 类)内的文件只能整体
   读取或原样引用;不得编辑、重写、"顺手清理"或删除其中任何文件。
2. **冻结产物的目录位置也是血缘的一部分。** 冻结审计脚本(`audit/*.py`、
   `reports/stage5/*.py` 等)以 `Path(__file__).resolve().parents[1]` 解析
   仓库根,并按根相对路径引用兄弟目录(`contracts/`、`runs/`、`cases/`、
   `tests/fixtures/`、`harness/`、`snapshots/` 等),部分检查直接对这些路径
   的文件计算 sha256。因此:**不得移动任何 ❄️/🔒 类目录,不得重命名,
   不得改变其相对层级。**
3. **被记录即被钉住。** 以下冻结产物按路径记录了文件的 sha256,记录在案的
   文件(无论在哪个目录)视同冻结:
   - `contracts/stage3_acceptance_contracts.frozen.v*.json`(bundle 的
     `artifacts` 列表;v3.7 起钉住 `pyproject.toml` 与 `uv.lock`);
   - `catalog/**/frozen_manifest.v*.json`(记录用例、快照、oracle 及
     `pipelines/` 等依赖源码的哈希);
   - `cases/**/case_card.*.json`、`snapshots/**/data_snapshot.*.json`;
   - `evidence/**/bundle.manifest.json`、`reports/stage5/*_bundle.v1.json`。
4. **改动前必查。** 移动、重命名或编辑任何文件前,先确认它未被上述产物
   记录:`grep -rn "<路径或文件名>" contracts/ catalog/ cases/ snapshots/
   evidence/ reports/ audit/`。有疑问就不动。
5. **drift 报错不是待修的 bug。** `tests/test_financial_acceptance_v3_*.py`
   中的 freeze gate 报告 `artifact drift` 时,说明有被钉住文件发生了变化;
   正确的动作是回滚改动,而不是修改测试、fixture 或冻结记录。确需演进时,
   由评测交付负责人发布新的契约版本(附书面理由),不做追溯改写。
6. **`runs/` 纪律。** `runs/` 整体 gitignore,冻结运行输出仅本地保存;
   已提交的证据血缘以 `evidence/` 的 bundle 为准。不要在 `runs/` 之外
   散落运行产物。

## Python and Environment Management

- Use `uv` exclusively for Python versions, virtual environments, dependency
  changes, locking, and command execution. 项目命令一律 `uv run <command>`。
- The supported Python baseline is 3.11, pinned in `.python-version`; the local
  environment lives in `.venv`.
- **`pyproject.toml` 与 `uv.lock` 被 v3.7 冻结 bundle 钉住**(见上节)。
  添加/删除依赖或引入 build-system 会改变这两个文件的哈希并触发 freeze gate
  drift。此类变更必须先由评测交付负责人发布新契约版本,不得单方面修改。
  在此之前,本项目是 uv 的 virtual project:依赖由 `uv sync` 安装,源码从
  仓库根导入,不打包安装。
- 不使用 `pip`、Poetry、Conda 直接管理本项目环境;不手工编辑 `uv.lock`。
- 顶层可导入包(`harness`、`contracts`、`cases`、`catalog`、`oracles`、
  `pipelines`、`providers`、`graders`、`reporting`、`simulators`)的导入名
  与目录名一致,导入名即接口,不得重命名。

## Node Runtime Boundary

- `package.json` 被冻结 harness 配置(`contracts/run_trace_harness_config.*.json`)
  按根相对路径记录,且钉死 `@mariozechner/pi-agent-core@0.73.1`。
  不得移动 `package.json`,不得升级该依赖。
- `vendor/mariozechner-pi-agent-core-0.73.1.tgz` 是离线 vendored 归档;
  `package-lock.json` 从 npm registry 解析,不引用该本地文件。
- 运行时边界验证:`npm run test:runtime`。

## Naming Conventions

- **契约版本化**:契约、schema、预注册一律带版本后缀(`*.v3.11.json`、
  `*.frozen.v2.json`);新版本另起文件,不改写旧版本。
- **四位一体命名**:每个验收契约版本对应一组同名版本后缀文件——
  `contracts/run_trace_validator_v3_X.py`、`harness/acceptance_v3_X.py`、
  `harness/live_acceptance_v3_X.mjs`、`tests/test_financial_acceptance_v3_X.py`、
  `tests/integration/financial_acceptance_v3_X.test.mjs`。新增版本时五者齐备。
- **运行目录**:`runs/stageN/<用途>-<YYYYMMDD>-vX/`;证据 bundle:
  `evidence/stageN/<运行目录名>/`。
- 测试文件 `tests/test_*.py`(unittest);fixture 在 `tests/fixtures/`,
  期望输出在 `tests/expected/`;两者被血缘钉住,改动前必查。

## Secrets Discipline(密钥纪律)

- 密钥**仅限环境变量**:`BENCH_BAILIAN_API_KEY`、`BENCH_BAILIAN_BASE_URL`、
  `BENCH_BAILIAN_MODEL_IDS`。严禁写入源码、fixture、日志、报告、提交或提示词。
- 候选模型 ID 固定为 `qwen-3.8-max`、`glm-5.2`、`deepseek-v4-pro`;模型身份
  预检失败时如实报告 blocked,不得回退或冒名。
- 日志与产物必须脱敏(`harness/redaction.py`);
  `contracts.run_trace_validator_v3_7.scan_persisted_value_for_secrets` 是
  持久化内容的密钥扫描契约门,不得绕过。

## Research and Data Discipline

- Record a source, publication date, access date when relevant, jurisdiction or
  market, and applicability limits for factual claims.
- Label conclusions as direct evidence, inference, or illustration. Preserve
  counterevidence and uncertainty instead of smoothing disagreements away.
- Never place credentials, private account data, licensed datasets, or material
  non-public information in source files, fixtures, logs, reports, or prompts.
- Use only synthetic or explicitly approved data for tests. No test or example
  may place a real order, move money, or mutate a production financial system.
  正式运行只读冻结数据。

## Implementation Conventions

- Keep executable validation logic deterministic. Freeze versioned contracts,
  schemas, preregistrations, and expected outputs before candidate evaluation;
  do not modify them after seeing candidate results without a new version and a
  documented rationale.
- Put reusable code in importable modules, tests in `tests/`, fixtures under
  `tests/fixtures/`, and human-readable design or contract notes under `docs/`.
- Preserve traceability from raw input and data snapshot through tool calls,
  intermediate decisions, grader output, and the final report.
- Prefer small, reviewable changes. Do not rewrite unrelated files or silently
  change frozen artifacts.

## Verification and Handoff

- Run the relevant focused test first, then the full suite with
  `uv run python -m unittest discover -s tests -v` before handoff;运行时边界
  另跑 `npm run test:runtime`。
- Validate generated JSON and reports against their schemas or deterministic
  expected outputs. Report the exact commands run and any unverified areas.
- A successful average score is not sufficient acceptance evidence: verify
  high-loss cases, abstention and escalation behavior, identity and time-basis
  checks, provenance, permission boundaries, and independent validation where
  the affected contract requires them.
- 交付时提供可复现命令、相关配置哈希与失败证据;无法验证的部分如实说明。
