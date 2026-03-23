from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ArticleResponse(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    summary: str
    body: str
    bucket: str
    status: str
    language: str
    tags: list[str] = []
    categories: list[str] = []
    entities: list[dict] = []
    confidence: int = 0
    llm_provider: str | None = None
    source_chunk_ids: list[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ArticleListResponse(BaseModel):
    articles: list[ArticleResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ArticleGenerateRequest(BaseModel):
    force: bool = Field(False, description="Regenerate even if articles already exist")


class ArticleGenerateResponse(BaseModel):
    task_id: str
    document_id: str
    message: str


class ArticleBackfillResponse(BaseModel):
    task_ids: list[str]
    document_count: int
    message: str
