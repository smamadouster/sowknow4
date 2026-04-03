import pytest
from app.models.space import Space, SpaceItem, SpaceRule, SpaceBucket, SpaceItemType, SpaceRuleType


class TestSpaceEnums:
    def test_bucket_values(self):
        assert SpaceBucket.PUBLIC.value == "public"
        assert SpaceBucket.CONFIDENTIAL.value == "confidential"

    def test_item_type_values(self):
        assert SpaceItemType.DOCUMENT.value == "document"
        assert SpaceItemType.BOOKMARK.value == "bookmark"
        assert SpaceItemType.NOTE.value == "note"

    def test_rule_type_values(self):
        assert SpaceRuleType.TAG.value == "tag"
        assert SpaceRuleType.KEYWORD.value == "keyword"


class TestSpaceModel:
    def test_space_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Space)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "user_id", "name", "description", "icon", "bucket", "is_pinned", "created_at", "updated_at"]:
            assert col in column_names, f"Missing column: {col}"

    def test_space_item_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(SpaceItem)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "space_id", "item_type", "document_id", "bookmark_id", "note_id", "added_by", "added_at", "note", "is_excluded"]:
            assert col in column_names, f"Missing column: {col}"

    def test_space_rule_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(SpaceRule)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "space_id", "rule_type", "rule_value", "is_active", "created_at"]:
            assert col in column_names, f"Missing column: {col}"
