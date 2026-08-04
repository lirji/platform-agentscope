# 软件供应链与可信发布

本文说明 AgentScope 编排服务的构建、扫描、签名、验证和回滚规则。唯一发布入口是
`.github/workflows/ci.yml`；生产部署只能引用通过下述验证的不可变镜像 digest，不能把 tag
当作可信身份。

## CI 与发布边界

- Pull Request、`main` push 和手工运行只使用 `contents: read`，执行锁文件审计、契约快照、
  lint/format/mypy/pytest、shadow smoke、Python 包构建、CycloneDX SBOM、镜像构建和
  Trivy `HIGH,CRITICAL` 阻断扫描。
- 只有 `v*` tag 的 `release` job 拥有 `packages`、`id-token`、`attestations` 和
  `artifact-metadata` 写权限。没有长期签名私钥，Cosign 与 GitHub attestations 都使用
  GitHub OIDC 短时身份。
- 所有第三方 Action 固定到完整 commit SHA。Dependabot 只提出升级 PR；合并前必须核对
  上游 release、commit 与 security advisory，尤其要复核 Trivy Action 的历史 tag
  供应链事件，不能把 SHA 改回 `@vN` 或可移动 tag。
- 发布镜像启用 BuildKit `sbom` 和 `provenance: mode=max`，并对实际推送 digest 再生成
  CycloneDX SBOM、执行阻断扫描、Cosign 签名及 SLSA provenance/SBOM attestation。
- Python wheel/sdist 同样绑定 provenance 和依赖 SBOM。CI 证据保留 30 天；正式发布证据
  还应由制品归档系统按组织留存策略保存。

发布必须先推送镜像才能取得 registry digest。因此，digest 扫描失败时 GHCR 可能留下一个
**未签名、未证明的孤立镜像**。这是失败制品，不得部署；消费者/admission policy 必须要求
签名和 provenance 都通过，而不是只检查“镜像存在”。工作流不自动部署任何镜像。

## 本地门禁

```bash
uv sync --frozen --dev
uv run python scripts/test_supply_chain_config.py
uv --preview-features audit audit --locked --no-dev
uv build
uv --preview-features sbom-export export --quiet --frozen --no-dev \
  --format cyclonedx1.5 --output-file dist/agentscope-platform.cdx.json
```

静态门禁会拒绝浮动 Action、`pull_request_target`、非 tag 发布权限，以及被移除的审计、
扫描、签名或 attestation 步骤。镜像扫描仍需要可用的 Docker daemon；OIDC 签名和 GHCR
attestation 只能在真实 GitHub tag workflow 中验证。

## 发布后验证

先从发布记录取得 digest，不要从可变 tag 推断。以下示例中的 `OWNER/REPO`、版本和 digest
必须替换为实际值：

```bash
REPO=OWNER/REPO
IMAGE=ghcr.io/OWNER/REPO@sha256:0123456789abcdef

cosign verify "$IMAGE" \
  --certificate-identity-regexp \
  "^https://github.com/${REPO}/.github/workflows/ci\\.yml@refs/tags/v.+$" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

gh attestation verify "oci://${IMAGE}" \
  --repo "$REPO" \
  --signer-workflow "$REPO/.github/workflows/ci.yml"
```

验证结果必须绑定预期仓库、`ci.yml`、`refs/tags/v*` 和目标 digest。随后从对应 workflow run
下载 `agentscope-release-evidence-*`，确认 digest 扫描报告无阻断漏洞、CycloneDX JSON 可解析，
并记录 workflow URL、run ID、source commit、tag、digest、签名和 attestation 验证输出。

命令语义以 [Sigstore Cosign verification](https://docs.sigstore.dev/cosign/verifying/verify/)
和 [GitHub CLI attestation verification](https://cli.github.com/manual/gh_attestation_verify)
为准。

## 失败处置与回滚

1. 审计、测试、SBOM 或本地镜像扫描失败：不创建 release job，修复依赖或代码后重新走 PR。
2. digest 扫描失败：把该 digest 加入 denylist/准入策略，保留报告做审计；不要签名、证明或部署。
3. OIDC、签名或 attestation 失败：制品仍不可信，禁止人工绕过；确认 GitHub/Sigstore/GHCR
   状态后从同一 source tag 重新构建，不能补签来源不明的旧镜像。
4. 已部署版本需要回滚：选择此前验证通过的 digest，重新执行 Cosign 与 provenance 验证后按
   正常排空流程部署。不得回滚到 mutable tag，也不要删除签名或 attestation 来“修复”失败。
5. 发现 Action/构建器被攻陷：立即冻结发布、撤销受影响 digest 的准入、保全 workflow/SBOM/
   扫描证据，升级到核验后的 immutable commit，并从已知良好 source commit 全量重建。

## 目标环境证据

本地验证不能替代以下证据：真实 GitHub Actions `v*` run、GHCR digest 推送、Cosign/Rekor
验证、GitHub provenance 与 SBOM attestation、registry/admission 拒绝未签名 digest 的测试，
以及从前一可信 digest 回滚的演练记录。缺少任一项时不得宣称生产供应链门禁已闭环。
