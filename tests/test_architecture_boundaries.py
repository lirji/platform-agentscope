import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "agentscope_platform"
AGENTSCOPE_ADAPTER = PACKAGE_ROOT / "infrastructure" / "agentscope"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _root(module: str) -> str:
    return module.split(".", 1)[0]


@pytest.mark.parametrize("path", sorted(PACKAGE_ROOT.rglob("*.py")), ids=str)
def test_agentscope_imports_are_confined_to_adapter(path: Path) -> None:
    roots = {_root(module) for module in _imports(path)}
    if "agentscope" in roots:
        assert _is_under(path, AGENTSCOPE_ADAPTER), (
            f"{path.relative_to(PACKAGE_ROOT)} imports AgentScope outside "
            "infrastructure/agentscope"
        )


@pytest.mark.parametrize(
    ("layer", "forbidden_roots"),
    [
        (
            "domain",
            {
                "agentscope",
                "fastapi",
                "httpx",
                "sqlalchemy",
                "redis",
                "kafka",
                "celery",
            },
        ),
        ("application", {"agentscope", "fastapi", "httpx"}),
        ("api", {"agentscope"}),
    ],
)
def test_framework_dependencies_do_not_cross_inward(
    layer: str,
    forbidden_roots: set[str],
) -> None:
    violations: list[str] = []
    for path in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
        roots = {_root(module) for module in _imports(path)}
        forbidden = sorted(roots & forbidden_roots)
        if forbidden:
            violations.append(
                f"{path.relative_to(PACKAGE_ROOT)} imports {', '.join(forbidden)}"
            )
    assert not violations, "\n".join(violations)


def test_domain_and_application_do_not_depend_on_outer_layers() -> None:
    violations: list[str] = []
    rules = {
        "domain": (
            "agentscope_platform.api",
            "agentscope_platform.application",
            "agentscope_platform.evaluation",
            "agentscope_platform.infrastructure",
        ),
        "application": (
            "agentscope_platform.api",
            "agentscope_platform.evaluation",
            "agentscope_platform.infrastructure",
        ),
    }
    for layer, forbidden_prefixes in rules.items():
        for path in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
            forbidden = sorted(
                module
                for module in _imports(path)
                if module.startswith(forbidden_prefixes)
            )
            if forbidden:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT)} imports {', '.join(forbidden)}"
                )
    assert not violations, "\n".join(violations)


def test_agentscope_orchestrator_does_not_embed_conversation_runtime() -> None:
    forbidden_modules = [
        PACKAGE_ROOT / "domain" / "conversation.py",
        PACKAGE_ROOT / "application" / "conversation.py",
        PACKAGE_ROOT / "infrastructure" / "conversation",
    ]
    assert not [path for path in forbidden_modules if path.exists()]

    api_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PACKAGE_ROOT / "api").rglob("*.py"))
    )
    assert '"/chat' not in api_source
    assert '"/internal/conversation/generate' not in api_source
