# 节点恢复默认启用

## 范围与计划

用户要求默认开启功能并推送远程。本次增量 S4：按角色启用默认值、同步 Compose/模板、验证默认与显式回退、正常提交合入并推送 main。不执行部署。

## 实现

- API/worker 未配置开关时，节点恢复与 DAG 优化均开启；inline 默认关闭。
- 构造参数、环境变量及 .env 中的显式值优先；恢复开启但优化关闭仍拒绝启动。
- readonly Compose 两个角色均默认 true，环境模板不再钉死 false。已有私有 .env 不被覆盖，升级需核对显式旧值。
- API 默认提交 DAG/规划/Analyst/Process v2，run 保持 v1；worker 默认领取能力 checkpointVersion=1。关闭恢复后恢复 v1 入队/领取。
- v1 跨进程演练显式关闭两个开关，保留历史兼容性测试意图。

## 验证

- uv sync --dev 成功；Ruff、format（312文件）、Mypy（103源文件）、契约快照检查通过。
- pytest：589 passed，覆盖率89.71%；包括默认入队版本、默认领取协议、环境显式关闭、inline/非法组合及 API/worker 配置摘要一致性。
- Compose 使用 .env.example 渲染：API/worker 两个开关默认 true，显式覆盖均为 false；基础配置静态校验通过。
- 本轮未重复真实数据库/进程恢复演练；此前功能验证见 TEST_RESULT.md。本次没有修改检查点或数据库协议。

## 交付

任务分支 feat/dag-recovery-defaults，目标 origin/main。提交/推送完成后补充实际提交标识。

## 回退与边界

先确保中央所有实例已升级 V5，再升级 worker、API。旧环境显式 false 会继续关闭功能。
回退时 API 显式关闭恢复；排空/取消已有 v2 后才可回退 worker。需要旧调度时两个开关都设置 false。
历史 Java SBOM 扫描失败仍属独立依赖整改；本次不宣称生产部署或发布就绪。
本轮复用原项目目录，新建任务分支，无新工作树；历史工作树、私有配置、缓存与演练日志全部保留，不执行清理。
