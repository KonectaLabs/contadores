"""Deep Research module using Perplexity Agentic Research API."""

import json
from typing import Any

from perplexity import AsyncPerplexity
from pydantic import BaseModel, Field

from backend.config import PERPLEXITY_API_KEY


class PerplexityResponseData(BaseModel):
    """Structured data extracted from Perplexity API response."""

    output_text: str = Field(default="")
    citations: str | None = Field(default=None, description="JSON string of citation objects")
    search_queries: str | None = Field(default=None, description="JSON string of search queries")
    model: str | None = Field(default=None)
    response_id: str | None = Field(default=None)
    usage: str | None = Field(default=None, description="JSON string of usage data")

    @classmethod
    def from_response(cls, response) -> "PerplexityResponseData":
        """Extract structured data from Perplexity response.

        Args:
            response: ResponseCreateResponse object from Perplexity API

        Returns:
            PerplexityResponseData with extracted fields
        """
        output_text = response.output_text
        citations = []
        search_queries = []

        output_items = getattr(response, "output", None) or []
        for output_item in output_items:
            if not hasattr(output_item, "type"):
                continue

            if output_item.type == "search_results":
                queries = getattr(output_item, "queries", None) or []
                if queries:
                    search_queries.extend(queries)

                results = getattr(output_item, "results", None) or []
                for result in results:
                    citation = {
                        "id": getattr(result, "id", None),
                        "title": getattr(result, "title", None)
                        or getattr(result, "url", None),
                        "url": getattr(result, "url", None),
                        "snippet": getattr(result, "snippet", None),
                        "date": getattr(result, "date", None),
                        "source": getattr(result, "source", None),
                    }
                    if citation["url"]:
                        citations.append(citation)

        usage_data = None
        usage_obj = getattr(response, "usage", None)
        if usage_obj:
            cost_obj = getattr(usage_obj, "cost", None)
            usage_data = {
                "input_tokens": getattr(usage_obj, "input_tokens", None),
                "output_tokens": getattr(usage_obj, "output_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
            if cost_obj:
                usage_data["cost"] = {
                    "currency": getattr(cost_obj, "currency", None),
                    "input_cost": getattr(cost_obj, "input_cost", None),
                    "output_cost": getattr(cost_obj, "output_cost", None),
                    "total_cost": getattr(cost_obj, "total_cost", None),
                }

        response_model = getattr(response, "model", None)
        response_id = getattr(response, "id", None)
        return cls(
            output_text=output_text,
            citations=json.dumps(citations) if citations else None,
            search_queries=json.dumps(search_queries) if search_queries else None,
            model=response_model,
            response_id=response_id,
            usage=json.dumps(usage_data) if usage_data else None,
        )


def extract_response_data(response) -> dict[str, Any]:
    """Backward-compatible function that returns dict representation.

    Args:
        response: ResponseCreateResponse object from Perplexity API

    Returns:
        Dict with output_text, citations, search_queries, model, response_id, usage
    """
    data = PerplexityResponseData.from_response(response)
    return data.model_dump()


async def fast_search(query: str, model: str = None):
    """Conduct fast search using Perplexity fast-search preset with grok model override."""
    client = AsyncPerplexity(api_key=PERPLEXITY_API_KEY)
    try:
        if model is None:
            model = "xai/grok-4-1-fast-non-reasoning"

        response = await client.responses.create(
            preset="fast-search",
            model=model,
            input=query,
        )
        return response
    finally:
        try:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                await client.close()
        except (RuntimeError, Exception):
            pass


async def pro_search(query: str, model: str = None):
    """Conduct pro research using Perplexity pro-search preset with grok model override."""
    client = AsyncPerplexity(api_key=PERPLEXITY_API_KEY)
    try:
        if model is None:
            model = "xai/grok-4-1-fast-non-reasoning"

        response = await client.responses.create(
            preset="pro-search",
            model=model,
            input=query,
        )
        return response
    finally:
        try:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                await client.close()
        except (RuntimeError, Exception):
            pass


async def deep_research(query: str):
    """Conduct deep research using Perplexity deep-research preset with grok model override."""
    client = AsyncPerplexity(api_key=PERPLEXITY_API_KEY)
    try:
        response = await client.responses.create(
            preset="deep-research",
            input=query,
        )
        return response
    finally:
        try:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                await client.close()
        except (RuntimeError, Exception):
            pass


if __name__ == "__main__":
    import asyncio

    query = """Search for a faster alternative to Musetalk 1.5 for video + audio -> lipsynced video\nit needs to be open source and open weights so I can run it, it needs to be faster than musetalk, because musetalk is too slow on my tests... so latentsync will not work, things like flashlips are promising looking faster, but there are no weights... go ahead and bring me new alternatives, from 2026 or late 2025"""
    result = asyncio.run(fast_search(query))
    data = extract_response_data(result)
    print(json.dumps(data, indent=2))
