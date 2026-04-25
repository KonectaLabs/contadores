"""Tests for the automated daily auditor intake loop."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

import utils
from utils import automated_auditor_daily_tag, run_automated_auditor_intake_iteration


def test_run_automated_auditor_intake_iteration_skips_before_window(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 11, 0, tzinfo=timezone.utc),
    )

    result = asyncio.run(run_automated_auditor_intake_iteration(SimpleNamespace()))

    assert result == {
        "status": "before_window",
        "local_date": "2026-04-06",
        "target_count": utils.AUTOMATED_AUDITOR_COMPANIES_PER_DAY,
    }


def test_run_automated_auditor_intake_iteration_discovers_and_scans_companies(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 2)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 15, 0, tzinfo=timezone.utc),
    )

    scan_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            assert request.url.params["limit"] == "500"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "known-company",
                        "source_url": "https://known.example",
                        "company_name": "Known Co",
                        "tags": ["manual"],
                    }
                ],
            )

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            body = json.loads(request.content.decode("utf-8"))
            assert body == {
                "count": 2,
                "exclude_company_urls": ["https://known.example"],
                "exclude_company_names": ["Known Co"],
            }
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Acme Logistics",
                            "website_url": "https://acme-logistics.example",
                            "industry": "logistics",
                            "country_or_region": "Argentina",
                            "fit_summary": "Inbound quote requests appear central to revenue.",
                            "likely_contact_owner": "Sales coordinators",
                            "leadership_recipient_name": "Jane Doe",
                            "leadership_recipient_role": "Managing Director",
                            "leadership_recipient_email": "jane@acme-logistics.example",
                            "leadership_recipient_evidence": "A public leadership page ties Jane Doe to the managing director role and company email.",
                            "public_contact_channels": ["email", "quote form"],
                            "public_contact_paths": ["https://acme-logistics.example/contact"],
                            "lead_dependency_evidence": ["The site pushes users to ask for a quote."],
                            "source_urls": ["https://acme-logistics.example/contact"],
                        },
                        {
                            "company_name": "Beta Industrial",
                            "website_url": "https://beta-industrial.example",
                            "industry": "industrial b2b services",
                            "country_or_region": "Chile",
                            "fit_summary": "Public commercial contacts seem critical to lead intake.",
                            "likely_contact_owner": "Commercial team",
                            "leadership_recipient_name": "John Roe",
                            "leadership_recipient_role": "CEO",
                            "leadership_recipient_email": "john@beta-industrial.example",
                            "leadership_recipient_evidence": "The company leadership page ties John Roe to the CEO role and company email.",
                            "public_contact_channels": ["email", "whatsapp"],
                            "public_contact_paths": ["https://beta-industrial.example/contacto"],
                            "lead_dependency_evidence": ["The homepage asks buyers to contact sales."],
                            "source_urls": ["https://beta-industrial.example/contacto"],
                        },
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            body = json.loads(request.content.decode("utf-8"))
            scan_calls.append(body)
            company_number = len(scan_calls)
            return httpx.Response(
                200,
                json={
                    "task_id": f"task-{company_number}",
                    "company_id": f"company-{company_number}",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    daily_tag = automated_auditor_daily_tag(datetime(2026, 4, 6).date())
    assert result == {
        "status": "completed",
        "local_date": "2026-04-06",
        "target_count": 2,
        "already_loaded_today": 0,
        "discovered": 2,
        "created": 2,
        "duplicates": 0,
        "rejected": 0,
        "attempts": 1,
        "scheduled_weekend_holds": 0,
        "remaining_after": 0,
        "run_tag": daily_tag,
    }
    assert scan_calls == [
        {
            "url": "https://acme-logistics.example",
            "objective": utils.AUTOMATED_AUDITOR_OBJECTIVE,
            "tags": ["auto-intake", daily_tag, "industry:logistics"],
            "conversation_automation_enabled": True,
            "ceo_delivery_enabled": True,
        },
        {
            "url": "https://beta-industrial.example",
            "objective": utils.AUTOMATED_AUDITOR_OBJECTIVE,
            "tags": ["auto-intake", daily_tag, "industry:industrial-b2b-services"],
            "conversation_automation_enabled": True,
            "ceo_delivery_enabled": True,
        },
    ]


def test_run_automated_auditor_intake_iteration_applies_weekend_hold(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 1)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_WEEKEND_HOLD_HOUR_LOCAL", 20)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 4, 15, 0, tzinfo=timezone.utc),
    )

    put_bodies: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            return httpx.Response(200, json=[])

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Weekend Target",
                            "website_url": "https://weekend-target.example",
                            "industry": "education",
                            "country_or_region": "Brazil",
                            "fit_summary": "Admissions contact handling appears commercially important.",
                            "likely_contact_owner": "Admissions team",
                            "leadership_recipient_name": "Ana Silva",
                            "leadership_recipient_role": "Founder",
                            "leadership_recipient_email": "ana@weekend-target.example",
                            "leadership_recipient_evidence": "A public founder profile ties Ana Silva to the founder role and company email.",
                            "public_contact_channels": ["email", "form"],
                            "public_contact_paths": ["https://weekend-target.example/contact"],
                            "lead_dependency_evidence": ["The site asks prospects to talk to admissions."],
                            "source_urls": ["https://weekend-target.example/contact"],
                        }
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-1",
                    "company_id": "company-1",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        if request.method == "PUT" and request.url.path == "/api/companies/company-1/report-schedule":
            put_bodies.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "company_id": "company-1",
                    "scheduled_send_at": put_bodies[-1]["scheduled_send_at"],
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    assert result["scheduled_weekend_holds"] == 1
    assert result["rejected"] == 0
    assert result["attempts"] == 1
    assert put_bodies == [{"scheduled_send_at": "2026-04-06T20:00:00-03:00"}]


def test_run_automated_auditor_intake_iteration_retries_when_scan_rejects_candidate(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 2)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 15, 0, tzinfo=timezone.utc),
    )

    discovery_calls: list[dict[str, object]] = []
    scan_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            return httpx.Response(200, json=[])

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            body = json.loads(request.content.decode("utf-8"))
            discovery_calls.append(body)
            if len(discovery_calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "companies": [
                            {
                                "company_name": "Rejected Candidate",
                                "website_url": "https://rejected.example",
                                "industry": "logistics",
                                "country_or_region": "Argentina",
                                "fit_summary": "Looks like a fit.",
                                "likely_contact_owner": "Sales team",
                                "leadership_recipient_name": "Missing Recipient",
                                "leadership_recipient_role": "CEO",
                                "leadership_recipient_email": "missing@rejected.example",
                                "leadership_recipient_evidence": "Weak evidence.",
                                "public_contact_channels": ["email"],
                                "public_contact_paths": ["https://rejected.example/contact"],
                                "lead_dependency_evidence": ["Public quote flow."],
                                "source_urls": ["https://rejected.example/contact"],
                            },
                            {
                                "company_name": "Accepted One",
                                "website_url": "https://accepted-one.example",
                                "industry": "software",
                                "country_or_region": "Chile",
                                "fit_summary": "Looks like a fit.",
                                "likely_contact_owner": "Sales ops",
                                "leadership_recipient_name": "Alice Doe",
                                "leadership_recipient_role": "Founder",
                                "leadership_recipient_email": "alice@accepted-one.example",
                                "leadership_recipient_evidence": "Public founder page.",
                                "public_contact_channels": ["email"],
                                "public_contact_paths": ["https://accepted-one.example/contact"],
                                "lead_dependency_evidence": ["Demo requests matter."],
                                "source_urls": ["https://accepted-one.example/contact"],
                            },
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Accepted Two",
                            "website_url": "https://accepted-two.example",
                            "industry": "education",
                            "country_or_region": "Brazil",
                            "fit_summary": "Looks like a fit.",
                            "likely_contact_owner": "Admissions",
                            "leadership_recipient_name": "Bob Doe",
                            "leadership_recipient_role": "Managing Director",
                            "leadership_recipient_email": "bob@accepted-two.example",
                            "leadership_recipient_evidence": "Public leadership page.",
                            "public_contact_channels": ["email"],
                            "public_contact_paths": ["https://accepted-two.example/contact"],
                            "lead_dependency_evidence": ["Admissions flow matters."],
                            "source_urls": ["https://accepted-two.example/contact"],
                        }
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            body = json.loads(request.content.decode("utf-8"))
            scan_calls.append(body)
            if body["url"] == "https://rejected.example":
                return httpx.Response(422, json={"detail": "No leadership recipient email was found for this company."})
            return httpx.Response(
                200,
                json={
                    "task_id": f"task-{len(scan_calls)}",
                    "company_id": f"company-{len(scan_calls)}",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    assert result["created"] == 2
    assert result["rejected"] == 1
    assert result["attempts"] == 2
    assert result["discovered"] == 3
    assert all("ceo_email" not in item for item in scan_calls)
    assert discovery_calls == [
        {
            "count": 2,
            "exclude_company_urls": [],
            "exclude_company_names": [],
        },
        {
            "count": 1,
            "exclude_company_urls": [
                "https://accepted-one.example",
                "https://rejected.example",
            ],
            "exclude_company_names": [
                "Accepted One",
                "Rejected Candidate",
            ],
        },
    ]


def test_run_automated_auditor_intake_iteration_retries_after_partial_and_empty_discovery(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 2)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 15, 0, tzinfo=timezone.utc),
    )

    discovery_calls: list[dict[str, object]] = []
    scan_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            return httpx.Response(200, json=[])

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            body = json.loads(request.content.decode("utf-8"))
            discovery_calls.append(body)
            if len(discovery_calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "companies": [
                            {
                                "company_name": "Accepted One",
                                "website_url": "https://accepted-one.example",
                                "industry": "software",
                                "country_or_region": "Chile",
                                "fit_summary": "Looks like a fit.",
                                "likely_contact_owner": "Sales ops",
                                "leadership_recipient_name": "Alice Doe",
                                "leadership_recipient_role": "Founder",
                                "leadership_recipient_email": "alice@accepted-one.example",
                                "leadership_recipient_evidence": "Public founder page.",
                                "public_contact_channels": ["email"],
                                "public_contact_paths": ["https://accepted-one.example/contact"],
                                "lead_dependency_evidence": ["Demo requests matter."],
                                "source_urls": ["https://accepted-one.example/contact"],
                            }
                        ]
                    },
                )
            if len(discovery_calls) == 2:
                return httpx.Response(200, json={"companies": []})
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Accepted Two",
                            "website_url": "https://accepted-two.example",
                            "industry": "education",
                            "country_or_region": "Brazil",
                            "fit_summary": "Looks like a fit.",
                            "likely_contact_owner": "Admissions",
                            "leadership_recipient_name": "Bob Doe",
                            "leadership_recipient_role": "Managing Director",
                            "leadership_recipient_email": "bob@accepted-two.example",
                            "leadership_recipient_evidence": "Public leadership page.",
                            "public_contact_channels": ["email"],
                            "public_contact_paths": ["https://accepted-two.example/contact"],
                            "lead_dependency_evidence": ["Admissions flow matters."],
                            "source_urls": ["https://accepted-two.example/contact"],
                        }
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            body = json.loads(request.content.decode("utf-8"))
            scan_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "task_id": f"task-{len(scan_calls)}",
                    "company_id": f"company-{len(scan_calls)}",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    assert result["created"] == 2
    assert result["discovered"] == 2
    assert result["attempts"] == 3
    assert discovery_calls == [
        {
            "count": 2,
            "exclude_company_urls": [],
            "exclude_company_names": [],
        },
        {
            "count": 1,
            "exclude_company_urls": ["https://accepted-one.example"],
            "exclude_company_names": ["Accepted One"],
        },
        {
            "count": 1,
            "exclude_company_urls": ["https://accepted-one.example"],
            "exclude_company_names": ["Accepted One"],
        },
    ]
    assert [call["url"] for call in scan_calls] == [
        "https://accepted-one.example",
        "https://accepted-two.example",
    ]


def test_run_automated_auditor_intake_iteration_retries_when_discovery_returns_zero(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 2)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 15, 0, tzinfo=timezone.utc),
    )

    discovery_calls: list[dict[str, object]] = []
    scan_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            return httpx.Response(200, json=[])

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            body = json.loads(request.content.decode("utf-8"))
            discovery_calls.append(body)
            if len(discovery_calls) == 1:
                return httpx.Response(200, json={"companies": []})
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Recovered One",
                            "website_url": "https://recovered-one.example",
                            "industry": "logistics",
                            "country_or_region": "Argentina",
                            "fit_summary": "Looks like a fit.",
                            "likely_contact_owner": "Sales team",
                            "leadership_recipient_name": "Jane Doe",
                            "leadership_recipient_role": "CEO",
                            "leadership_recipient_email": "jane@recovered-one.example",
                            "leadership_recipient_evidence": "Public CEO page.",
                            "public_contact_channels": ["email"],
                            "public_contact_paths": ["https://recovered-one.example/contact"],
                            "lead_dependency_evidence": ["Public quote flow."],
                            "source_urls": ["https://recovered-one.example/contact"],
                        },
                        {
                            "company_name": "Recovered Two",
                            "website_url": "https://recovered-two.example",
                            "industry": "software",
                            "country_or_region": "Chile",
                            "fit_summary": "Looks like a fit.",
                            "likely_contact_owner": "Sales ops",
                            "leadership_recipient_name": "John Doe",
                            "leadership_recipient_role": "Founder",
                            "leadership_recipient_email": "john@recovered-two.example",
                            "leadership_recipient_evidence": "Public founder page.",
                            "public_contact_channels": ["email"],
                            "public_contact_paths": ["https://recovered-two.example/contact"],
                            "lead_dependency_evidence": ["Demo requests matter."],
                            "source_urls": ["https://recovered-two.example/contact"],
                        },
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            body = json.loads(request.content.decode("utf-8"))
            scan_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "task_id": f"task-{len(scan_calls)}",
                    "company_id": f"company-{len(scan_calls)}",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    assert result["created"] == 2
    assert result["attempts"] == 2
    assert result["discovered"] == 2
    assert discovery_calls[0]["count"] == 2
    assert discovery_calls[1]["count"] == 2
    assert len(scan_calls) == 2


def test_run_automated_auditor_intake_iteration_requests_missing_remainder(monkeypatch) -> None:
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_INTAKE_ENABLED", True)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANIES_PER_DAY", 2)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", 500)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", 9)
    monkeypatch.setattr(utils, "AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", 0)
    monkeypatch.setattr(
        utils,
        "get_automated_auditor_now_utc",
        lambda: datetime(2026, 4, 6, 15, 0, tzinfo=timezone.utc),
    )

    discovery_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/companies":
            return httpx.Response(200, json=[])

        if request.method == "POST" and request.url.path == "/api/companies/discover-auditor-candidates":
            body = json.loads(request.content.decode("utf-8"))
            discovery_calls.append(body)
            if len(discovery_calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "companies": [
                            {
                                "company_name": "Partial One",
                                "website_url": "https://partial-one.example",
                                "industry": "logistics",
                                "country_or_region": "Argentina",
                                "fit_summary": "Looks like a fit.",
                                "likely_contact_owner": "Sales team",
                                "leadership_recipient_name": "Jane Doe",
                                "leadership_recipient_role": "CEO",
                                "leadership_recipient_email": "jane@partial-one.example",
                                "leadership_recipient_evidence": "Public CEO page.",
                                "public_contact_channels": ["email"],
                                "public_contact_paths": ["https://partial-one.example/contact"],
                                "lead_dependency_evidence": ["Public quote flow."],
                                "source_urls": ["https://partial-one.example/contact"],
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "companies": [
                        {
                            "company_name": "Partial Two",
                            "website_url": "https://partial-two.example",
                            "industry": "software",
                            "country_or_region": "Chile",
                            "fit_summary": "Looks like a fit.",
                            "likely_contact_owner": "Sales ops",
                            "leadership_recipient_name": "John Doe",
                            "leadership_recipient_role": "Founder",
                            "leadership_recipient_email": "john@partial-two.example",
                            "leadership_recipient_evidence": "Public founder page.",
                            "public_contact_channels": ["email"],
                            "public_contact_paths": ["https://partial-two.example/contact"],
                            "lead_dependency_evidence": ["Demo requests matter."],
                            "source_urls": ["https://partial-two.example/contact"],
                        }
                    ]
                },
            )

        if request.method == "POST" and request.url.path == "/api/companies/scan":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-1",
                    "company_id": f"company-{len(discovery_calls)}",
                    "status": "queued",
                    "duplicate_ignored": False,
                },
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_automated_auditor_intake_iteration(client)

    result = asyncio.run(run())

    assert result["created"] == 2
    assert result["attempts"] == 2
    assert result["discovered"] == 2
    assert discovery_calls == [
        {
            "count": 2,
            "exclude_company_urls": [],
            "exclude_company_names": [],
        },
        {
            "count": 1,
            "exclude_company_urls": ["https://partial-one.example"],
            "exclude_company_names": ["Partial One"],
        },
    ]
