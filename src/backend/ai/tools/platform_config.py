"""Platform configuration agent tool registrations."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from backend.ai.tools.registry import ToolRegistration


def tool_registrations(
    *,
    read_args_model: type[BaseModel],
    validate_args_model: type[BaseModel],
    read_handler: Callable[[dict[str, Any]], dict[str, Any]],
    validate_handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[ToolRegistration]:
    """Return platform config tool registrations."""
    return [
        ToolRegistration(
            name="read_platform_config",
            description="Read funnels, delivery sources, config file paths, validation issues, and optional schemas.",
            args_model=read_args_model,
            handler=read_handler,
            audit_target=lambda _arguments: ("platform", "platform"),
            effect="read",
        ),
        ToolRegistration(
            name="validate_platform_config",
            description="Validate funnel and delivery setup before enabling automation.",
            args_model=validate_args_model,
            handler=validate_handler,
            audit_target=lambda _arguments: ("platform", "platform"),
            effect="read",
        ),
    ]
