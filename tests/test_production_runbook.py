import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_production_runbook.py"
TEMPLATE = ROOT / "docs" / "operations" / "production-evidence-template.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runbook_and_pending_template_pass_static_validation_but_not_release_gate() -> None:
    static = run()
    blocked = run("--evidence", str(TEMPLATE), "--require-go")

    assert static.returncode == 0, static.stdout + static.stderr
    assert blocked.returncode == 1
    assert "NO-GO" in blocked.stdout


def test_release_gate_requires_complete_owned_and_timestamped_evidence(tmp_path: Path) -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["releaseId"] = "release-2026-08-03"
    payload["candidateDigest"] = "sha256:" + "a" * 64
    payload["rollbackDigest"] = "sha256:" + "b" * 64
    payload["decision"] = "GO"
    for check in payload["checks"]:
        check.update(
            {
                "status": "PASS",
                "owner": "release-owner",
                "observedAt": "2026-08-03T08:00:00Z",
                "evidenceUri": "https://evidence.example/release/item",
            }
        )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    passed = run("--evidence", str(evidence), "--require-go")

    assert passed.returncode == 0, passed.stdout + passed.stderr

    payload["checks"][0]["owner"] = ""
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    incomplete = run("--evidence", str(evidence), "--require-go")
    assert incomplete.returncode == 1
