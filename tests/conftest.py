from __future__ import annotations

import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

_FAKE_SCRIPT = Path(__file__).parent / "_fake_prime_agent.py"


@pytest.fixture
def fake_prime_agent_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Puts a stand-in `prime-agent` executable on PATH (tests/_fake_prime_agent.py).

    Real `prime-agent` isn't available in CI/most dev shells -- spike-01
    already validated the real CLI end to end (docs/spikes/spike-01-*); these
    tests validate PrimeAdapter/AgentWorker's own plumbing (timeout handling,
    file I/O, Band-3 gating) against a controllable stand-in instead.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    if sys.platform == "win32":
        wrapper = bin_dir / "prime-agent.cmd"
        wrapper.write_text(
            f'@"{sys.executable}" "{_FAKE_SCRIPT}" %*\r\n', encoding="utf-8"
        )
    else:
        wrapper = bin_dir / "prime-agent"
        wrapper.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                exec "{sys.executable}" "{_FAKE_SCRIPT}" "$@"
                """
            ),
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return bin_dir
