"""Task endpoints for generic frontend polling."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from backend.database import Company, CompanyStatus, Task, TaskStatus, engine

tasks_router = APIRouter(prefix="/api", tags=["tasks"])


def mark_running_tasks_as_failed() -> None:
    """Mark non-terminal tasks as failed during startup recovery."""
    with Session(engine) as session:
        pending_tasks = session.exec(
            select(Task).where(Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING]))
        ).all()
        for task in pending_tasks:
            task.status = TaskStatus.FAILED
            task.error = "Task was pending when server restarted"
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            if task.task_type == "run_company_scan_task" and task.resource_id:
                company = session.get(Company, task.resource_id)
                if company:
                    company.status = CompanyStatus.FAILED
                    company.updated_at = datetime.now(timezone.utc)
                    session.add(company)
        session.commit()


@tasks_router.get("/tasks/{task_id}", response_model=Task)
async def get_task_status(task_id: str):
    """Get one task by ID."""
    task = Task.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
