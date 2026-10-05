from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestration.core.errors import ConfigurationError


class Settings(BaseSettings):
    """Runtime settings loaded from the environment and an optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    llm_provider: str = Field(default="ollama", min_length=1)
    llm_model: str = Field(min_length=1)
    llm_base_url: AnyHttpUrl
    llm_timeout_seconds: float = Field(default=60, gt=0)
    max_task_attempts: int = Field(default=3, ge=1)
    max_review_revisions: int = Field(default=2, ge=1)
    max_plan_attempts: int = Field(default=3, ge=1)
    search_provider: str = Field(default="tavily", min_length=1)
    search_api_key: SecretStr | None = None
    search_timeout_seconds: float = Field(default=20, gt=0)
    max_search_queries: int = Field(default=3, ge=1, le=10)
    max_results_per_query: int = Field(default=5, ge=1, le=20)
    max_source_chars: int = Field(default=2000, ge=1)
    max_research_attempts: int = Field(default=3, ge=1)
    max_review_excerpt_chars: int = Field(default=2000, ge=1)
    max_review_attempts: int = Field(default=3, ge=1)
    reviewer_model: str | None = None
    max_graph_steps: int = Field(default=100, ge=1)

    @field_validator("search_api_key", "reviewer_model", mode="before")
    @classmethod
    def blank_value_is_missing(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("llm_provider", "llm_model", "search_provider", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("llm_base_url")
    @classmethod
    def require_url_host(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if not value.host:
            raise ValueError("must include a host")
        return value

    def __repr__(self) -> str:
        return "Settings(redacted)"

    def __str__(self) -> str:
        return "Settings(redacted)"


def load_settings(*, env_file: str | None = ".env") -> Settings:
    """Load settings or raise ConfigurationError without echoing values."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from None


_ERROR_TEXT = {
    "missing": "missing",
    "string_too_short": "must not be empty",
    "string_type": "must be text",
    "url_parsing": "invalid URL",
    "url_scheme": "URL scheme must be http or https",
    "url_type": "invalid URL",
    "value_error": "invalid value",
    "greater_than_equal": "must be at least 1",
    "greater_than": "must be greater than zero",
    "less_than_equal": "is above the allowed maximum",
    "int_parsing": "must be an integer",
    "int_type": "must be an integer",
    "float_parsing": "must be a number",
    "float_type": "must be a number",
}


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "settings"
        error_type = str(error.get("type", "invalid"))
        parts.append(f"{location}: {_ERROR_TEXT.get(error_type, error_type)}")
    detail = "; ".join(parts) if parts else "invalid settings"
    return f"Invalid configuration. {detail}"
