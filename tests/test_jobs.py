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

    job_id, joined = manager.submit("unit", work)
    assert joined is False
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

    job_id, _ = manager.submit("unit", broken)
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.FAILED)

    job = manager.get(job_id)
    assert job.error == "boom"
    assert job.result is None
    manager.shutdown()


def test_list_recent_orders_newest_first_and_is_bounded():
    manager = JobManager(max_workers=2)
    manager.start()
    ids = [manager.submit("unit", lambda progress: {"ok": True})[0] for _ in range(5)]
    assert _wait_for(lambda: all(manager.get(i).status == JobStatus.COMPLETED for i in ids))

    recent = manager.list_recent(limit=3)
    assert len(recent) == 3
    created = [j.created_at for j in recent]
    assert created == sorted(created, reverse=True)
    manager.shutdown()


def test_to_dict_is_json_friendly():
    manager = JobManager(max_workers=1)
    manager.start()
    job_id, _ = manager.submit("pipeline", lambda progress: {"done": 1})
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.COMPLETED)

    data = manager.get(job_id).to_dict()
    assert data["job_type"] == "pipeline"
    assert data["status"] == "completed"
    assert isinstance(data["created_at"], str)
    assert data["result"] == {"done": 1}
    manager.shutdown()


def test_submit_with_same_key_joins_existing_running_job():
    import threading

    manager = JobManager(max_workers=2)
    manager.start()
    started = threading.Event()
    release = threading.Event()

    def slow(progress):
        started.set()
        release.wait(timeout=5.0)
        return {"done": True}

    job_id_1, joined_1 = manager.submit("pipeline", slow, key="daily:all")
    assert joined_1 is False
    assert started.wait(timeout=5.0)

    job_id_2, joined_2 = manager.submit("pipeline", slow, key="daily:all")
    assert joined_2 is True
    assert job_id_2 == job_id_1

    # A different scope (different key) must NOT be treated as a duplicate.
    job_id_3, joined_3 = manager.submit("pipeline", lambda progress: {"ok": True}, key="weekly:all")
    assert joined_3 is False
    assert job_id_3 != job_id_1

    release.set()
    assert _wait_for(lambda: manager.get(job_id_1).status == JobStatus.COMPLETED)
    manager.shutdown()


def test_start_marks_orphaned_running_jobs_as_failed(monkeypatch):
    from datetime import datetime, timezone

    import tech_desk.api.jobs as jobs_module

    orphan = jobs_module.Job(
        id="orphan1",
        job_type="pipeline",
        status=JobStatus.RUNNING,
        key="daily:all",
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(jobs_module, "_load_recent_from_db", lambda limit=100: [orphan])
    monkeypatch.setattr(jobs_module, "_persist", lambda job: None)

    manager = jobs_module.JobManager(max_workers=1)
    manager.start()

    rehydrated = manager.get("orphan1")
    assert rehydrated.status == JobStatus.FAILED
    assert rehydrated.error == "Interrupted by server restart"

    # A new submission with the same job_type+key must NOT join the orphan —
    # it should start fresh since the orphan is no longer active.
    job_id, joined = manager.submit("pipeline", lambda progress: {"ok": True}, key="daily:all")
    assert joined is False
    assert job_id != "orphan1"
    assert _wait_for(lambda: manager.get(job_id).status == JobStatus.COMPLETED)
    manager.shutdown()


