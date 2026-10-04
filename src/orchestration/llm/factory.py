from orchestration.core.config import Settings
from orchestration.core.errors import ConfigurationError
from orchestration.llm.ollama import OllamaProvider
from orchestration.llm.provider import LLMProvider


def create_llm_provider(settings: Settings, *, model: str | None = None) -> LLMProvider:
    """Return the adapter selected by settings. Unknown providers fail immediately.

    `model` replaces `llm_model` for this provider only. Leave it unset to use
    the configured model.
    """
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "ollama":
        return OllamaProvider(
            base_url=str(settings.llm_base_url),
            model=model if model is not None else settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ConfigurationError(f"Unknown LLM provider '{settings.llm_provider}'.")


def create_reviewer_llm_provider(settings: Settings) -> LLMProvider:
    """Return the provider for review calls.

    Uses `reviewer_model` when it is set, and the shared `llm_model` otherwise.
    """
    return create_llm_provider(settings, model=settings.reviewer_model)
