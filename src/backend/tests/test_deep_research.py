"""Regression tests for Perplexity response normalization."""

from types import SimpleNamespace

from backend.deep_research import PerplexityResponseData


def test_from_response_handles_none_queries_and_results() -> None:
    """Perplexity search result blocks may omit arrays instead of returning empty lists."""
    response = SimpleNamespace(
        output_text="memo",
        output=[
            SimpleNamespace(
                type="search_results",
                queries=None,
                results=None,
            )
        ],
        usage=None,
        model="test-model",
        id="resp-1",
    )

    data = PerplexityResponseData.from_response(response)

    assert data.output_text == "memo"
    assert data.search_queries is None
    assert data.citations is None
    assert data.model == "test-model"
    assert data.response_id == "resp-1"
