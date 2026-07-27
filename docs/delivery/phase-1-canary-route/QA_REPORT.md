# QA Report

## Environment Profile

- Target: local candidate app plus retained Java/LiteLLM/Ollama stack.
- Version: working tree based on `9ed1e91`.
- Identity: short-lived internal tokens; values were not persisted.
- Data: committed four-case suite and seeded `tenantA` order data.

## Cases

| ID | AC/Risk | Setup and steps | Expected | Actual/evidence | Verdict |
| --- | --- | --- | --- | --- | --- |
| QA-01 | AC-01 | Create app with default settings; POST V2 | Route absent | 404 | pass |
| QA-02 | AC-02 | Enable flag and call with fake runner | Legacy-compatible body | Exact body assertion | pass |
| QA-03 | AC-03 | Enabled route without token and with forged token | Both denied | 401/401 | pass |
| QA-04 | AC-04 | Valid tenant token and trace | Identity/context preserved | Exact tenant/user/dept/scope/trace assertions | pass |
| QA-05 | AC-05 | Readiness with flag off/on | DISABLED/ENABLED | Exact status assertions | pass |
| QA-06 | AC-06 | Start real app enabled; authenticated current-time request | Registered and usable | 200, `DONE`, correct tenant | pass |
| QA-07 | AC-06 | Restart real app disabled; repeat route probe | Route removed | Readiness DISABLED and route 404 | pass |
| QA-08 | Regression | Three runs per case against old/new stack | Candidate meets gate | 12/12 pass; P95 12.734s | pass |

## Defects And Retests

- The first repeated-run identity had no seeded order 101 and correctly received upstream 404.
  The entire suite was rerun with `tenantA`; candidate order upstream returned 200 three times.

## Automated Regression

- 57 tests passed; coverage 90.31%.
- All static, contract, package, Compose, and offline Shadow checks passed.

## Blocked External Checks

- Actual edge test-tenant routing and rollback.
- Target-attributed model cost and semantic answer grading.

## Verdict

Conditional-pass: candidate-side routing is reversible and locally verified; edge cutover remains
external.
