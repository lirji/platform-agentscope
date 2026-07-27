from dataclasses import dataclass

from agentscope_platform.domain.dag import AgentDagCritique


@dataclass(frozen=True, slots=True)
class CritiqueWeights:
    correctness: float = 0.5
    completeness: float = 0.35
    clarity: float = 0.15


def aggregate_critique(
    critique: AgentDagCritique,
    weights: CritiqueWeights,
) -> float:
    total = weights.correctness + weights.completeness + weights.clarity
    if total <= 0:
        return (critique.correctness + critique.completeness + critique.clarity) / 3
    return (
        weights.correctness * critique.correctness
        + weights.completeness * critique.completeness
        + weights.clarity * critique.clarity
    ) / total
