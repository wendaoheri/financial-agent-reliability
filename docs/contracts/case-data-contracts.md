# `case_card` 与 `data_snapshot` 冻结契约 v1

状态：Frozen；版本：`1.0.0`；冻结议题：PER-23；Stage 2 及其后只能消费本版本，不得依据候选模型表现改题、改权重或修改契约。发现契约缺陷时必须创建新版本并保留旧版本、变更理由和影响范围，已开始的正式运行仍绑定原冻结清单。

## 产物与验证入口

- `contracts/case_card.schema.v1.json`：案例卡 JSON Schema 2020-12。
- `contracts/data_snapshot.schema.v1.json`：数据快照 JSON Schema 2020-12。
- `contracts/case_data_validation_config.v1.json`：质量层级、变体、时点、访问范围和哈希配置。
- `contracts/validate_case_data.py`：无第三方依赖的跨对象语义验证器。
- `contracts/case_data_contracts.frozen.v1.json`：所有冻结文件的 SHA-256 与 bundle hash。
- `tests/fixtures/case_data/`：正常、单因素扰动、缺证/异常三种 fixture 和独立数值 oracle。

执行：

```bash
python3 contracts/validate_case_data.py validate-bundle tests/fixtures/case_data
python3 contracts/validate_case_data.py verify-manifest contracts/case_data_contracts.frozen.v1.json
python3 -m unittest tests.test_case_data_contracts -v
```

## 不可变与标识

只有 `status: frozen` 的对象可进入评测。`case_id` / `snapshot_id` 与 `revision` 共同标识内容；冻结后不得就地覆盖。任何事实、口径、来源、时间、oracle 或验证配置变化都须生成新 revision（有语义变化时优先生成新 ID），并通过 `parent_snapshot_ids`、`source_case_id` 或 `parent_case_id` 连接上游。

每个对象的 `integrity.content_sha256` 校验其规范化内容。冻结 manifest 再校验 schema、配置、验证器、fixtures 和 oracle 的文件字节，形成 Stage 2 的单一入口 hash。

## `data_snapshot` 语义

快照同时记录：

- 来源、数据集、URI 与明确许可证；`redistributable` 只描述能否再分发，不推断未声明权利。
- 金融主体的稳定标识、MIC 市场、国家、时区、ISO 货币、金额倍数、价格调整口径和会计口径。
- `event_time`（事实发生）、`as_of`（数据代表的观察时点）、`available_at`（外部使用者首次可知）、`retrieved_at`（采集时点）。必须满足 `event_time <= available_at <= retrieved_at` 且 `as_of <= retrieved_at`。
- 每条 evidence 的稳定 `record_id`、类型、源定位符和 payload。
- collector、CLI/schema 版本、完整查询参数、原始响应 hash、代码 revision 和父快照 ID。原始响应可以因许可不能随 fixture 分发，但其 hash 仍必须保存。

Longbridge 只允许公开只读查询，`access.mode` 必须是 `public_read_only`。契约显式禁止 account、assets、cash、holdings、orders、positions、portfolio、trades；不得读取真实账户、持仓、订单或成交，也不得下单。交易类场景只能引用另外构造的模拟账本。

## `case_card` 语义

案例卡必须给出：

- 题目来源与许可证；任务域、提示、输入、工具、权限和初始状态。
- 与快照同口径的金融主体、市场、货币、单位、价格及会计口径。
- `event_time`、决策 `as_of` 与 `available_at_cutoff`，其中 `event_time <= as_of` 且 `available_at_cutoff <= as_of`。
- 风险等级 `low|medium|high|critical`、损失类别及理由。
- `Gold|Silver` 质量标记、主榜资格、可否独立复算及理由。
- 证据最小数量、证据类型、快照 hash 和 record ID；`future_information_prohibited` 固定为 `true`。
- 变体家族、父案例和变化因素；oracle 的版本、独立实现、实现 hash、预期状态、预期值和理由码。
- 生成器、版本、代码 revision、生成时间与父子血缘。

跨对象验证要求每个证据引用的快照和记录真实存在、hash 一致，并满足 `snapshot.available_at <= case.available_at_cutoff` 及 `snapshot.as_of <= case.as_of`。因此“文件后来能查到”不能让它成为早期案例的合法证据。

## Gold、Silver 与证据最小集

Gold 必须至少有一项证据、可由独立代码唯一重算且进入主排名。Silver 表示无法唯一判定或无法独立重算，只能用于诊断或弃权评测，必须 `ranking_eligible: false` 且 oracle 期望 `abstain`；不得用人工主观确信将 Silver 提升为 Gold。

正常与单因素样例均为 Gold；缺证样例把证据移除，明确降为 Silver 并期待 `INSUFFICIENT_EVIDENCE`。这使“正确弃权”成为可验证结果，而不是把缺证题伪装成有唯一答案的主榜题。

## 单因素变体

`single_factor_perturbation` 必须：

1. 指向同一 family 的父案例；
2. `changed_factors` 恰有一个可解析 JSON Pointer；
3. 该指针值确实变化；
4. 除 ID、变体描述、oracle 预期和血缘等追踪字段外，所有语义差分都落在该指针下。

验证器会拒绝“声明只改阈值但同时改货币”等多因素变体。`missing_or_anomalous` 可以改变证据与预期处置，但必须保留父关系和明确变化因素；若无法唯一复算则只能是 Silver。

## 规范化序列化与 hash

`financial-agent-c14n-json-v1` 规则为：UTF-8；对象键按 Unicode code point 排序；无无意义空白；字符串不作 ASCII 转义；布尔值和 null 使用 JSON 小写字面量；只允许整数作为 JSON number。价格、比率、金额等非整数金融数值必须使用规范十进制字符串，避免二进制浮点和不同语言的数字渲染漂移。禁止重复键、NaN 和 Infinity。

对象 content hash 的计算步骤：深复制对象，仅删除 `integrity.content_sha256`，按上述规则序列化，再取 lowercase SHA-256 hex。不得删除时间、血缘、来源或 oracle 字段。manifest 中的文件 hash 则直接对文件原始字节取 SHA-256；`contract_bundle_sha256` 是按 manifest 文件顺序拼接每行 `<sha256><两个空格><path>\n` 后再取 SHA-256。

## 失败策略与边界

验证器聚合并拒绝：时点倒置、未来信息、缺少许可证或血缘、内容/引用/manifest hash 不符、未标 Gold/Silver、Gold 无证据或不可复算、Silver 进入主榜、Longbridge 越权访问、单因素变体改变多个关键因素。验证通过只证明契约与冻结约束成立，不证明来源事实本身正确；事实正确性仍须由独立采集、复算和审计负责。
