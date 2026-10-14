# Java 依赖整改准备（2026-10-14）

本轮仅准备整改依据，不修改 Java 依赖、数据库或部署。用户已明确暂无非生产环境，先完成
本地整改和依赖准备。既有路线提案在同级 Java 仓的
`docs/delivery/cross-runtime-reliability/SECURITY_MIGRATION_PROPOSAL.md`，以下是新证据和必要增补，
不是已经批准的版本迁移方案。

## 固定扫描基线

- Java main：`0b8267340129a46407e649caae6badd51acf017f`，核查时工作区干净。
- [运行 38500333420](https://github.com/lirji/langchain4j-platform/actions/runs/38500333420)：
  reactor、打包和 SBOM 生成成功，聚合依赖扫描失败；镜像扫描、attestation 和 release 未执行。
- [制品 11865209329](https://github.com/lirji/langchain4j-platform/actions/runs/38500333420/artifacts/11865209329)：
  从 ZIP 按范围读取，仅提取 `trivy-dependencies.json` 与 `langchain4j-platform.cdx.json`。
- 当前 **88 条记录：71 HIGH、17 CRITICAL，31 个包坐标**，均有扫描器报告的修复版本。
  这不是 88 个已确认可利用漏洞；同包多版本和漏洞别名可能重复。
- 可持久复核的逐条结果、来源及原文件摘要见
  [扫描摘要](dependency-remediation-scan-2026-10-14.json)。原 JSON 保存在本地
  `.git/codex-pending-security-remediation/`，不提交 1.2 GB JAR 制品。

相比 10 月 2 日旧快照，增加 jsoup、WebFlux、WebMVC 三条记录；Jackson core 的一个 GHSA
换为 CVE 标识，净增仍为 3。旧报告中的 85 条只作为历史，不覆盖当前结果。

## 技术路线与新增兼容约束

| 路线 | 依据与代价 | 准备结论 |
|---|---|---|
| Java 21 + Boot 4.x + Cloud 2025.1.x | 当前官方矩阵支持 Boot 4.0/4.1；跨越 Spring 7、Jackson 3、Web/配置及持久化集成边界 | 推荐作为后续设计方向；具体补丁组合须由 BOM 解析与扫描确定，当前未选定或验证 |
| Boot 3.5.x + Cloud 2025.0.x | 升级跨度较小，但官方项目页已标 EOL；新增 Spring 公告的 6.x 修复列为企业支持版本 | 仅在有明确商业支持与过渡期限时评估，不能沿用旧提案版本宣称完成开源安全整改 |

依据：[Spring Cloud 当前兼容矩阵](https://spring.io/projects/spring-cloud/)。其 Wiki 页面仍保留
较旧的 2025.0 支持列，且提示以项目页最新信息为准；本准备记录采用项目页状态。

本轮新增需处理的边界：

1. **Spring 安全补丁下限**：扫描器将 `CVE-2026-47892` 和 `CVE-2026-47884` 记为 CRITICAL，
   [官方 WebFlux 公告](https://spring.io/security/cve-2026-47892/)与
   [官方 XsltView 公告](https://spring.io/security/cve-2026-47884/)标为 MEDIUM，公开修复均列
   Framework 7.0.9，6.x 补丁列为企业支持。保留严重度差异；后续逐条核查功能路由/XsltView
   的实际可达性，不自行忽略扫描或把版本命中等同于可利用。候选 BOM 必须实际解析到修复版本。
2. **MyBatis 迁移已经落地**：Java 当前为 MyBatis-Plus 3.5.17、MyBatis-Spring 3.0.5、
   MyBatis 3.5.19。官方 [MyBatis-Spring 矩阵](https://mybatis.org/spring/)将 Spring 7 对应到
   4.0 系列；[MyBatis-Plus 安装指南](https://baomidou.com/en/getting-started/install/)提供
   Boot 4 适配，但本项目使用自定义工厂及共享事务装配，不能仅替换 starter。须复验 22 个 XML、
   租户过滤、DELETED 条件、CAS、唯一约束和 Flowable 事务参与。
3. **Jackson 与外部 SDK**：按 [Boot 4 迁移指南](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
   验证 Jackson 3 包名、JSON 序列化与自定义 converter；临时 Jackson 2 桥接是已弃用过渡路径。
   固定 IAM SDK、JWT、Flowable 7.1.0、MCP beta、向量 SDK 均需分别验证，不能由框架编译成功替代。
4. **客户端专项**：LangChain4j/pgvector、gRPC/Netty、OpenNLP、LZ4、BouncyCastle、PostgreSQL、
   jsoup 按扫描记录核查直接/传递依赖与许可证；保留 gRPC/Milvus/Qdrant 既有兼容说明，升级后做
   真实组件测试。当前未核验目标版本许可证、运行依赖树或这些组件的实时可用性。

## 后续有界实施顺序与验收

| 阶段 | 产出 | 必须通过的验收 |
|---|---|---|
| D1 组合设计 | 固定 Boot/Cloud/BOM、MyBatis-Spring、Jackson/SDK 版本；依赖树、许可证、回退点 | 全部受影响坐标有明确处置；不混搭未经支持的 Spring 子模块 |
| D2 框架适配 | Gateway/Config/Security/Actuator/JSON/持久化兼容修改 | 全 reactor、Flowable profile、契约与租户隔离、22 XML 与配置门禁 |
| D3 客户端适配 | 模型/MCP/向量/文本解析/密码学客户端修改 | 真 MySQL/Redis、向量组件、独立 worker、JWT/SSE/TCP 取消与计费验证 |
| D4 发布验证 | 新 SBOM 和全部镜像扫描、验证指纹与 Git 交付 | 现有安全门禁通过；未通过不发布，不复用旧的 85 条合并例外 |

D1 完成并评审具体组合后才进入依赖修改。回滚必须保持现有 MyBatis 逻辑删除及新迁移兼容，
不能退回忽略 DELETED 的历史版本。此次没有 Java commit、tag/release、生产部署或真实模型调用。
