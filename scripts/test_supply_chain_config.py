from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SHA_PIN = re.compile(r"^\s*uses:\s*[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


def require(text: str, fragment: str) -> None:
    if fragment not in text:
        raise AssertionError(f"missing supply-chain control: {fragment}")


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    action_lines = [line for line in text.splitlines() if re.match(r"^\s*uses:", line)]
    unpinned = [line.strip() for line in action_lines if not SHA_PIN.match(line)]
    if unpinned:
        raise AssertionError(f"GitHub Actions must use immutable commit SHAs: {unpinned}")
    if "pull_request_target:" in text:
        raise AssertionError("untrusted pull_request_target workflows are forbidden")

    for fragment in (
        "persist-credentials: false",
        "uv sync --frozen --dev",
        "uv --preview-features audit audit --locked --no-dev",
        "--preview-features sbom-export export --quiet --frozen --no-dev",
        "--format cyclonedx1.5",
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25",
        "severity: HIGH,CRITICAL",
        'exit-code: "1"',
        "sbom: true",
        "provenance: mode=max",
        "Scan exact published digest before signing",
        "startsWith(github.ref, 'refs/tags/v')",
        "packages: write",
        "id-token: write",
        "attestations: write",
        'cosign sign --yes "${REGISTRY}/${IMAGE_NAME}@${IMAGE_DIGEST}"',
        "subject-digest: ${{ steps.image.outputs.digest }}",
        "sbom-path: release-evidence/agentscope-platform.cdx.json",
        "sbom-path: dist/agentscope-platform.cdx.json",
    ):
        require(text, fragment)

    release_index = text.index("  release:")
    quality_permissions = text[:release_index]
    if "packages: write" in quality_permissions or "id-token: write" in quality_permissions:
        raise AssertionError("write/OIDC permissions must be scoped to the tag-only release job")

    print("AgentScope supply-chain config gate passed")


if __name__ == "__main__":
    main()
