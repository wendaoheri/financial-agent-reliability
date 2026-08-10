## Harness 与 run_trace v1 冻结契约

本契约冻结评测运行层，而不宣称任何候选模型已经通过线上身份预检。正式全量运行在本阶段禁用；只有在三个 `BENCH_BAILIAN_*` 环境变量齐备且逐模型预检成功后，后续阶段才可运行付费样本。

### 固定面

- 运行时精确锁定 `@mariozechner/pi-agent-core@0.73.1`，同时记录 npm registry integrity；禁止 `^`、`~`、标签或未锁定版本。
- 候选模型 ID 仅为 `qwen-3.8-max`、`glm-5.2`、`deepseek-v4-pro`。逻辑标签、请求 ID 和供应商响应 ID 必须逐字相等，别名不算相等。
- 只允许通过 `BENCH_BAILIAN_API_KEY`、`BENCH_BAILIAN_BASE_URL`、`BENCH_BAILIAN_MODEL_IDS` 配置百炼。endpoint 只记录由 origin 生成的非敏感哈希标识，不记录 URL、路径、查询参数或凭证。
- system prompt、上下文正规化、四个工具 schema、顺序执行模式、请求参数和资源预算对所有模型完全相同。不得加入供应商或模型专用 prompt。

### 预检与作废

每个候选模型在正式运行前必须完成一次最小请求，核对请求 ID、响应 `model`、endpoint 标识、seed/temperature/top_p/max_tokens 的可接受性及工具调用能力。以下任一情况都将 trace 标为 `invalidated`，且禁止自动回退或用别的模型补跑：身份不匹配、供应商回退、参数被忽略、endpoint 未验证。预检失败时应保留脱敏失败证据并报告 blocked；不得冒名进入排名数据。

超时、限流、供应商暂时不可用可以在统一预算内重试；每次 attempt 必须记录失败分类、耗时、HTTP 状态（如有）和退避。身份、参数、安全与预算错误不可重试。

### 状态、恢复与幂等

`run_id` 是 `run_identity` 的规范 JSON SHA-256 前 32 位，输入包括 benchmark、case、variant、精确模型 ID、repeat、seed、Harness 配置哈希和 immutable bundle 哈希。同一个逻辑运行恢复时沿用相同 `run_id`，不得生成新矩阵单元。

checkpoint 记录事件偏移、状态哈希、前序事件哈希和创建时间。恢复只能追加事件；`source_run_id` 必须等于当前 `run_id`。immutable bundle 以排序后的 `path + NUL + sha256 + LF` 列表计算聚合哈希，冻结输入、oracle、prompt、工具和配置均需列入。

### trace 最小审计面

每条 trace 记录请求/响应模型 ID、endpoint 非敏感标识、参数与 seed、上下文与工具 schema 哈希、每次工具调用的参数/结果哈希、只读数据及模拟账本状态、起止时间与耗时、token、成本、attempt/retry、checkpoint/resume、失败类型、结果哈希和脱敏声明。原始敏感响应不得持久化。

### 安全边界

- 正式运行只读冻结数据；所有交易类行为仅进入 run-local `simulated_ledger`，禁止账户、持仓、下单或真实交易接口。
- 不读取或修改 cc-switch、Codex 配置。`touched_paths` 出现对应路径即拒绝。
- token、API key、Authorization/Cookie 头、原始响应与疑似密钥值不得进入 trace、日志、fixture、checkpoint、元数据或 bundle。验证器会递归扫描字段名和值，并在发现泄漏时拒绝 trace。
- 金额用规范非负十进制字符串保存；当前阶段 `full_paid_matrix_runs_allowed=false`。

### 可复现验证

运行 `python3 -m unittest discover -s tests -v` 验证全部契约；运行 `python3 contracts/run_trace_validator.py verify-freeze` 输出冻结文件数量和聚合哈希；运行 `python3 contracts/run_trace_validator.py validate-fixtures` 逐个验证 fixture，其中 secret 泄漏 fixture 必须被拒绝。
