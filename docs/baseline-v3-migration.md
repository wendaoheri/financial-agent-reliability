# Baseline v3 迁移说明（PER-328）

`baseline/v2/` 与 `docs/contracts/acceptance-criteria-v2.md` 原文保留，状态为
`superseded / failed independent audit`；其固定 sha256 由 v3 测试钉住，不作为现行
验收依据。

V3 只增新目录、新 schema、新 manifest、新 grader policy 与新口径。修订关闭：

- 严格 mapping 全对象等值；
- submission 对象级 secret scan；
- 八项 policy invariant 完整执行；
- 移除 v3 对不可再分发 Longbridge raw payload 的依赖，替换为 CC0 合成 fixture；
- run_trace 契约升至 v5，case/snapshot 契约升至 v3。

直接证据来自 PER-330 审计；上述整改是基于该证据的工程结论；合成报价只属说明性
案例。V2 中既存内容未复制、未修改、未删除，后续处置仍由独立审计与项目所有者裁决。
