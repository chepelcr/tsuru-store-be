from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FileDTO(BaseModel):
    """Base DTO for file uploads with base64-encoded data."""

    model_config = ConfigDict(populate_by_name=True)

    data: str = Field(..., description="Base64-encoded file data")
    name: Optional[str] = Field(None, description="Filename (e.g., file.ext)")
    content_type: Optional[str] = Field(None, description="MIME type (e.g., image/png)")
