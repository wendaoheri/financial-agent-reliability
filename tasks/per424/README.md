# PER-424 八维金融 Agent 离线评测资产

本目录是 `per424-report-eight-gates-100-dev-v2.1` 的 dev 资产。它以研究报告 D1–D8 可靠性门为主轴，包含恰好 100 个可执行任务：60 个 normal、40 个 challenge；40 个家族为单因素配对，另有 20 个 extra normal。

60 个 normal 的事实与 Gold 底座不是模型自由生成：24 个来自开放金融数据集，24 个来自冻结的 SEC Company Facts 官方记录，12 个来自已完结或已和解的监管执法记录。40 个 challenge 复用对应 normal 的来源证据，只改变一个注册控制因素。`sources.jsonl` 保存来源类别、定位符、版本、抓取时间、证据摘要、转换记录、裁决状态和 Gold 依据；个人研究不以许可证作为运行门禁，但保留 `license_id` 供未来共享或公开前复核。

`tasks.jsonl` 是 evaluator-side 自包含输入，其中 `gold`、`tags`、`notes`、variant 与 gate 信息绝不能传给候选。候选只收到 `prompt`、净化后的 `candidate_payload`，以及 `read_fixture` 返回的冻结 fixture。fixture 的公开 policy 定义控制条件与输出语义，mock 候选必须从 fixture 求值，禁止读取 Gold。

`candidate-contract.json` 固化可见性与三分类，`scoring.json` 固化 4/2/1 评分及安全硬门，`coverage.json` 固化维度、家族和来源分布，`manifest.json` 固化 Eval Pack 身份。运行记录单独保存在 `mock-run.jsonl`，确定性重评分结果保存在 `mock-replay.json`；二者不进入 Eval Pack 身份。

每个 candidate payload 的 `max_input_tokens` 为 24000；验证器对 prompt、候选契约和 fixture 工具返回做保守组装长度检查。公开 benchmark 原题可能存在训练污染，因此本 dev 包不用于“未见题泛化”或真实模型排名；它只证明报告驱动的来源、任务、Gold、工具和评分语义可执行、可回放。所有工具保持离线、只读或 simulated，不支持真实交易、生产写入、付费模型或外部账号。
