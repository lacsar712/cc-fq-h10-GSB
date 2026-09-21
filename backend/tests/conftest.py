"""Pytest fixtures: sqlite-backed app with the real /api/jobs scheduling path."""

from __future__ import annotations

import os
from pathlib import Path

# 必须在导入 app.* 之前：让默认 engine 不指向 Postgres（测试用独立 sqlite 库覆盖）
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api
from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import Sample


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    seed = TestingSessionLocal()
    seed.add(
        Sample(
            name="demo-good-r1",
            description="合格样例",
            is_broken=False,
            fastq_content=(DATA_DIR / "good.fastq").read_text(encoding="utf-8"),
        )
    )
    seed.add(
        Sample(
            name="demo-broken-malformed",
            description="损坏样例",
            is_broken=True,
            fastq_content=(DATA_DIR / "broken.fastq").read_text(encoding="utf-8"),
        )
    )
    seed.commit()
    seed.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # 后台任务自建会话：指向同一个测试库，验证真实调度链路
    api.SessionLocal = TestingSessionLocal
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers():
    token = create_access_token("bioops", "bioops")
    return {"Authorization": f"Bearer {token}"}
