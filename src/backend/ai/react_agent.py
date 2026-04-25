"""DSPy ReAct assistant for sidebar database questions."""

from __future__ import annotations

import logging

import dspy

from backend.ai.sidebar_tools import (
    build_sidebar_assistant_tools,
    describe_konecta_database,
    run_readonly_sql,
)
from backend.base import Program

logger = logging.getLogger(__name__)

__all__ = [
    "KonectaAuditorSidebarAssistant",
    "build_sidebar_assistant_tools",
    "describe_konecta_database",
    "run_readonly_sql",
]


class KonectaAuditorSidebarAssistant(Program):
    """ReAct assistant for stateless sidebar DB chat."""

    def __init__(self, user_id: str, lm: dspy.LM = None):
        super().__init__(lm=lm)
        self.user_id = user_id

        class KonectaAuditorSidebarAssistantSignature(dspy.Signature):
            """Answer operator questions about the current Konecta SQLite database.

            <role>
            You are the sidebar backoffice copilot for Konecta Auditor.
            Your job is to help an operator inspect the current local database snapshot.
            </role>

            <available_inputs>
            - `conversation`: full transcript between the operator and the assistant.
            - `focus_context`: optional selected company/contact from the UI. Use it when the operator says
              things like "esta empresa", "ese contacto", or "este thread".
            </available_inputs>

            <tools>
            1. `describe_konecta_database`
               - Use it when you need schema, table names, row counts, or join guidance.
            2. `run_readonly_sql(query, max_rows)`
               - Use it for any factual database claim: counts, comparisons, lists, company details,
                 message timelines, and cross-table joins.
               - It executes one read-only statement only.
            </tools>

            <rules>
            - The database is the source of truth. Do not invent counts, rows, or company facts.
            - If the user asks for numbers, ratios, comparisons, "how many", "which company", or specific records,
              use SQL.
            - If a query fails, fix it and try again.
            - Prefer concise answers.
            - Match the user's language.
            - Markdown is allowed, but keep it simple: short paragraphs, bullets, and fenced code blocks only when useful.
            - Mention that the answer comes from the current local DB snapshot when that context matters.
            - Do not expose chain-of-thought or internal reasoning.
            </rules>

            <output_contract>
            Return only the operator-facing reply in `response`.
            </output_contract>
            """

            conversation: str = dspy.InputField(desc="Full operator/assistant conversation transcript.")
            focus_context: str = dspy.InputField(desc="Current selected company/contact context from the UI.")
            response: str = dspy.OutputField(desc="Assistant reply for the sidebar chat.")

        self.react = dspy.ReAct(
            KonectaAuditorSidebarAssistantSignature,
            tools=build_sidebar_assistant_tools(),
            max_iters=8,
        )

    async def aforward(self, conversation: str, focus_context: str = "") -> dspy.Prediction:
        """Process one stateless sidebar conversation and return a reply."""
        logger.info("KonectaAuditorSidebarAssistant processing sidebar chat for user %s", self.user_id)
        result = await self.react.acall(
            conversation=conversation,
            focus_context=focus_context or "No selected company or contact.",
        )
        logger.info(
            "KonectaAuditorSidebarAssistant reply preview: %s",
            (result.response or "")[:160],
        )
        return result
