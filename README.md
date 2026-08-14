# Financial Agent Reliability(金融 Agent 可靠性研究)

围绕金融 Agent 从"会生成、能执行"到"能判断、能负责"之间的系统性断层开展研究,
以《金融Agent系统性失效问题研究报告.html》(现位于 `docs/research/`)为研究起点,
建设一套可验证、可复现的评测 harness、契约体系与冻结证据库,用于控制投研、估值、
量化、风险管理等场景中的高损失错误、结构化可信错误、越权执行与责任真空。

## 快速开始

环境基线:Python 3.11(见 `.python-version`),一律使用 `uv` 管理。项目为标准
src 布局的可安装包,`uv sync` 会以 editable 方式安装 `financial-agent-reliability`
并注册 `fareli-harness` / `fareli-report` 两个控制台入口。

```bash
uv sync                                            # 安装依赖并安装本项目(editable)
uv run python -m unittest discover -s tests -v     # 全量测试(261 个用例)
npm run test:runtime                               # pi-agent-core 运行时边界测试(node --test)
uv run fareli-harness --help                       # 评测 harness CLI
uv run fareli-report --help                        # 报告契约 CLI
```

付费模型评测仅在显式授权下进行,凭据只通过环境变量注入(见下文),正式运行只读
冻结数据,禁止真实交易。

## 目录结构

PER-85 用户裁决(D4/D5/D6)后,仓库分为**活的代码包**与**旧血缘历史基线**两层。
改动任何目录前,先读 `AGENTS.md` 的"冻结产物与证据血缘纪律"。

### 📦 代码包(src 布局,唯一可编辑代码区)

```
src/financial_agent_reliability/
├── harness/      评测 harness:验收契约各版本、bundle、checkpoint、脱敏、CLI 与 node 运行时(.mjs)
├── graders/      基于冻结评分政策的确定性评分管线
├── oracles/      Longbridge 案例 oracle(生产实现 + 独立参照实现)
├── pipelines/    案例/快照冻结管线(Longbridge v1 与 clean-room synthetic v2)
├── providers/    百炼 provider adapter 与 HTTP transport(模型中立、脱敏)
├── reporting/    PER-27 报告契约校验与确定性渲染
├── simulators/   确定性模拟账本
└── relocation.py PER-86 迁移映射:旧血缘路径钉住的统一解析与显式放行清单
```

顶层导入名为 `financial_agent_reliability`。`contracts`、`cases.public` 等旧血缘
Python 模块保留在仓库根,由包初始化时恢复 `sys.path` 后按原名导入;旧顶层包名
(`harness` 等)仅由兼容别名层为冻结脚本保留。

### ❄️ 旧血缘历史基线(内容不可修改、不可删除)

| 目录 | 内容 |
| --- | --- |
| `contracts/` | 版本化验收契约、schema、冻结 bundle 及其 Python 校验器 |
| `preregistration/` | 预注册文档(先于候选评测冻结) |
| `snapshots/` | 冻结数据快照(评测输入的唯一事实来源) |
| `runs/` | 运行输出(gitignore;冻结子集仅本地保存,证据以 `evidence/` 为准) |
| `evidence/` | 冻结证据 bundle(已提交的证据血缘记录) |
| `audit/` | 独立审计脚本与审计报告 |
| `reports/` | 阶段报告、交付报告与外部演示 |
| `cases/`、`catalog/` | 冻结用例与目录(含记录依赖源码哈希的 frozen manifest) |

按 PER-85-D6,这些目录的内容保留为历史基线:其路径/哈希钉住不再构成重构与
验收的阻塞,由 `financial_agent_reliability/relocation.py` 统一解析——迁移后
逐字节一致的文件按新位置校验,因重构机械改写的文件由放行清单逐条点名,不静默
跳过。所有实验将重跑,重跑产物以新契约版本建立新血缘(新版本发布由交付负责人
裁决)。

### 📝 常规目录

| 目录 | 内容 |
| --- | --- |
| `docs/` | 契约说明、运营文档;`docs/research/` 为研究起点文档 |
| `tests/` | 测试套件(unittest + node --test;fixture 与期望输出在其下) |
| `vendor/` | 离线 vendored 运行时归档(pi-agent-core 0.73.1) |

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
