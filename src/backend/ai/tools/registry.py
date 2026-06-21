"""Shared agent tool registration types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel


ToolEffect = Literal["read", "side_effect", "provider_write"]


@dataclass(frozen=True)
class ToolRegistration:
    """One cohesive tool manifest entry plus execution metadata."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., dict[str, Any]]
    audit_target: Callable[[dict[str, Any]], tuple[str, str]] | None = None
    run_aware: bool = False
    effect: ToolEffect = "side_effect"
