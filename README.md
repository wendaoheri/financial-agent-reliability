# Financial Agent Reliability(金融 Agent 可靠性研究)

围绕金融 Agent 从"会生成、能执行"到"能判断、能负责"之间的系统性断层开展研究,
以《金融Agent系统性失效问题研究报告.html》(现位于 `docs/research/`)为研究起点,
建设一套可验证、可复现的评测 harness、契约体系与冻结证据库,用于控制投研、估值、
量化、风险管理等场景中的高损失错误、结构化可信错误、越权执行与责任真空。

## 快速开始

环境基线:Python 3.11(见 `.python-version`),一律使用 `uv` 管理。

```bash
uv sync                                   # 安装依赖(jsonschema 等)
uv run python -m unittest discover -s tests -v   # 全量测试(261 个用例)
npm run test:runtime                      # pi-agent-core 运行时边界测试(node --test)
```

付费模型评测仅在显式授权下进行,凭据只通过环境变量注入(见下文),正式运行只读
冻结数据,禁止真实交易。

## 目录结构

顶层目录按"证据血缘约束强度"分为三类。**改动任何目录前,先读 `AGENTS.md`
的"冻结产物与证据血缘纪律"。**

### ❄️ 冻结评测产物(内容不可修改、不可删除)

| 目录 | 内容 |
| --- | --- |
| `contracts/` | 版本化验收契约、schema、冻结 bundle 及其 Python 校验器 |
| `preregistration/` | 预注册文档(先于候选评测冻结) |
| `snapshots/` | 冻结数据快照(评测输入的唯一事实来源) |
| `runs/` | 运行输出(gitignore;冻结子集仅本地保存,证据以 `evidence/` 为准) |
| `evidence/` | 冻结证据 bundle(已提交的证据血缘记录) |
| `audit/` | 独立审计脚本与审计报告 |
| `reports/` | 阶段报告、交付报告与外部演示 |

### 🔒 证据血缘钉住(路径与 sha256 记录在冻结产物中,不得移动或编辑)

| 目录/文件 | 原因 |
| --- | --- |
| `harness/` | 评测 harness;历史版本文件的哈希记录在冻结 bundle 中 |
| `cases/`、`catalog/` | 用例与目录;冻结 manifest 记录用例文件及依赖源码的哈希 |
| `oracles/`、`reporting/` | 路径被冻结契约引用并参与哈希校验 |
| `tests/fixtures/`、`tests/expected/` | 被冻结审计脚本与 bundle 直接引用 |
| `docs/` 中部分文件、`package.json`、`pyproject.toml`、`uv.lock` | 被冻结契约/配置按根相对路径记录(v3.7 bundle 钉住后两者) |

### 📝 常规目录

| 目录 | 内容 |
| --- | --- |
| `docs/` | 契约说明、运营文档;`docs/research/` 为研究起点文档 |
| `tests/` | 测试套件(血缘钉住的部分除外) |
| `vendor/` | 离线 vendored 运行时归档(pi-agent-core 0.73.1) |

顶层布局本身是证据血缘的一部分:冻结审计脚本以 `Path(__file__).parents[1]`
解析仓库根,并按根相对路径引用兄弟目录,因此上述目录均保留在仓库根的第一层。

## 环境变量(凭据纪律)

密钥**只允许**通过环境变量注入,严禁写入任何文件、日志或提示词:

- `BENCH_BAILIAN_API_KEY` — 百炼 API 密钥
- `BENCH_BAILIAN_BASE_URL` — 百炼接入点
- `BENCH_BAILIAN_MODEL_IDS` — 候选模型 ID 列表

候选模型 ID 固定为 `qwen-3.8-max`、`glm-5.2`、`deepseek-v4-pro`;模型身份预检
失败时如实报告 blocked,不回退、不冒名。

## 许可与来源

研究结论区分"研究直接证据 / 基于证据的金融推论 / 说明性案例",保留来源、时间、
适用范围、反例与不确定性。详见 `AGENTS.md`。
