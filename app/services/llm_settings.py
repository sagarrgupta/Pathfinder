"""Persist provider selection without rewriting credentials or unrelated settings."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import set_key

from app.adapters.llm.lmstudio import reset_llm_clients
from app.config.settings import _ENV_FILE, settings


def switch_llm_provider(provider: str) -> None:
    if provider not in {"lmstudio", "nvidia"}:
        raise ValueError("Choose LM Studio or NVIDIA")
    if provider == settings.llm_provider:
        return

    current_prefix = "NVIDIA" if settings.is_nvidia_endpoint else "LMSTUDIO"
    changes = {
        f"{current_prefix}_MODEL": settings.LLM_MODEL,
        f"{current_prefix}_VISION_MODEL": settings.VISION_MODEL,
    }
    if not settings.is_nvidia_endpoint:
        changes.update(
            LMSTUDIO_BASE_URL=settings.LLM_BASE_URL,
            LMSTUDIO_REQUIRE_EXACT_MODEL=settings.LLM_REQUIRE_EXACT_MODEL,
        )

    if provider == "nvidia":
        changes.update(
            LLM_BASE_URL="https://integrate.api.nvidia.com/v1",
            LLM_MODEL=settings.NVIDIA_MODEL,
            VISION_MODEL=settings.NVIDIA_VISION_MODEL,
            LLM_REQUIRE_EXACT_MODEL=True,
        )
    else:
        changes.update(
            LLM_BASE_URL=settings.LMSTUDIO_BASE_URL,
            LLM_MODEL=settings.LMSTUDIO_MODEL,
            VISION_MODEL=settings.LMSTUDIO_VISION_MODEL,
            LLM_REQUIRE_EXACT_MODEL=settings.LMSTUDIO_REQUIRE_EXACT_MODEL,
        )

    candidate = settings.model_copy(update=changes)
    # Check credentials before changing either the saved or running configuration.
    _ = candidate.llm_api_key

    # Replace atomically so a failed save cannot leave a partial configuration.
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=_ENV_FILE.parent,
                                prefix=".llm-settings-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(_ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else "")
        for key, value in changes.items():
            set_key(temporary_path, key, str(value).lower() if isinstance(value, bool) else str(value))
        temporary_path.replace(_ENV_FILE)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    for key, value in changes.items():
        setattr(settings, key, value)
    reset_llm_clients()
