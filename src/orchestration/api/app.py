import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from orchestration import __version__
from orchestration.api.runs import RunManager, RunSummary, RunView, TooManyRunsError
from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.core.logging import configure_logging
from orchestration.graph import build_default_providers

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_GOAL_CHARS = 2000

# The page loads only its own files. No inline script, no remote script, no framing.
_PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class HealthResponse(BaseModel):
    status: str
    version: str


class StatusResponse(BaseModel):
    """What the page shows about the setup. Names and a ready flag only, never a secret."""

    version: str
    ready: bool
    problem: str | None
    llm_provider: str | None
    llm_model: str | None
    search_provider: str | None
    max_goal_chars: int


class RunRequest(BaseModel):
    goal: str = Field(max_length=MAX_GOAL_CHARS)

    @field_validator("goal")
    @classmethod
    def goal_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Goal must not be empty.")
        return stripped


def create_app(manager: RunManager | None = None) -> FastAPI:
    """Build the API. Invalid settings raise ConfigurationError before serving."""
    load_settings()
    configure_logging()
    runs = manager if manager is not None else RunManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        runs.shutdown()

    application = FastAPI(
        title="Multi-Agent Orchestration System", version=__version__, lifespan=lifespan
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @application.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        try:
            settings = load_settings()
            build_default_providers(settings)
        except ConfigurationError as exc:
            return StatusResponse(
                version=__version__,
                ready=False,
                problem=str(exc),
                llm_provider=None,
                llm_model=None,
                search_provider=None,
                max_goal_chars=MAX_GOAL_CHARS,
            )
        return StatusResponse(
            version=__version__,
            ready=True,
            problem=None,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            search_provider=settings.search_provider,
            max_goal_chars=MAX_GOAL_CHARS,
        )

    @application.post("/api/runs", response_model=RunView, status_code=202)
    def start_run(request: RunRequest) -> RunView:
        try:
            settings = load_settings()
            return runs.start(request.goal, settings)
        except ConfigurationError as exc:
            raise HTTPException(status_code=503, detail=f"Configuration error: {exc}") from None
        except TooManyRunsError:
            raise HTTPException(
                status_code=429,
                detail="Too many runs are working. Wait for one to finish, then try again.",
            ) from None

    @application.get("/api/runs", response_model=list[RunSummary])
    def list_runs() -> list[RunSummary]:
        return runs.recent()

    @application.get("/api/runs/{run_id}", response_model=RunView)
    def get_run(run_id: str) -> RunView:
        view = runs.get(run_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return view

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers=_PAGE_HEADERS)

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    logger.info("api_started")
    return application


app = create_app()
