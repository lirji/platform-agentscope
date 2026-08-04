from opentelemetry import metrics

_meter = metrics.get_meter("agentscope_platform.governed_tools")
_policy_denials = _meter.create_counter(
    "agent_tool_policy_denials",
    description="Governed Agent tool invocations denied before execution.",
)
_provider_failures = _meter.create_counter(
    "agent_tool_provider_failures",
    description="Governed Agent tool provider calls that failed.",
)


def record_tool_policy_denied(tool: str, reason: str) -> None:
    _policy_denials.add(1, {"tool": tool, "reason": reason})


def record_tool_provider_failure(tool: str, provider: str) -> None:
    _provider_failures.add(1, {"tool": tool, "provider": provider})
