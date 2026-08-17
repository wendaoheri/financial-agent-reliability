# 手动执行指南(PER-323 Stage 2 落地版 v1)

- 状态:**落地版**。由 Stage 1b 草案(`docs/per323-stage1b-manual-execution-guide-v1-draft.md`)按 Stage 2 实际改造落地;草案中的占位与 F1–F8 发现已按本文收口。
- 议题:PER-327(PER-323 Stage 2);结论血缘:C-323-2、C-323-4/7(方案 v2 用户已批准)、C-323-10(推理配置设计契约裁决)。
- 实测基线:2026-08-17,分支 `agent/harness/4c8db3ea`(基于 main `f084302` + Stage 2 提交),全新裸检出;uv 0.11.21、node v26.3.0、npm 11.16.0、Python 3.11.14。
- 纪律边界:密钥一律只经环境变量注入,不落盘、不入文档;不执行付费模型矩阵与真实交易。

## 0. 工作环境:裸检出即可跑全(PER-323 清理后)

Stage 1b 草案曾区分「裸检出 / 完整工作区」两档,差异全部来自 gitignore 的本地
`runs/`。PER-323 Stage 2 已按冻结清理清单删除基线 v1(含 `runs/`,删除前已归档,
见 `docs/per323-stage2-deletion-record.md`),依赖它的旧基线测试随之退役或迁移,
**干净 git 检出现在可以跑全量验证**:

| 能力 | 命令 |
| --- | --- |
| Python 全量测试(62 用例) | `uv run python -m unittest discover -s tests -v` |
| node 运行时边界(6 用例) | `npm run test:runtime` |
| 集成 `.test.mjs` 全集 | `node --test tests/integration/*.test.mjs`(集合与上一行相同,F5/F8 已收口) |
| 基线 v2 校验(Stage 3 起) | `python3 baseline/v2/validate_baseline_v2.py validate-bundle baseline/v2` 与 `verify-manifest baseline/v2` |
| 预检(离线可演练错误路径) | `uv run fareli-harness preflight --output <path>` |

复盘工具链(`fareli-retro`)与基线 v1 的历史运行绑定;基线 v1 已删除且基线 v2
为最小可用版本、不恢复历史运行证据,因此所有子命令显式返回
`{"status": "baseline_gap", ...}` 并以退出码 2 结束。这是预期行为,不是检出损坏。

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

## 2. 安装

```bash
uv sync     # 安装依赖并以 editable 方式安装本项目,注册 fareli-harness / fareli-report / fareli-retro
npm ci      # 按 package-lock.json 精确安装 @mariozechner/pi-agent-core@0.73.1
```

`npm ci` 可能出现 `allow-scripts` 信息级警告(传递依赖的 install 脚本审查提示),
不影响安装与测试(实测留痕)。后续一律 `uv run <入口>`,无需手动激活环境。

## 3. 路径 A:离线验证(无需任何凭据)

```bash
uv run python -m unittest discover -s tests -v   # 实测:62 用例全部通过(OK,Stage 3)
npm run test:runtime                             # 实测:6/6 通过
node --test tests/integration/*.test.mjs         # 实测:6/6 通过(与 npm 脚本同集合)
python3 baseline/v2/validate_baseline_v2.py validate-bundle baseline/v2   # 实测:ok
python3 baseline/v2/validate_baseline_v2.py verify-manifest baseline/v2   # 实测:ok
```

三个控制台入口的离线行为:

```bash
uv run fareli-harness --help          # 子命令:preflight / freeze-preflight
uv run fareli-harness preflight --output scratch/preflight.json
# 无凭据时实测:exit 1,输出结构化错误(不再抛原始 traceback,F7 已修复):
#   {"error": "missing required environment: BENCH_BAILIAN_API_KEY", "status": "config_error"}
uv run fareli-report --help           # 子命令:validate / render(报告 bundle 由基线 v2 重建后提供)
uv run fareli-retro list              # 基线空窗期:exit 2,{"status": "baseline_gap", ...}
```

说明:基线 v1 的 `build-manifest` / `build-smoke-plan` / `smoke` 子命令已随 v3.x
验收链退役(清理清单 M2);`fareli-report verify-freeze` 随基线 v1 报告契约退役。
Stage 3 基线 v2 冻结后按新契约恢复相应入口。

## 4. 路径 B:线上预检(需环境变量;本文不执行真实请求)

### 4.1 凭据纪律

密钥**只允许**通过环境变量注入,严禁写入任何文件、日志、提示词或本文档。

### 4.2 推理配置文件(Stage 2 新)

provider 与候选模型现在由 `configs/inference.json` 声明(schema:
`configs/inference.schema.v1.json`;运行时不变量在 `configs/harness_contract.v1.json`):

```json
{
  "providers": [{ "name": "bailian", "credential_env": "BENCH_BAILIAN_API_KEY", "...": "..." }],
  "models": [{ "model_id": "qwen3.8-max", "provider": "bailian", "roles": ["candidate"], "...": "..." }]
}
```

- 解析顺序:CLI `--config <path>` > 环境变量 `FARELI_INFERENCE_CONFIG` > 默认
  `configs/inference.json`。
- 配置文件**不含密钥**:只保存凭证环境变量的名称;密钥值只存在于环境变量与内存。
- 增改 provider/模型:直接编辑 `configs/inference.json`,或用
  `FARELI_INFERENCE_CONFIG` 指向私有副本(私有副本同样不得含密钥值)。
- 模型 ID 权威拼写以配置文件为准:`qwen3.8-max`(**无连字符**)、`glm-5.2`、
  `deepseek-v4-pro`(F2 已修复,README/AGENTS.md 同步更正)。

### 4.3 环境变量

```bash
export BENCH_BAILIAN_API_KEY='<你的百炼 API 密钥,勿写入任何文件>'
# 可选:覆盖配置文件中的接入点(必须是绝对 HTTP(S) URL)
export BENCH_BAILIAN_BASE_URL='https://<百炼 OpenAI 兼容接入点>/compatible-mode/v1'
# 或通用命名(优先级高于上一行):
export FARELI_BAILIAN_BASE_URL='https://<百炼 OpenAI 兼容接入点>/compatible-mode/v1'
```

- `base_url` 缺省取配置文件值(百炼公开接入点),设置覆盖变量时以环境变量优先。
- `BENCH_BAILIAN_MODEL_IDS` 已退役(模型清单回归配置文件)。**过渡期严格一致
  校验(C-323-10/Q3)**:若仍设置该变量,其解析结果必须与配置文件中 bailian 的
  模型集逐项一致,否则在任何网络请求前报错;不再需要设置它。
- 缺失凭据或配置非法时,配置门在任何网络请求前拒绝,输出结构化
  `config_error`(exit 1)。

### 4.4 预检调用

```bash
uv run fareli-harness preflight --output runs/preflight.<日期>.json
# 可选:--config <自定义 inference.json 路径>
```

- 按配置文件对每个 `live_preflight_required=true` 的模型执行身份预检(系统提示词、
  工具 schema 与资源预算来自 `configs/harness_contract.v1.json`,seed 固定 20260811)。
- 退出码:0 = 全部通过;2 = 存在 blocked/invalidated;1 = 配置错误(结构化输出)。
- 结果 JSON 含 `inference_config_sha256` 与 `harness_contract_sha256` 两个契约哈希
  (取代旧 `harness_config_sha256` / `model_manifest_sha256` 的血缘职能)。
- **判定纪律**:响应模型 ID 不完全相等、检测到回退、参数未被接受或工具能力不可
  验证时,该模型如实记为 blocked,不得换模型补跑、不得回退、不得冒名。
- 预检通过后可冻结证据:
  `uv run fareli-harness freeze-preflight --preflight <输出文件> --destination <bundle 目录>`
  (bundle 内附两份契约文件副本与对账决策)。

## 5. 实测记录(留痕)

实测日期 2026-08-17,裸检出(删除缓存后按 §2 重建,验证重建路径本身):

| 命令 | 结果 |
| --- | --- |
| `uv sync` | 成功,三入口注册 |
| `npm ci` | pi-agent-core 0.73.1;allow-scripts 信息级警告 |
| `uv run python -m unittest discover -s tests -v` | Stage 2 实测 **40 用例通过**;Stage 3(PER-328)新增基线 v2 套件后为 **62 用例全部通过(OK)** |
| `npm run test:runtime` | **6/6 通过** |
| `node --test tests/integration/*.test.mjs` | **6/6 通过** |
| `uv run fareli-harness preflight --output ...`(无凭据) | exit 1,结构化 `config_error`(F7 修复验证) |
| `uv run fareli-retro list` | exit 2,`baseline_gap` 显式提示 |
| `uv run fareli-report --help` | exit 0(validate/render 两子命令) |

未实测项(按纪律不执行):真实密钥下的线上预检请求与任何付费矩阵。
