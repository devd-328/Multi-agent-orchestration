from orchestration.core.config import Settings
from orchestration.core.errors import ConfigurationError
from orchestration.llm.ollama import OllamaProvider
from orchestration.llm.provider import LLMProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Return the adapter selected by settings. Unknown providers fail immediately."""
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "ollama":
        return OllamaProvider(
            base_url=str(settings.llm_base_url),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ConfigurationError(f"Unknown LLM provider '{settings.llm_provider}'.")
