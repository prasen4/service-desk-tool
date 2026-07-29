from __future__ import annotations

import time

from tech_desk.api.jobs import JobManager, JobStatus


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_job_completes_and_reports_progress():
    manager = JobManager(max_workers=1)
    manager.start()
    seen: list[int] = []

    def work(progress):
        progress("halfway", 50)
        seen.append(50)
        return {"answer": 42}

    job_id = manager.submit("unit", work)
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.COMPLETED)

    job = manager.get(job_id)
    assert job.result == {"answer": 42}
    assert job.progress == 100
    assert job.completed_at is not None
    assert 50 in seen
    manager.shutdown()


def test_job_records_failure():
    manager = JobManager(max_workers=1)
    manager.start()

    def broken(progress):
        raise ValueError("boom")

    job_id = manager.submit("unit", broken)
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.FAILED)

    job = manager.get(job_id)
    assert job.error == "boom"
    assert job.result is None
    manager.shutdown()


def test_list_recent_orders_newest_first_and_is_bounded():
    manager = JobManager(max_workers=2)
    manager.start()
    ids = [manager.submit("unit", lambda progress: {"ok": True}) for _ in range(5)]
    assert _wait_for(lambda: all(manager.get(i).status == JobStatus.COMPLETED for i in ids))

    recent = manager.list_recent(limit=3)
    assert len(recent) == 3
    created = [j.created_at for j in recent]
    assert created == sorted(created, reverse=True)
    manager.shutdown()


def test_to_dict_is_json_friendly():
    manager = JobManager(max_workers=1)
    manager.start()
    job_id = manager.submit("pipeline", lambda progress: {"done": 1})
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.COMPLETED)

    data = manager.get(job_id).to_dict()
    assert data["job_type"] == "pipeline"
    assert data["status"] == "completed"
    assert isinstance(data["created_at"], str)
    assert data["result"] == {"done": 1}
    manager.shutdown()
