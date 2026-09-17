from __future__ import annotations

import time

import pytest
from agent.prime_adapter import PrimeAdapter, PrimeAgentTimeout


def test_prompt_success_returns_stats_and_text(
    tmp_path, fake_prime_agent_on_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "success")
    with PrimeAdapter(cwd=tmp_path) as adapter:
        result = adapter.prompt("hello", timeout_s=10)
    assert result.final_text == "done"
    assert result.stats == {"tokens": {"total": 100}}


def test_prompt_timeout_kills_process_and_raises(
    tmp_path, fake_prime_agent_on_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spike-01 Finding 4: a process that goes silent mid-run (not one that
    errors out) has to be caught by PrimeAdapter's own deadline."""
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "hang")
    adapter = PrimeAdapter(cwd=tmp_path)
    start = time.monotonic()
    with pytest.raises(PrimeAgentTimeout):
        adapter.prompt("count forever", timeout_s=1.5)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0  # the deadline actually fired, not a full hang
    assert adapter._proc is None  # killed and cleared, not leaked


def test_healthcheck_true_when_executable_resolves(fake_prime_agent_on_path) -> None:
    adapter = PrimeAdapter(cwd=".")
    assert adapter.healthcheck() is True


def test_healthcheck_false_when_executable_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # nothing on PATH
    adapter = PrimeAdapter(cwd=".")
    assert adapter.healthcheck() is False
