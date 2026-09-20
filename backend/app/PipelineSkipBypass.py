"""BUG: skip scheduling actor chain after job create."""
from __future__ import annotations

SKIP_SCHEDULE = True
KEEP_PENDING = True


def should_schedule() -> bool:
    return not SKIP_SCHEDULE


def after_create_touch(job) -> None:
    if KEEP_PENDING:
        job.status = "pending"
        job.error_message = None


def list_hanging_reasons() -> list[str]:
    reasons = []
    if SKIP_SCHEDULE:
        reasons.append("background_task_not_queued")
    if KEEP_PENDING:
        reasons.append("status_forced_pending")
    return reasons or ["ok"]


def should_poll_forever(status: str) -> bool:
    return SKIP_SCHEDULE and status in {"pending", "running"}
