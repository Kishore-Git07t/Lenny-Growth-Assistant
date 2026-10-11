"""Provider and model status endpoint returning safe LLM capability metadata."""

from fastapi import APIRouter, Depends

from backend.app.config import Settings, get_settings
from backend.app.schemas.provider import ProviderInfo, ProviderStatusResponse

router = APIRouter(tags=["Models & Providers"])


@router.get(
    "/api/models",
    response_model=ProviderStatusResponse,
    summary="Get available LLM providers and configuration status",
)
@router.get(
    "/api/providers",
    response_model=ProviderStatusResponse,
    summary="Get available LLM providers and configuration status (alias)",
)
def get_available_models(
    settings: Settings = Depends(get_settings),
) -> ProviderStatusResponse:
    """Return safe metadata about supported local and cloud LLM providers.

    Guarantees:
        1. Never exposes API keys, authorization headers, or sensitive secrets.
        2. Distinguishes local offline inference from cloud external inference.
        3. Accurately reports whether cloud credentials are configured in the environment.
    """
    has_gemini = bool(settings.gemini_api_key and settings.gemini_api_key.strip())

    providers = [
        ProviderInfo(
            id="ollama",
            name="Local (Ollama)",
            model=settings.ollama_model,
            type="local",
            is_configured=True,
            description="Offline local inference using Ollama with genuine Pi Coding Agent.",
        ),
        ProviderInfo(
            id="google",
            name="Cloud (Google Gemini)",
            model=settings.gemini_model,
            type="cloud",
            is_configured=has_gemini,
            description=(
                f"Fast, high-context cloud inference via Google Gemini ({settings.gemini_model}). Free-tier eligible via Google AI Studio."
                if has_gemini
                else "Google Gemini is not configured. Set GEMINI_API_KEY in the server .env to enable (free tier available via Google AI Studio)."
            ),
        ),
    ]

    return ProviderStatusResponse(
        default_provider=settings.llm_provider,
        active_provider=settings.llm_provider,
        providers=providers,
    )
