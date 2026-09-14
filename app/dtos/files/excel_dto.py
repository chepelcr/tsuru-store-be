from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.dtos.files.file_dto import FileDTO


class ExcelDTO(FileDTO):
    """DTO for Excel file uploads."""

    name: Optional[str] = Field(None, description="File name without extension")
    content_type: Optional[str] = Field(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        description="Excel MIME type",
    )
