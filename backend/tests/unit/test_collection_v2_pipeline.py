"""Tests for Smart Collections v2 — 3-stage pipeline with articles-first search."""
import uuid
import pytest
from app.models.collection import Collection, CollectionItem, CollectionStatus
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole


class TestCollectionItemArticleField:
    """CollectionItem must have an optional article_id field."""

    def test_article_id_accepts_uuid(self, db):
        user = User(email="v2art@example.com", hashed_password="h", full_name="V2", role=UserRole.ADMIN, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        doc = Document(filename="test.pdf", original_filename="test.pdf", file_path="/data/public/test.pdf",
                       bucket=DocumentBucket.PUBLIC, status=DocumentStatus.INDEXED, size=1024, mime_type="application/pdf")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        collection = Collection(user_id=user.id, name="V2 Test", query="test", collection_type="smart",
                                visibility="private", status=CollectionStatus.READY, document_count=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        fake_article_id = uuid.uuid4()
        item = CollectionItem(
            collection_id=collection.id, document_id=doc.id, article_id=fake_article_id,
            relevance_score=85, order_index=0, added_by="ai",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        assert item.article_id == fake_article_id
        assert item.document_id == doc.id

    def test_article_id_nullable(self, db):
        user = User(email="v2null@example.com", hashed_password="h", full_name="V2N", role=UserRole.ADMIN, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        doc = Document(filename="no_article.pdf", original_filename="no_article.pdf", file_path="/data/public/no.pdf",
                       bucket=DocumentBucket.PUBLIC, status=DocumentStatus.INDEXED, size=1024, mime_type="application/pdf")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        collection = Collection(user_id=user.id, name="No Article", query="test", collection_type="smart",
                                visibility="private", status=CollectionStatus.READY, document_count=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        item = CollectionItem(
            collection_id=collection.id, document_id=doc.id,
            relevance_score=50, order_index=0, added_by="ai",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        assert item.article_id is None
        assert item.document_id == doc.id
