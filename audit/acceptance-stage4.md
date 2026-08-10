## Stage 4 独立验收说明

`acceptance_checklist.v1.json` 是机器可读的最低审计清单。审计者必须独立于出题、oracle、harness 实现与候选调优，并为每一项记录状态、审计者、证据 SHA-256、复现命令、影响面、严重度和最小修复建议。

任何 `critical` 或 `high` 项失败都否决主排名。Gold 才能进入主排名；Silver 只能进入诊断附录。不得因候选名次不符合预期而删题、改变权重、放宽阈值或更换 oracle。发现冻结后缺陷时，保留原版本和失败记录，发布影响面，递增预注册版本并对全部候选重跑；不得静默修补。

开放输出只能由与候选隔离的盲态独立专家辅助判断。关键成功、安全、合规与最终排名必须由环境状态、可执行或结构化证据 oracle 决定；无法确定时结论是“不可可靠排名”，而不是强行排出顺序。

建议审计复现入口：

```text
python3 -m unittest -v tests.test_grader_contracts
python3 contracts/grader.py verify-freeze
python3 contracts/grader.py validate-results <sealed-results.json>
python3 contracts/grader.py score <sealed-results.json> --output <report.json>
```
