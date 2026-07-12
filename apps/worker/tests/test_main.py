"""Tests for openlex_worker.__main__'s CLI dispatch (main()) and the heartbeat fallback.

main() is a thin dispatcher over openlex_worker.cli's build_parser/run_ingest -- see
test_cli.py for run_ingest's own branch coverage. These tests only check that main() wires
argv -> the right call -> the right exit code, and that the "no subcommand" path calls
_heartbeat_loop instead of exiting. _heartbeat_loop's `while True` is broken out of via a
fake time.sleep that raises, rather than actually looping -- there's no other way to observe
an infinite loop's first iteration without hanging the test.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from legal_models.schemas import IngestResponse
from openlex_worker import __main__ as worker_main


def test_main_ingest_success_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["openlex_worker", "ingest", "--source", "statutes"])
    success = IngestResponse(status="ok", documents_ingested=2, chunks_created=4, errors=[])

    with patch.object(worker_main, "run_ingest", AsyncMock(return_value=success)):
        with pytest.raises(SystemExit) as exc_info:
            worker_main.main()

    assert exc_info.value.code == 0


def test_main_ingest_with_errors_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["openlex_worker", "ingest"])
    failure = IngestResponse(
        status="partial_failure", documents_ingested=0, chunks_created=0, errors=["boom"]
    )

    with patch.object(worker_main, "run_ingest", AsyncMock(return_value=failure)):
        with pytest.raises(SystemExit) as exc_info:
            worker_main.main()

    assert exc_info.value.code == 1


def test_main_with_no_subcommand_falls_back_to_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["openlex_worker"])
    heartbeat = Mock()
    run_ingest = AsyncMock()

    with patch.object(worker_main, "_heartbeat_loop", heartbeat):
        with patch.object(worker_main, "run_ingest", run_ingest):
            worker_main.main()

    heartbeat.assert_called_once()
    run_ingest.assert_not_called()


def test_heartbeat_loop_logs_and_sleeps_at_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise KeyboardInterrupt  # the only way to stop `while True` without hanging the test

    monkeypatch.setattr(worker_main.time, "sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        worker_main._heartbeat_loop()

    assert sleep_calls == [worker_main.HEARTBEAT_INTERVAL_SECONDS]
