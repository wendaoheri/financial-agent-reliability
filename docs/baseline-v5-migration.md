# 基线 v5 迁移说明

PER-330 第三轮审计证明：v4 只校验 `frozen_input_sha256` 是否出现在 bundle 中，未把
它绑定到当前 `(case_id, variant_id)`。因此同一双文件 bundle 内，case A 可改指 case B
的真实 path/SHA 而逃过旧门。C-323-23 作废 v4 Stage 3/4 通过结论；C-323-24 选择方案 A，
发布 v5/口径 v5。

PER-327 提交 `451befce04eeeb5cffdf50e74df8b28bce5301fc` 提供 trace schema/
validator v7、`frozen_input_path`、runner v7 和专项负例。本次将其连同显式 12 项 registry、
grader v5、许可与双 oracle 工件逐件纳入 v5 grader contract 和 manifest。新运行只可
声明 v5/trace v7；v2/v3/v4 继续按原世代作为历史失败证据解读。
