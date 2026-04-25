"""Tests for batch scan input shaping and concurrency."""

from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.testclient import TestClient
import pytest
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
from backend.ai.batch_input_to_company_urls import BatchInputToCompanyUrlsProgram
from backend.database import Company, TaskStatus
from backend.endpoints.companies import (
    BATCH_SCAN_MAX_CONCURRENCY,
    BatchCompanyScanJob,
    build_batch_scan_bundle,
    scan_companies_batch_core,
)
from backend.main import app


def test_batch_url_program_returns_llm_output_without_python_url_cleanup() -> None:
    program = BatchInputToCompanyUrlsProgram()

    async def fake_acall(*, bundled_input: str):
        assert bundled_input == "batch input"

        class Prediction:
            urls = [
                "example.com",
                "example.com",
                "https://linkedin.com/company/example",
            ]

        return Prediction()

    program.extractor.acall = fake_acall

    result = asyncio.run(program.aforward("batch input"))

    assert result.urls == [
        "example.com",
        "example.com",
        "https://linkedin.com/company/example",
    ]


def test_build_batch_scan_bundle_preserves_raw_text_blocks(monkeypatch) -> None:
    async def fake_extract_upload_file_text(file: UploadFile) -> str:
        return {
            "companies.csv": " https://one.com\nhttps://two.com\n",
            "deck.pdf": "Three Co - https://three.com",
        }[file.filename]

    monkeypatch.setattr(
        "backend.endpoints.companies.extract_upload_file_text",
        fake_extract_upload_file_text,
    )

    bundle = asyncio.run(
        build_batch_scan_bundle(
            freeform_text=" Example text block\nLine 2 ",
            files=[
                UploadFile(filename="companies.csv", file=BytesIO(b"csv")),
                UploadFile(filename="deck.pdf", file=BytesIO(b"pdf")),
            ],
        )
    )

    assert bundle == "\n----\n".join(
        [
            "freeform text:\n Example text block\nLine 2 ",
            "companies.csv:\n https://one.com\nhttps://two.com\n",
            "deck.pdf:\nThree Co - https://three.com",
        ]
    )


def test_scan_companies_batch_core_caps_concurrency_at_configured_limit(monkeypatch) -> None:
    jobs = [
        BatchCompanyScanJob(
            task_id=f"task-{index}",
            company_id=f"company-{index}",
            source_value=f"https://example-{index}.com",
        )
        for index in range(25)
    ]
    stats = {"current": 0, "max": 0}

    async def fake_execute_company_scan_task(_: BatchCompanyScanJob) -> None:
        stats["current"] += 1
        stats["max"] = max(stats["max"], stats["current"])
        await asyncio.sleep(0.01)
        stats["current"] -= 1
        return TaskStatus.COMPLETED

    monkeypatch.setattr(
        "backend.endpoints.companies.execute_company_scan_task",
        fake_execute_company_scan_task,
    )

    asyncio.run(scan_companies_batch_core(jobs))

    assert stats["max"] == BATCH_SCAN_MAX_CONCURRENCY


def test_scan_companies_batch_core_raises_when_any_job_fails(monkeypatch) -> None:
    jobs = [
        BatchCompanyScanJob(
            task_id="task-1",
            company_id="company-1",
            source_value="https://one.example",
        ),
        BatchCompanyScanJob(
            task_id="task-2",
            company_id="company-2",
            source_value="https://two.example",
        ),
    ]

    async def fake_execute_company_scan_task(job: BatchCompanyScanJob) -> TaskStatus:
        if job.company_id == "company-2":
            return TaskStatus.FAILED
        return TaskStatus.COMPLETED

    monkeypatch.setattr(
        "backend.endpoints.companies.execute_company_scan_task",
        fake_execute_company_scan_task,
    )

    with pytest.raises(RuntimeError, match="failed company scans"):
        asyncio.run(scan_companies_batch_core(jobs))


def test_scan_company_batch_accepts_json_text_payload(monkeypatch) -> None:
    created_companies: list[dict[str, object]] = []

    async def fake_extract_batch_urls(self, bundled_input: str):
        assert bundled_input == "freeform text:\nhttps://one.com\nhttps://two.com"
        return SimpleNamespace(urls=["https://one.com", "https://two.com"])

    def fake_company_create(**kwargs):
        company_id = f"company-{len(created_companies) + 1}"
        created_companies.append({"id": company_id, **kwargs})
        return SimpleNamespace(id=company_id)

    created_tasks: list[dict[str, str]] = []

    def fake_task_create(*, task_type: str, resource_id: str):
        task_id = f"task-{len(created_tasks) + 1}"
        created_tasks.append(
            {
                "id": task_id,
                "task_type": task_type,
                "resource_id": resource_id,
            }
        )
        return SimpleNamespace(id=task_id)

    def fake_run_async(background_tasks, fn, **kwargs):
        assert fn.__name__ == "scan_companies_batch_core"
        assert len(kwargs["scan_jobs"]) == 2
        return SimpleNamespace(id="batch-task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        return "ceo@example.com"

    monkeypatch.setattr(
        "backend.endpoints.companies.BatchInputToCompanyUrlsProgram.aforward",
        fake_extract_batch_urls,
    )
    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.create", fake_task_create)
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan-batch",
        json={
            "freeform_text": "https://one.com\nhttps://two.com",
            "objective": "Audit lead handling",
            "tags": ["vip", "argentina"],
            "conversation_automation_enabled": True,
            "ceo_delivery_enabled": True,
            "report_window_minutes": 90,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "batch-task-1",
        "company_ids": ["company-1", "company-2"],
        "company_count": 2,
        "status": "queued",
        "duplicate_count": 0,
        "duplicate_company_ids": [],
        "rejected_count": 0,
        "rejected_urls": [],
    }
    assert [item["source_url"] for item in created_companies] == [
        "https://one.com",
        "https://two.com",
    ]
    assert all(item["objective"] == "Audit lead handling" for item in created_companies)
    assert all(item["tags"] == ["vip", "argentina"] for item in created_companies)
    assert all(item["conversation_automation_enabled"] is True for item in created_companies)
    assert all(item["ceo_delivery_enabled"] is True for item in created_companies)
    assert all(item["ceo_email"] == "ceo@example.com" for item in created_companies)
    assert all(item["report_window_minutes"] == 90 for item in created_companies)
    assert [item["resource_id"] for item in created_tasks] == ["company-1", "company-2"]


def test_scan_company_batch_accepts_form_text_alias(monkeypatch) -> None:
    created_companies: list[dict[str, object]] = []

    async def fake_extract_batch_urls(self, bundled_input: str):
        assert bundled_input == "freeform text:\nhttps://one.com\nhttps://two.com"
        return SimpleNamespace(urls=["https://one.com", "https://two.com"])

    def fake_company_create(**kwargs):
        company_id = f"company-{len(created_companies) + 1}"
        created_companies.append({"id": company_id, **kwargs})
        return SimpleNamespace(id=company_id)

    created_tasks: list[dict[str, str]] = []

    def fake_task_create(*, task_type: str, resource_id: str):
        task_id = f"task-{len(created_tasks) + 1}"
        created_tasks.append(
            {
                "id": task_id,
                "task_type": task_type,
                "resource_id": resource_id,
            }
        )
        return SimpleNamespace(id=task_id)

    def fake_run_async(background_tasks, fn, **kwargs):
        assert fn.__name__ == "scan_companies_batch_core"
        assert len(kwargs["scan_jobs"]) == 2
        return SimpleNamespace(id="batch-task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        return "ceo@example.com"

    monkeypatch.setattr(
        "backend.endpoints.companies.BatchInputToCompanyUrlsProgram.aforward",
        fake_extract_batch_urls,
    )
    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.create", fake_task_create)
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan-batch",
        data={
            "text": "https://one.com\nhttps://two.com",
            "objective": "Audit lead handling",
            "tags": ["vip", "argentina"],
            "conversation_automation_enabled": "true",
            "ceo_delivery_enabled": "true",
            "report_window_minutes": "90",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "batch-task-1",
        "company_ids": ["company-1", "company-2"],
        "company_count": 2,
        "status": "queued",
        "duplicate_count": 0,
        "duplicate_company_ids": [],
        "rejected_count": 0,
        "rejected_urls": [],
    }
    assert [item["source_url"] for item in created_companies] == [
        "https://one.com",
        "https://two.com",
    ]
    assert all(item["objective"] == "Audit lead handling" for item in created_companies)
    assert all(item["tags"] == ["vip", "argentina"] for item in created_companies)
    assert all(item["conversation_automation_enabled"] is True for item in created_companies)
    assert all(item["ceo_delivery_enabled"] is True for item in created_companies)
    assert all(item["ceo_email"] == "ceo@example.com" for item in created_companies)
    assert all(item["report_window_minutes"] == 90 for item in created_companies)
    assert [item["resource_id"] for item in created_tasks] == ["company-1", "company-2"]


def test_scan_company_batch_rejects_urls_without_leadership_recipient(monkeypatch) -> None:
    async def fake_extract_batch_urls(self, bundled_input: str):
        assert bundled_input == "freeform text:\nhttps://one.com\nhttps://two.com"
        return SimpleNamespace(urls=["https://one.com", "https://two.com"])

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        raise HTTPException(status_code=422, detail="No leadership recipient email was found for this company.")

    monkeypatch.setattr(
        "backend.endpoints.companies.BatchInputToCompanyUrlsProgram.aforward",
        fake_extract_batch_urls,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan-batch",
        json={"freeform_text": "https://one.com\nhttps://two.com"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": None,
        "company_ids": [],
        "company_count": 0,
        "status": "rejected",
        "duplicate_count": 0,
        "duplicate_company_ids": [],
        "rejected_count": 2,
        "rejected_urls": ["https://one.com", "https://two.com"],
    }


def test_scan_company_batch_skips_duplicate_normalized_urls(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "batch-deduplicate.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_batch_urls(self, bundled_input: str):
        assert bundled_input == "freeform text:\nbatch body"
        return SimpleNamespace(
            urls=[
                "one.com",
                "https://www.one.com/?utm=1",
                "https://two.com",
                "http://two.com/",
            ]
        )

    created_tasks: list[dict[str, str]] = []

    def fake_task_create(*, task_type: str, resource_id: str):
        task_id = f"task-{len(created_tasks) + 1}"
        created_tasks.append(
            {
                "id": task_id,
                "task_type": task_type,
                "resource_id": resource_id,
            }
        )
        return SimpleNamespace(id=task_id)

    def fake_run_async(background_tasks, fn, **kwargs):
        assert fn.__name__ == "scan_companies_batch_core"
        assert len(kwargs["scan_jobs"]) == 2
        return SimpleNamespace(id="batch-task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        return "ceo@example.com"

    monkeypatch.setattr(
        "backend.endpoints.companies.BatchInputToCompanyUrlsProgram.aforward",
        fake_extract_batch_urls,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.create", fake_task_create)
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan-batch",
        json={
            "freeform_text": "batch body",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "batch-task-1"
    assert payload["company_count"] == 2
    assert payload["status"] == "queued"
    assert payload["duplicate_count"] == 2
    assert payload["rejected_count"] == 0
    assert len(payload["company_ids"]) == 2
    assert len(payload["duplicate_company_ids"]) == 2
    assert len(created_tasks) == 2

    created_companies = Company.list_recent()
    assert [item.source_url for item in created_companies] == [
        "https://two.com",
        "https://one.com",
    ]
    assert [item.normalized_source_url for item in created_companies] == [
        "two.com",
        "one.com",
    ]
