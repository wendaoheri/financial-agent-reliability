# 基线 v4 验收口径（冻结）

状态：Frozen；版本：4.0.0；冻结事项：PER-328。

## 边界与世代

v4 是追加式新世代，不回写、不删除 v2/v3，也不改变
`validation/stage4/per329-baseline-v3-validation-v2/` 的独立审计证据。v3 第二轮
审计失败只说明其实现—契约配对不可作为新结论的有效基线；历史证据仍保留。

v4 沿用 4 个家族、每家族 normal / single-factor / missing-or-anomalous 三变体、
8 个冻结快照。只允许 SEC EDGAR 公开领域材料和项目自制合成 fixture；所有源与
派生件必须 `redistributable=true`，不得含授权市场数据、账户数据、密钥或真实交易。

## 必须通过的硬门

1. provider 与模型身份：runner 必须使用配置中的 provider；requested/response
   model 只能按同一 `ModelConfig.allowed_response_model_ids` 判定，禁止跨模型全局别名。
2. trace v6：必须执行完整 Draft 2020-12 schema，并重算 run identity、配置路径与
   哈希、provider/model、harness contract、immutable bundle 与 frozen input 跨块锚点。
3. freeze 顺序：只有 preflight 通过后才可冻结 bundle；失败时不得产生可冒充 passed
   的冻结结果。
4. claim-label：要求标签的 answer 必须提供非空 `claims`；
   `evidence_tier_labels` 的键集合必须与 claims 完全一致，且值只能是三种注册层级。

上述任一硬门失败，run 不得进入有效评分或排名。四组负例必须在
`tests/test_per327_second_audit_regressions.py` 中逐组通过。

## 六节点可追溯性

每个有效 run 必须可从冻结输入、模型请求、工具调用/尝试、模型输出、grader 结果、
报告结论六节点追溯；节点间用 v6 trace 的哈希、ID 与 bundle commitments 连接。
模型输出不要求确定性重放，但落盘证据必须逐件校验，评分与聚合必须可确定性重算。

## 验收与禁止事项

必须通过 v4 focused tests、全量 Python unittest、Node runtime tests、v2/v3/Stage 4
零漂移锚点以及干净 clone 复验。不得用付费模型或真实金融系统完成本次验收。
冻结后任何修订只能发布新版本；candidate 表现不得反向改变 case、权重、oracle 或门槛。
