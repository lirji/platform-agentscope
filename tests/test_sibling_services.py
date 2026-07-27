import asyncio

import pytest
from pydantic import ValidationError

from agentscope_platform.application.quality import CritiqueWeights
from agentscope_platform.application.sibling import (
    PromptChainService,
    ReflexionPolicy,
    ReflexionService,
    SiblingValidationError,
    VotingService,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.dag import AgentDagCritique, DagPlan
from agentscope_platform.domain.sibling import (
    ChainRunRequest,
    ChainStepDefinition,
    ReflexionRequest,
    VoteRequest,
    VotingStrategy,
)


class FakeGenerator:
    def __init__(self, outputs: list[str], delay: float = 0) -> None:
        self.outputs = list(outputs)
        self.delay = delay
        self.calls: list[tuple[str, str, RunContext, bool]] = []
        self.active = 0
        self.max_active = 0

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: RunContext,
        *,
        deterministic: bool = False,
    ) -> str:
        self.calls.append((system_prompt, user_prompt, context, deterministic))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self.outputs.pop(0)
        finally:
            self.active -= 1


class SequenceReviewer:
    def __init__(self, scores: list[AgentDagCritique]) -> None:
        self.scores = list(scores)
        self.calls: list[tuple[str, str, RunContext]] = []

    async def critique(
        self,
        goal: str,
        answer: str,
        context: RunContext,
    ) -> AgentDagCritique:
        self.calls.append((goal, answer, context))
        return self.scores.pop(0)

    async def revise(
        self,
        goal: str,
        previous_plan: DagPlan,
        previous_answer: str,
        critique: AgentDagCritique,
        context: RunContext,
    ) -> DagPlan:
        del goal, previous_plan, previous_answer, critique, context
        raise AssertionError("reflexion must not invoke DAG replanning")


def context(tenant: str = "acme") -> RunContext:
    return RunContext(
        identity=TenantIdentity(tenant, "alice"),
        internal_token="must-not-enter-model-prompt",
        trace_id=f"trace-{tenant}",
    )


def critique(score: float, issue: str = "improve evidence") -> AgentDagCritique:
    return AgentDagCritique(
        correctness=score,
        completeness=score,
        clarity=score,
        mainIssue=issue,
    )


def test_settings_reject_default_vote_count_above_candidate_limit() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(
            _env_file=None,
            agent_voting_n=4,
            agent_voting_max_candidates=3,
        )


async def test_chain_runs_server_steps_in_order_and_preserves_context() -> None:
    generator = FakeGenerator(["translated output", "最终总结内容"])
    service = PromptChainService(
        generator,
        (
            ChainStepDefinition(
                name="translate",
                instruction="translate",
                gateMinLength=10,
            ),
            ChainStepDefinition(
                name="summarize",
                instruction="summarize",
                gateMinLength=5,
            ),
        ),
    )
    run_context = context()

    reply = await service.run(ChainRunRequest(input="原始输入"), run_context)

    assert reply.completed is True
    assert reply.final_output == "最终总结内容"
    assert [step.name for step in reply.steps] == ["translate", "summarize"]
    assert "translated output" in generator.calls[1][1]
    assert "summarize" in generator.calls[1][0]
    assert all(call[2] is run_context for call in generator.calls)
    assert "must-not-enter-model-prompt" not in str(
        [(call[0], call[1]) for call in generator.calls]
    )


async def test_chain_short_circuits_on_gate_failure() -> None:
    generator = FakeGenerator(["short", "must not run"])
    service = PromptChainService(
        generator,
        (
            ChainStepDefinition(name="first", instruction="one", gateMinLength=8),
            ChainStepDefinition(name="second", instruction="two"),
        ),
    )

    reply = await service.run(ChainRunRequest(input="hello"), context())

    assert reply.completed is False
    assert len(reply.steps) == 1
    assert reply.steps[0].gate_reason == "输出过短（5 < 8 字符）"
    assert len(generator.calls) == 1


async def test_chain_applies_contains_and_regex_gates_and_skips_invalid_regex() -> None:
    service = PromptChainService(
        FakeGenerator(["required value", "anything"]),
        (
            ChainStepDefinition(
                name="contains",
                instruction="one",
                gateMustContain="required",
                gateMustMatch=r"value$",
            ),
            ChainStepDefinition(
                name="bad-regex",
                instruction="two",
                gateMustMatch="[",
            ),
        ),
    )

    reply = await service.run(ChainRunRequest(input="hello"), context())

    assert reply.completed is True


@pytest.mark.parametrize(
    ("payload", "steps", "message"),
    [
        (ChainRunRequest(), (), "input is required"),
        (
            ChainRunRequest(input="hello"),
            (),
            "no chain steps configured",
        ),
    ],
)
async def test_chain_validates_before_generation(
    payload: ChainRunRequest,
    steps: tuple[ChainStepDefinition, ...],
    message: str,
) -> None:
    generator = FakeGenerator(["unused"])
    service = PromptChainService(generator, steps)

    with pytest.raises(SiblingValidationError, match=message):
        await service.run(payload, context())

    assert generator.calls == []


async def test_voting_majority_is_parallel_stable_and_case_insensitive() -> None:
    generator = FakeGenerator(["Yes", " yes ", "No"], delay=0.01)
    service = VotingService(
        generator,
        default_n=3,
        strategy=VotingStrategy.MAJORITY,
        min_agreement=0.7,
        max_parallel_workers=2,
    )
    run_context = context()

    reply = await service.run(VoteRequest(question="Proceed?"), run_context)

    assert reply.decision == "Yes"
    assert reply.agreement == pytest.approx(2 / 3)
    assert reply.confident is False
    assert generator.max_active == 2
    assert all(call[2] is run_context for call in generator.calls)


async def test_voting_synthesis_uses_deterministic_call_and_json_safe_agreement() -> None:
    generator = FakeGenerator(["A", "B", "combined"])
    service = VotingService(
        generator,
        default_n=2,
        strategy=VotingStrategy.SYNTHESIS,
    )

    reply = await service.run(VoteRequest(question="question"), context())

    assert reply.decision == "combined"
    assert reply.agreement is None
    assert reply.confident is True
    assert generator.calls[-1][3] is True
    assert "CANDIDATE 1:\nA" in generator.calls[-1][1]


@pytest.mark.parametrize("n", [0, 4])
async def test_voting_rejects_candidate_count_outside_bounds(n: int) -> None:
    generator = FakeGenerator(["unused"])
    service = VotingService(generator, max_candidates=3)

    with pytest.raises(SiblingValidationError, match="between 1 and 3"):
        await service.run(VoteRequest(question="q", n=n), context())

    assert generator.calls == []


async def test_reflexion_stops_when_threshold_is_accepted() -> None:
    generator = FakeGenerator(["initial"])
    reviewer = SequenceReviewer([critique(0.9, "n/a")])
    service = ReflexionService(generator, reviewer)

    reply = await service.run(ReflexionRequest(question="question"), context())

    assert reply.final_answer == "initial"
    assert reply.accepted_by_threshold is True
    assert len(reply.attempts) == 1
    assert len(generator.calls) == 1


async def test_reflexion_improves_until_budget_is_exhausted() -> None:
    generator = FakeGenerator(["initial", "improved once", "improved twice"])
    reviewer = SequenceReviewer([critique(0.2, "missing facts"), critique(0.4), critique(0.6)])
    service = ReflexionService(
        generator,
        reviewer,
        ReflexionPolicy(
            threshold=0.75,
            max_improvements=2,
            weights=CritiqueWeights(0.4, 0.4, 0.2),
        ),
    )
    run_context = context()

    reply = await service.run(ReflexionRequest(question="question"), run_context)

    assert reply.final_answer == "improved twice"
    assert reply.accepted_by_threshold is False
    assert [attempt.n for attempt in reply.attempts] == [1, 2, 3]
    assert "missing facts" in generator.calls[1][1]
    assert all(call[2] is run_context for call in generator.calls)
