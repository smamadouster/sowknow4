"""
Article API endpoints — list, view, generate, and manage AI-generated articles.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.article import Article, ArticleStatus
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.schemas.article import (
    ArticleBackfillResponse,
    ArticleGenerateRequest,
    ArticleGenerateResponse,
    ArticleListResponse,
    ArticleResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/articles", tags=["articles"])


def _bucket_filter(user: User) -> list[str]:
    """Return allowed buckets based on user role."""
    if user.role in (UserRole.ADMIN, UserRole.SUPERUSER):
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    return [DocumentBucket.PUBLIC.value]


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    document_id: UUID | None = Query(None, description="Filter by document ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List articles with RBAC filtering."""
    allowed_buckets = _bucket_filter(current_user)

    query = db.query(Article).filter(
        Article.bucket.in_(allowed_buckets),
        Article.status == ArticleStatus.INDEXED,
    )
    if document_id:
        query = query.filter(Article.document_id == document_id)

    total = query.count()
    articles = (
        query.order_by(Article.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return ArticleListResponse(
        articles=[ArticleResponse.model_validate(a) for a in articles],
        total=total,
        page=(offset // limit) + 1,
        page_size=limit,
    )


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single article by ID."""
    allowed_buckets = _bucket_filter(current_user)

    article = (
        db.query(Article)
        .filter(Article.id == article_id, Article.bucket.in_(allowed_buckets))
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    return ArticleResponse.model_validate(article)


@router.post("/generate/{document_id}", response_model=ArticleGenerateResponse)
async def generate_articles(
    document_id: UUID,
    request: ArticleGenerateRequest = ArticleGenerateRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Trigger article generation for a specific document. Admin only."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.status != DocumentStatus.INDEXED:
        raise HTTPException(
            status_code=400,
            detail=f"Document must be indexed first (current: {document.status.value})",
        )

    if document.articles_generated and not request.force:
        raise HTTPException(
            status_code=400,
            detail=f"Articles already generated ({document.article_count}). Use force=true to regenerate.",
        )

    from app.tasks.article_tasks import generate_articles_for_document

    task = generate_articles_for_document.delay(str(document_id), force=request.force)

    return ArticleGenerateResponse(
        task_id=task.id,
        document_id=str(document_id),
        message=f"Article generation queued for {document.original_filename}",
    )


@router.post("/backfill", response_model=ArticleBackfillResponse)
async def backfill_articles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Trigger article generation for all indexed documents without articles. Admin only."""
    documents = (
        db.query(Document)
        .filter(
            Document.status == DocumentStatus.INDEXED,
            Document.articles_generated == False,  # noqa: E712
            Document.chunk_count > 0,
        )
        .all()
    )

    if not documents:
        return ArticleBackfillResponse(
            task_ids=[],
            document_count=0,
            message="All indexed documents already have articles generated.",
        )

    from app.tasks.article_tasks import generate_articles_for_document

    task_ids = []
    for doc in documents:
        task = generate_articles_for_document.delay(str(doc.id))
        task_ids.append(task.id)

    return ArticleBackfillResponse(
        task_ids=task_ids,
        document_count=len(documents),
        message=f"Article generation queued for {len(documents)} documents.",
    )


@router.delete("/{article_id}", status_code=204)
async def delete_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete an article. Admin only."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # Update document article count
    doc = db.query(Document).filter(Document.id == article.document_id).first()
    if doc and doc.article_count and doc.article_count > 0:
        doc.article_count -= 1

    db.delete(article)
    db.commit()
