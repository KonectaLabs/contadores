"""Tests for PDF rendering with per-contact objectives."""

from __future__ import annotations

from backend.report_pdf import (
    ContactItemModel,
    HeroModel,
    ReportDocumentModel,
    ThreadInsightBlockModel,
    ThreadMessageModel,
    ThreadModel,
    ThreadQuoteModel,
    build_vector_pdf,
)


def test_build_vector_pdf_renders_thread_objective_without_layout_overflow() -> None:
    document = ReportDocumentModel(
        hero=HeroModel(
            company="Example Motors",
            url="example.com",
            line_1="Sales audit snapshot",
            line_2_a="1 active contact",
            line_2_b="1 conversation reviewed",
            context="We tested how the seller handled a realistic buyer objective.",
            impact="The seller answered the core question and kept momentum.",
            auth="Konecta Auditor",
        ),
        contacts=[
            ContactItemModel(
                value="sales@example.com",
                meta="Email · responsive",
            )
        ],
        threads=[
            ThreadModel(
                title="sales@example.com",
                channel="Email",
                objective_text="Ask whether they have a Toyota T-Cross, the price, and which option they recommend",
                status_kind="ok",
                status_text="Helpful",
                messages=[
                    ThreadMessageModel(
                        side="buyer",
                        badge="Buyer",
                        timestamp="10:00",
                        text="Hola, queria consultar por una Toyota T-Cross.",
                    ),
                    ThreadMessageModel(
                        side="seller",
                        badge="Seller",
                        timestamp="10:02",
                        text="Si, tenemos disponibilidad. Sale 32.000 y por equipamiento tambien te recomendaria mirar la Taos.",
                    ),
                ],
                insight_title="Seller assessment",
                insight_blocks=[
                    ThreadInsightBlockModel(
                        label="Objective result",
                        text="Achieved. The seller answered availability and price, then added a recommendation with context.",
                    ),
                    ThreadInsightBlockModel(
                        label="Clarity",
                        text="The reply was direct and easy to understand.",
                    ),
                ],
                quote=ThreadQuoteModel(
                    quote="Si, tenemos disponibilidad.",
                    attribution="Seller reply",
                    observed="Fast answer",
                ),
            )
        ],
        conclusion_text="The seller resolved the tested objective and left a reasonable next step.",
    )

    pdf_bytes = build_vector_pdf(document, strict_layout_fit=True)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1_000
