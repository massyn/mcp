"""Pydantic input models for Citadel MCP tools."""

from typing import Literal, Optional

from pydantic import BaseModel, field_validator

EntryStatus = Literal["active", "archived", "deprecated"]


class AddEntryInput(BaseModel):
    room: str
    title: str
    summary: str
    detail: str
    tags: list[str] = []

    @field_validator("room", "title", "summary", "detail")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v


class UpdateEntryInput(BaseModel):
    room: str
    entry_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[EntryStatus] = None
    tags: Optional[list[str]] = None


class BulkEntryItem(BaseModel):
    room: str
    title: str
    summary: str
    detail: str
    tags: list[str] = []

    @field_validator("room", "title", "summary", "detail")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v
