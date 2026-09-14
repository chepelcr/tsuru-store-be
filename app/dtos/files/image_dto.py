from __future__ import annotations

from pydantic import Field

from app.dtos.files.file_dto import FileDTO


class ImageDTO(FileDTO):
    """DTO for image file uploads."""

    content_type: str = Field(
        ...,
        description="Image MIME type (e.g., image/png, image/jpeg, image/gif, image/webp)",
    )
