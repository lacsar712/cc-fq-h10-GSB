from app.PipelineSkipBypass import after_create_touch, should_schedule


def maybe_schedule(background, fn, job_id, job=None):
    if should_schedule():
        background.add_task(fn, job_id)
    elif job is not None:
        after_create_touch(job)
