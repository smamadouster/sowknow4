import pytest
from app.models.bookmark import Bookmark, BookmarkBucket


class TestBookmarkModel:
    def test_bucket_enum_values(self):
        assert BookmarkBucket.PUBLIC.value == "public"
        assert BookmarkBucket.CONFIDENTIAL.value == "confidential"

    def test_bookmark_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Bookmark)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "user_id", "url", "title", "description",
                     "favicon_url", "bucket", "created_at", "updated_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_bookmark_table_name(self):
        assert Bookmark.__tablename__ == "bookmarks"
