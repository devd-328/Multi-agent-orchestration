import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestration import cli
from orchestration.core.config import load_settings
from orchestration.graph import Providers
from orchestration.llm import FakeLLMProvider
from orchestration.search import FakeSearchProvider
from orchestration.state import RunStatus, StateError
from tests.graph.helpers import APPROVED, GOAL, hit, plan_json, queries_json, task_json

_SECRET_KEY = "tvly-super-secret-key-value"
_CONFIG_ENV = (
    "LLM_PROVIDER",
    "SEARCH_PROVIDER",
    "SEARCH_API_KEY",
    "REVIEWER_MODEL",
    "MAX_TASK_ATTEMPTS",
    "MAX_REVIEW_REVISIONS",
    "MAX_PLAN_ATTEMPTS",
    "MAX_GRAPH_STEPS",
    "MAX_SEARCH_QUERIES",
    "MAX_RESEARCH_ATTEMPTS",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No .env file, no stray settings, and the global logging setup put back."""
    monkeypatch.chdir(tmp_path)
    for name in _CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _state(status: RunStatus, output: str | None, errors: list[str]):
    return {
        "goal": GOAL,
        "tasks": [],
        "results": {},
        "review": None,
        "final_output": output,
        "errors": [StateError(source="workflow", message=message) for message in errors],
        "status": status,
    }


def _patch_workflow(monkeypatch: pytest.MonkeyPatch, state: object) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    fake = FakeLLMProvider([])
    monkeypatch.setattr(
        cli,
        "build_default_providers",
        lambda settings: Providers(llm=fake, search=FakeSearchProvider([]), reviewer_llm=fake),
    )

    def run(goal: str, **kwargs: object) -> object:
        calls.append({"goal": goal, **kwargs})
        return state

    monkeypatch.setattr(cli, "run_workflow", run)
    return calls


def test_success_prints_the_final_output_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _state(RunStatus.DONE, "# Research results\n\nBody.\n", [])
    calls = _patch_workflow(monkeypatch, state)

    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "# Research results\n\nBody.\n"
    assert captured.err.startswith("Run id: ")
    assert calls[0]["goal"] == GOAL
    assert calls[0]["run_id"] is not None
    assert calls[0]["settings"] is not None


def test_failure_exits_non_zero_prints_no_output_and_lists_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_workflow(
        monkeypatch,
        _state(RunStatus.FAILED, None, ["Review failed. Model request timed out."]),
    )

    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "Run failed." in captured.err
    assert "- Review failed. Model request timed out." in captured.err


def test_a_done_run_without_output_is_treated_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_workflow(monkeypatch, _state(RunStatus.DONE, None, []))

    assert cli.main(["run", GOAL]) == 1
    assert capsys.readouterr().out == ""


def test_long_and_many_errors_are_cut(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    errors = ["e" * 1000] + [f"error {n}" for n in range(30)]
    _patch_workflow(monkeypatch, _state(RunStatus.FAILED, None, errors))

    cli.main(["run", GOAL])

    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("- ")]
    assert len(lines) == 10
    assert len(lines[0]) == len("- ") + 300


def test_the_whole_workflow_runs_from_the_cli_with_fake_providers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    llm = FakeLLMProvider(
        [plan_json(task_json("t1")), queries_json("q"), "A finding [1].", APPROVED]
    )
    search = FakeSearchProvider([[hit(1)]])
    monkeypatch.setattr(
        cli,
        "build_default_providers",
        lambda settings: Providers(llm=llm, search=search, reviewer_llm=llm),
    )

    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 0
    assert "A finding [1]." in captured.out
    assert "- [1] Source 1 (https://site1.example.test/page)" in captured.out
    assert '"message"' in captured.err


def test_missing_search_key_fails_fast_with_a_clear_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "Configuration error: Search API key is missing. Set SEARCH_API_KEY." in captured.err
    assert "Run id" not in captured.err


def test_unknown_search_provider_does_not_print_the_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SEARCH_PROVIDER", "not-a-provider")
    monkeypatch.setenv("SEARCH_API_KEY", _SECRET_KEY)

    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 2
    assert "Configuration error: Unknown search provider 'not-a-provider'." in captured.err
    assert _SECRET_KEY not in captured.out + captured.err


def test_invalid_settings_do_not_print_their_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "not-a-url-secret-looking")
    monkeypatch.setenv("SEARCH_API_KEY", _SECRET_KEY)

    code = cli.main(["run", GOAL])

    captured = capsys.readouterr()
    assert code == 2
    assert "Configuration error: Invalid configuration. llm_base_url: invalid URL" in captured.err
    assert "not-a-url-secret-looking" not in captured.err
    assert _SECRET_KEY not in captured.out + captured.err


@pytest.mark.parametrize("goal", ["", "   "])
def test_an_empty_goal_is_a_usage_error(goal: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", goal]) == 2
    assert "Goal must not be empty." in capsys.readouterr().err


def test_a_missing_goal_or_command_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit) as no_command:
        cli.main([])
    with pytest.raises(SystemExit) as no_goal:
        cli.main(["run"])

    assert no_command.value.code == 2
    assert no_goal.value.code == 2


def test_module_entry_point_reports_missing_config_and_exits_non_zero(tmp_path: Path) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _CONFIG_ENV
    }
    env.update({"LLM_MODEL": "test-model", "LLM_BASE_URL": "http://127.0.0.1:9"})

    done = subprocess.run(
        [sys.executable, "-m", "orchestration", "run", GOAL],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 2
    assert done.stdout == ""
    assert "Configuration error: Search API key is missing." in done.stderr


def test_module_entry_point_has_help() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "orchestration", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0
    assert "run" in done.stdout


def test_cli_uses_loaded_settings_for_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_GRAPH_STEPS", "7")
    calls = _patch_workflow(monkeypatch, _state(RunStatus.DONE, "ok\n", []))

    cli.main(["run", GOAL])

    assert calls[0]["settings"].max_graph_steps == 7
    assert load_settings(env_file=None).max_graph_steps == 7


def test_logs_go_to_stderr_as_json_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    llm = FakeLLMProvider(
        [plan_json(task_json("t1")), queries_json("q"), "A finding [1].", APPROVED]
    )
    monkeypatch.setattr(
        cli,
        "build_default_providers",
        lambda settings: Providers(
            llm=llm, search=FakeSearchProvider([[hit(1)]]), reviewer_llm=llm
        ),
    )

    cli.main(["run", GOAL])

    captured = capsys.readouterr()
    log_lines = [line for line in captured.err.splitlines() if line.startswith("{")]
    assert log_lines
    assert all(json.loads(line)["logger"].startswith("orchestration") for line in log_lines)
    assert all(not line.startswith("{") for line in captured.out.splitlines())
