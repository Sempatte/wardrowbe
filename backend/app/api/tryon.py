import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.image_service import ImageService
from app.services.studio_service import ItemOwnershipError, validate_item_ownership
from app.services.tryon_service import (
    TryOnDisabledError,
    TryOnGenerationError,
    TryOnQuotaExhaustedError,
    generate_tryon,
    require_tryon_enabled,
)
from app.utils.auth import get_current_user
from app.utils.prompts import load_prompt
from app.utils.signed_urls import sign_image_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tryon", tags=["Virtual Try-On"])

TRYON_PROMPT = load_prompt("virtual_tryon")


class TryOnGenerateRequest(BaseModel):
    item_ids: list[UUID]
    # Free-text tweaks from the user (e.g. "no metas la camisa adentro del short").
    # Every generation still starts from the original body photo + garment photos
    # (see person_path/garment_paths below) - comments are re-applied as prompt
    # instructions on top of that, never by feeding a previous result back into the
    # model, which would compound and drift the person's face/body over successive edits.
    comments: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("comments")
    @classmethod
    def _clean_comments(cls, value: list[str]) -> list[str]:
        return [c.strip()[:300] for c in value if c.strip()]


class BodyPhotoResponse(BaseModel):
    body_photo_url: str | None = None


@router.post("/body-photo", response_model=BodyPhotoResponse, status_code=status.HTTP_201_CREATED)
async def upload_body_photo(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    image: UploadFile = File(...),
) -> BodyPhotoResponse:
    image_service = ImageService()
    content = await image.read()
    content_type = image.content_type or "application/octet-stream"

    if not image_service.validate_image(content, content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file. Supported formats: JPEG, PNG, WebP, HEIC",
        )

    try:
        image_paths = await image_service.process_and_store(
            user_id=current_user.id,
            image_data=content,
            original_filename=image.filename or "body_photo.jpg",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None

    old_paths = {
        "image_path": current_user.body_photo_path,
        "medium_path": current_user.body_photo_medium_path,
        "thumbnail_path": current_user.body_photo_thumbnail_path,
    }

    current_user.body_photo_path = image_paths["image_path"]
    current_user.body_photo_medium_path = image_paths["medium_path"]
    current_user.body_photo_thumbnail_path = image_paths["thumbnail_path"]
    await db.commit()

    if old_paths["image_path"]:
        image_service.delete_images(old_paths)

    return BodyPhotoResponse(body_photo_url=sign_image_url(current_user.body_photo_path))


@router.delete("/body-photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_body_photo(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    if not current_user.body_photo_path:
        return

    image_service = ImageService()
    image_service.delete_images(
        {
            "image_path": current_user.body_photo_path,
            "medium_path": current_user.body_photo_medium_path,
            "thumbnail_path": current_user.body_photo_thumbnail_path,
        }
    )

    current_user.body_photo_path = None
    current_user.body_photo_medium_path = None
    current_user.body_photo_thumbnail_path = None
    await db.commit()


@router.post("/generate")
async def generate_tryon_image(
    request: TryOnGenerateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        require_tryon_enabled()
    except TryOnDisabledError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    if not current_user.body_photo_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subí una foto de tu cuerpo antes de usar el probador virtual.",
        )

    try:
        items = await validate_item_ownership(db, current_user.id, request.item_ids)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ItemOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e

    image_service = ImageService()
    person_path = image_service.get_image_path(current_user.body_photo_path)
    garment_paths = [image_service.get_image_path(item.image_path) for item in items]

    prompt = TRYON_PROMPT
    if request.comments:
        notes = "\n".join(f"- {c}" for c in request.comments)
        prompt = f"{TRYON_PROMPT}\n\nInstrucciones adicionales del usuario (aplicar todas):\n{notes}"

    try:
        image_bytes, mime_type = await generate_tryon(
            person_image_path=person_path,
            garment_image_paths=garment_paths,
            prompt=prompt,
        )
    except TryOnQuotaExhaustedError as e:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(e)) from e
    except TryOnGenerationError as e:
        logger.error(f"Try-on generation failed for user {current_user.id}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    return Response(content=image_bytes, media_type=mime_type)
