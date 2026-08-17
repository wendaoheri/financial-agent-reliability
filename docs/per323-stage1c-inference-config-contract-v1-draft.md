# 通用推理配置契约草案 v1（PER-323 Stage 1c，设计契约待冻结）

状态：**草案**（由评测交付负责人裁决冻结后成为设计契约，Stage 2 据此实现）
议题：PER-326（父议题 PER-323，方案 v2 已获批准，结论 C-323-7）
盘点时点：`HEAD = 8b4e1c1b50f9be888fc7e51f0f7524fdde65e4f7`（分支 `per324-cleanup-list-draft`，= origin 同名分支）
纪律声明：本草案为纯文档产物——未改动任何代码、未执行付费模型调用、不含任何真实密钥（示例全部为占位值）。

## 0. 摘要

本契约设计一套 provider ↔ 模型可配置的通用推理层：

1. **独立配置文件** `configs/inference.json`（JSON，随仓库提交，不含密钥），以 JSON Schema `inference_config.schema.v1.json` 校验；声明 provider 列表（名称、API 类型、base_url、凭证环境变量名、默认请求参数）与模型列表（精确模型 ID、所属 provider、角色标签、身份核验规则）。
2. **环境变量命名规范**：密钥一律只走环境变量、不落盘；配置文件只保存环境变量的**名称**；命名规则避开密钥扫描契约门的误报模式（§4）。
3. **迁移与兼容**：`providers/bailian.py`（`BailianSettings`）成为「可配置 provider 之一」的适配路径，公开类名与模块路径不变；`fareli-harness preflight` 按配置运行；钉住模型 ID 的 `live_*.mjs` 随清理清单 M2 整体退役；`BENCH_BAILIAN_*` 环境变量保持向后兼容（§5）。
4. **新契约版本清单**：旧 `contracts/run_trace_harness_config.v2.json` 随冻结目录删除，其内容按字段拆分由「推理配置文件 + 新 harness 契约」承接；`model_manifest.frozen.v2.json` 被配置文件 `models` 段吸收，不再发新版本（§6）。

位置约束（C-323-5）：新配置文件与新契约**不放入任何删除清单目录**（`contracts/ cases/ catalog/ snapshots/ preregistration/ evidence/ audit/ reports/ runs/`），落在新建顶层目录 `configs/`（与清理清单 G3 建议「src/ 或仓库根部新路径」一致；见 §8 Q1）。

## 1. 现状锚点（设计依据，均为盘点时点只读事实）

| # | 事实 | 位置 |
| --- | --- | --- |
| F1 | `BailianSettings.from_env` 只读 `BENCH_BAILIAN_API_KEY/BASE_URL/MODEL_IDS`；`MODEL_IDS` 支持 JSON 数组或逗号分隔，且必须逐字符等于 `EXPECTED_MODELS` | `src/financial_agent_reliability/providers/bailian.py:30-61` |
| F2 | `EXPECTED_MODELS = ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro")` 硬编码 | `providers/bailian.py:15` |
| F3 | 请求模板（system_prompt、tools、request_parameters、preflight 指令）读自冻结目录 `contracts/run_trace_harness_config.v2.json`（模块级 `CONFIG_PATH` 钉住） | `providers/bailian.py:13-14, 88-105` |
| F4 | 同一钉住还存在于 `harness/runner.py:25`、`harness/smoke.py:23,157`、`harness/stage3.py:20`、`harness/matrix.py:81,447`；`tests/integration/pi_runtime.test.mjs` 亦读取该文件 | src 侧 5 个模块 + npm 运行时测试 |
| F5 | `live_smoke.mjs` 与 12 个 `live_acceptance_v3*.mjs` 钉住模型 ID（如 `ALLOWED_MODELS`）与 `BENCH_BAILIAN_*` 环境变量 | `src/financial_agent_reliability/harness/*.mjs` |
| F6 | 模型身份清单（logical_label、allowed_response_model_ids、identity_rule=exact_response_match、live_preflight_required）冻结于 `contracts/model_manifest.frozen.v2.json` | 冻结目录（将删除） |
| F7 | `endpoint_id` 策略：`bailian_<sha256(origin)[:12]>`，origin 不含 path/query/凭证 | `providers/bailian.py:49-60`、`model_manifest.frozen.v2.json` |
| F8 | 密钥扫描契约门：`contracts.run_trace_validator_v3_7.scan_persisted_value_for_secrets`，`SECRET_KEYS={api_key, authorization, bearer_token, password, client_secret, access_token}`，`SECRET_TEXT=(?i)(Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})` | `contracts/run_trace_validator_v3_7.py:20-22,44-57`（该文件将随冻结目录删除，扫描门须在新契约中重建，见 §6 C4） |
| F9 | 日志脱敏：`harness/redaction.py` 字段集 + 3 个值模式（含针对 `BENCH_BAILIAN_API_KEY=...` 文本的专项模式） | `src/financial_agent_reliability/harness/redaction.py:11-27` |
| F10 | 预检入口：`fareli-harness preflight --output`（`cli.py:53-71`，exit 0=passed / 2=失败）与 `freeze-preflight`（其中 `stage3.py:146` 硬编码三模型列表做对账） | `harness/cli.py`、`harness/stage3.py` |
| F11 | 模型 ID 权威拼写为 `qwen3.8-max`（无连字符）：`model_manifest.frozen.v2.json` 的 supersedes 记录载明「workspace owner corrected the Bailian qwen model id from qwen-3.8-max to qwen3.8-max」。README/AGENTS.md 中的 `qwen-3.8-max` 为笔误（Stage 1b 指南 F2 已记录），Stage 2 文档落地时一并修正 | `model_manifest.frozen.v2.json:5-9` |

结论血缘：C-323-3（百炼现状，上表 F1–F10 为其细化实证）、C-323-4/C-323-7（方案及方案 v2 获批准）、C-323-5（冻结目录删除、新文件不得入删除清单目录）。

## 2. 配置文件位置与布局

```
configs/                                # 新建顶层目录（不在任何删除清单内）
├── inference.schema.v1.json            # 配置文件的 JSON Schema（契约，冻结后只按版本演进）
├── inference.json                      # 默认运行配置（提交入库；只含非密钥内容）
└── harness_contract.v1.json            # 新 harness 契约（承接旧 v2 配置的 harness 部分，§6 C3）
```

- **解析顺序**：显式路径（CLI `--config`）> 环境变量 `FARELI_INFERENCE_CONFIG` > 默认 `configs/inference.json`（相对仓库根）。
- **入库策略**：`inference.json` 不含密钥（凭证只有环境变量名），直接提交，保证检出即可离线校验；用户增改 provider/模型通过修改该文件（或 `FARELI_INFERENCE_CONFIG` 指向私有副本）完成。
- **演进规则**：schema 破坏性变更升大版本并新增文件（`inference.schema.v2.json`），旧版本文件保留一个过渡期；配置文件顶部 `schema_version` 声明其遵循的 schema 版本，加载器严格匹配。

## 3. 配置文件 schema

### 3.1 顶层结构

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `contract_type` | string | 是 | 恒等于 `"inference_config"`（加载器据此拒收错文件） |
| `schema_version` | string | 是 | semver；当前 `"1.0.0"`，必须与 schema 文件主版本一致 |
| `providers` | array | 是 | ≥1 项；`name` 全局唯一；单项见 §3.2 |
| `models` | array | 是 | ≥1 项；`model_id` 全局唯一；单项见 §3.3 |

跨字段校验（schema 之外的加载器规则）：

1. 每个 `models[].provider` 必须命中某个 `providers[].name`；
2. 每个 provider 的 `credential_env` 互不相同；
3. `models[].allowed_response_model_ids`（若给出）必须包含其 `model_id`；
4. 任何字段名不得落入密钥扫描门 `SECRET_KEYS` 集合（§4 规则 R1）；任何字符串值不得命中 `SECRET_TEXT`（§4 规则 R2）——加载器把这两条作为硬校验，命中即拒收。

### 3.2 `providers[]` 单项

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `name` | string | 是 | `^[a-z][a-z0-9_-]{0,31}$`，全局唯一；同时是 `endpoint_id` 前缀与默认凭证环境变量名的构成部分 |
| `description` | string | 否 | ≤200 字符，仅说明用途 |
| `api` | string | 是 | 枚举：`"openai_chat_completions_compatible"`（v1 唯一取值；新增 API 族走 schema 新版本） |
| `base_url` | string | 是 | 绝对 HTTP(S) URL（scheme ∈ {http, https} 且有 hostname）。非密钥，直接入库；可被环境变量覆盖（§3.5） |
| `credential_env` | string | 是 | 承载该 provider 密钥的**环境变量名**：`^[A-Z][A-Z0-9_]{2,63}$`；只存名称、永不存值；命名须通过 §4 误报规避校验 |
| `default_parameters` | object | 否 | 该 provider 的默认请求参数，键限白名单：`temperature`（6 位小数字符串，如 `"0.000000"`）、`top_p`（同前）、`max_tokens`（正整数）、`stream`（bool）。缺省 `{temperature:"0.000000", top_p:"1.000000", max_tokens:4096, stream:true}`（与现行冻结值逐字一致，保证迁移零行为漂移） |
| `tool_choice` | string | 否 | 枚举：`"auto"`（v1 唯一取值。现行实证：`"required"` 被 qwen/deepseek 拒绝、被 glm 忽略，见 `bailian_http.py:64-69`） |
| `timeout_seconds` | number | 否 | 1–600，缺省 120（与现行 `BailianHTTPTransport` 一致） |
| `preflight_tool_instruction` | string | 否 | 预检用户指令，缺省 `"Call read_frozen_case with case_id PREFLIGHT."`（沿用旧 v2 配置 provider 块） |

### 3.3 `models[]` 单项

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `model_id` | string | 是 | **精确模型 ID**（请求与响应逐字符核验用）：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，全局唯一。例：`qwen3.8-max`（注意无连字符，F11） |
| `provider` | string | 是 | 引用 `providers[].name` |
| `roles` | array[string] | 是 | ≥1 项；每项 `^[a-z][a-z0-9_]{0,31}$`；初始词表仅 `"candidate"`（基准候选模型；预检对全部 `live_preflight_required=true` 的模型执行，不按 roles 过滤）。扩词表走 schema 新版本（§8 Q4） |
| `logical_label` | string | 否 | 人读标签，缺省等于 `model_id` |
| `identity_rule` | string | 否 | 枚举：`"exact_response_match"`（v1 唯一取值，沿用 `model_manifest.frozen.v2.json`） |
| `allowed_response_model_ids` | array[string] | 否 | 响应 `model` 字段的允许集，缺省 `[model_id]`；必须含 `model_id` |
| `live_preflight_required` | bool | 否 | 缺省 `true` |
| `parameter_overrides` | object | 否 | 覆盖 provider `default_parameters` 的同名键（键白名单相同，不含 seed 相关项）；用于个别模型的参数差异 |

### 3.4 示例文件（`configs/inference.json` 默认实例，占位 base_url）

```json
{
  "contract_type": "inference_config",
  "schema_version": "1.0.0",
  "providers": [
    {
      "name": "bailian",
      "description": "阿里云百炼 OpenAI 兼容端点（现行唯一 provider，兼容 BENCH_BAILIAN_* 环境变量）",
      "api": "openai_chat_completions_compatible",
      "base_url": "https://dashscope.example.invalid/compatible-mode/v1",
      "credential_env": "BENCH_BAILIAN_API_KEY",
      "default_parameters": {
        "temperature": "0.000000",
        "top_p": "1.000000",
        "max_tokens": 4096,
        "stream": true
      },
      "tool_choice": "auto",
      "timeout_seconds": 120,
      "preflight_tool_instruction": "Call read_frozen_case with case_id PREFLIGHT."
    }
  ],
  "models": [
    {
      "model_id": "qwen3.8-max",
      "provider": "bailian",
      "roles": ["candidate"],
      "identity_rule": "exact_response_match",
      "allowed_response_model_ids": ["qwen3.8-max"],
      "live_preflight_required": true
    },
    {
      "model_id": "glm-5.2",
      "provider": "bailian",
      "roles": ["candidate"],
      "identity_rule": "exact_response_match",
      "allowed_response_model_ids": ["glm-5.2"],
      "live_preflight_required": true
    },
    {
      "model_id": "deepseek-v4-pro",
      "provider": "bailian",
      "roles": ["candidate"],
      "identity_rule": "exact_response_match",
      "allowed_response_model_ids": ["deepseek-v4-pro"],
      "live_preflight_required": true
    }
  ]
}
```

说明：`base_url` 为占位值（`example.invalid`），冻结裁决时由交付负责人按现行 `BENCH_BAILIAN_BASE_URL` 实际值语义确认（真实 URL 非密钥，可入库；若所有者要求不入库，则 `base_url` 写占位、以环境变量覆盖为准，见 §3.5 与 §8 Q5）。

### 3.5 优先级与覆盖规则（加载器行为契约）

1. `base_url`：环境变量覆盖 > 配置文件（仅当对应覆盖变量已设置且为绝对 HTTP(S) URL，否则报错）；
2. 请求参数：`model.parameter_overrides` > `provider.default_parameters` > schema 缺省；
3. 密钥：仅来自 `credential_env` 指向的环境变量，无其他来源；缺失即在任何网络请求前报错（沿用现行 fail-fast，`bailian.py:37-39`）；
4. seed 策略（`seed_required` 与预检 seed `20260811`）不属于 provider/模型可变项，归 harness 契约（§6 C3），配置文件不得表达。

## 4. 环境变量命名规范

### 4.1 变量表

| 用途 | 命名 | 必填 | 说明 |
| --- | --- | --- | --- |
| provider 密钥（新 provider 通用式） | `FARELI_<PROVIDER>_API_KEY`（`<PROVIDER>` 为 provider `name` 大写、`-` 转 `_`） | 该 provider 参与运行时必填 | 例：`FARELI_MOONSHOT_API_KEY`。值永不落盘 |
| 百炼密钥（兼容默认） | `BENCH_BAILIAN_API_KEY` | 是（bailian 为默认 provider） | 配置文件中 bailian 的 `credential_env` 默认即此名；现有文档、运行手册与用户环境不受影响 |
| base_url 覆盖（可选） | `FARELI_<PROVIDER>_BASE_URL`；bailian 兼容名 `BENCH_BAILIAN_BASE_URL` | 否 | 设置时覆盖配置文件 `base_url`；必须为绝对 HTTP(S) URL |
| 配置文件路径（可选） | `FARELI_INFERENCE_CONFIG` | 否 | 覆盖默认路径 `configs/inference.json` |
| 模型 ID 列表（**退役**） | `BENCH_BAILIAN_MODEL_IDS` | 否 | 模型清单回归配置文件。过渡期兼容规则：若环境中仍存在该变量，其解析结果必须与配置文件中 bailian provider 的模型集**逐项一致**，否则在任何网络请求前报错（严格一致，杜绝静默分叉）；Stage 3 基线 v2 冻结后彻底移除支持 |

### 4.2 密钥纪律（不变式）

- 密钥只走环境变量：不写入配置文件、源码、fixture、日志、报告、提交、提示词（与 AGENTS.md「Secrets Discipline」一致）；
- 配置文件与日志中只允许出现环境变量的**名称**，不允许出现其值；
- 一切持久化输出先经脱敏（F9），脱敏值模式需按 §5.6 扩展。

### 4.3 密钥扫描契约门误报规避规则

扫描门判据（F8）：持久化 JSON 的**键名**命中 `SECRET_KEYS`，或**字符串值**命中 `SECRET_TEXT`。据此：

- **R1（键名）**：配置文件 schema 与实例中禁止出现 `api_key`、`authorization`、`bearer_token`、`password`、`client_secret`、`access_token` 作为字段名——本 schema 一律采用 `credential_env`、`base_url` 等指称性命名；
- **R2（值）**：`credential_env` 等承载环境变量名的字符串不得命中 `SECRET_TEXT`。加载器硬校验：环境变量名经大小写不敏感匹配，禁止含 `bearer`、`sk-`、`akid` 子串模式（例：provider 名不得取 `sk-xxx`、`akid*` 一类会拼出敏感子串的形态）；
- **R3（示例值）**：文档与 fixture 中的示例一律用保留域占位（`example.invalid`、`PLACEHOLDER`），不出现真实凭证形态的长随机串；
- **R4（重建扫描门）**：旧扫描门文件随冻结目录删除，Stage 2 在 src 内重建为独立模块（§6 C4），模式集在 F8 基础上扩展、不得收窄。

## 5. 迁移与兼容方案

总原则：**公开符号不消失、钉住路径全部改接配置、行为缺省值逐字不变**（Stage 2 以全量测试绿 + 预检输出字段兼容为验收）。

### 5.1 新增加载器模块（Stage 2 实现）

新模块 `src/financial_agent_reliability/inference_config.py`，接口契约（签名即契约，不可变数据结构）：

```python
class InferenceConfigError(ValueError): ...

@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api: str
    base_url: str
    credential_env: str
    default_parameters: Mapping[str, Any]
    tool_choice: str
    timeout_seconds: float
    preflight_tool_instruction: str

@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    provider: str
    roles: tuple[str, ...]
    logical_label: str
    identity_rule: str
    allowed_response_model_ids: tuple[str, ...]
    live_preflight_required: bool
    parameter_overrides: Mapping[str, Any]

@dataclass(frozen=True)
class InferenceConfig:
    schema_version: str
    providers: tuple[ProviderConfig, ...]
    models: tuple[ModelConfig, ...]
    def provider(self, name: str) -> ProviderConfig: ...
    def models_for_provider(self, name: str) -> tuple[ModelConfig, ...]: ...

def load_inference_config(
    path: str | pathlib.Path | None = None,
    env: Mapping[str, str] = os.environ,
) -> InferenceConfig:
    """解析顺序 §2；执行 §3.1 跨字段校验与 §4.3 R1/R2 校验；失败抛 InferenceConfigError。"""

@dataclass(frozen=True)
class ProviderRuntime:
    provider_name: str
    base_url: str          # 已按 §3.5 规则解析（env 覆盖优先）
    credential: str        # 仅内存持有；repr/str 不显示（沿用 bailian.py:24-25 field(repr=False) 做法）
    endpoint_id: str       # f"{provider_name}_{sha256(origin)[:12]}"，origin 不含 path/query/凭证（F7）

def resolve_provider_runtime(
    config: InferenceConfig, provider_name: str, env: Mapping[str, str]
) -> ProviderRuntime:
    """credential_env 未设置 → InferenceConfigError（先于任何网络请求）。"""
```

### 5.2 `providers/bailian.py` → 可配置 provider 适配路径

- `BailianSettings`、`BailianAdapter`、`BailianConfigError`、`PreflightResult`、`build_all_adapters`、`BailianHTTPTransport` 的**模块路径与名称保持不变**（现有导入方：`bailian_http.py`、`harness/runner.py`、`harness/cli.py`、`harness/stage3.py`、`tests/integration/test_harness_runtime.py`）；
- `BailianSettings` 新增构造路径 `from_config(config: InferenceConfig, env, provider_name="bailian")`；原 `from_env(env)` 保留为兼容入口，语义等同 `from_config(load_inference_config(), env)`；
- `EXPECTED_MODELS` 硬编码（F2）删除，改为由配置文件派生：bailian provider 的 `models_for_provider("bailian")` 的 `model_id` 序列。模块级常量名以只读派生属性/函数形式保留一个过渡期（供残留引用），其值必须与配置文件一致；
- `BailianAdapter.__init__` 不再读 `CONFIG_PATH`（F3 钉住）：system_prompt、tools、preflight 指令改由 harness 契约（§6 C3）提供，经构造注入（`BailianAdapter(settings, model_id, harness_contract=...)`，缺省读默认 `configs/harness_contract.v1.json`）；
- `BailianHTTPTransport` 无需结构改动（只依赖 `settings.base_url` 与密钥字段），其字段来源改为 `ProviderRuntime` 映射。

### 5.3 `fareli-harness` 预检按配置运行的接入点

`harness/cli.py` `preflight` 子命令（F10）改造为：

1. 新增可选参数 `--config <path>`；解析顺序同 §2；
2. 流程：加载并校验配置 → 对每个 provider `resolve_provider_runtime`（凭证缺失即 fail-fast）→ 为每个 `live_preflight_required=true` 的模型构建 adapter → 执行预检 → 汇总。多 provider 时按 provider 分组计数；
3. 输出 JSON 兼容现行字段（`status`/`counts`/`endpoint_id`/`output`），新增 `inference_config_sha256` 与 `harness_contract_sha256`（取代旧 `harness_config_sha256`/`model_manifest_sha256` 的血缘绑定职能）；exit code 语义不变（0=passed，2=非 passed）；
4. `freeze-preflight`：`stage3.py:146` 硬编码三模型对账改为按配置文件模型集对账，并把两个契约哈希写入冻结 bundle；
5. `smoke`/`build-smoke-plan` 等依赖旧 v2 配置与旧基线用例的子命令：其钉住路径（`smoke.py:23,157`、`matrix.py:81,447`、`runner.py:25`）随 Stage 2 迁移改接新配置/新契约；其中与旧基线用例集绑定的部分按清理清单 M1/M2 退役或改写，不在本契约范围内。

### 5.4 `live_*.mjs`（钉住模型 ID 的脚本）策略

- **处置：整体退役**（与清理清单 M2 一致）。理由：13 个 `live_*.mjs` 属基线 v1 验收链，钉住 `contracts/` 内 v3.x 契约路径与硬编码模型集（F5），与配置驱动目标冲突；其对应 Python 验收链 `acceptance_v3*.py` 同样在 M2 退役清单内，单独保留 mjs 侧无意义；
- **过渡规则**：Stage 2 起任何新代码不得新增对 `ALLOWED_MODELS` 式硬编码模型集或 `contracts/*.json` 路径的引用；
- **能力接替**：live 预检能力由 §5.3 的 `fareli-harness preflight`（配置驱动）承接；如 Stage 3 基线 v2 需要新的 live smoke/acceptance 运行时脚本，必须从 `configs/inference.json` 读取模型清单（Node 侧直接读 JSON，同一 schema 校验规则以 §3 为准）。

### 5.5 npm 运行时测试与其他引用方

- `tests/integration/pi_runtime.test.mjs`（读旧 v2 配置，清理清单影响表）：Stage 2 改为读 `configs/harness_contract.v1.json`（+ `inference.json` 中 runtime 相关字段），断言语义不放松（清理清单 M1/M3）；
- `tests/integration/test_harness_runtime.py`：沿用 §5.2 兼容符号，新增配置加载/校验用例（§7 测试点）；
- `retrospective/registry.py` 等的自有 `EXPECTED_MODELS` 副本与冻结根路径：随 Stage 3 基线 v2 重建改写（清理清单 M2），重建前 `fareli-retro` 显式报「基线空窗」——本契约只要求其后的模型集引用改读配置文件，不规定复盘工具链的其他细节。

### 5.6 脱敏与扫描门扩展（Stage 2 同步落地）

- `redaction.py` `_VALUE_PATTERNS` 新增通用环境变量赋值模式（在现有 F9 三条之上扩展，不删旧条目）：
  `(?i)\b[A-Z][A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)\s*[=:]\s*[^\s]+`；
- 密钥扫描门重建为 `src/financial_agent_reliability/harness/secret_scan.py`（§6 C4），`SECRET_KEYS` 与 `SECRET_TEXT` 从 F8 逐字继承，另把 §4.3 R2 的 `credential_env` 形态校验纳入同模块复用。

## 6. 新契约版本清单与承接映射

### 6.1 清单

| # | 契约 | 建议落位 | 发布阶段 | 承接 |
| --- | --- | --- | --- | --- |
| C1 | `inference.schema.v1.json`（配置文件 JSON Schema） | `configs/` | Stage 2（本草案冻结后物化） | 新增；provider↔模型关联的唯一权威 |
| C2 | `configs/inference.json` 默认实例 | `configs/` | Stage 2 | 旧 v2 配置 `provider` 块（name/api/env 名/tool_choice/preflight 指令）、`candidate_model_ids`；整体吸收 `model_manifest.frozen.v2.json`（logical_label/allowed_response_model_ids/identity_rule/live_preflight_required）——**model_manifest 契约不再发新版本** |
| C3 | `harness_contract.v1.json`（命名待裁决，§8 Q2） | `configs/` | Stage 2（runner/smoke/stage3/mjs 读取所需；Stage 3 基线 v2 可按需升版） | 旧 v2 配置的 `runtime`（pi-agent-core 0.73.1 钉住与完整性哈希）、`system_prompt`、`context_contract`、`tools`、`request_parameters` 中 seed 策略（`seed_required`、预检 seed `20260811`）、`resource_budget`、`failure_policy`、`checkpoint_policy`、`security` |
| C4 | 密钥扫描门 v2（`secret_scan.py` 模块 + 模式集） | `src/.../harness/secret_scan.py` | Stage 2 | `contracts.run_trace_validator_v3_7.scan_persisted_value_for_secrets`（F8，随冻结目录删除）；模式集只增不减 |
| C5 | run_trace schema 后继版本 | 由 Stage 3 基线 v2 决定落位 | Stage 3（PER-328） | `run_trace.schema.v3.11.json`（旧谱系最新版）；其 `run_identity` 哈希绑定项以 `inference_config_sha256` + `harness_contract_sha256` 取代旧 `harness_config_sha256` |

旧契约处置：`run_trace_harness_config.v1/v2/v3.*.json`、`model_manifest.frozen.v1/v2.json`、各 `run_trace_validator*.py` 随冻结目录删除（清理清单 A1），内容可按回滚索引 SHA（`contracts/` 最后内容 commit `077fcb56...`）从 git 历史找回；新契约文件的 `supersedes` 块沿用旧惯例记录被承接文件的路径、SHA 与原因（C3 发布时填写，SHA 取删除前快照）。

### 6.2 旧 `run_trace_harness_config.v2.json` 逐块承接映射

| 旧 v2 块 | 承接者 | 说明 |
| --- | --- | --- |
| `runtime` | C3 | pi-agent-core 版本钉住与 registry 完整性哈希是 harness 不变量，与 provider 无关 |
| `provider`（name/api/api_key_env/base_url_env/model_ids_env/allowed_env/tool_schema_wire_format/tool_choice/preflight_tool_instruction） | C2（`providers[]`） | env 名三个字段收敛为 `credential_env` 一名 + §4.1 兼容名；`allowed_env` 职能由 §4.1 变量表承接 |
| `candidate_model_ids` | C2（`models[]`） | 三个候选即 `roles:["candidate"]` 的模型 |
| `system_prompt` | C3 | 模型中立提示词，全 provider 共享 |
| `context_contract` | C3 | frozen_bundle_only 等输入约束 |
| `tools` | C3 | 四工具 schema 逐字保留 |
| `request_parameters` | C2（`default_parameters`，数值类）+ C3（`seed_required` 与预检 seed） | 参数字段值逐字沿用（§3.2 缺省）；seed 策略不可按 provider 配置 |
| `resource_budget` / `failure_policy` / `checkpoint_policy` / `security` | C3 | 安全块的 `secret_field_names` 与 C4 扫描门保持同源 |

## 7. Stage 2 实现测试点（支撑直接实现）

离线（无密钥即可全跑）：

1. schema 校验：合法样例通过；逐类非法输入拒绝（缺必填、坏枚举、坏正则、`providers[].name` 重复、`models[].model_id` 重复、`provider` 悬空引用、`allowed_response_model_ids` 不含 `model_id`）；
2. 密钥扫描门误报规避：含 `api_key` 字段名的 JSON 拒绝；`credential_env` 值含 `sk-`/`AKID`/`bearer` 形态拒绝；合规实例通过；
3. 解析顺序：`--config` > `FARELI_INFERENCE_CONFIG` > 默认路径；`base_url` env 覆盖优先于文件；
4. fail-fast：凭证 env 缺失在任一网络调用前报错（mock transport 零调用断言）；
5. 兼容：`BailianSettings.from_env`（仅设 `BENCH_BAILIAN_*`）行为与改造前一致（现有 `test_harness_runtime.py` 用例不放松地通过）；`BENCH_BAILIAN_MODEL_IDS` 与配置一致时通过、不一致时拒绝；
6. `endpoint_id` 对同一 origin 逐字节复现（F7 策略回归）；
7. `fareli-harness preflight` 以 mock transport 跑通配置驱动路径，输出含两个契约哈希字段。

线上预检路径：仅需按 §4.1 设置真实环境变量后执行 `fareli-harness preflight --output ...`（不新增其他密钥配置步骤），Stage 4 按《手动执行指南》复现核验。

## 8. 开放问题（请交付负责人冻结裁决时一并裁定）

- **Q1**：新目录名 `configs/`（本草案推荐）vs 其他名称；`inference.json` 与三个新契约文件同目录是否可接受。
- **Q2**：C3 命名 `harness_contract.v1.json` 是否可用；发布时点随 Stage 2（推荐，runner/smoke/mjs 读取所需）还是并入 Stage 3 基线 v2 一次性发布。
- **Q3**：`BENCH_BAILIAN_MODEL_IDS` 过渡期「严格一致校验」（本草案推荐）vs 直接拒绝设置该变量 vs 静默忽略。
- **Q4**：`roles` 初始词表是否仅 `candidate`（本草案推荐），还是预置 `judge`/`baseline`。
- **Q5**：`configs/inference.json` 中 bailian `base_url` 是否写入真实端点 URL（非密钥，可入库）；否，则以占位值 + 环境变量覆盖为唯一来源。

## 附录：可复现盘点命令（只读）

```bash
git rev-parse HEAD                                   # 8b4e1c1...（本草案基线）
grep -n "BENCH_BAILIAN\|EXPECTED_MODELS" src/financial_agent_reliability/providers/bailian.py
grep -rn "run_trace_harness_config.v2.json" src tests package.json
grep -n "ALLOWED_MODELS\|BENCH_BAILIAN" src/financial_agent_reliability/harness/live_smoke.mjs
sed -n '20,22p;44,57p' contracts/run_trace_validator_v3_7.py   # 扫描门判据
grep -n "SECRET\|_VALUE_PATTERNS" src/financial_agent_reliability/harness/redaction.py
```
