import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestration.api import runs as runs_module
from orchestration.api.app import STATIC_DIR, create_app
from orchestration.api.runs import RunManager, Stage, derive_stage
from orchestration.graph import Providers
from orchestration.llm import FakeLLMProvider
from orchestration.search import FakeSearchProvider
from orchestration.state import (
    AgentId,
    Review,
    ReviewVerdict,
    RunStatus,
    Task,
    TaskStatus,
)
from tests.graph.helpers import APPROVED, GOAL, hit, plan_json, queries_json, task_json

_CONFIG_ENV = (
    "LLM_PROVIDER",
    "SEARCH_PROVIDER",
    "SEARCH_API_KEY",
    "REVIEWER_MODEL",
    "MAX_TASK_ATTEMPTS",
    "MAX_REVIEW_REVISIONS",
    "MAX_PLAN_ATTEMPTS",
    "MAX_GRAPH_STEPS",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No .env file and no stray settings."""
    monkeypatch.chdir(tmp_path)
    for name in _CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")


@pytest.fixture
def manager() -> Iterator[RunManager]:
    run_manager = RunManager()
    yield run_manager
    run_manager.shutdown()


@pytest.fixture
def client(manager: RunManager) -> TestClient:
    return TestClient(create_app(manager))


def _use_providers(monkeypatch: pytest.MonkeyPatch, llm, search) -> None:
    monkeypatch.setattr(
        runs_module,
        "build_default_providers",
        lambda settings: Providers(llm=llm, search=search, reviewer_llm=llm),
    )


def _happy_providers() -> tuple[FakeLLMProvider, FakeSearchProvider]:
    llm = FakeLLMProvider(
        [plan_json(task_json("t1")), queries_json("q"), "A finding [1].", APPROVED]
    )
    return llm, FakeSearchProvider([[hit(1)]])


def _wait_finished(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_a_run_goes_from_goal_to_final_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_providers(monkeypatch, *_happy_providers())

    started = client.post("/api/runs", json={"goal": f"  {GOAL}  "})

    assert started.status_code == 202
    assert started.json()["status"] == "running"
    assert started.json()["goal"] == GOAL
    body = _wait_finished(client, started.json()["id"])
    assert body["status"] == "done"
    assert body["stage"] == "done"
    assert "A finding [1]." in body["final_output"]
    assert "- [1] Source 1 (https://site1.example.test/page)" in body["final_output"]
    assert body["errors"] == []
    assert [task["status"] for task in body["tasks"]] == ["done"]
    assert body["tasks"][0]["agent"] == "research"
    assert body["review"] == {"verdict": "approved", "issues": [], "revision_count": 0}


def test_a_failed_run_has_no_final_output_and_lists_safe_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_providers(
        monkeypatch,
        FakeLLMProvider(["not json", "still not json", "nope"]),
        FakeSearchProvider([]),
    )

    started = client.post("/api/runs", json={"goal": GOAL})

    body = _wait_finished(client, started.json()["id"])
    assert body["status"] == "failed"
    assert body["stage"] == "failed"
    assert body["final_output"] is None
    assert any("Plan could not be formed" in message for message in body["errors"])


def test_progress_is_visible_while_a_run_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    reached_search = threading.Event()

    class SlowSearch(FakeSearchProvider):
        def search(self, query: str, max_results: int):
            reached_search.set()
            assert release.wait(10)
            return super().search(query, max_results)

    llm = FakeLLMProvider(
        [plan_json(task_json("t1")), queries_json("q"), "A finding [1].", APPROVED]
    )
    _use_providers(monkeypatch, llm, SlowSearch([[hit(1)]]))

    started = client.post("/api/runs", json={"goal": GOAL})
    assert reached_search.wait(10)
    midway = client.get(f"/api/runs/{started.json()['id']}").json()
    release.set()

    assert midway["status"] == "running"
    assert midway["stage"] == "research"
    assert [task["id"] for task in midway["tasks"]] == ["t1"]
    assert midway["final_output"] is None
    assert _wait_finished(client, started.json()["id"])["status"] == "done"


def test_runs_are_listed_newest_first_with_a_short_goal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMProvider(["x"] * 6)
    _use_providers(monkeypatch, llm, FakeSearchProvider([]))
    first = client.post("/api/runs", json={"goal": "first goal"}).json()
    second = client.post("/api/runs", json={"goal": "g" * 500}).json()
    _wait_finished(client, first["id"])
    _wait_finished(client, second["id"])

    listed = client.get("/api/runs").json()

    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    assert len(listed[0]["goal"]) == 120
    assert "final_output" not in listed[0]


@pytest.mark.parametrize("goal", ["", "   ", "x" * 2001])
def test_a_blank_or_oversized_goal_is_rejected(client: TestClient, goal: str) -> None:
    response = client.post("/api/runs", json={"goal": goal})

    assert response.status_code == 422
    assert client.get("/api/runs").json() == []


def test_a_request_without_a_json_goal_is_rejected(client: TestClient) -> None:
    assert client.post("/api/runs", content="goal=hi").status_code == 422
    assert client.post("/api/runs", json={}).status_code == 422


def test_missing_search_key_returns_a_clear_error_and_starts_no_run(client: TestClient) -> None:
    response = client.post("/api/runs", json={"goal": GOAL})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Configuration error: Search API key is missing. Set SEARCH_API_KEY."
    )
    assert client.get("/api/runs").json() == []


def test_the_error_never_contains_the_search_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "tvly-super-secret-key-value"
    monkeypatch.setenv("SEARCH_API_KEY", secret)
    monkeypatch.setenv("SEARCH_PROVIDER", "not-a-provider")

    response = client.post("/api/runs", json={"goal": GOAL})

    assert response.status_code == 503
    assert secret not in response.text
    status = client.get("/api/status")
    assert secret not in status.text


def test_too_many_active_runs_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    class BlockedLLM(FakeLLMProvider):
        def generate(self, prompt: str) -> str:
            assert release.wait(10)
            return super().generate(prompt)

    _use_providers(monkeypatch, BlockedLLM(["x"] * 9), FakeSearchProvider([]))
    manager = RunManager(max_active=2)
    client = TestClient(create_app(manager))
    try:
        assert client.post("/api/runs", json={"goal": "one"}).status_code == 202
        assert client.post("/api/runs", json={"goal": "two"}).status_code == 202
        third = client.post("/api/runs", json={"goal": "three"})
    finally:
        release.set()
        manager.shutdown()

    assert third.status_code == 429
    assert "Too many runs" in third.json()["detail"]


def test_old_finished_runs_are_dropped_but_active_runs_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_providers(monkeypatch, FakeLLMProvider(["x"] * 30), FakeSearchProvider([]))
    manager = RunManager(max_active=1, max_kept=2)
    client = TestClient(create_app(manager))
    ids = []
    try:
        for index in range(4):
            started = client.post("/api/runs", json={"goal": f"goal {index}"})
            ids.append(started.json()["id"])
            _wait_finished(client, ids[-1])
    finally:
        manager.shutdown()

    kept = [item["id"] for item in client.get("/api/runs").json()]
    assert kept == [ids[3], ids[2]]
    assert client.get(f"/api/runs/{ids[0]}").status_code == 404


def test_an_unknown_run_is_404(client: TestClient) -> None:
    response = client.get("/api/runs/does-not-exist")

    assert response.status_code == 404


def test_a_crash_in_the_workflow_is_a_failed_run_without_the_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_providers(monkeypatch, *_happy_providers())

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret detail that must not leak")

    monkeypatch.setattr(runs_module, "run_workflow", explode)

    started = client.post("/api/runs", json={"goal": GOAL})

    body = _wait_finished(client, started.json()["id"])
    assert body["status"] == "failed"
    assert body["errors"] == ["Run stopped on an internal error (RuntimeError)."]
    assert "secret detail" not in str(body)


def test_status_reports_setup_without_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = client.get("/api/status").json()
    assert missing["ready"] is False
    assert "SEARCH_API_KEY" in missing["problem"]

    monkeypatch.setenv("SEARCH_API_KEY", "tvly-secret-value")
    ready = client.get("/api/status").json()

    assert ready["ready"] is True
    assert ready["problem"] is None
    assert ready["llm_model"] == "test-model"
    assert ready["search_provider"] == "tavily"
    assert "tvly-secret-value" not in str(ready)


def test_the_page_is_served_with_a_strict_content_security_policy(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Multi-Agent Orchestration" in response.text
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy
    assert "frame-ancestors 'none'" in policy
    assert response.headers["x-content-type-options"] == "nosniff"


def test_the_page_has_no_inline_script_and_no_remote_resource() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son\w+\s*=", html)
    assert not re.search(r"(?:src|href)=\"https?://", html)


def test_the_scripts_never_write_html_from_data() -> None:
    for name in ("app.js", "theme.js"):
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert banned not in source, f"{name} uses {banned}"


@pytest.mark.parametrize("name", ["app.js", "app.css", "theme.js"])
def test_static_files_are_served(client: TestClient, name: str) -> None:
    assert client.get(f"/static/{name}").status_code == 200


def _task(task_id: str, status: TaskStatus) -> Task:
    return Task(
        id=task_id,
        description="d",
        assigned_agent=AgentId.RESEARCH,
        status=status,
        error="e" if status is TaskStatus.FAILED else None,
    )


def _state(status: RunStatus, tasks: list[Task], review: Review | None = None):
    return {
        "goal": GOAL,
        "tasks": tasks,
        "results": {},
        "review": review,
        "final_output": None,
        "errors": [],
        "status": status,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(RunStatus.PLANNING, []), Stage.PLAN),
        (_state(RunStatus.RUNNING, [_task("a", TaskStatus.PENDING)]), Stage.RESEARCH),
        (
            _state(
                RunStatus.RUNNING,
                [_task("a", TaskStatus.DONE), _task("b", TaskStatus.PENDING)],
            ),
            Stage.RESEARCH,
        ),
        (_state(RunStatus.RUNNING, [_task("a", TaskStatus.DONE)]), Stage.REVIEW),
        (
            _state(
                RunStatus.REVIEWING,
                [_task("a", TaskStatus.DONE)],
                Review(verdict=ReviewVerdict.APPROVED),
            ),
            Stage.FINALIZE,
        ),
        (
            _state(
                RunStatus.REVIEWING,
                [_task("a", TaskStatus.DONE)],
                Review(verdict=ReviewVerdict.REVISE, issues=["x"], revision_count=1),
            ),
            Stage.REVISE,
        ),
        (
            _state(
                RunStatus.RUNNING,
                [_task("a", TaskStatus.PENDING)],
                Review(verdict=ReviewVerdict.REVISE, issues=["x"], revision_count=1),
            ),
            Stage.RESEARCH,
        ),
        (_state(RunStatus.DONE, [_task("a", TaskStatus.DONE)]), Stage.DONE),
        (_state(RunStatus.FAILED, [_task("a", TaskStatus.FAILED)]), Stage.FAILED),
    ],
)
def test_stage_is_derived_from_the_streamed_state(state, expected: Stage) -> None:
    assert derive_stage(state) is expected
