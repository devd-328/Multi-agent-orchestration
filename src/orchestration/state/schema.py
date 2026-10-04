from typing import Annotated, TypedDict

from orchestration.state.models import Review, RunStatus, StateError, Task, TaskResult
from orchestration.state.reducers import append_errors, merge_results, merge_tasks


class AgentState(TypedDict):
    """Shared LangGraph state for one run.

    `tasks`, `results`, and `errors` use reducers because more than one node
    can write them. `results` merges by task id. `errors` appends. `tasks`
    merges by id. `goal`, `review`, `final_output`, and `status` keep the
    latest write.
    """

    goal: str
    tasks: Annotated[list[Task], merge_tasks]
    results: Annotated[dict[str, TaskResult], merge_results]
    review: Review | None
    final_output: str | None
    errors: Annotated[list[StateError], append_errors]
    status: RunStatus
