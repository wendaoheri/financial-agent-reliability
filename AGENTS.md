
# Project Working Agreement(项目工作规范)

These rules apply to every agent working in this directory. The auto-managed
Multica runtime block above remains authoritative for platform operations.

本文件是盘点现行目录、命名、测试、产物冻结与密钥纪律后固化的可执行规范。
与冻结产物冲突时,以证据血缘完整性为准。

> **PER-323 状态(2026-08-17,Stage 3)**:基线 v1 的 ❄️ 旧血缘历史基线已按
> 项目所有者批准的方案 B 与冻结清理清单 v1 整体删除——下文「Frozen Artifacts」
> 与口径 v1 各节自删除起转为**历史记录**(原文保留,不改写)。现行冻结世代为
> **基线 v2**(`baseline/v2/`,最小可用重建,PER-328):冻结纪律与之一致——
> 基线 v2 工件冻结后不改不删、修订只增版本;验收与复盘判读以口径 v2
> (`docs/contracts/acceptance-criteria-v2.md`)为准。删除留痕与回滚索引:
> `docs/per323-stage2-deletion-record.md`;手动执行:
> `docs/manual-execution-guide.md`;推理 provider/模型由 `configs/inference.json`
> 配置,运行时不变量在 `configs/harness_contract.v1.json`。

## Project Purpose

- Treat `docs/research/金融Agent系统性失效问题研究报告.html` as the research
  starting point, not as a frozen standard or implementation template.
- Optimize for detecting and controlling high-loss failures, correlated errors,
  unsafe execution, and responsibility gaps in financial-agent systems.
- Keep research evidence, evidence-based financial inference, and illustrative
  examples explicitly separated.

## Repository Layout(目录语义)

PER-85 用户裁决(D4/D5/D6)后,布局分为"活的代码包"与"旧血缘历史基线"两层:

| 分类 | 位置 |
| --- | --- |
| 📦 代码包(src 布局,唯一可编辑代码区) | `src/financial_agent_reliability/`(`harness`、`graders`、`oracles`、`pipelines`、`providers`、`reporting`、`simulators` 子包) |
| 🧪 测试 | `tests/`(unittest)、`tests/integration/`(Python + node --test)、fixture/期望输出在 `tests/fixtures/`、`tests/expected/` |
| ❄️ 旧血缘历史基线(内容不可修改、不可删除) | `contracts/`、`preregistration/`、`snapshots/`、`runs/`、`evidence/`、`audit/`、`reports/`、`catalog/`、`cases/` |
| 📝 常规 | `docs/`(契约说明、验收口径 `docs/contracts/`、复盘证据 `docs/retrospectives/`、运营文档、`docs/research/` 研究起点)、`vendor/`(离线运行时归档)、`attachments/`(gitignore,Multica 临时文件) |

辅助文件:`pyproject.toml`、`uv.lock`、`.python-version`(Python);
`package.json`、`package-lock.json`、`node_modules/`(gitignore)与
`vendor/mariozechner-pi-agent-core-0.73.1.tgz`(Node 运行时边界)。

代码包以标准 src 布局打包安装(uv sync 安装为 editable 包),顶层导入名为
`financial_agent_reliability`;`contracts` 与 `cases.public` 等旧血缘 Python
模块保留在仓库根,由包初始化时把仓库根加回 `sys.path` 后按原名导入。

## Frozen Artifacts and Evidence Lineage(冻结产物与证据血缘纪律)

PER-85-D6:旧 v3.x 冻结血缘降级为**历史基线**——内容保留、不改不删,但其
路径/哈希钉住不再构成重构与验收的阻塞。按现行可复现口径(见下节),历史
运行以轨迹日志复盘验收,暂不要求全量重跑;若未来裁决重启重跑,重跑产物
以新契约版本建立新血缘、不回写旧 bundle(新契约版本发布须由评测交付负责
人裁决)。在此前提下:

1. **旧血缘内容不可修改、不可删除。** ❄️ 目录内的文件只能整体读取或原样
   引用;不得编辑、重写、"顺手清理"或删除其中任何文件,也不得向这些目录
   新增文件。
2. **旧路径钉住按迁移映射解析,而不是移动冻结记录。** PER-86 把代码包移入
   `src/financial_agent_reliability/` 后,冻结产物中钉住的旧代码路径由
   `financial_agent_reliability/relocation.py` 统一解析:迁移后内容逐字节
   一致的文件按新位置校验;因重构机械改写(导入路径、ROOT 深度、mjs 相对
   URL)而变更的文件由 `CONTENT_CHANGED_BY_REFACTOR`、
   `TESTS_CHANGED_BY_REFACTOR`、`ROOT_CONFIG_CHANGED_BY_REFACTOR` **逐条
   点名放行,禁止静默跳过**。新增放行条目必须对应真实的机械改写,并在提交
   信息中说明。
3. **被记录即被钉住(历史基线语义)。** 以下冻结产物按路径记录了文件的
   sha256,其承诺值本身(文档完整性)仍然逐字节校验;对已迁移代码文件的
   哈希钉住按上条解析:
   - `contracts/stage3_acceptance_contracts.frozen.v*.json`(bundle 的
     `artifacts` 列表;v3.7 起钉住 `pyproject.toml` 与 `uv.lock`);
   - `catalog/**/frozen_manifest.v*.json`(记录用例、快照、oracle 及
     pipeline 源码的哈希);
   - `cases/**/case_card.*.json`、`snapshots/**/data_snapshot.*.json`;
   - `evidence/**/bundle.manifest.json`、`reports/stage5/*_bundle.v1.json`。
4. **旧冻结脚本的处置。** `audit/` 等旧脚本按三类对待,全部保留原文:
   - 仅读取未移动冻结目录的脚本仍可直接运行;
   - 按旧包名(`from harness...`)导入的 Python 脚本,先
     `import financial_agent_reliability`(注册旧名兼容别名)即可继续导入;
   - 以相对路径引用旧 `harness/*.mjs` 的 node 驱动脚本声明废弃,仅作历史
     记录。旧脚本内部针对重构前路径/哈希的校验结论一律按历史记录对待。
5. **改动前必查。** 移动、重命名或编辑任何文件前,先确认它未被冻结产物
   记录:`grep -rn "<路径或文件名>" contracts/ catalog/ cases/ snapshots/
   evidence/ reports/ audit/`。被记录且仍在原位的文件(未迁移类)不得改动。
6. **drift 报错的处理边界。** 针对**新契约版本**建立后的产物,drift 仍按
   原纪律处理(回滚改动,不改测试与冻结记录);针对旧 v3.x 历史基线的
   drift,只能通过 relocation 放行清单机制处理,且每次放行都必须被点名。
   演进一律发布新契约版本(附书面理由),不做追溯改写。
7. **`runs/` 纪律。** `runs/` 整体 gitignore,冻结运行输出仅本地保存;
   已提交的证据血缘以 `evidence/` 的 bundle 为准。不要在 `runs/` 之外
   散落运行产物。`runs/` 等 gitignore 目录不在 git 覆盖范围,其完整性
   依据为 **bundle manifest 逐件 sha256 自证 + 独立重算**;git 零改动
   验证仅对 tracked 目录主张(PER-320 审计 P1 纠正)。

## Reproducibility and Traceability Acceptance Criteria(可复现性与可追溯性验收口径)

- **现行验收标准**:评测运行验收与事后复盘以
  `docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md`(口径 v1,
  PER-317 冻结;只增版本、不改写)为准。配套:Stage 1 历史轨迹盘点与差距报告
  `docs/stage1-historical-trace-inventory-gap-report.v1.md`(PER-318);Stage 2
  复盘工具链与证据 `src/financial_agent_reliability/retrospective/` 与
  `docs/retrospectives/`(PER-319);Stage 3 独立审计报告
  `docs/stage3-independent-audit-per320-report.v1.md`(PER-320,审计通过)。
- **口径内容(PER-316-D1,用户已确认)**:验收口径 = 场景与结论可复现可追溯
  (历史轨迹日志复盘)。场景输入可由冻结产物原样重建、逐件 sha256 对上;
  评分与排名结论可由落盘轨迹与冻结评分件确定性重算推导、逐位一致。复盘
  入口为证据 bundle 的 `bundle.manifest.json`,方法按口径文档第 3 节执行;
  复盘命令为 `uv run fareli-retro run --all` 与 `uv run fareli-retro evidence`。
- **代码级重放不作要求及其边界**(口径文档 1.3):不要求模型输出确定性重放、
  不要求代码+环境依赖逐哈希重建重跑、不要求重新访问提供商端点或外部数据源。
  继续要求的是:落盘证据内容完整(逐 sha256 校验)与评分/聚合的确定性重算。
  放弃的是"重放执行",不放弃的是"证据完整 + 结论可重算"。
- **协议门批次判读约束(PER-320 审计 P3)**:v3–v3.4 协议门批次与
  frozen-preflight v1–v4 等 H1 标注批次按设计无验收运行,其定位是**协议/
  身份门证据**;明文禁止将这些批次引用为评分/排名证据,其结论边界限于协议
  与模型身份预检判定,复盘判定须逐批留痕(scope_note/H1 标注)。
- **复盘证据稳定性限定(PER-320 审计 P4)**:`fareli-retro evidence` 产物的
  字节级稳定性仅在**同一 HEAD** 下成立——证据内嵌 `git_commit` 锚点,跨
  HEAD 再生成仅该字段变化,其余逐字节一致;引用稳定性结论时必须附"同一
  HEAD"限定。
- **runs/ 完整性口径(PER-320 审计 P1)**:见冻结纪律第 7 条——gitignore
  目录的完整性以 bundle manifest 逐件 sha256 自证 + 独立重算为依据;git
  零改动验证仅对 tracked 目录主张。
- **PER-257-D10 收口**:契约 v4 世代方案(暂缓事项)按 PER-316 新口径
  **收口关闭**——不再以代码级重放为设计目标;未来如需代码级重放,另行
  立项。未来发布新契约世代时,须把口径文档第 2 节六节点字段作为最小集
  纳入,或书面说明差异并另起口径版本(口径文档 4.4)。

## Python and Environment Management

- Use `uv` exclusively for Python versions, virtual environments, dependency
  changes, locking, and command execution. 项目命令一律 `uv run <command>`。
- The supported Python baseline is 3.11, pinned in `.python-version`; the local
  environment lives in `.venv`.
- 本项目是标准 src 布局的可安装包:`uv sync` 以 editable 方式安装
  `financial-agent-reliability`(hatchling 后端),并生成三个控制台入口:
  `fareli-harness`(评测 harness CLI)、`fareli-report`(报告契约 CLI)与
  `fareli-retro`(历史轨迹复盘 CLI,见上节验收口径)。
  PER-85-D6 解除了旧 v3.7 bundle 对 `pyproject.toml`/`uv.lock` 的钉住后,
  依赖与打包配置的变更不再需要契约豁免,但仍须走正常评审与锁定流程
  (`uv lock`),不手工编辑 `uv.lock`。
- 不使用 `pip`、Poetry、Conda 直接管理本项目环境。
- 顶层导入名:代码一律 `financial_agent_reliability.*`;`contracts`、
  `cases.public` 等旧血缘模块按原名从仓库根导入。旧顶层包名
  (`harness` 等)仅由兼容别名层为冻结脚本保留,不得用于新代码。

## Node Runtime Boundary

- `package.json` 被冻结 harness 配置(`contracts/run_trace_harness_config.*.json`)
  按根相对路径记录,且钉死 `@mariozechner/pi-agent-core@0.73.1`。
  不得移动 `package.json`,不得升级该依赖。
- `vendor/mariozechner-pi-agent-core-0.73.1.tgz` 是离线 vendored 归档;
  `package-lock.json` 从 npm registry 解析,不引用该本地文件。
- 运行时边界验证:`npm run test:runtime`。harness 的 `.mjs` 运行时随代码包
  位于 `src/financial_agent_reliability/harness/`,其相对路径解析已按新深度
  调整;新增 `.mjs` 必须沿用同一 ROOT 解析方式。

## Naming Conventions

- **契约版本化**:契约、schema、预注册一律带版本后缀(`*.v3.11.json`、
  `*.frozen.v2.json`);新版本另起文件,不改写旧版本。
- **四位一体命名**:每个验收契约版本对应一组同名版本后缀文件——
  `contracts/run_trace_validator_v3_X.py`、
  `src/financial_agent_reliability/harness/acceptance_v3_X.py`、
  `src/financial_agent_reliability/harness/live_acceptance_v3_X.mjs`、
  `tests/test_financial_acceptance_v3_X.py`、
  `tests/integration/financial_acceptance_v3_X.test.mjs`。新增版本时五者齐备。
- **运行目录**:`runs/stageN/<用途>-<YYYYMMDD>-vX/`;证据 bundle:
  `evidence/stageN/<运行目录名>/`。
- 测试文件 `tests/test_*.py`(unittest);fixture 在 `tests/fixtures/`,
  期望输出在 `tests/expected/`;被旧血缘记录的文件改动前必查。

## Secrets Discipline(密钥纪律)

- 密钥**仅限环境变量**:`BENCH_BAILIAN_API_KEY`(必填);
  `BENCH_BAILIAN_BASE_URL` / `FARELI_BAILIAN_BASE_URL` 与
  `FARELI_INFERENCE_CONFIG` 为可选覆盖。严禁写入源码、fixture、日志、报告、
  提交或提示词。`BENCH_BAILIAN_MODEL_IDS` 已退役(过渡期严格一致校验,
  PER-323 契约 §4.1)。
- 候选模型 ID 以 `configs/inference.json` 为权威:`qwen3.8-max`(无连字符)、
  `glm-5.2`、`deepseek-v4-pro`;模型身份预检失败时如实报告 blocked,不得回退
  或冒名。
- 日志与产物必须脱敏(`financial_agent_reliability.harness.redaction`);
  `financial_agent_reliability.harness.secret_scan.scan_persisted_value_for_secrets`
  是持久化内容的密钥扫描契约门(PER-323 C4,模式集自旧冻结门逐字继承、
  只增不减),不得绕过。

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
- Put reusable code in `src/financial_agent_reliability/` subpackages, tests in
  `tests/`, fixtures under `tests/fixtures/`, and human-readable design or
  contract notes under `docs/`.
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
