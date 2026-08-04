import pytest
from pydantic import ValidationError

from agentscope_platform.core.config import Settings


def test_default_agent_execution_limits_are_finite() -> None:
    settings = Settings(_env_file=None)

    assert settings.agent_max_tokens == 24_000
    assert settings.agent_timeout_seconds == 120
    assert settings.agent_model_max_output_tokens == 4_096
    assert settings.agent_model_max_retries == 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"agent_max_tokens": 0}, "AGENT_MAX_TOKENS"),
        ({"agent_timeout_seconds": 0}, "AGENT_TIMEOUT_SECONDS"),
        ({"agent_model_max_output_tokens": 0}, "AGENT_MODEL_MAX_OUTPUT_TOKENS"),
    ],
)
def test_agent_execution_limits_reject_unbounded_values(
    override: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **override)
