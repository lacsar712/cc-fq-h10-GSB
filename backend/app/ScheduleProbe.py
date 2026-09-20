from app.PipelineSkipBypass import KEEP_PENDING, SKIP_SCHEDULE, should_schedule


def describe_schedule() -> dict:
    return {
        "skip": SKIP_SCHEDULE,
        "keep_pending": KEEP_PENDING,
        "will_run": should_schedule(),
    }


def hanging_stage_template(actor_name: str, order: int) -> dict:
    return {
        "actor_name": actor_name,
        "stage_order": order,
        "status": "pending",
        "message": "未调度",
    }
