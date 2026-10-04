import logging

from fastapi import FastAPI
from pydantic import BaseModel

from orchestration import __version__
from orchestration.core.config import load_settings
from orchestration.core.logging import configure_logging

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    """Build the API. Invalid settings raise ConfigurationError before serving."""
    load_settings()
    configure_logging()
    application = FastAPI(title="Multi-Agent Orchestration System", version=__version__)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    logger.info("api_started")
    return application


app = create_app()
