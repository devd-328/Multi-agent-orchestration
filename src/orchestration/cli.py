import argparse
import sys
import uuid
from collections.abc import Sequence

from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.core.logging import configure_logging
from orchestration.graph import build_default_providers, run_workflow
from orchestration.state.models import RunStatus

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

_MAX_LISTED_ERRORS = 10
_MAX_ERROR_CHARS = 300


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line. Returns the process exit code.

    Output goes to stdout only on success. Logs, the run id, and every error go
    to stderr. Messages come from configuration and agent errors, which are
    written to be safe to print. No setting value or key is printed.
    """

    args = _parser().parse_args(argv)
    goal: str = args.goal
    if not goal.strip():
        print("Goal must not be empty.", file=sys.stderr)
        return EXIT_USAGE

    configure_logging(sys.stderr)
    try:
        settings = load_settings()
        providers = build_default_providers(settings)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    run_id = uuid.uuid4().hex[:12]
    print(f"Run id: {run_id}", file=sys.stderr)
    state = run_workflow(
        goal,
        llm=providers.llm,
        search=providers.search,
        reviewer_llm=providers.reviewer_llm,
        settings=settings,
        run_id=run_id,
    )

    output = state["final_output"]
    if state["status"] is RunStatus.DONE and output:
        print(output, end="")
        return EXIT_OK

    print("Run failed.", file=sys.stderr)
    for error in state["errors"][:_MAX_LISTED_ERRORS]:
        print(f"- {error.message[:_MAX_ERROR_CHARS]}", file=sys.stderr)
    return EXIT_FAILED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestration",
        description="Run the multi-agent workflow.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one goal and print the final answer.")
    run.add_argument("goal", help="The goal to research, in quotes.")
    return parser
