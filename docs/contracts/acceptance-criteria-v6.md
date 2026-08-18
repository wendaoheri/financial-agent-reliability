# 基线 v6 验收口径（冻结）

状态：Frozen；版本：6.0.0；冻结事项：PER-328；路线：C-323-16 append-only。

## 世代边界

v6 是追加式新世代。v2/v3/v4/v5、trace v7 与全部既有 Stage 4/Stage 4-v5
证据逐字节保留，不升级、不回写；其历史通过结论因相应审计缺口作废。v6 沿用 4 个家族、每家族
normal / single-factor / missing-or-anomalous 三变体及 8 个冻结快照，仅允许 SEC
EDGAR 公开领域材料和项目自制合成 fixture，所有数据必须可再分发。

## 累积硬门

1. provider 与模型身份必须来自同一配置项；response alias 只能在该模型的
   `allowed_response_model_ids` 内匹配。
2. 配置实际 path/SHA、harness contract SHA、run identity、request、provider 和
   immutable bundle 必须跨块重算一致。
3. preflight 未通过时不得形成可声明 passed 的冻结 bundle。
4. 要求标签的 answer 必须有非空 claims，labels 键集合与 claims 完全一致且层级合法。
5. trace v8 必须通过完整 Draft 2020-12 schema，并包含 `context.frozen_input_path`。
6. 冻结输入必须在 `frozen_input_registry.frozen.v6.json` 中按
   `(case_id, variant_id)` 唯一注册；trace path 必须等于注册 path，注册 SHA 必须
   同时等于实际冻结文件 SHA、该 path 的 bundle artifact commitment 与 trace
   context SHA。registry loader 必须向 validator 原样传递 path 与 SHA 的强类型
   commitment，不得只传 path。
7. 即使攻击者保持 case/path 不变，同时篡改 bundle artifact SHA、bundle SHA、
   run identity、run_id 与 context SHA，使 trace 内部全部重新自洽，也必须因其与
   registry/实际冻结文件的外部 SHA 锚不一致而硬失败。case A 改指同 bundle 内
   case B 的真实 path/SHA、错误 SHA 与未注册 case 也必须硬失败。

任一硬门失败的 run 不得进入有效评分、排名或通过结论。所有负例断言不得放松。

## 可追溯与复算

有效 run 必须覆盖冻结输入、模型请求、工具调用/尝试、模型输出、grader 结果、报告
结论六节点；各节点由 trace v8 的 ID、path 和哈希承诺连接。模型输出无需确定性重放，
但证据逐件哈希、registry 映射、评分与聚合必须可确定性重算。

## 验收方式与禁止事项

必须通过 v6 focused tests、全量 Python、Node runtime/integration、v2-v5、trace v7
与既有 Stage 4/Stage 4-v5 证据零漂移，以及全新 clone 复验。不得调用付费模型、真实凭据预检、账户或真实
交易系统；不得用候选表现或演示案例反向调整 case、oracle、权重或门槛。冻结后修订
只能发布新世代。
