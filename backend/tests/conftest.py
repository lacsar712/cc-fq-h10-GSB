"""Shared fixtures: in-memory SQLite app with real BackgroundTasks execution."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module
from app.database import Base, get_db
from app.main import app
from app.models import Sample


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    data_dir = Path(__file__).resolve().parent.parent / "data"
    with TestingSessionLocal() as seed:
        seed.add(
            Sample(
                name="demo-good-r1",
                description="合格样例",
                is_broken=False,
                fastq_content=(data_dir / "good.fastq").read_text(encoding="utf-8"),
            )
        )
        seed.add(
            Sample(
                name="demo-broken-malformed",
                description="损坏样例",
                is_broken=True,
                fastq_content=(data_dir / "broken.fastq").read_text(encoding="utf-8"),
            )
        )
        seed.commit()

    # Background task opens its own session via app.api.SessionLocal
    api_module.SessionLocal = TestingSessionLocal

    def _override_get_db() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestingSessionLocal
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: sessionmaker) -> TestClient:
    # Do NOT enter lifespan: it would create_all() against the real Postgres engine.
    # Background tasks still run after each response without lifespan, which is the
    # "created job must be scheduled" behavior under test.
    return TestClient(app)


@pytest.fixture()
def bioops_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"username": "bioops", "password": "fastq123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sample_ids(db_session: sessionmaker) -> dict[str, int]:
    with db_session() as db:
        return {s.name: s.id for s in db.query(Sample).all()}
