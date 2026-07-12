"""Tests for openlex_worker.cli -- argument parsing and the run_ingest orchestration
that apps/worker/src/openlex_worker/__main__.py's entrypoint dispatches to. No real DB or
network calls: SessionLocal and upsert_all_seed_statutes/upsert_all_seed_cases are patched
at the cli module's import site, mirroring apps/api/tests' patch-at-call-site convention."""

from unittest.mock import AsyncMock, patch

import pytest
from legal_models.schemas import IngestResponse
from openlex_worker.cli import build_parser, run_ingest


def test_build_parser_ingest_defaults_to_source_all() -> None:
    args = build_parser().parse_args(["ingest"])

    assert args.command == "ingest"
    assert args.source == "all"
    assert args.force is False


def test_build_parser_ingest_explicit_source_and_force() -> None:
    args = build_parser().parse_args(["ingest", "--source", "statutes", "--force"])

    assert args.source == "statutes"
    assert args.force is True


def test_build_parser_no_subcommand() -> None:
    args = build_parser().parse_args([])

    assert args.command is None


def test_build_parser_rejects_unknown_source() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ingest", "--source", "not-a-real-source"])


@pytest.fixture
def mock_session_local():
    with patch("openlex_worker.cli.SessionLocal") as session_local:
        session = AsyncMock()
        session_local.return_value.__aenter__.return_value = session
        yield session_local, session


async def test_run_ingest_statutes_only(mock_session_local) -> None:
    session_local, session = mock_session_local
    statute_result = IngestResponse(status="ok", documents_ingested=3, chunks_created=3, errors=[])
    with patch(
        "openlex_worker.cli.upsert_all_seed_statutes", AsyncMock(return_value=statute_result)
    ):
        result = await run_ingest("statutes")

    assert result.status == "ok"
    assert result.documents_ingested == 3
    assert result.chunks_created == 3
    assert result.errors == []
    session.commit.assert_awaited_once()


async def test_run_ingest_cases_only(mock_session_local) -> None:
    session_local, session = mock_session_local
    case_result = IngestResponse(status="ok", documents_ingested=3, chunks_created=15, errors=[])
    with patch("openlex_worker.cli.upsert_all_seed_cases", AsyncMock(return_value=case_result)):
        result = await run_ingest("cases")

    assert result.status == "ok"
    assert result.documents_ingested == 3
    assert result.chunks_created == 15
    assert result.errors == []
    session.commit.assert_awaited_once()


async def test_run_ingest_all_combines_statutes_and_cases(mock_session_local) -> None:
    _session_local, _session = mock_session_local
    statute_result = IngestResponse(status="ok", documents_ingested=5, chunks_created=12, errors=[])
    case_result = IngestResponse(status="ok", documents_ingested=3, chunks_created=15, errors=[])
    with (
        patch(
            "openlex_worker.cli.upsert_all_seed_statutes", AsyncMock(return_value=statute_result)
        ),
        patch("openlex_worker.cli.upsert_all_seed_cases", AsyncMock(return_value=case_result)),
    ):
        result = await run_ingest("all")

    assert result.status == "ok"
    assert result.documents_ingested == 8
    assert result.chunks_created == 27


async def test_run_ingest_reports_partial_failure_on_document_errors(mock_session_local) -> None:
    _session_local, _session = mock_session_local
    statute_result = IngestResponse(
        status="partial_failure",
        documents_ingested=1,
        chunks_created=1,
        errors=["RPAPL 711: normalization failed"],
    )
    case_result = IngestResponse(status="ok", documents_ingested=0, chunks_created=0, errors=[])
    with (
        patch(
            "openlex_worker.cli.upsert_all_seed_statutes", AsyncMock(return_value=statute_result)
        ),
        patch("openlex_worker.cli.upsert_all_seed_cases", AsyncMock(return_value=case_result)),
    ):
        result = await run_ingest("all", force=True)

    assert result.status == "partial_failure"
    assert result.errors == ["RPAPL 711: normalization failed"]


async def test_run_ingest_reports_partial_failure_on_case_errors(mock_session_local) -> None:
    _session_local, _session = mock_session_local
    statute_result = IngestResponse(status="ok", documents_ingested=1, chunks_created=1, errors=[])
    case_result = IngestResponse(
        status="partial_failure",
        documents_ingested=0,
        chunks_created=0,
        errors=["5683523: normalization failed"],
    )
    with (
        patch(
            "openlex_worker.cli.upsert_all_seed_statutes", AsyncMock(return_value=statute_result)
        ),
        patch("openlex_worker.cli.upsert_all_seed_cases", AsyncMock(return_value=case_result)),
    ):
        result = await run_ingest("all")

    assert result.status == "partial_failure"
    assert result.errors == ["5683523: normalization failed"]


async def test_run_ingest_force_flag_is_forwarded(mock_session_local) -> None:
    _session_local, session = mock_session_local
    statute_result = IngestResponse(status="ok", documents_ingested=1, chunks_created=1, errors=[])
    mocked_upsert = AsyncMock(return_value=statute_result)
    with patch("openlex_worker.cli.upsert_all_seed_statutes", mocked_upsert):
        await run_ingest("statutes", force=True)

    mocked_upsert.assert_awaited_once_with(session, force=True)
