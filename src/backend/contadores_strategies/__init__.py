"""Code-defined Contadores sequence strategies."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


LOOM_STEP = "loom"
LOOM_MP4_PATH = "data/contadores/videos/loom_60_seconds_captions.mp4"


@dataclass(frozen=True)
class ContadoresOutboundDraft:
    """One outbound message draft produced by a strategy."""

    text: str
    sequence_step: str
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None


class ContadoresSequenceStrategy:
    """Base class for one code-defined Contadores strategy."""

    step: str = ""
    id: str = ""
    label: str = ""
    weight: int = 1

    def build_messages(self, *, lead: Any, config: Any) -> list[ContadoresOutboundDraft]:
        """Return the outbound drafts for this lead."""
        raise NotImplementedError


class LoomLinkStrategy(ContadoresSequenceStrategy):
    """Send the existing Loom URL as a text link."""

    step = LOOM_STEP
    id = "loom_link"
    label = "Loom link"
    weight = 0

    def build_messages(self, *, lead: Any, config: Any) -> list[ContadoresOutboundDraft]:
        del lead
        return [
            ContadoresOutboundDraft(
                text=build_loom_intro_text(),
                sequence_step="loom_intro",
            ),
            ContadoresOutboundDraft(
                text=str(config.loom_url or "").strip(),
                sequence_step="loom_url",
            ),
        ]


class LoomMp4Strategy(ContadoresSequenceStrategy):
    """Send the explanation video directly as a WhatsApp MP4."""

    step = LOOM_STEP
    id = "loom_mp4"
    label = "WhatsApp MP4"
    weight = 100

    def build_messages(self, *, lead: Any, config: Any) -> list[ContadoresOutboundDraft]:
        del lead, config
        return [
            ContadoresOutboundDraft(
                text=build_loom_intro_text(),
                sequence_step="loom_intro",
            ),
            ContadoresOutboundDraft(
                text="Video de explicación enviado por WhatsApp.",
                sequence_step="loom_video",
                media_type="video",
                media_path=LOOM_MP4_PATH,
            ),
        ]


def build_loom_intro_text() -> str:
    """Return the shared pre-video explanation text."""
    return (
        "Perfecto. Te cuento rápido:\n"
        "Los contadores que trabajan con nosotros reciben un flujo de prospectos y posibles "
        "clientes que les llega directo al WhatsApp de forma automática.\n"
        "Te invito a que veas este video donde te explicamos la propuesta a detalle:"
    )


STRATEGIES: tuple[ContadoresSequenceStrategy, ...] = (
    LoomLinkStrategy(),
    LoomMp4Strategy(),
)

ContadoresStrategyWeights = Mapping[str, Mapping[str, int]]


def list_contadores_strategies() -> list[ContadoresSequenceStrategy]:
    """Return every configured strategy."""
    return list(STRATEGIES)


def list_contadores_strategies_by_step(step: str) -> list[ContadoresSequenceStrategy]:
    """Return configured strategies for one sequence step."""
    clean_step = (step or "").strip()
    return [strategy for strategy in STRATEGIES if strategy.step == clean_step]


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
