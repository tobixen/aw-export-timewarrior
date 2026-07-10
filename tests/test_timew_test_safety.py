"""Tests for the test-suite's own real-timew safety net (conftest.py).

These tests protect the protection: if `_guard_real_timew` or
`timew_sandbox` regress, every other test in the suite is at risk of
silently mutating the developer's real, live TimeWarrior database.
"""

import subprocess

import pytest


def test_unmocked_real_timew_call_is_blocked() -> None:
    """A plain unit test must never be able to reach the real timew binary."""
    with pytest.raises(RuntimeError, match="Blocked unmocked real 'timew'"):
        subprocess.run(["timew", "get", "dom.active.json"])


def test_unmocked_real_timew_check_output_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="Blocked unmocked real 'timew'"):
        subprocess.check_output(["timew", "get", "dom.active.json"])


def test_non_timew_commands_are_not_blocked() -> None:
    """The guard only targets 'timew' commands, not subprocess in general."""
    result = subprocess.run(["true"])

    assert result.returncode == 0


def test_timew_sandbox_lifts_the_guard_and_isolates_data(timew_sandbox) -> None:
    """Inside `timew_sandbox`, real timew calls work against an isolated DB."""
    subprocess.run(["timew", "start", "sandboxed-test-tag"], check=True, capture_output=True)

    result = subprocess.run(["timew", "export"], check=True, capture_output=True, text=True)

    assert "sandboxed-test-tag" in result.stdout

    subprocess.run(["timew", "stop"], check=False, capture_output=True)


def test_guard_is_restored_after_timew_sandbox_test() -> None:
    """A subsequent plain test must have the guard back in place.

    Regression test: if the sandbox fixture failed to reset the module-level
    allow-flag, every test running after any `timew_sandbox` test would be
    unprotected for the rest of the session.
    """
    with pytest.raises(RuntimeError, match="Blocked unmocked real 'timew'"):
        subprocess.run(["timew", "get", "dom.active.json"])
