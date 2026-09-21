import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from app.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class TryOnDisabledError(RuntimeError):
    """Raised when GEMINI_API_KEY is not configured."""


class TryOnGenerationError(RuntimeError):
    """Raised when Gemini fails to return a usable image."""


class TryOnQuotaExhaustedError(TryOnGenerationError):
    """Raised when Gemini rejects the request for lack of prepaid credit."""


def require_tryon_enabled() -> None:
    if not get_settings().gemini_api_key:
        raise TryOnDisabledError(
            "Virtual try-on is disabled (GEMINI_API_KEY is not set)."
        )


def _image_to_base64_jpeg(path: str | Path, max_size: int = 1024) -> str:
    with Image.open(path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=90)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")


async def generate_tryon(
    person_image_path: str | Path,
    garment_image_paths: list[str | Path],
    prompt: str,
) -> tuple[bytes, str]:
    """Call Gemini's image generation API to composite a person photo with garments.

    Returns (image_bytes, mime_type). Raises TryOnQuotaExhaustedError when the
    project's prepaid credit is depleted (observed as HTTP 402 in practice), or
    TryOnGenerationError for any other failure.
    """
    settings = get_settings()

    parts = [{"text": prompt}]
    parts.append(
        {"inline_data": {"mime_type": "image/jpeg", "data": _image_to_base64_jpeg(person_image_path)}}
    )
    for garment_path in garment_image_paths:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": _image_to_base64_jpeg(garment_path),
                }
            }
        )

    request_body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    url = f"{GEMINI_API_BASE}/models/{settings.gemini_image_model}:generateContent"

    async with httpx.AsyncClient(timeout=settings.ai_timeout) as client:
        try:
            response = await client.post(
                url,
                params={"key": settings.gemini_api_key},
                json=request_body,
            )
        except httpx.RequestError as e:
            raise TryOnGenerationError(f"Could not reach Gemini API: {e}") from e

    if response.status_code == 402:
        raise TryOnQuotaExhaustedError(
            "Se agotó el crédito de la API de Gemini. Cargá saldo en "
            "https://ai.studio/projects para seguir generando imágenes."
        )

    if response.status_code != 200:
        error_message = response.text[:300]
        try:
            data = response.json()
            error_message = data.get("error", {}).get("message", error_message)
        except ValueError:
            pass
        logger.warning(f"Gemini try-on request failed ({response.status_code}): {error_message}")
        raise TryOnGenerationError(f"Gemini API error ({response.status_code}): {error_message}")

    data = response.json()
    candidates = data.get("candidates", [])
    for candidate in candidates:
        for part in candidate.get("content", {}).get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                image_bytes = base64.b64decode(inline_data["data"])
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type") or "image/jpeg"
                return image_bytes, mime_type

    raise TryOnGenerationError("Gemini response did not include an image.")
