import enum

import pytest

from app.models.tag import Tag, TagType, TargetType


class TestTagEnums:
    def test_tag_type_values(self):
        assert TagType.TOPIC.value == "topic"
        assert TagType.ENTITY.value == "entity"
        assert TagType.PROJECT.value == "project"
        assert TagType.IMPORTANCE.value == "importance"
        assert TagType.CUSTOM.value == "custom"

    def test_target_type_values(self):
        assert TargetType.DOCUMENT.value == "document"
        assert TargetType.BOOKMARK.value == "bookmark"
        assert TargetType.NOTE.value == "note"
        assert TargetType.SPACE.value == "space"


class TestTagModel:
    def test_tag_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Tag)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "tag_name", "tag_type", "target_type", "target_id",
                     "auto_generated", "confidence_score", "created_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_tag_table_name(self):
        assert Tag.__tablename__ == "tags"
