# 基线 v4 迁移说明

PER-330 第二轮审计发现 v3 的四个缺口：live runner provider 固定与别名越界、v5
trace 校验未执行完整 schema/跨块锚点、preflight 失败仍可形成冻结件、研究结论标签
未与 claims 做键集合闭合。PER-327 的 `f7c22699ece7f22e5c847e00f60b29071da8950a`
先修复运行代码与负例；PER-328 再以 v4 契约、grader bundle 和 manifest 将这些修复冻结。

迁移策略是 append-only：v2/v3 和既有审计证据只读保留；v4 case/snapshot 从同一许可
捕获确定性生成，新增 claim-label contract，并把 runner、provider、配置、v6 schema/
validator、grader v4 与四组回归测试逐件哈希纳入 grader contract。新运行只能声明 v4，
旧运行继续按其原世代解读，不升级、不改写。
