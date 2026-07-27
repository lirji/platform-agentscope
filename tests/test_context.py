import pytest

from agentscope_platform.core.context import (
    bind_run_context,
    current_run_context,
    reset_run_context,
)
from agentscope_platform.domain.agent import RunContext, TenantIdentity


def test_context_is_bound_and_reset() -> None:
    context = RunContext(
        identity=TenantIdentity("tenant-a", "user-a"),
        internal_token="token",
        trace_id="trace",
    )

    token = bind_run_context(context)
    assert current_run_context() == context

    reset_run_context(token)
    with pytest.raises(RuntimeError, match="not bound"):
        current_run_context()
