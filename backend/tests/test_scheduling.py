"""调度复验：作业创建后必须真实入队执行，阶段不能永久 pending。

背景：曾存在 PipelineSkipBypass/ScheduleGate，创建作业后不入队后台任务
还强制保持 pending，导致四阶段永久待处理。相关旁路已废除。
"""

from __future__ import annotations

import time

import pytest

STAGE_ORDER = [
    "ParseActor",
    "QualityHistActor",
    "NContentActor",
    "ReportActor",
]


def _stage_map(payload):
    return {s["actor_name"]: s for s in payload}


def _wait_terminal(client, job_id, headers=None, timeout=5.0):
    """轮询直到作业进入终态；超时则返回最后一次状态（测试随后断言）。"""
    deadline = time.monotonic() + timeout
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("success", "failed"):
            return job
        time.sleep(0.05)
    return job


def test_no_bypass_modules_left():
    # 调度旁路与 pending 伪装模块必须彻底废除
    with pytest.raises(ModuleNotFoundError):
        __import__("app.PipelineSkipBypass", fromlist=["x"])
    with pytest.raises(ModuleNotFoundError):
        __import__("app.ScheduleGate", fromlist=["x"])
    with pytest.raises(ModuleNotFoundError):
        __import__("app.ScheduleProbe", fromlist=["x"])


def test_create_response_then_stages_leave_pending(client, auth_headers):
    # 创建瞬间可以是 pending，但短暂等待后不允许四阶段全部待处理
    resp = client.post("/api/jobs", json={"sampleId": 1}, headers=auth_headers)
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    statuses = None
    while time.monotonic() < deadline:
        stages = client.get(f"/api/jobs/{job_id}/stages", headers=auth_headers).json()
        statuses = [s["status"] for s in sorted(stages, key=lambda s: s["stage_order"])]
        if any(s != "pending" for s in statuses):
            break
        time.sleep(0.05)
    assert statuses is not None
    assert any(s != "pending" for s in statuses), f"阶段始终全为待处理: {statuses}"


def test_good_sample_runs_four_stages_to_success(client, auth_headers):
    resp = client.post("/api/jobs", json={"sampleId": 1}, headers=auth_headers)
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    job = _wait_terminal(client, job_id, headers=auth_headers)
    assert job["status"] == "success", job.get("error_message")
    assert job["error_message"] is None
    assert job["finished_at"] is not None

    stages = _stage_map(
        client.get(f"/api/jobs/{job_id}/stages", headers=auth_headers).json()
    )
    assert [stages[n]["status"] for n in STAGE_ORDER] == ["success"] * 4
    for name in STAGE_ORDER:
        assert stages[name]["started_at"] is not None
        assert stages[name]["finished_at"] is not None

    metrics = job["metrics"]
    assert metrics["reads"] == 3
    assert metrics["mean_quality"] > 0
    assert "n_rate" in metrics
    assert metrics["report"] is not None


def test_broken_sample_fails_parse_and_skips_rest(client, auth_headers):
    resp = client.post("/api/jobs", json={"sampleId": 2}, headers=auth_headers)
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    job = _wait_terminal(client, job_id, headers=auth_headers)
    assert job["status"] == "failed"
    assert job["error_message"]
    assert job["finished_at"] is not None

    stages = _stage_map(
        client.get(f"/api/jobs/{job_id}/stages", headers=auth_headers).json()
    )
    assert stages["ParseActor"]["status"] == "failed"
    assert [stages[n]["status"] for n in STAGE_ORDER[1:]] == ["skipped"] * 3


def test_custom_fastq_text_is_also_scheduled(client, auth_headers):
    fastq = "@CUSTOM1\nACGTACGT\n+\nIIIIHHHH\n"
    resp = client.post("/api/jobs", json={"fastqText": fastq}, headers=auth_headers)
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    job = _wait_terminal(client, job_id, headers=auth_headers)
    assert job["status"] == "success"
    stages = _stage_map(
        client.get(f"/api/jobs/{job_id}/stages", headers=auth_headers).json()
    )
    assert [stages[n]["status"] for n in STAGE_ORDER] == ["success"] * 4


def test_auditor_cannot_submit(client):
    # auditor 只读，提交仍应被拒绝（调度修复不改变鉴权）
    from app.auth import create_access_token

    token = create_access_token("auditor", "auditor")
    resp = client.post(
        "/api/jobs",
        json={"sampleId": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
