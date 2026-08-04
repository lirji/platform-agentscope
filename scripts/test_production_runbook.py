#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "operations" / "production-release-runbook.md"
TEMPLATE = ROOT / "docs" / "operations" / "production-evidence-template.json"
REQUIRED_REPORTS = {
    ROOT / "docs" / "delivery" / "production-agent-hardening" / "REVIEW_REPORT.md": (
        "Engineering scope: PASS",
        "Production cutover: NO-GO",
    ),
    ROOT / "docs" / "delivery" / "production-agent-hardening" / "QA_REPORT.md": (
        "Local engineering QA: PASS",
        "Production release QA: CONDITIONAL / NO-GO",
    ),
    ROOT / "docs" / "delivery" / "production-agent-hardening" / "DELIVERY_REPORT.md": (
        "AC-01 through AC-16",
        "NO-GO for production cutover",
    ),
}

REQUIRED_SECTIONS = {
    "## 发布角色与变更记录",
    "## RPO / RTO",
    "## 发布前门禁",
    "## Shadow、对抗与回放",
    "## Canary 与扩量",
    "## 监控与停止条件",
    "## 整服务回滚",
    "## 恢复验证",
    "## 外部证据门禁",
    "## 事故与升级",
}
REQUIRED_TEXT = {
    "uv run ruff check .",
    "uv run mypy src",
    "uv run pytest",
    "scripts/test_production_runbook.py",
    "mvn -q -DskipITs test",
    "deploy/test-production-cutover-config.sh",
    "agentscope-shadow-eval",
    "--require-version-metadata",
    "--replay-report",
    "agent_run_duration_ms_bucket",
    "agent_run_terminations_total",
    "agent_async_task_backlog",
    "PENDING",
    "RUNNING",
}
REQUIRED_CHECKS = {
    "release.change_approval",
    "release.oncall",
    "supply_chain.signature",
    "supply_chain.sbom_scan",
    "iam.workload_identity",
    "security.egress_callbacks",
    "database.migration",
    "recovery.redis_restore",
    "recovery.mysql_restore",
    "capacity.peak",
    "capacity.autoscaling",
    "soak.peak_cycle",
    "evaluation.shadow_v4",
    "evaluation.adversarial",
    "security.tenant_isolation",
    "canary.tenant",
    "observability.dashboard_alert",
    "rollback.full_service",
    "rollback.post_restore",
}
OBJECTIVES = {
    "agentRouting": (0, 15),
    "agentSessionRedis": (5, 30),
    "authoritativeMysql": (5, 60),
    "evaluationArtifacts": (1440, 240),
}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Validate the production release runbook/evidence.")
    value.add_argument("--evidence", type=Path, default=TEMPLATE)
    value.add_argument("--require-go", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    errors = [*_validate_runbook(), *_validate_evidence(args.evidence, args.require_go)]
    if errors:
        print("production release gate NO-GO")
        for error in errors:
            print(f"- {error}")
        return 1
    message = (
        "production release evidence GO"
        if args.require_go
        else "production runbook static gate passed"
    )
    print(message)
    return 0


def _validate_runbook() -> list[str]:
    try:
        text = RUNBOOK.read_text(encoding="utf-8")
    except OSError:
        return [f"runbook missing: {RUNBOOK}"]
    errors = [f"runbook section missing: {item}" for item in REQUIRED_SECTIONS if item not in text]
    errors.extend(
        f"runbook command/metric missing: {item}" for item in REQUIRED_TEXT if item not in text
    )
    for report, required_markers in REQUIRED_REPORTS.items():
        try:
            report_text = report.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"delivery report missing: {report}")
            continue
        errors.extend(
            f"delivery report marker missing: {report.name}: {marker}"
            for marker in required_markers
            if marker not in report_text
        )
    return sorted(errors)


def _validate_evidence(path: Path, require_go: bool) -> list[str]:
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"invalid evidence JSON: {path}"]
    errors: list[str] = []
    if payload.get("schemaVersion") != "agent-production-evidence.v1":
        errors.append("unsupported evidence schemaVersion")
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return [*errors, "evidence checks must be an array"]
    by_id = {
        item.get("id"): item
        for item in checks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(by_id) != len(checks):
        errors.append("evidence check ids must be unique strings")
    missing = REQUIRED_CHECKS - set(by_id)
    unexpected = set(by_id) - REQUIRED_CHECKS
    errors.extend(f"required evidence check missing: {item}" for item in sorted(missing))
    errors.extend(f"unexpected evidence check: {item}" for item in sorted(unexpected))
    if any(by_id[item].get("required") is not True for item in REQUIRED_CHECKS & set(by_id)):
        errors.append("all production evidence checks must remain required")
    objectives = payload.get("objectives")
    if not isinstance(objectives, dict):
        errors.append("recovery objectives are required")
    else:
        for name, (rpo, rto) in OBJECTIVES.items():
            value = objectives.get(name)
            if (
                not isinstance(value, dict)
                or value.get("rpoMinutes") != rpo
                or value.get("rtoMinutes") != rto
            ):
                errors.append(f"recovery objective mismatch: {name}")
    if not require_go:
        return errors

    if payload.get("decision") != "GO":
        errors.append("decision is not GO")
    if not isinstance(payload.get("releaseId"), str) or payload["releaseId"].startswith("REPLACE_"):
        errors.append("releaseId is not resolved")
    for field in ("candidateDigest", "rollbackDigest"):
        if not isinstance(payload.get(field), str) or DIGEST.fullmatch(payload[field]) is None:
            errors.append(f"{field} must be an immutable SHA-256 digest")
    for check_id in sorted(REQUIRED_CHECKS & set(by_id)):
        check = by_id[check_id]
        if check.get("status") != "PASS":
            errors.append(f"required check is not PASS: {check_id}")
        if not isinstance(check.get("owner"), str) or not check["owner"].strip():
            errors.append(f"required check has no owner: {check_id}")
        if not isinstance(check.get("evidenceUri"), str) or not check["evidenceUri"].startswith(
            "https://"
        ):
            errors.append(f"required check has no HTTPS evidence URI: {check_id}")
        if not _valid_timestamp(check.get("observedAt")):
            errors.append(f"required check has no valid observedAt: {check_id}")
    return errors


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
