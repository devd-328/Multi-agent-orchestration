from orchestration.core.config import Settings
from orchestration.core.errors import ConfigurationError
from orchestration.search.provider import SearchProvider
from orchestration.search.tavily import TavilyProvider


def create_search_provider(settings: Settings) -> SearchProvider:
    """Return the adapter selected by settings. Unknown providers fail immediately."""
    provider_name = settings.search_provider.strip().lower()
    if provider_name == "tavily":
        key = settings.search_api_key
        if key is None or not key.get_secret_value().strip():
            raise ConfigurationError("Search API key is missing. Set SEARCH_API_KEY.")
        return TavilyProvider(
            api_key=key.get_secret_value(),
            timeout_seconds=settings.search_timeout_seconds,
        )
    raise ConfigurationError(f"Unknown search provider '{settings.search_provider}'.")
