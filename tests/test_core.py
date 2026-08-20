from __future__ import annotations

from datetime import datetime

import pytest

from tech_desk.config import load_desk_config
from tech_desk.models import TechDeskDefinition
from tech_desk.reports.generator import _period_bounds


def test_load_desk_config():
    config = load_desk_config()
    assert "desks" in config
    assert len(config["desks"]) == 5
    priority = [d for d in config["desks"] if d.get("priority")]
    assert len(priority) == 3


def test_desk_definition():
    config = load_desk_config()
    desk = TechDeskDefinition.model_validate(config["desks"][0])
    assert desk.code in ("I", "M", "ET", "APPS", "HCLS")
    assert len(desk.search_queries) > 0


def test_period_bounds():
    end = datetime(2025, 6, 17)
    daily_start, daily_end = _period_bounds("daily", end)
    assert (daily_end - daily_start).days == 1

    weekly_start, _ = _period_bounds("weekly", end)
    assert (end - weekly_start).days == 7

    monthly_start, _ = _period_bounds("monthly", end)
    assert monthly_start.month == 5 or monthly_start.day <= 17


def test_resolve_desks_by_id_code_and_name():
    from tech_desk.config import resolve_desks

    apps = resolve_desks(["applications"])
    assert len(apps) == 1
    assert apps[0].code == "APPS"

    by_code = resolve_desks(["APPS"])
    assert by_code[0].id == "applications"

    by_name = resolve_desks(["Gen AI Models"])
    assert by_name[0].code == "M"

    all_desks = resolve_desks(None)
    assert len(all_desks) == 5


def test_resolve_desks_unknown():
    from tech_desk.config import resolve_desks

    with pytest.raises(ValueError, match="Unknown desk"):
        resolve_desks(["not-a-desk"])


def test_group_updates_by_vendor():
    from tech_desk.models import CuratedUpdate
    from tech_desk.reports.vendor_intel import group_updates_by_vendor

    updates = [
        CuratedUpdate(desk_id="models", title="A", summary="s", source_url="http://a", vendor="OpenAI"),
        CuratedUpdate(desk_id="models", title="B", summary="s", source_url="http://b", vendor="Anthropic"),
        CuratedUpdate(desk_id="models", title="C", summary="s", source_url="http://c", vendor="OpenAI"),
    ]
    grouped = group_updates_by_vendor(updates, ["OpenAI", "Anthropic", "Meta AI"])
    assert len(grouped["OpenAI"]) == 2
    assert len(grouped["Anthropic"]) == 1
    assert grouped["Meta AI"] == []


def test_research_run_result_after_session_close():
    """Ensure research results are plain data, not session-bound ORM objects."""
    from tech_desk.database import ResearchRunORM, get_session_factory, init_db, research_run_from_orm

    init_db()
    session = get_session_factory()()
    try:
        orm = ResearchRunORM(
            period="daily",
            status="completed",
            desks_processed=2,
            updates_found=12,
        )
        session.add(orm)
        session.commit()
        session.refresh(orm)
        result = research_run_from_orm(orm)
    finally:
        session.close()

    assert result.id == orm.id
    assert result.updates_found == 12
    assert result.desks_processed == 2
    assert result.status == "completed"


def test_collector_returns_detached_result():
    """Collector.run() must return plain data usable after its session closes."""
    from unittest.mock import MagicMock

    from tech_desk.database import init_db
    from tech_desk.models import ResearchRunResult
    from tech_desk.research.collector import ResearchCollector

    init_db()
    collector = ResearchCollector(llm=MagicMock())
    collector.searcher.search_desk = MagicMock(return_value=[])

    result = collector.run(period="daily", desk_keys=["M"])

    assert isinstance(result, ResearchRunResult)
    assert result.id > 0
    assert result.status == "completed"
    assert result.updates_found == 0
    # Simulate pipeline job reading fields after collector closed its session
    assert result.desks_processed == 1


def test_collector_auto_tracks_new_vendor(monkeypatch):
    """Research isn't limited to tracked vendors — newly discovered ones get auto-tracked."""
    from unittest.mock import MagicMock

    from tech_desk.config import list_desk_definitions
    from tech_desk.database import init_db
    from tech_desk.models import CuratedUpdate, ResearchResult
    from tech_desk.research import collector as collector_module
    from tech_desk.research.collector import ResearchCollector

    init_db()
    desk = next(d for d in list_desk_definitions() if d.id == "models")
    assert "Snowflake" not in desk.key_vendors  # sanity: not already tracked

    collector = ResearchCollector(llm=MagicMock())
    collector.searcher.search_desk = MagicMock(
        return_value=[ResearchResult(title="Snowflake launches AI copilot", url="https://example.com/snowflake")]
    )
    collector.analyzer.analyze_result = MagicMock(
        return_value=CuratedUpdate(
            desk_id="models",
            title="Snowflake launches AI copilot",
            summary="Snowflake shipped a new AI copilot for enterprise data teams.",
            source_url="https://example.com/snowflake",
            vendor="Snowflake",
        )
    )

    added_calls = []
    monkeypatch.setattr(collector_module, "add_vendor_to_desk", lambda desk_id, vendor: added_calls.append((desk_id, vendor)))

    result = collector.run(period="daily", desk_keys=["M"])

    assert added_calls == [("models", "Snowflake")]
    assert result.vendors_added == ["Snowflake (M)"]
    assert result.updates_found == 1


def test_collector_skips_already_tracked_vendor(monkeypatch):
    """Vendors already on the desk's tracked list should not trigger another add."""
    from unittest.mock import MagicMock

    from tech_desk.config import list_desk_definitions
    from tech_desk.database import init_db
    from tech_desk.models import CuratedUpdate, ResearchResult
    from tech_desk.research import collector as collector_module
    from tech_desk.research.collector import ResearchCollector

    init_db()
    desk = next(d for d in list_desk_definitions() if d.id == "models")
    tracked_vendor = desk.key_vendors[0]

    collector = ResearchCollector(llm=MagicMock())
    collector.searcher.search_desk = MagicMock(
        return_value=[ResearchResult(title="t", url="https://example.com/x")]
    )
    collector.analyzer.analyze_result = MagicMock(
        return_value=CuratedUpdate(
            desk_id="models",
            title="t",
            summary="s",
            source_url="https://example.com/x",
            vendor=tracked_vendor,
        )
    )

    added_calls = []
    monkeypatch.setattr(collector_module, "add_vendor_to_desk", lambda desk_id, vendor: added_calls.append((desk_id, vendor)))

    result = collector.run(period="daily", desk_keys=["M"])

    assert added_calls == []
    assert result.vendors_added == []


def test_analyzer_rejects_non_specific_event():
    """Quality gate: generic/evergreen 'trends' or marketing content must be
    rejected even if the LLM otherwise judged it topically relevant."""
    from unittest.mock import MagicMock

    from tech_desk.config import list_desk_definitions
    from tech_desk.models import ResearchResult
    from tech_desk.research.analyzer import UpdateAnalyzer

    desk = next(d for d in list_desk_definitions() if d.id == "infrastructure")
    llm = MagicMock()
    llm.chat_json.return_value = {
        "relevant": True,
        "specific_event": False,
        "title": "AI Infrastructure Trends and Statistics for 2026",
        "summary": "A generic overview of AI infrastructure market trends.",
        "vendor": "Other",
        "relevance": "high",
    }
    analyzer = UpdateAnalyzer(llm)
    result = ResearchResult(title="AI Infrastructure Trends and Statistics for 2026", url="https://example.com/trends")

    curated = analyzer.analyze_result(desk, result)

    assert curated is None


def test_analyzer_rejects_incomplete_analysis():
    """Quality gate: reject analyses missing a title or summary rather than
    persist a low-quality/malformed update."""
    from unittest.mock import MagicMock

    from tech_desk.config import list_desk_definitions
    from tech_desk.models import ResearchResult
    from tech_desk.research.analyzer import UpdateAnalyzer

    desk = next(d for d in list_desk_definitions() if d.id == "infrastructure")
    llm = MagicMock()
    llm.chat_json.return_value = {
        "relevant": True,
        "specific_event": True,
        "title": "",
        "summary": "",
        "vendor": "CoreWeave",
        "relevance": "high",
    }
    analyzer = UpdateAnalyzer(llm)
    result = ResearchResult(title="", url="https://example.com/incomplete")

    curated = analyzer.analyze_result(desk, result)

    assert curated is None


def test_analyzer_accepts_specific_event():
    """Sanity check: a concrete, dateable vendor event still passes through."""
    from unittest.mock import MagicMock

    from tech_desk.config import list_desk_definitions
    from tech_desk.models import ResearchResult
    from tech_desk.research.analyzer import UpdateAnalyzer

    desk = next(d for d in list_desk_definitions() if d.id == "infrastructure")
    llm = MagicMock()
    llm.chat_json.return_value = {
        "relevant": True,
        "specific_event": True,
        "title": "CoreWeave Signs $11.9B Contract With OpenAI",
        "summary": "CoreWeave expands its AI infrastructure partnership with OpenAI.",
        "vendor": "CoreWeave",
        "relevance": "high",
        "stakeholder_impact": "Signals continued hyperscaler-scale demand for GPU capacity.",
    }
    analyzer = UpdateAnalyzer(llm)
    result = ResearchResult(title="CoreWeave Signs Contract", url="https://example.com/coreweave")

    curated = analyzer.analyze_result(desk, result)

    assert curated is not None
    assert curated.vendor == "CoreWeave"


def test_collector_dedupes_near_duplicate_titles(monkeypatch):
    """Multiple sources covering the same underlying event should only
    surface once per run, even with slightly different headlines/URLs."""
    from unittest.mock import MagicMock

    from tech_desk.database import init_db
    from tech_desk.models import CuratedUpdate, ResearchResult
    from tech_desk.research import collector as collector_module
    from tech_desk.research.collector import ResearchCollector

    init_db()
    collector = ResearchCollector(llm=MagicMock())
    collector.searcher.search_desk = MagicMock(
        return_value=[
            ResearchResult(title="NTT DATA Opens Sydney Innovation Centre for AI", url="https://a.example.com/1"),
            ResearchResult(title="NTT DATA opens new Sydney AI innovation centre", url="https://b.example.com/2"),
        ]
    )
    updates = [
        CuratedUpdate(
            desk_id="models",
            title="NTT DATA Opens Sydney Innovation Centre for AI",
            summary="NTT DATA opened a new AI-focused innovation centre in Sydney.",
            source_url="https://a.example.com/1",
            vendor="NTT DATA",
        ),
        CuratedUpdate(
            desk_id="models",
            title="NTT DATA opens new Sydney AI innovation centre",
            summary="NTT DATA opened a new AI-focused innovation centre in Sydney.",
            source_url="https://b.example.com/2",
            vendor="NTT DATA",
        ),
    ]
    collector.analyzer.analyze_result = MagicMock(side_effect=updates)
    monkeypatch.setattr(collector_module, "add_vendor_to_desk", lambda desk_id, vendor: None)

    result = collector.run(period="daily", desk_keys=["M"])

    assert result.updates_found == 1


def test_pipeline_job_reads_research_after_session_close(monkeypatch):
    """Regression: pipeline must not crash accessing research stats after collector closes."""
    from datetime import datetime
    from unittest.mock import MagicMock

    from tech_desk.models import GeneratedReport, ResearchRunResult

    fake_run = ResearchRunResult(
        id=99,
        status="completed",
        period="daily",
        desks_processed=1,
        updates_found=7,
    )

    class FakeCollector:
        def __init__(self, llm=None):
            pass

        def run(self, **kwargs):
            return fake_run

    class FakeGenerator:
        def __init__(self, llm=None):
            pass

        def generate(self, **kwargs):
            return GeneratedReport(
                id="42",
                period="daily",
                title="Test Brief",
                period_start=datetime(2026, 6, 28),
                period_end=datetime(2026, 6, 29),
                metadata={"total_updates": 5, "desk_codes": ["M"]},
            )

    monkeypatch.setattr("tech_desk.api.services.ResearchCollector", FakeCollector)
    monkeypatch.setattr("tech_desk.api.services.ReportGenerator", FakeGenerator)
    monkeypatch.setattr("tech_desk.api.services.LLMClient", lambda: MagicMock())

    from tech_desk.api.services import run_pipeline_job

    result = run_pipeline_job(period="daily", desk_keys=["M"])
    assert result["research"]["updates_found"] == 7
    assert result["report"]["title"] == "Test Brief"


def test_vendor_summaries_and_feed():
    from tech_desk.database import UpdateORM, get_session_factory, init_db
    from tech_desk.vendors import get_vendor_updates, list_vendor_summaries

    init_db()
    session = get_session_factory()()
    try:
        session.add(UpdateORM(
            desk_id="models",
            title="OpenAI launches new model",
            summary="GPT update announced.",
            source_url="http://example.com/a",
            vendor="OpenAI",
            relevance="high",
            dedup_hash="test-vendor-openai-1",
        ))
        session.add(UpdateORM(
            desk_id="applications",
            title="OpenAI partners with Salesforce",
            summary="Enterprise integration.",
            source_url="http://example.com/b",
            vendor="OpenAI",
            relevance="medium",
            dedup_hash="test-vendor-openai-2",
        ))
        session.commit()

        summaries = list_vendor_summaries(session)["vendors"]
        openai = next(v for v in summaries if v["name"] == "OpenAI")
        assert openai["update_count"] >= 2
        assert openai["latest_at"] is not None

        feed = get_vendor_updates(session, "OpenAI", limit=10)
        assert feed is not None
        assert feed["update_count"] >= 2
        assert feed["updates"][0]["desk_code"] in ("M", "APPS")
        assert feed["updates"][0]["sort_at"] >= feed["updates"][-1]["sort_at"]
    finally:
        session.query(UpdateORM).filter(UpdateORM.dedup_hash.like("test-vendor-%")).delete()
        session.commit()
        session.close()


def test_desk_has_key_vendors():
    from tech_desk.config import list_desk_definitions

    desks = list_desk_definitions()
    apps = next(d for d in desks if d.id == "applications")
    assert "Microsoft Copilot" in apps.key_vendors
    assert len(apps.key_vendors) >= 5
