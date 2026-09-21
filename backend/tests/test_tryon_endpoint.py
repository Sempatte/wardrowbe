from io import BytesIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.item import ClothingItem, ItemStatus
from app.models.user import User
from app.services.image_service import ImageService
from app.services.tryon_service import TryOnQuotaExhaustedError


def _jpeg_bytes(size: tuple[int, int] = (400, 600)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (10, 200, 30)).save(buf, format="JPEG")
    return buf.getvalue()


async def _make_item(db_session: AsyncSession, user: User, **overrides) -> ClothingItem:
    svc = ImageService()
    paths = await svc.process_and_store(
        user_id=user.id, image_data=_jpeg_bytes(), original_filename="test.jpg"
    )
    defaults = {
        "user_id": user.id,
        "type": "shirt",
        "image_path": paths["image_path"],
        "medium_path": paths["medium_path"],
        "thumbnail_path": paths["thumbnail_path"],
        "image_hash": paths["image_hash"],
        "status": ItemStatus.ready,
    }
    defaults.update(overrides)
    item = ClothingItem(**defaults)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


async def _upload_body_photo(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/tryon/body-photo",
        files={"image": ("body.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=auth_headers,
    )
    assert response.status_code == 201


class TestBodyPhoto:
    @pytest.mark.asyncio
    async def test_upload_and_delete(self, client: AsyncClient, auth_headers):
        response = await client.post(
            "/api/v1/tryon/body-photo",
            files={"image": ("body.jpg", _jpeg_bytes(), "image/jpeg")},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["body_photo_url"]

        profile = await client.get("/api/v1/users/me", headers=auth_headers)
        assert profile.json()["body_photo_url"]

        delete_response = await client.delete("/api/v1/tryon/body-photo", headers=auth_headers)
        assert delete_response.status_code == 204

        profile = await client.get("/api/v1/users/me", headers=auth_headers)
        assert profile.json()["body_photo_url"] is None

    @pytest.mark.asyncio
    async def test_unauthenticated(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/tryon/body-photo",
            files={"image": ("body.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert response.status_code == 401


class TestGenerate:
    @pytest.mark.asyncio
    async def test_disabled_without_api_key(
        self, client: AsyncClient, test_user, auth_headers, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key=None),
        )
        response = await client.post(
            "/api/v1/tryon/generate",
            json={"item_ids": [str(uuid4())]},
            headers=auth_headers,
        )
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_requires_body_photo(
        self, client: AsyncClient, test_user, auth_headers, db_session, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key="test-key"),
        )
        item = await _make_item(db_session, test_user)

        response = await client.post(
            "/api/v1/tryon/generate",
            json={"item_ids": [str(item.id)]},
            headers=auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_items_from_another_user(
        self, client: AsyncClient, test_user, auth_headers, db_session, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key="test-key"),
        )
        await _upload_body_photo(client, auth_headers)

        other_user = User(
            external_id=f"other-{uuid4()}",
            email=f"other-{uuid4()}@example.com",
            display_name="Other User",
            timezone="UTC",
        )
        db_session.add(other_user)
        await db_session.commit()
        await db_session.refresh(other_user)
        foreign_item = await _make_item(db_session, other_user)

        response = await client.post(
            "/api/v1/tryon/generate",
            json={"item_ids": [str(foreign_item.id)]},
            headers=auth_headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_happy_path_multiple_items(
        self, client: AsyncClient, test_user, auth_headers, db_session, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key="test-key"),
        )
        await _upload_body_photo(client, auth_headers)
        item1 = await _make_item(db_session, test_user)
        item2 = await _make_item(db_session, test_user)

        with patch(
            "app.api.tryon.generate_tryon",
            new=AsyncMock(return_value=(b"fake-image-bytes", "image/jpeg")),
        ) as mock_generate:
            response = await client.post(
                "/api/v1/tryon/generate",
                json={"item_ids": [str(item1.id), str(item2.id)]},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.content == b"fake-image-bytes"
        assert response.headers["content-type"] == "image/jpeg"
        mock_generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_comments_are_folded_into_the_prompt_from_scratch(
        self, client: AsyncClient, test_user, auth_headers, db_session, monkeypatch
    ):
        # Regenerating with a comment must still start from the original body photo +
        # garment photos (never from a previous result), so the prompt just grows with
        # the extra instruction - it never re-feeds generated output back as input.
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key="test-key"),
        )
        await _upload_body_photo(client, auth_headers)
        item = await _make_item(db_session, test_user)

        with patch(
            "app.api.tryon.generate_tryon",
            new=AsyncMock(return_value=(b"fake-image-bytes", "image/jpeg")),
        ) as mock_generate:
            response = await client.post(
                "/api/v1/tryon/generate",
                json={
                    "item_ids": [str(item.id)],
                    "comments": ["No me pongas la camisa adentro del short", "  ", ""],
                },
                headers=auth_headers,
            )

        assert response.status_code == 200
        call_kwargs = mock_generate.call_args.kwargs
        prompt = call_kwargs["prompt"]
        assert "No me pongas la camisa adentro del short" in prompt
        # the base prompt's own bullet list must stay intact - only one extra bullet
        # for the (single, non-blank) comment should be appended after it
        notes_section = prompt.split("Instrucciones adicionales del usuario")[1]
        # blank/whitespace-only comments must be dropped, not sent through as noise
        assert notes_section.count("\n- ") == 1

    @pytest.mark.asyncio
    async def test_quota_exhausted_surfaces_402(
        self, client: AsyncClient, test_user, auth_headers, db_session, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.tryon_service.get_settings",
            lambda: Settings(gemini_api_key="test-key"),
        )
        await _upload_body_photo(client, auth_headers)
        item = await _make_item(db_session, test_user)

        with patch(
            "app.api.tryon.generate_tryon",
            new=AsyncMock(side_effect=TryOnQuotaExhaustedError("no credit")),
        ):
            response = await client.post(
                "/api/v1/tryon/generate",
                json={"item_ids": [str(item.id)]},
                headers=auth_headers,
            )

        assert response.status_code == 402
