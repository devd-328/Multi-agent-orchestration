import json

from orchestration.search import SearchResult

GOAL = "Research upcoming technology events and summarize the useful findings."
APPROVED = json.dumps({"verdict": "approved", "issues": []})


def plan_json(*tasks: dict[str, object]) -> str:
    return json.dumps({"tasks": list(tasks)})


def task_json(
    task_id: str,
    *depends_on: str,
    description: str | None = None,
) -> dict[str, object]:
    return {
        "id": task_id,
        "description": description or f"Find facts for {task_id}.",
        "assigned_agent": "research",
        "depends_on": list(depends_on),
        "inputs": {"topic": f"topic of {task_id}"},
    }


def queries_json(*queries: str) -> str:
    return json.dumps({"queries": list(queries)})


def hit(number: int, **overrides: object) -> SearchResult:
    values: dict[str, object] = {
        "title": f"Source {number}",
        "url": f"https://site{number}.example.test/page",
        "content": f"Fact number {number} about technology events.",
    }
    values.update(overrides)
    return SearchResult.model_validate(values)


def revise_json(task_id: str, description: str) -> str:
    return json.dumps(
        {
            "verdict": "revise",
            "issues": [{"severity": "blocking", "task_id": task_id, "description": description}],
        }
    )
