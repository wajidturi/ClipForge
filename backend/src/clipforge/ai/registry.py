"""Which AI provider to use, from settings."""

from __future__ import annotations

from clipforge.ai.base import Provider
from clipforge.ai.ollama import OllamaProvider
from clipforge.core.config import Settings


def make_provider(settings: Settings, model: str | None = None) -> Provider | None:
    """None means "no AI" (the heuristic picker)."""
    if settings.ai_provider == "ollama":
        return OllamaProvider(model or settings.ollama_model, settings.ollama_url)
    return None
