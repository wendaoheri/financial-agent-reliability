# 基线 v6 迁移说明

PER-330 第四轮审计证明：baseline v5 的 registry loader 虽会校验实际文件 SHA，
但只向 trace v7 validator 传递 path，丢弃登记 SHA。攻击者可保持 case/path 不变，
篡改 artifact SHA 并同步重算 bundle SHA、run identity、run_id 与 context SHA，使
trace 内部自洽并逃过旧门。C-323-27 因而作废 v5 Stage 3/4 通过结论；按 C-323-16
继续 append-only 发布 v6/口径 v6。

PER-327 提交 `d689aad804256c74f34f62228e8478d5e4292bde` 提供 trace schema/
validator v8、强类型 `(path, sha256)` commitment、runner v8 与同步重锚负例。本次将其
连同显式 12 项 registry、grader v6、许可与双 oracle 工件逐件纳入 v6 grader contract
和 manifest。新运行只可声明 v6/trace v8；v2-v5、trace v7 与旧验证证据继续按原世代
作为历史失败证据解读，不得回写。
