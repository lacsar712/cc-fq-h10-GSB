"""调度校正集成测试。

复验点:
1. 作业创建后必须经 BackgroundTasks 入队执行(无旁路);
2. 不允许永久 pending 冒充正常;
3. 合格样例 → 四阶段推进并成功;损坏样例 → ParseActor 失败、作业失败;
4. 创建后短暂等待,阶段不再全部停留在 pending。
"""

from __future__ import annotations

import importlib.util
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from starlette.background import BackgroundTasks

from app import api as api_module
from app.models import Job, JobStage

STAGE_CHAIN = ["ParseActor", "QualityHistActor", "NContentActor", "ReportActor"]


def test_bypass_modules_removed():
    """PipelineSkipBypass / ScheduleGate / ScheduleProbe 必须已废除。"""
    for name in ("app.PipelineSkipBypass", "app.ScheduleGate", "app.ScheduleProbe"):
        assert importlib.util.find_spec(name) is None, f"{name} 不应再存在"


def test_created_job_is_enqueued(
    client: TestClient,
    bioops_headers: dict[str, str],
    db_session: sessionmaker,
    sample_ids: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
):
    """创建作业时必须向 BackgroundTasks 入队 _run_job_background(入队端口不变)。"""
    enqueued: list[tuple[object, tuple]] = []
    original = BackgroundTasks.add_task

    def spy_add_task(self, func, *args, **kwargs):
        enqueued.append((func, args))
        return original(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", spy_add_task)

    resp = client.post("/api/jobs", json={"sampleId": sample_ids["demo-good-r1"]}, headers=bioops_headers)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    calls = [(fn, args) for fn, args in enqueued if fn is api_module._run_job_background]
    assert calls, "创建后必须将 _run_job_background 入队"
    assert calls[0][1] == (job_id,)


def _poll_stages(
    client: TestClient, job_id: int, headers: dict[str, str], timeout: float = 5.0
) -> list[dict]:
    """短暂轮询直到阶段离开全 pending,返回最终阶段列表。"""
    deadline = time.monotonic() + timeout
    while True:
        resp = client.get(f"/api/jobs/{job_id}/stages", headers=headers)
        assert resp.status_code == 200, resp.text
        stages = resp.json()
        if any(s["status"] != "pending" for s in stages) or time.monotonic() > deadline:
            return stages
        time.sleep(0.05)


def test_good_sample_four_stages_succeed(
    client: TestClient,
    bioops_headers: dict[str, str],
    db_session: sessionmaker,
    sample_ids: dict[str, int],
):
    """现象复验:好样例创建后四阶段推进并成功。"""
    resp = client.post(
        "/api/jobs", json={"sampleId": sample_ids["demo-good-r1"]}, headers=bioops_headers
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    stages = _poll_stages(client, job_id, bioops_headers)

    # 创建后短暂等待,阶段不再全是 pending
    assert len(stages) == 4
    assert [s["actor_name"] for s in stages] == STAGE_CHAIN
    assert any(s["status"] != "pending" for s in stages)

    # 最终:作业成功,四阶段全部成功(推进到终态)
    detail = client.get(f"/api/jobs/{job_id}", headers=bioops_headers).json()
    assert detail["status"] == "success"
    assert detail["error_message"] is None
    assert detail["finished_at"] is not None
    assert {s["status"] for s in detail["stages"]} == {"success"}
    assert detail["metrics"]["reads"] == 3
    assert detail["metrics"]["mean_quality"] > 0

    with db_session() as db:
        job = db.get(Job, job_id)
        assert job.status == "success"
        assert all(s.status == "success" for s in job.stages)
        assert all(s.started_at and s.finished_at for s in job.stages)


def test_broken_sample_fails(
    client: TestClient,
    bioops_headers: dict[str, str],
    db_session: sessionmaker,
    sample_ids: dict[str, int],
):
    """损坏样例:ParseActor 失败,后续阶段跳过,作业失败且不冒充正常。"""
    resp = client.post(
        "/api/jobs", json={"sampleId": sample_ids["demo-broken-malformed"]},
        headers=bioops_headers,
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    stages = _poll_stages(client, job_id, bioops_headers)
    assert any(s["status"] != "pending" for s in stages)

    detail = client.get(f"/api/jobs/{job_id}", headers=bioops_headers).json()
    assert detail["status"] == "failed"
    assert detail["finished_at"] is not None
    assert detail["error_message"]

    by_name = {s["actor_name"]: s["status"] for s in detail["stages"]}
    assert by_name["ParseActor"] == "failed"
    for later in ("QualityHistActor", "NContentActor", "ReportActor"):
        assert by_name[later] == "skipped"

    with db_session() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed"
        assert job.error_message
        stage_rows = (
            db.query(JobStage).filter(JobStage.job_id == job_id).order_by(JobStage.stage_order).all()
        )
        assert [s.status for s in stage_rows] == ["failed", "skipped", "skipped", "skipped"]


def test_no_forever_pending_for_custom_input(
    client: TestClient, bioops_headers: dict[str, str]
):
    """自定义合格输入同样必须被调度并跑到终态,不得永久 pending。"""
    fastq = "@C1\nACGT\n+\nIIII\n"
    resp = client.post(
        "/api/jobs", json={"fastqText": fastq}, headers=bioops_headers
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    stages = _poll_stages(client, job_id, bioops_headers)
    assert any(s["status"] != "pending" for s in stages)

    detail = client.get(f"/api/jobs/{job_id}", headers=bioops_headers).json()
    assert detail["status"] in {"success", "failed"}
    assert detail["status"] != "pending"
    assert {s["status"] for s in detail["stages"]} == {"success"}
