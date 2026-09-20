from app.PipelineSkipBypass import should_schedule


def test_skip_schedule():
    assert should_schedule() is False


def test_reasons():
    from app.PipelineSkipBypass import list_hanging_reasons
    assert "background_task_not_queued" in list_hanging_reasons()
