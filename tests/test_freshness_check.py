"""
Test the timestamp-comparison logic of the freshness checker.

The script uses a small helper `is_stale(timestamp_iso, max_age_seconds)`
which we test directly. The shell wrapper handles I/O and email.
"""
import subprocess
from datetime import datetime, timedelta, timezone


def run_check(ts: str, max_age: int) -> int:
    """Invoke the helper via bash and return exit code."""
    script = (
        "source scripts/raffle-backup-freshness.sh; "
        f"is_stale '{ts}' {max_age}; "
        "echo exit=$?"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    # Parse 'exit=N' from output
    for line in result.stdout.splitlines():
        if line.startswith("exit="):
            return int(line.split("=")[1])
    raise AssertionError(f"helper produced no exit line: {result.stdout!r} stderr={result.stderr!r}")


def test_fresh_timestamp_returns_0():
    now = datetime.now(timezone.utc).isoformat()
    assert run_check(now, 3600) == 0


def test_stale_timestamp_returns_1():
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert run_check(old, 3600) == 1


def test_missing_timestamp_returns_2():
    assert run_check("", 3600) == 2
