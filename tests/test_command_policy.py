from agent_orchestrator.safety.command_policy import assert_commands_allowed, is_command_blocked


def test_block_git_push() -> None:
    blocked, _ = is_command_blocked("git push origin main")
    assert blocked


def test_allow_git_status() -> None:
    blocked, _ = is_command_blocked("git status")
    assert not blocked


def test_assert_commands_allowed() -> None:
    assert_commands_allowed(["pytest -q", "git status"])
