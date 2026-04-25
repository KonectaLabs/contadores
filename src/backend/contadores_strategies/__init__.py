"""Configurable Contadores sequence strategies."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.funnel_config import FunnelDefinition, FunnelStrategyDefinition, get_contadores_funnel

LOOM_STEP = "loom"


@dataclass(frozen=True)
class ContadoresOutboundDraft:
    """One outbound message draft produced by a strategy."""

    text: str
    sequence_step: str
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None


class ContadoresSequenceStrategy:
    """Base class for one Contadores strategy."""

    step: str = ""
    id: str = ""
    label: str = ""
    weight: int = 1

    def __init__(self, *, funnel: FunnelDefinition | None = None):
        self.funnel = funnel or get_contadores_funnel()

    def build_messages(self, *, lead: Any, config: Any) -> list[ContadoresOutboundDraft]:
        """Return the outbound drafts for this lead."""
        raise NotImplementedError


class ConfiguredContadoresStrategy(ContadoresSequenceStrategy):
    """Strategy loaded from the funnel definition."""

    def __init__(self, *, funnel: FunnelDefinition, definition: FunnelStrategyDefinition):
        super().__init__(funnel=funnel)
        self.definition = definition
        self.step = definition.step
        self.id = definition.id
        self.label = definition.label
        self.weight = definition.weight

    def build_messages(self, *, lead: Any, config: Any) -> list[ContadoresOutboundDraft]:
        del lead
        text = self.definition.message_text.strip()
        if self.definition.delivery == "link" and not text:
            text = str(getattr(config, "loom_url", "") or self.funnel.loom_url).strip()
        if not text:
            text = self.label
        return [
            ContadoresOutboundDraft(
                text=build_loom_intro_text(),
                sequence_step="loom_intro",
            ),
            ContadoresOutboundDraft(
                text=text,
                sequence_step=self.definition.sequence_step,
                media_type=self.definition.media_type,
                media_path=self.definition.media_path,
                media_caption=self.definition.media_caption,
            ),
        ]

ContadoresStrategyWeights = Mapping[str, Mapping[str, int]]


def list_contadores_strategies() -> list[ContadoresSequenceStrategy]:
    """Return every configured strategy."""
    funnel = get_contadores_funnel()
    return [
        ConfiguredContadoresStrategy(funnel=funnel, definition=definition)
        for definition in funnel.strategies
    ]


def build_loom_intro_text() -> str:
    """Return the shared pre-video explanation text."""
    return get_contadores_funnel().loom_intro_text


def list_contadores_strategies_by_step(step: str) -> list[ContadoresSequenceStrategy]:
    """Return configured strategies for one sequence step."""
    clean_step = (step or "").strip()
    return [strategy for strategy in list_contadores_strategies() if strategy.step == clean_step]


def get_contadores_strategy(step: str, strategy_id: str) -> ContadoresSequenceStrategy | None:
    """Return one configured strategy by step and id."""
    clean_strategy_id = (strategy_id or "").strip()
    for strategy in list_contadores_strategies_by_step(step):
        if strategy.id == clean_strategy_id:
            return strategy
    return None


def get_contadores_strategy_weight(
    strategy: ContadoresSequenceStrategy,
    strategy_weights: ContadoresStrategyWeights | None = None,
) -> int:
    """Return the effective rollout weight for one strategy."""
    configured_weight = (strategy_weights or {}).get(strategy.step, {}).get(strategy.id)
    if configured_weight is None:
        configured_weight = strategy.weight
    return max(0, int(configured_weight))


def choose_contadores_strategy(
    *,
    step: str,
    lead_id: str,
    strategy_id: str | None = None,
    strategy_weights: ContadoresStrategyWeights | None = None,
) -> ContadoresSequenceStrategy:
    """Choose a weighted strategy for a lead using stable random bucketing."""
    if strategy_id:
        strategy = get_contadores_strategy(step, strategy_id)
        if strategy is None:
            raise ValueError(f"Unknown Contadores strategy: {step}/{strategy_id}")
        return strategy

    strategies = list_contadores_strategies_by_step(step)
    if not strategies:
        raise ValueError(f"No Contadores strategies configured for step: {step}")

    total_weight = sum(
        get_contadores_strategy_weight(strategy, strategy_weights)
        for strategy in strategies
    )
    if total_weight <= 0:
        return strategies[0]

    bucket_source = f"{step}:{lead_id}".encode("utf-8")
    bucket = int(hashlib.sha256(bucket_source).hexdigest(), 16) % total_weight
    running_total = 0
    for strategy in strategies:
        running_total += get_contadores_strategy_weight(strategy, strategy_weights)
        if bucket < running_total:
            return strategy
    return strategies[-1]
